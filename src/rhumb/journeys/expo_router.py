"""Expo Router journey plugin — filesystem routes + parse_js navigation.

Route table = ``app/`` or ``src/app/`` (filesystem-first).
Navigation = ``Link href``, ``router.push|replace|navigate``, ``Redirect href``.

Phase 3: relative href resolve, typed-routes cross-check, nested groups,
``+native-intent`` gaps, constant miss-path via ``parse_js``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rhumb.framework import FrameworkDetection
from rhumb.graphify_runner import AstResult
from rhumb.journeys.parse_js import (
    JsParseResult,
    extract_imports,
    find_exported_initializer,
    follow_export,
    node_text,
    parse_js_ts,
    string_literal_value,
)
from rhumb.journeys.react_router import (
    build_file_route_index,
    from_path_for_file,
)
from rhumb.journeys.types import (
    Confidence,
    JourneyGap,
    JourneyGraph,
    NavEdge,
    RouteNode,
    RouteSource,
)

SOURCE_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js")
PLATFORM_SUFFIXES = (".web", ".native", ".ios", ".android")
SKIP_PLUS_STEMS = frozenset(
    {
        "+html",
        "+native-intent",
        "+middleware",
        "+api",
        "+server",
    }
)
# Special files that are not journey steps but should be flagged as gaps.
DEEP_LINK_STEMS = frozenset({"+native-intent"})
NAV_SCAN_MARKERS = (
    "<Link",
    "<Redirect",
    "router.push",
    "router.replace",
    "router.navigate",
    "href=",
)
LINK_TAGS = frozenset({"Link", "Redirect"})
ROUTER_METHODS = {
    "push": "navigate",
    "replace": "navigate",
    "navigate": "navigate",
}
SKIP_DIRS = frozenset({"node_modules", "dist", "build", ".expo", ".git"})

# Expo typed routes: `| \`/about\`` or `| "/about"` inside StaticRoutes / Href unions.
_TYPED_STATIC_RE = re.compile(r"""\|\s*[`'"](/[^`'"{}$]*)[`'"]""")
_TYPED_DYNAMIC_RE = re.compile(r"""\|\s*`(/[^`$]*)/\$\{[^}]+\}`""")
_TYPED_PATHNAME_RE = re.compile(
    r"""pathname\s*:\s*[`'"](/[^`'"]+)[`'"]"""
)
_TEMPLATE_INTERP_RE = re.compile(r"\$\{[^}]+\}")


def find_app_root(project_dir: Path) -> Path | None:
    """Locate Expo Router ``app/`` or ``src/app/`` directory."""
    project_dir = project_dir.resolve()
    for candidate in (project_dir / "app", project_dir / "src" / "app"):
        if candidate.is_dir():
            return candidate
    return None


def _strip_platform_suffix(stem: str) -> str:
    for suffix in PLATFORM_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _is_group_segment(name: str) -> bool:
    return len(name) >= 2 and name.startswith("(") and name.endswith(")")


def _is_private_segment(name: str) -> bool:
    """Expo: ``_foo`` dirs/files are private (not routes), except ``_layout``."""
    return name.startswith("_") and name != "_layout"


def file_to_route_url(rel: Path) -> tuple[str, bool, bool] | None:
    """Map ``app/``-relative file path → ``(url_path, is_index, is_wildcard)``.

    Returns ``None`` for layouts, private files, and non-route ``+`` files.
    Dynamic segments keep Expo form (``[id]``, ``[...slug]``).
    Nested groups ``(a)/(b)/x`` → ``/x`` (all paren dirs omitted).
    """
    stem = _strip_platform_suffix(rel.stem)
    if stem == "_layout":
        return None
    if _is_private_segment(stem):
        return None
    if stem in SKIP_PLUS_STEMS:
        return None

    if stem == "+not-found":
        return ("*", False, True)

    segments: list[str] = []
    for part in rel.parent.parts:
        if _is_group_segment(part):
            continue
        if _is_private_segment(part):
            return None
        segments.append(part)

    is_index = stem == "index"
    is_wildcard = stem.startswith("[...") or stem == "[...]"
    if not is_index:
        segments.append(stem)

    if not segments:
        return ("/", True, False)

    url = "/" + "/".join(segments)
    return (url, is_index, is_wildcard)


def collect_layouts(app_root: Path, route_file: Path, project_dir: Path) -> list[str]:
    """All ``_layout`` files from route dir up to app root (nearest first)."""
    layouts: list[str] = []
    current = route_file.parent
    app_root = app_root.resolve()
    while True:
        for ext in SOURCE_EXTENSIONS:
            for platform in ("", *PLATFORM_SUFFIXES):
                candidate = current / f"_layout{platform}{ext}"
                if candidate.is_file():
                    layouts.append(
                        str(candidate.relative_to(project_dir)).replace("\\", "/")
                    )
                    break
            else:
                continue
            break
        if current == app_root or current.parent == current:
            break
        current = current.parent
    return layouts


def _nearest_layout(app_root: Path, route_file: Path, project_dir: Path) -> str | None:
    layouts = collect_layouts(app_root, route_file, project_dir)
    return layouts[0] if layouts else None


def extract_filesystem_routes(
    project_dir: Path,
    app_root: Path | None = None,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Walk ``app/`` and build ``RouteNode`` list from Expo file notation."""
    project_dir = project_dir.resolve()
    root = app_root or find_app_root(project_dir)
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []

    if root is None:
        gaps.append(
            JourneyGap(
                message="no Expo Router app/ or src/app/ directory found",
                confidence=Confidence.LOW,
            )
        )
        return routes, gaps

    seen_urls: dict[str, str] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        if any(_is_private_segment(p) for p in rel.parts[:-1]):
            continue

        stem = _strip_platform_suffix(path.stem)
        source_file = str(path.relative_to(project_dir)).replace("\\", "/")

        # Phase 3: deep-link / special files → gaps, not routes
        if stem in DEEP_LINK_STEMS:
            gaps.append(
                JourneyGap(
                    message=(
                        f"deep-link / special file not modeled as journey step: "
                        f"{source_file}"
                    ),
                    source_file=source_file,
                    confidence=Confidence.LOW,
                )
            )
            continue
        if stem in SKIP_PLUS_STEMS:
            continue

        mapped = file_to_route_url(rel)
        if mapped is None:
            continue

        url_path, is_index, is_wildcard = mapped

        if url_path in seen_urls:
            gaps.append(
                JourneyGap(
                    message=(
                        f"duplicate URL {url_path}: {source_file} "
                        f"conflicts with {seen_urls[url_path]}"
                    ),
                    source_file=source_file,
                    confidence=Confidence.MEDIUM,
                )
            )
            continue
        seen_urls[url_path] = source_file

        confidence = Confidence.HIGH
        if "[" in url_path and url_path != "*":
            confidence = Confidence.MEDIUM

        layouts = collect_layouts(root, path, project_dir)
        routes.append(
            RouteNode(
                url_path=url_path,
                component=source_file,
                source_file=source_file,
                source_line=1,
                is_index=is_index,
                is_wildcard=is_wildcard,
                layout=layouts[0] if layouts else None,
                confidence=confidence,
                source=RouteSource.FILESYSTEM,
            )
        )

    return routes, gaps


def canonicalize_expo_href(href: str) -> str:
    """Strip query/hash and route-group segments ``(auth)`` / ``(tabs)``.

    Expo allows group-qualified hrefs (``/(auth)/sign-in``); filesystem routes
    omit groups (``/sign-in``). Canonical form matches FS ``url_path``.
    Group-only hrefs like ``/(tabs)`` collapse to ``/``.
    """
    path = href.split("?", 1)[0].split("#", 1)[0]
    parts: list[str] = []
    for part in path.split("/"):
        if not part or part in {".", ".."}:
            continue
        if _is_group_segment(part):
            continue
        parts.append(part)
    return "/" + "/".join(parts) if parts else "/"


def soften_template_href(raw: str, known_routes: set[str]) -> str | None:
    """Map ``/group/${id}`` → matching FS dynamic route (e.g. ``/group/[id]``).

    Query-only interpolation (``/add-expense?x=${id}``) → path without query.
    """
    path = raw.split("?", 1)[0].split("#", 1)[0]
    path = canonicalize_expo_href(path)

    if "${" not in path:
        return path

    # Match FS dynamics: ${...} ↔ [param] segment
    regex_body: list[str] = []
    last = 0
    for match in _TEMPLATE_INTERP_RE.finditer(path):
        regex_body.append(re.escape(path[last : match.start()]))
        regex_body.append(r"\[[^\]/]+\]")
        last = match.end()
    regex_body.append(re.escape(path[last:]))
    pattern = re.compile("^" + "".join(regex_body) + "$")

    matches = sorted(r for r in known_routes if pattern.match(r))
    if not matches:
        return None
    return matches[0]


def resolve_relative_href(href: str, from_path: str | None) -> str | None:
    """Resolve ``./`` / ``../`` against the owning route URL.

    Absolute paths and ``*`` pass through. Returns ``None`` when relative
    but ``from_path`` is unknown. Uses file-path semantics (drop leaf segment).
    """
    if href == "*" or href.startswith("/"):
        return href
    if from_path is None:
        return None
    if not href.startswith(("./", "../")):
        href = "./" + href.lstrip("/")

    if from_path == "/":
        base_parts: list[str] = []
    else:
        # Drop leaf — current route is a "file" in the URL tree.
        base_parts = from_path.strip("/").split("/")[:-1]

    for part in href.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if base_parts:
                base_parts.pop()
            continue
        base_parts.append(part)

    return "/" + "/".join(base_parts) if base_parts else "/"


def find_typed_routes_file(project_dir: Path) -> Path | None:
    """Locate Expo generated typed-routes declaration if present."""
    project_dir = project_dir.resolve()
    candidates = [
        project_dir / ".expo" / "types" / "router.d.ts",
        project_dir / "node_modules" / ".expo" / "types" / "router.d.ts",
        project_dir / "expo-env.d.ts",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def parse_typed_routes(text: str) -> set[str]:
    """Extract static (+ normalized dynamic) paths from generated router.d.ts."""
    paths: set[str] = set()
    for match in _TYPED_STATIC_RE.finditer(text):
        paths.add(match.group(1))
    for match in _TYPED_PATHNAME_RE.finditer(text):
        paths.add(match.group(1))
    for match in _TYPED_DYNAMIC_RE.finditer(text):
        # `/user/${string}` → keep prefix + `[param]` placeholder for compare
        prefix = match.group(1).rstrip("/")
        paths.add(f"{prefix}/[param]" if prefix else "/[param]")
    return paths


def cross_check_typed_routes(
    project_dir: Path,
    routes: list[RouteNode] | tuple[RouteNode, ...],
) -> tuple[list[JourneyGap], dict[str, str]]:
    """Optional cross-check FS routes vs Expo typed routes file.

    Returns gaps + meta fragment (typed_routes_file, typed_count).
    """
    meta: dict[str, str] = {}
    typed_file = find_typed_routes_file(project_dir)
    if typed_file is None:
        meta["typed_routes"] = "absent"
        return [], meta

    try:
        text = typed_file.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            [
                JourneyGap(
                    message=f"typed routes file unreadable: {exc}",
                    source_file=str(typed_file.relative_to(project_dir)).replace("\\", "/"),
                    confidence=Confidence.LOW,
                )
            ],
            {"typed_routes": "error"},
        )

    typed = parse_typed_routes(text)
    rel = str(typed_file.relative_to(project_dir)).replace("\\", "/")
    meta["typed_routes"] = rel
    meta["typed_count"] = str(len(typed))

    if not typed:
        return [], meta

    gaps: list[JourneyGap] = []
    fs_paths = {r.url_path for r in routes if not r.is_wildcard}
    # Compare static FS paths present in typed set (ignore dynamic form mismatch loosely)
    typed_static = {p for p in typed if "[" not in p}
    fs_static = {p for p in fs_paths if "[" not in p}

    for path in sorted(fs_static - typed_static):
        # Typed file often omits group aliases; only flag if typed has *some* overlap
        if typed_static & fs_static:
            gaps.append(
                JourneyGap(
                    message=f"FS route missing from typed routes: {path}",
                    source_file=rel,
                    confidence=Confidence.LOW,
                )
            )

    for path in sorted(typed_static - fs_static):
        # Skip Expo internals
        if path in {"/_sitemap", "/_sitemap/"} or path.startswith("/+"):
            continue
        gaps.append(
            JourneyGap(
                message=f"typed route not found on filesystem: {path}",
                source_file=rel,
                confidence=Confidence.MEDIUM,
            )
        )

    return gaps, meta


def _resolve_module_path(project_dir: Path, source_file: Path, module: str) -> str | None:
    if not module.startswith("."):
        return None
    base = (project_dir / source_file.parent / module).resolve()
    candidates = [base] if base.suffix else [base.with_suffix(ext) for ext in SOURCE_EXTENSIONS]
    if not base.suffix:
        candidates.extend(base / f"index{ext}" for ext in SOURCE_EXTENSIONS)
    for candidate in candidates:
        if candidate.is_file():
            try:
                return str(candidate.relative_to(project_dir)).replace("\\", "/")
            except ValueError:
                return str(candidate)
    return None


def _string_from_init(source_bytes: bytes, init: Any) -> str | None:
    if init is None:
        return None
    if init.type in {"string", "template_string"}:
        return string_literal_value(source_bytes, init)
    return None


def _property_from_object(source_bytes: bytes, obj: Any, prop: str) -> str | None:
    for child in obj.children:
        if child.type != "pair":
            continue
        key = None
        value_node = None
        for part in child.children:
            if part.type == "property_identifier" and key is None:
                key = node_text(source_bytes, part)
            elif part.type == "string" and key is None:
                # {"home": "/home"} quoted key
                key = string_literal_value(source_bytes, part)
            elif part.type in {"string", "template_string"}:
                value_node = part
        if key == prop and value_node is not None:
            return string_literal_value(source_bytes, value_node)
    return None


def resolve_path_expression(
    source_bytes: bytes,
    expr: Any,
    parsed: JsParseResult,
    project_dir: Path | None,
    source_file: str,
) -> str | None:
    """Resolve string / local const / imported const / ``Obj.key`` to a path.

    Template literals with ``${...}`` return the raw inner text (including
    interpolations) so callers can ``soften_template_href`` against known routes.
    """
    if expr.type == "string":
        return string_literal_value(source_bytes, expr)

    if expr.type == "template_string":
        raw = node_text(source_bytes, expr)
        if len(raw) >= 2 and raw[0] == "`" and raw[-1] == "`":
            inner = raw[1:-1]
        else:
            inner = raw
        # Static template → plain string; interpolated → keep for softening
        if "${" not in inner:
            return inner
        return inner

    if expr.type == "object":
        return _pathname_from_object(source_bytes, expr)

    if expr.type == "identifier":
        name = node_text(source_bytes, expr)
        local = find_exported_initializer(parsed, name)
        got = _string_from_init(source_bytes, local)
        if got is not None:
            return got
        if project_dir is not None:
            imports = extract_imports(parsed)
            miss = follow_export(
                project_dir,
                Path(source_file),
                name,
                imports,
                resolve_file=_resolve_module_path,
            )
            if miss.ok and miss.binding_node is not None and miss.parsed is not None:
                return _string_from_init(miss.parsed.source_bytes, miss.binding_node)
        return None

    if expr.type == "member_expression":
        parts = [c for c in expr.children if c.type in {"identifier", "property_identifier"}]
        if len(parts) < 2:
            return None
        obj_name = node_text(source_bytes, parts[0])
        prop_name = node_text(source_bytes, parts[-1])
        local = find_exported_initializer(parsed, obj_name)
        if local is not None and local.type == "object":
            got = _property_from_object(source_bytes, local, prop_name)
            if got is not None:
                return got
        if project_dir is not None:
            imports = extract_imports(parsed)
            miss = follow_export(
                project_dir,
                Path(source_file),
                obj_name,
                imports,
                resolve_file=_resolve_module_path,
            )
            if (
                miss.ok
                and miss.binding_node is not None
                and miss.parsed is not None
                and miss.binding_node.type == "object"
            ):
                return _property_from_object(
                    miss.parsed.source_bytes, miss.binding_node, prop_name
                )
        return None

    return None


def iter_nav_candidate_files(project_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(marker in text for marker in NAV_SCAN_MARKERS):
            files.append(path)
    return files


def extract_navigation(
    project_dir: Path,
    routes: list[RouteNode] | tuple[RouteNode, ...],
) -> tuple[list[NavEdge], list[JourneyGap]]:
    """Scan for Expo ``Link`` / ``router.*`` / ``Redirect`` static targets."""
    project_dir = project_dir.resolve()
    file_routes = build_file_route_index(routes)
    known_routes = {r.url_path for r in routes}
    edges: list[NavEdge] = []
    gaps: list[JourneyGap] = []
    seen: set[tuple[str | None, str, str, str]] = set()

    for abs_path in iter_nav_candidate_files(project_dir):
        source_file = str(abs_path.relative_to(project_dir)).replace("\\", "/")
        parsed = parse_js_ts(abs_path)
        if not parsed.ok or parsed.root is None:
            gaps.append(
                JourneyGap(
                    message=f"nav parse failed for {source_file}: {parsed.detail}",
                    source_file=source_file,
                    confidence=Confidence.LOW,
                )
            )
            continue

        from_path = from_path_for_file(source_file, file_routes)
        file_edges, file_gaps = extract_nav_from_parse(
            parsed,
            source_file,
            from_path,
            project_dir=project_dir,
        )
        gaps.extend(file_gaps)
        for edge in file_edges:
            to_path = edge.to_path
            confidence = edge.confidence

            # Template soft-resolve before relative/canonicalize
            if "${" in to_path:
                softened = soften_template_href(to_path, known_routes)
                if softened is None:
                    gaps.append(
                        JourneyGap(
                            message=f"dynamic router target unresolved: {to_path}",
                            source_file=edge.source_file,
                            source_line=edge.source_line,
                            confidence=Confidence.LOW,
                        )
                    )
                    continue
                to_path = softened
                confidence = Confidence.MEDIUM
            elif to_path.startswith(("./", "../")) or (
                not to_path.startswith("/") and to_path != "*"
            ):
                resolved = resolve_relative_href(to_path, edge.from_path)
                if resolved is None:
                    gaps.append(
                        JourneyGap(
                            message=f"relative href unresolved (no owning route): {to_path}",
                            source_file=edge.source_file,
                            source_line=edge.source_line,
                            confidence=Confidence.LOW,
                        )
                    )
                    continue
                to_path = resolved
                confidence = Confidence.HIGH

            # Strip (groups) + query so href matches FS url_path
            to_path = canonicalize_expo_href(to_path)

            edge = NavEdge(
                from_path=edge.from_path,
                to_path=to_path,
                source_file=edge.source_file,
                source_line=edge.source_line,
                kind=edge.kind,
                confidence=confidence,
            )

            key = (edge.from_path, edge.to_path, edge.kind, edge.source_file)
            if key in seen:
                continue
            seen.add(key)
            edges.append(edge)
            if (
                known_routes
                and edge.to_path not in known_routes
                and edge.to_path != "*"
                and edge.confidence in {Confidence.HIGH, Confidence.MEDIUM}
            ):
                gaps.append(
                    JourneyGap(
                        message=f"nav target not in route tree: {edge.to_path}",
                        source_file=edge.source_file,
                        source_line=edge.source_line,
                        confidence=Confidence.MEDIUM,
                    )
                )

    return edges, gaps


def extract_nav_from_parse(
    parsed: JsParseResult,
    source_file: str,
    from_path: str | None,
    *,
    project_dir: Path | None = None,
) -> tuple[list[NavEdge], list[JourneyGap]]:
    """Extract Expo nav edges; resolve string constants via miss-path when possible."""
    if not parsed.ok or parsed.root is None:
        return [], []

    source_bytes = parsed.source_bytes
    edges: list[NavEdge] = []
    gaps: list[JourneyGap] = []

    def emit_path(raw: str | None, kind: str, line: int, unresolved_msg: str) -> None:
        if raw is None:
            gaps.append(
                JourneyGap(
                    message=unresolved_msg,
                    source_file=source_file,
                    source_line=line,
                    confidence=Confidence.LOW,
                )
            )
            return
        if raw.startswith(("http://", "https://", "mailto:")):
            return
        conf = (
            Confidence.MEDIUM
            if raw.startswith(("./", "../"))
            else Confidence.HIGH
        )
        edges.append(
            NavEdge(
                from_path=from_path,
                to_path=raw,
                source_file=source_file,
                source_line=line,
                kind=kind,
                confidence=conf,
            )
        )

    def walk(node: Any) -> None:
        if node.type in {"jsx_self_closing_element", "jsx_opening_element"}:
            name = _jsx_name(source_bytes, node)
            if name in LINK_TAGS:
                kind = "redirect" if name == "Redirect" else "link"
                line = node.start_point[0] + 1
                href = _jsx_href_raw(source_bytes, node)
                if href is not None:
                    emit_path(href, kind, line, f"dynamic {name} href unresolved")
                else:
                    expr = _jsx_href_expression(source_bytes, node)
                    if expr is not None:
                        resolved = resolve_path_expression(
                            source_bytes, expr, parsed, project_dir, source_file
                        )
                        emit_path(
                            resolved,
                            kind,
                            line,
                            f"dynamic {name} href unresolved",
                        )
                    elif _jsx_has_attr(source_bytes, node, "href"):
                        gaps.append(
                            JourneyGap(
                                message=f"dynamic {name} href unresolved",
                                source_file=source_file,
                                source_line=line,
                                confidence=Confidence.LOW,
                            )
                        )

        if node.type == "call_expression":
            method = _router_method_name(source_bytes, node)
            if method is not None:
                line = node.start_point[0] + 1
                first = _first_call_arg(node)
                if first is None:
                    gaps.append(
                        JourneyGap(
                            message=f"dynamic router.{method} target unresolved",
                            source_file=source_file,
                            source_line=line,
                            confidence=Confidence.LOW,
                        )
                    )
                else:
                    raw = resolve_path_expression(
                        source_bytes, first, parsed, project_dir, source_file
                    )
                    emit_path(
                        raw,
                        ROUTER_METHODS[method],
                        line,
                        f"dynamic router.{method} target unresolved",
                    )

        for child in node.children:
            walk(child)

    walk(parsed.root)
    return edges, gaps


def _jsx_name(source_bytes: bytes, node: Any) -> str | None:
    for child in node.children:
        if child.type == "identifier":
            return node_text(source_bytes, child)
        if child.type == "member_expression":
            return node_text(source_bytes, child)
    return None


def _jsx_has_attr(source_bytes: bytes, opening_or_self: Any, attr_name: str) -> bool:
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        for part in child.children:
            if part.type == "property_identifier":
                if node_text(source_bytes, part) == attr_name:
                    return True
    return False


def _jsx_href_raw(source_bytes: bytes, opening_or_self: Any) -> str | None:
    """Static string ``href="..."`` only (no expression)."""
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif name == "href" and part.type == "string":
                return string_literal_value(source_bytes, part)
    return None


def _jsx_href_expression(source_bytes: bytes, opening_or_self: Any) -> Any | None:
    """Inner expression node of ``href={...}``."""
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif name == "href" and part.type == "jsx_expression":
                for inner in part.children:
                    if inner.type in {"{", "}"}:
                        continue
                    return inner
    return None


def _pathname_from_object(source_bytes: bytes, obj: Any) -> str | None:
    for child in obj.children:
        if child.type != "pair":
            continue
        key = None
        value_node = None
        for part in child.children:
            if part.type == "property_identifier" and key is None:
                key = node_text(source_bytes, part)
            elif part.type in {"string", "template_string"}:
                value_node = part
        if key == "pathname" and value_node is not None:
            return string_literal_value(source_bytes, value_node)
    return None


def _router_method_name(source_bytes: bytes, call: Any) -> str | None:
    if not call.children:
        return None
    callee = call.children[0]
    if callee.type != "member_expression":
        return None
    parts = [c for c in callee.children if c.type in {"identifier", "property_identifier"}]
    if len(parts) < 2:
        return None
    obj = node_text(source_bytes, parts[0])
    method = node_text(source_bytes, parts[-1])
    if obj.lower() != "router":
        return None
    if method not in ROUTER_METHODS:
        return None
    return method


def _first_call_arg(call: Any) -> Any | None:
    args = next((c for c in call.children if c.type == "arguments"), None)
    if args is None:
        return None
    for child in args.children:
        if child.type in {"(", ")", ","}:
            continue
        return child
    return None


def _looks_like_route_path(value: str) -> bool:
    return value == "*" or value.startswith("/")


class ExpoRouterExtractor:
    """Expo Router plugin — filesystem routes + parse_js navigation."""

    framework = "expo-router"

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
        ast_result: AstResult | None = None,
    ) -> JourneyGraph:
        del detection, ast_result
        project_dir = project_dir.resolve()
        app_root = find_app_root(project_dir)
        routes, gaps = extract_filesystem_routes(project_dir, app_root)

        edges, nav_gaps = extract_navigation(project_dir, routes)
        gaps.extend(nav_gaps)

        typed_gaps, typed_meta = cross_check_typed_routes(project_dir, routes)
        gaps.extend(typed_gaps)

        layout_depths = []
        if app_root is not None:
            for route in routes:
                if not route.component:
                    continue
                abs_comp = project_dir / route.component
                if abs_comp.is_file():
                    layout_depths.append(len(collect_layouts(app_root, abs_comp, project_dir)))

        return JourneyGraph(
            framework=self.framework,
            project_root=project_dir,
            routes=tuple(routes),
            edges=tuple(edges),
            gaps=tuple(gaps),
            meta={
                "app_root": (
                    str(app_root.relative_to(project_dir)).replace("\\", "/")
                    if app_root
                    else ""
                ),
                "route_source": "filesystem",
                "dynamic_form": "expo",
                "parser": "tree_sitter",
                "edges": str(len(edges)),
                "max_layout_depth": str(max(layout_depths) if layout_depths else 0),
                **typed_meta,
            },
        )
