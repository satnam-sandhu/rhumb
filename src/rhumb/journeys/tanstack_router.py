"""TanStack Router journey plugin — gen/FS/virtual routes + parse_js navigation.

Priority: ``routeTree.gen.ts`` → virtualRouteConfig → ``src/routes/`` +
``createFileRoute`` → code-based ``createRoute``.

Navigation = ``Link to``, ``Navigate to``, ``navigate({ to })``, ``redirect({ to })``.
Phase 3: virtual file routes, ``tsr``/vite config dirs, template soft-match,
constant miss-path (local + re-exported ``to``).
Dynamic form: ``$param`` (``meta.dynamic_form=tanstack``).
"""

from __future__ import annotations

import json
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
SKIP_DIRS = frozenset({"node_modules", "dist", "build", ".git", ".tanstack"})
NAV_SCAN_MARKERS = (
    "<Link",
    "<Navigate",
    "navigate(",
    "redirect(",
    " to=",
    "to:",
)
LINK_TAGS = frozenset({"Link", "Navigate"})
VIRTUAL_BUILDERS = frozenset(
    {"rootRoute", "route", "index", "layout", "physical", "defineVirtualSubtreeConfig"}
)

_CREATE_FILE_ROUTE_RE = re.compile(
    r"""createFileRoute\s*\(\s*(['"`])([^'"`]+)\1\s*,?\s*\)"""
)
_CREATE_ROUTE_PATH_RE = re.compile(
    r"""create(?:Root)?Route\s*\(\s*\{[^}]*?\bpath\s*:\s*(['"`])([^'"`]+)\1""",
    re.S,
)
_BY_FULLPATH_RE = re.compile(
    r"export\s+interface\s+FileRoutesByFullPath\s*\{([^}]*)\}",
    re.S,
)
_BY_TO_RE = re.compile(
    r"export\s+interface\s+FileRoutesByTo\s*\{([^}]*)\}",
    re.S,
)
_INTERFACE_KEY_RE = re.compile(r"""['"](/[^'"]*)['"]\s*:""")
_FULLPATHS_UNION_RE = re.compile(
    r"""fullPaths\s*:\s*((?:\s*\|\s*['"`][^'"`]+['"`])+)""",
    re.S,
)
_UNION_PATH_RE = re.compile(r"""['"`](/[^'"`]*)['"`]""")
_GEN_IMPORT_RE = re.compile(
    r"""from\s+['"](\./routes/[^'"]+)['"]"""
)
_TEMPLATE_INTERP_RE = re.compile(r"\$\{[^}]+\}")
_VITE_VIRTUAL_RE = re.compile(
    r"""virtualRouteConfig\s*:\s*['"]([^'"]+)['"]"""
)
_VITE_ROUTES_DIR_RE = re.compile(
    r"""routesDirectory\s*:\s*['"]([^'"]+)['"]"""
)
_VITE_GEN_RE = re.compile(
    r"""generatedRouteTree\s*:\s*['"]([^'"]+)['"]"""
)
_DOT_ESCAPE = "[.]"
_DOT_PLACEHOLDER = "\0DOT\0"


def sniff_vite_plugin_config(project_dir: Path) -> dict[str, str]:
    """Cheap regex scrape of ``vite.config.*`` TanStack plugin options."""
    project_dir = project_dir.resolve()
    out: dict[str, str] = {}
    for name in (
        "vite.config.ts",
        "vite.config.js",
        "vite.config.mts",
        "vite.config.mjs",
    ):
        path = project_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if match := _VITE_VIRTUAL_RE.search(text):
            out["virtualRouteConfig"] = match.group(1)
        if match := _VITE_ROUTES_DIR_RE.search(text):
            out["routesDirectory"] = match.group(1)
        if match := _VITE_GEN_RE.search(text):
            out["generatedRouteTree"] = match.group(1)
        if out:
            out["vite_config"] = name
            break
    return out


def load_tsr_config(project_dir: Path) -> dict[str, Any]:
    """Load ``tsr.config.json`` + vite plugin overrides (paths + virtual config)."""
    project_dir = project_dir.resolve()
    out: dict[str, Any] = {}
    cfg_path = project_dir / "tsr.config.json"
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data.get("routesDirectory"), str):
            out["routesDirectory"] = data["routesDirectory"]
        if isinstance(data.get("generatedRouteTree"), str):
            out["generatedRouteTree"] = data["generatedRouteTree"]
        if "virtualRouteConfig" in data:
            out["virtualRouteConfig"] = data["virtualRouteConfig"]
        out["tsr_config"] = "tsr.config.json"

    vite = sniff_vite_plugin_config(project_dir)
    # tsr wins on conflict; vite fills gaps
    for key in ("routesDirectory", "generatedRouteTree", "virtualRouteConfig"):
        if key not in out and key in vite:
            out[key] = vite[key]
    if "vite_config" in vite:
        out["vite_config"] = vite["vite_config"]
    return out


def find_config_paths(project_dir: Path) -> dict[str, str]:
    """String path overrides only (compat helper)."""
    cfg = load_tsr_config(project_dir)
    out: dict[str, str] = {}
    for key in ("routesDirectory", "generatedRouteTree"):
        if isinstance(cfg.get(key), str):
            out[key] = cfg[key]
    return out


def find_routes_dir(project_dir: Path, config: dict[str, Any] | None = None) -> Path | None:
    """Locate TanStack routes directory (default ``src/routes``)."""
    project_dir = project_dir.resolve()
    config = config if config is not None else load_tsr_config(project_dir)
    candidates: list[Path] = []
    routes_dir = config.get("routesDirectory")
    if isinstance(routes_dir, str):
        candidates.append(project_dir / routes_dir)
    candidates.extend(
        [
            project_dir / "src" / "routes",
            project_dir / "routes",
            project_dir / "app" / "routes",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def find_route_tree_gen(
    project_dir: Path, config: dict[str, Any] | None = None
) -> Path | None:
    """Locate ``routeTree.gen.ts`` (default ``src/routeTree.gen.ts``)."""
    project_dir = project_dir.resolve()
    config = config if config is not None else load_tsr_config(project_dir)
    candidates: list[Path] = []
    gen = config.get("generatedRouteTree")
    if isinstance(gen, str):
        candidates.append(project_dir / gen)
    candidates.extend(
        [
            project_dir / "src" / "routeTree.gen.ts",
            project_dir / "routeTree.gen.ts",
            project_dir / "src" / "routeTree.gen.js",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def join_route_paths(parent: str, child: str) -> str:
    """Join parent URL with absolute or relative child segment."""
    child = child.strip()
    if not child or child == "/":
        return normalize_url_path(parent) if parent else "/"
    if child.startswith("/"):
        return normalize_url_path(child)
    base = parent if parent and parent != "/" else ""
    return normalize_url_path(f"{base}/{child}")


def normalize_url_path(path: str) -> str:
    """Strip query/hash; collapse trailing slash except root."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path or "/"


def strip_pathless_segments(path: str) -> str:
    """Drop pathless ``_layout`` ids; strip trailing ``_`` nest opt-out.

    ``/project/$projectId_/session`` → ``/project/$projectId/session``
    (TanStack route id keeps ``$projectId_``; URL / fullPath does not.)
    """
    parts: list[str] = []
    for part in path.strip("/").split("/"):
        if not part:
            continue
        if part.startswith("_") and not part.startswith("$"):
            # Pathless layout id — omit from URL
            continue
        part = _strip_layout_opt_out(part)
        if part:
            parts.append(part)
    return "/" + "/".join(parts) if parts else "/"


def canonicalize_tanstack_url(path: str) -> str:
    """Normalize journey URL: query/hash strip + pathless/opt-out canonicalize."""
    return normalize_url_path(strip_pathless_segments(path.split("?", 1)[0]))

def parse_route_tree_gen(text: str) -> tuple[set[str], dict[str, str]]:
    """Extract navigable full paths + import path → rough module map.

    Prefers ``FileRoutesByTo`` / ``fullPaths``; falls back to ``FileRoutesByFullPath``.
    """
    paths: set[str] = set()

    for block_re in (_BY_TO_RE, _BY_FULLPATH_RE):
        match = block_re.search(text)
        if match:
            for key in _INTERFACE_KEY_RE.finditer(match.group(1)):
                paths.add(normalize_url_path(key.group(1)))

    union = _FULLPATHS_UNION_RE.search(text)
    if union:
        for key in _UNION_PATH_RE.finditer(union.group(1)):
            paths.add(normalize_url_path(key.group(1)))

    # Drop pure pathless ids if any leaked (no URL segments)
    paths = {p for p in paths if p}

    imports: dict[str, str] = {}
    for match in _GEN_IMPORT_RE.finditer(text):
        mod = match.group(1)
        # ./routes/posts.$postId → key by basename stem
        stem = Path(mod).name
        imports[stem] = mod[2:] if mod.startswith("./") else mod

    return paths, imports


def _is_group_segment(name: str) -> bool:
    return len(name) >= 2 and name.startswith("(") and name.endswith(")")


def _is_private_segment(name: str) -> bool:
    """``-components`` style — excluded from route tree."""
    return name.startswith("-")


def _is_pathless_segment(name: str) -> bool:
    """``_auth`` pathless layout — omitted from URL (not ``__root``)."""
    return name.startswith("_") and name != "__root__" and not name.startswith("$")


def _strip_layout_opt_out(segment: str) -> str:
    """``posts_`` → ``posts`` (trailing ``_`` = layout nest opt-out)."""
    if segment.endswith("_") and not segment.startswith("_") and len(segment) > 1:
        return segment[:-1]
    return segment


def _unescape_dots(segment: str) -> str:
    return segment.replace(_DOT_PLACEHOLDER, ".")


def _split_flat_segments(stem: str) -> list[str]:
    """``posts.$postId`` / ``script[.]js`` → segment list."""
    escaped = stem.replace(_DOT_ESCAPE, _DOT_PLACEHOLDER)
    return [_unescape_dots(p) for p in escaped.split(".") if p]


def file_to_route_url(rel: Path) -> tuple[str, bool, bool] | None:
    """Map routes-dir-relative file → ``(url_path, is_index, is_wildcard)``.

    Returns ``None`` for ``__root``, private ``-``, pathless-only layouts,
    and non-route files.
    """
    stem = rel.stem
    # Directory route token: posts/route.tsx → path = parent
    if stem == "route":
        flat_parts = list(rel.parent.parts)
        is_index = False
    else:
        flat_parts = list(rel.parent.parts) + _split_flat_segments(stem)
        is_index = flat_parts[-1] == "index" if flat_parts else stem == "index"

    if any(_is_private_segment(p) for p in flat_parts):
        return None
    if "__root" in flat_parts or stem == "__root":
        return None

    segments: list[str] = []
    for part in flat_parts:
        if part == "index":
            continue
        if part == "route":
            continue
        if _is_group_segment(part):
            continue
        if _is_pathless_segment(part):
            continue
        part = _strip_layout_opt_out(part)
        if not part:
            continue
        segments.append(part)

    # Pathless layout file alone (e.g. _pathlessLayout.tsx) → no URL leaf
    if not segments and not is_index and stem != "index":
        return None

    if not segments:
        return ("/", True, False)

    url = "/" + "/".join(segments)
    is_wildcard = any(s == "$" for s in segments)
    return (url, is_index or stem == "index", is_wildcard)


def extract_create_file_route_path(text: str) -> str | None:
    """Return first ``createFileRoute('/path')`` literal, if any."""
    match = _CREATE_FILE_ROUTE_RE.search(text)
    if not match:
        return None
    return match.group(2)


def url_from_file_route_id(route_id: str) -> str | None:
    """Convert createFileRoute id → journey URL (strip pathless).

    Pathless-only ids (``/_auth``) → ``None`` (layout, not leaf).
    """
    if route_id in {"__", "__root__", "/__root__"}:
        return None
    url = strip_pathless_segments(route_id)
    # If original had only pathless segments, strip yields "/" — treat as layout
    raw_parts = [p for p in route_id.strip("/").split("/") if p]
    if raw_parts and all(_is_pathless_segment(p) for p in raw_parts):
        return None
    return normalize_url_path(url)


def collect_layouts(
    routes_root: Path, route_file: Path, project_dir: Path
) -> list[str]:
    """Nearest pathless / ``route.tsx`` / ``__root`` layouts (nearest first)."""
    layouts: list[str] = []
    routes_root = routes_root.resolve()
    current = route_file.parent

    while True:
        for ext in SOURCE_EXTENSIONS:
            route_token = current / f"route{ext}"
            if route_token.is_file() and route_token.resolve() != route_file.resolve():
                layouts.append(
                    str(route_token.relative_to(project_dir)).replace("\\", "/")
                )
                break

        name = current.name
        if _is_pathless_segment(name) and current != routes_root:
            for ext in SOURCE_EXTENSIONS:
                candidate = current.parent / f"{name}{ext}"
                if candidate.is_file():
                    layouts.append(
                        str(candidate.relative_to(project_dir)).replace("\\", "/")
                    )
                    break

        if current == routes_root or current.parent == current:
            break
        current = current.parent

    for ext in SOURCE_EXTENSIONS:
        root = routes_root / f"__root{ext}"
        if root.is_file():
            layouts.append(str(root.relative_to(project_dir)).replace("\\", "/"))
            break

    return layouts


def _confidence_for_url(url: str) -> Confidence:
    if "$" in url:
        return Confidence.MEDIUM
    return Confidence.HIGH


def extract_filesystem_routes(
    project_dir: Path,
    routes_dir: Path | None = None,
    *,
    skip_dirs: set[Path] | None = None,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Walk routes dir; prefer ``createFileRoute`` path, else file notation.

    ``skip_dirs``: absolute dirs owned by ``__virtual.ts`` (FS walk skips them).
    """
    project_dir = project_dir.resolve()
    root = routes_dir or find_routes_dir(project_dir)
    skip = {p.resolve() for p in (skip_dirs or set())}
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []

    if root is None:
        gaps.append(
            JourneyGap(
                message="no TanStack routes directory found (src/routes)",
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
        if path.stem == "__virtual":
            continue
        # Skip files inside virtual subtrees (handled separately)
        if skip and any(
            path.resolve() == d or d in path.resolve().parents for d in skip
        ):
            continue
        rel = path.relative_to(root)
        if any(_is_private_segment(p) for p in rel.parts):
            continue

        source_file = str(path.relative_to(project_dir)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        url_path: str | None = None
        is_index = False
        is_wildcard = False

        route_id = extract_create_file_route_path(text)
        if route_id is not None:
            url_path = url_from_file_route_id(route_id)
            if url_path is None:
                continue  # pathless / root layout
            is_index = url_path == "/"
            is_wildcard = any(
                seg == "$" for seg in url_path.strip("/").split("/") if seg
            )
        else:
            mapped = file_to_route_url(rel)
            if mapped is None:
                continue
            url_path, is_index, is_wildcard = mapped

        url_path = canonicalize_tanstack_url(url_path)

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
                confidence=_confidence_for_url(url_path),
                source=RouteSource.FILESYSTEM,
            )
        )

    return routes, gaps


def extract_generated_routes(
    project_dir: Path,
    gen_file: Path | None = None,
    routes_dir: Path | None = None,
) -> tuple[list[RouteNode], list[JourneyGap], dict[str, str]]:
    """Parse ``routeTree.gen.ts`` → routes (``RouteSource.GENERATED``).

    Attaches FS ``component`` when a matching routes file exists.
    """
    project_dir = project_dir.resolve()
    meta: dict[str, str] = {}
    gen = gen_file or find_route_tree_gen(project_dir)
    if gen is None:
        meta["route_tree_gen"] = "absent"
        return [], [], meta

    try:
        text = gen.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            [],
            [
                JourneyGap(
                    message=f"routeTree.gen.ts unreadable: {exc}",
                    confidence=Confidence.LOW,
                )
            ],
            {"route_tree_gen": "error"},
        )

    rel_gen = str(gen.relative_to(project_dir)).replace("\\", "/")
    meta["route_tree_gen"] = rel_gen
    paths, _imports = parse_route_tree_gen(text)
    meta["gen_path_count"] = str(len(paths))

    root = routes_dir or find_routes_dir(project_dir)
    fs_by_url: dict[str, str] = {}
    if root is not None:
        fs_routes, _ = extract_filesystem_routes(project_dir, root)
        fs_by_url = {r.url_path: r.source_file for r in fs_routes}

    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    for url in sorted(paths):
        # Skip pathless-looking leftovers
        if any(
            _is_pathless_segment(p) for p in url.strip("/").split("/") if p
        ):
            continue
        component = fs_by_url.get(url)
        layout = None
        if component and root is not None:
            abs_comp = project_dir / component
            if abs_comp.is_file():
                layouts = collect_layouts(root, abs_comp, project_dir)
                layout = layouts[0] if layouts else None
        routes.append(
            RouteNode(
                url_path=url,
                component=component,
                source_file=component or rel_gen,
                source_line=1,
                is_index=url == "/" or url.endswith("/"),
                is_wildcard=any(p == "$" for p in url.split("/")),
                layout=layout,
                confidence=_confidence_for_url(url),
                source=RouteSource.GENERATED,
            )
        )

    # Cross-check: FS paths missing from gen
    for url, source_file in sorted(fs_by_url.items()):
        if url not in paths:
            gaps.append(
                JourneyGap(
                    message=f"FS route missing from routeTree.gen.ts: {url}",
                    source_file=source_file,
                    confidence=Confidence.MEDIUM,
                )
            )
    for url in sorted(paths):
        if url not in fs_by_url and root is not None:
            gaps.append(
                JourneyGap(
                    message=f"gen route not found on filesystem: {url}",
                    source_file=rel_gen,
                    confidence=Confidence.LOW,
                )
            )

    return routes, gaps, meta


def extract_code_based_routes(
    project_dir: Path,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Fallback: scan ``createRoute({ path })`` when no gen/FS routes."""
    project_dir = project_dir.resolve()
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    seen: set[str] = set()

    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "createRoute" not in text and "createRootRoute" not in text:
            continue
        source_file = str(path.relative_to(project_dir)).replace("\\", "/")
        for match in _CREATE_ROUTE_PATH_RE.finditer(text):
            url = normalize_url_path(match.group(2))
            if url in seen:
                continue
            seen.add(url)
            routes.append(
                RouteNode(
                    url_path=url,
                    component=source_file,
                    source_file=source_file,
                    source_line=text[: match.start()].count("\n") + 1,
                    is_index=url == "/",
                    is_wildcard="$" in url,
                    confidence=_confidence_for_url(url),
                    source=RouteSource.CONFIG_AST,
                )
            )

    if not routes:
        gaps.append(
            JourneyGap(
                message="no TanStack routes found (gen, FS, or createRoute)",
                confidence=Confidence.LOW,
            )
        )
    return routes, gaps


def _prefix_physical_url(prefix: str, url: str) -> str:
    """Apply physical mount prefix without double-joining absolute paths."""
    if prefix in {"", "/"}:
        return normalize_url_path(url)
    if url.startswith(normalize_url_path(prefix) + "/") or url == normalize_url_path(
        prefix
    ):
        return normalize_url_path(url)
    if url == "/":
        return normalize_url_path(prefix)
    return join_route_paths(prefix, url.lstrip("/"))


def _component_rel(
    project_dir: Path, routes_dir: Path | None, file_ref: str | None
) -> str | None:
    if not file_ref:
        return None
    candidates: list[Path] = []
    if routes_dir is not None:
        candidates.append(routes_dir / file_ref)
    candidates.append(project_dir / file_ref)
    candidates.append(project_dir / "src" / "routes" / file_ref)
    for base in candidates:
        paths = [base] if base.suffix else [base.with_suffix(ext) for ext in SOURCE_EXTENSIONS]
        if not base.suffix:
            paths.append(base)  # already has extension in ref sometimes
        for path in paths:
            if path.is_file():
                try:
                    return str(path.relative_to(project_dir)).replace("\\", "/")
                except ValueError:
                    return str(path)
    if routes_dir is not None:
        try:
            return str((routes_dir / file_ref).relative_to(project_dir)).replace(
                "\\", "/"
            )
        except ValueError:
            pass
    return file_ref.replace("\\", "/")


def walk_virtual_json(
    node: dict[str, Any],
    *,
    parent_path: str,
    project_dir: Path,
    routes_dir: Path | None,
    source_file: str,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Walk ``tsr.config.json`` inline ``virtualRouteConfig`` object."""
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    typ = node.get("type")
    children = node.get("children") if isinstance(node.get("children"), list) else []
    file_ref = node.get("file") if isinstance(node.get("file"), str) else None

    if typ == "root":
        for child in children:
            if isinstance(child, dict):
                r, g = walk_virtual_json(
                    child,
                    parent_path="/",
                    project_dir=project_dir,
                    routes_dir=routes_dir,
                    source_file=source_file,
                )
                routes.extend(r)
                gaps.extend(g)
        return routes, gaps

    if typ == "layout":
        for child in children:
            if isinstance(child, dict):
                r, g = walk_virtual_json(
                    child,
                    parent_path=parent_path,
                    project_dir=project_dir,
                    routes_dir=routes_dir,
                    source_file=source_file,
                )
                routes.extend(r)
                gaps.extend(g)
        return routes, gaps

    if typ == "index":
        url = normalize_url_path(parent_path or "/")
        component = _component_rel(project_dir, routes_dir, file_ref)
        routes.append(
            RouteNode(
                url_path=url,
                component=component,
                source_file=component or source_file,
                source_line=1,
                is_index=True,
                is_wildcard=False,
                confidence=Confidence.HIGH,
                source=RouteSource.CONFIG_AST,
            )
        )
        return routes, gaps

    if typ == "route":
        path = node.get("path") if isinstance(node.get("path"), str) else ""
        url = join_route_paths(parent_path, path) if path else normalize_url_path(parent_path)
        if file_ref:
            component = _component_rel(project_dir, routes_dir, file_ref)
            routes.append(
                RouteNode(
                    url_path=url,
                    component=component,
                    source_file=component or source_file,
                    source_line=1,
                    is_index=False,
                    is_wildcard=any(p == "$" or p.startswith("$") for p in url.split("/")),
                    confidence=_confidence_for_url(url),
                    source=RouteSource.CONFIG_AST,
                )
            )
        for child in children:
            if isinstance(child, dict):
                r, g = walk_virtual_json(
                    child,
                    parent_path=url,
                    project_dir=project_dir,
                    routes_dir=routes_dir,
                    source_file=source_file,
                )
                routes.extend(r)
                gaps.extend(g)
        return routes, gaps

    if typ == "physical":
        path = node.get("path") if isinstance(node.get("path"), str) else ""
        directory = node.get("directory") or node.get("dir") or node.get("file")
        if not isinstance(directory, str):
            gaps.append(
                JourneyGap(
                    message=f"virtual physical route missing directory at {parent_path}",
                    source_file=source_file,
                    confidence=Confidence.LOW,
                )
            )
            return routes, gaps
        prefix = join_route_paths(parent_path, path) if path else parent_path
        phys_dir = None
        if routes_dir is not None and (routes_dir / directory).is_dir():
            phys_dir = routes_dir / directory
        elif (project_dir / directory).is_dir():
            phys_dir = project_dir / directory
        if phys_dir is None:
            gaps.append(
                JourneyGap(
                    message=(
                        f"virtual physical directory not found: {directory} "
                        f"(prefix {prefix})"
                    ),
                    source_file=source_file,
                    confidence=Confidence.MEDIUM,
                )
            )
            return routes, gaps
        fs_routes, fs_gaps = extract_filesystem_routes(project_dir, phys_dir)
        gaps.extend(fs_gaps)
        for route in fs_routes:
            url = _prefix_physical_url(prefix, route.url_path)
            # Remap when phys_dir is nested under routes — component already relative
            routes.append(
                RouteNode(
                    url_path=url,
                    component=route.component,
                    source_file=route.source_file,
                    source_line=route.source_line,
                    is_index=route.is_index,
                    is_wildcard=route.is_wildcard,
                    layout=route.layout,
                    confidence=route.confidence,
                    source=RouteSource.CONFIG_AST,
                )
            )
        return routes, gaps

    gaps.append(
        JourneyGap(
            message=f"unknown virtualRouteConfig node type: {typ!r}",
            source_file=source_file,
            confidence=Confidence.LOW,
        )
    )
    return routes, gaps


def _call_callee_name(source_bytes: bytes, call: Any) -> str | None:
    if not call.children:
        return None
    callee = call.children[0]
    if callee.type == "identifier":
        return node_text(source_bytes, callee)
    if callee.type == "member_expression":
        parts = [
            c for c in callee.children if c.type in {"identifier", "property_identifier"}
        ]
        if parts:
            return node_text(source_bytes, parts[-1])
    return None


def _call_args(call: Any) -> list[Any]:
    args = next((c for c in call.children if c.type == "arguments"), None)
    if args is None:
        return []
    out: list[Any] = []
    for child in args.children:
        if child.type in {"(", ")", ","}:
            continue
        out.append(child)
    return out


def _array_elements(arr: Any) -> list[Any]:
    return [c for c in arr.children if c.type not in {"[", "]", ","}]


def walk_virtual_call(
    source_bytes: bytes,
    call: Any,
    *,
    parent_path: str,
    project_dir: Path,
    routes_dir: Path | None,
    source_file: str,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Walk ``rootRoute`` / ``route`` / ``index`` / ``layout`` / ``physical`` calls."""
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    name = _call_callee_name(source_bytes, call)
    if name not in VIRTUAL_BUILDERS:
        return routes, gaps

    args = _call_args(call)

    def emit(url: str, file_ref: str | None, is_index: bool) -> None:
        component = _component_rel(project_dir, routes_dir, file_ref)
        routes.append(
            RouteNode(
                url_path=normalize_url_path(url),
                component=component,
                source_file=component or source_file,
                source_line=call.start_point[0] + 1,
                is_index=is_index,
                is_wildcard=any(
                    p == "$" or (p.startswith("$") and p != "$")
                    for p in url.split("/")
                    if p
                )
                or any(p == "$" for p in url.split("/")),
                confidence=_confidence_for_url(url),
                source=RouteSource.CONFIG_AST,
            )
        )

    def recurse_array(arr: Any, path: str) -> None:
        for el in _array_elements(arr):
            if el.type == "call_expression":
                r, g = walk_virtual_call(
                    source_bytes,
                    el,
                    parent_path=path,
                    project_dir=project_dir,
                    routes_dir=routes_dir,
                    source_file=source_file,
                )
                routes.extend(r)
                gaps.extend(g)

    if name == "defineVirtualSubtreeConfig":
        if args and args[0].type == "array":
            recurse_array(args[0], parent_path)
        elif args and args[0].type == "arrow_function":
            gaps.append(
                JourneyGap(
                    message="virtual subtree config is a function — not evaluated",
                    source_file=source_file,
                    source_line=call.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
        return routes, gaps

    if name == "rootRoute":
        # rootRoute(file, children)
        children = next((a for a in args if a.type == "array"), None)
        if children is not None:
            recurse_array(children, "/")
        return routes, gaps

    if name == "index":
        file_ref = string_literal_value(source_bytes, args[0]) if args else None
        emit(parent_path or "/", file_ref, True)
        return routes, gaps

    if name == "layout":
        # layout(file, children) | layout(id, file, children)
        children = next((a for a in args if a.type == "array"), None)
        if children is not None:
            recurse_array(children, parent_path)
        return routes, gaps

    if name == "route":
        # route(path, file?, children?) | route(path, children)
        if not args:
            return routes, gaps
        path_lit = (
            string_literal_value(source_bytes, args[0])
            if args[0].type in {"string", "template_string"}
            else None
        )
        if path_lit is None:
            gaps.append(
                JourneyGap(
                    message="virtual route() path not a string literal",
                    source_file=source_file,
                    source_line=call.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
            return routes, gaps
        url = join_route_paths(parent_path, path_lit)
        file_ref = None
        children = None
        for arg in args[1:]:
            if arg.type in {"string", "template_string"} and file_ref is None:
                file_ref = string_literal_value(source_bytes, arg)
            elif arg.type == "array":
                children = arg
        if file_ref:
            emit(url, file_ref, False)
        if children is not None:
            recurse_array(children, url)
        return routes, gaps

    if name == "physical":
        # physical(path, dir) | physical(dir) | physical('', dir)
        strs = [
            string_literal_value(source_bytes, a)
            for a in args
            if a.type in {"string", "template_string"}
        ]
        strs = [s for s in strs if s is not None]
        if not strs:
            gaps.append(
                JourneyGap(
                    message="virtual physical() missing path/directory literals",
                    source_file=source_file,
                    source_line=call.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
            return routes, gaps
        if len(strs) == 1:
            path_prefix, directory = "", strs[0]
        else:
            path_prefix, directory = strs[0], strs[1]
        prefix = join_route_paths(parent_path, path_prefix) if path_prefix else parent_path
        phys_dir = None
        if routes_dir is not None and (routes_dir / directory).is_dir():
            phys_dir = routes_dir / directory
        elif (project_dir / directory).is_dir():
            phys_dir = project_dir / directory
        if phys_dir is None:
            gaps.append(
                JourneyGap(
                    message=(
                        f"virtual physical directory not found: {directory} "
                        f"(prefix {prefix})"
                    ),
                    source_file=source_file,
                    source_line=call.start_point[0] + 1,
                    confidence=Confidence.MEDIUM,
                )
            )
            return routes, gaps
        fs_routes, fs_gaps = extract_filesystem_routes(project_dir, phys_dir)
        gaps.extend(fs_gaps)
        for route in fs_routes:
            url = _prefix_physical_url(prefix, route.url_path)
            routes.append(
                RouteNode(
                    url_path=url,
                    component=route.component,
                    source_file=route.source_file,
                    source_line=route.source_line,
                    is_index=route.is_index,
                    is_wildcard=route.is_wildcard,
                    layout=route.layout,
                    confidence=route.confidence,
                    source=RouteSource.CONFIG_AST,
                )
            )
        return routes, gaps

    return routes, gaps


def parse_virtual_routes_module(
    path: Path,
    project_dir: Path,
    routes_dir: Path | None,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Parse a ``routes.ts`` / ``__virtual.ts`` virtual config module."""
    project_dir = project_dir.resolve()
    source_file = str(path.relative_to(project_dir)).replace("\\", "/")
    parsed = parse_js_ts(path)
    if not parsed.ok or parsed.root is None:
        return [], [
            JourneyGap(
                message=f"virtual route module parse failed: {parsed.detail}",
                source_file=source_file,
                confidence=Confidence.LOW,
            )
        ]

    source_bytes = parsed.source_bytes
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []

    # Prefer exported `routes` / default export call, else any top-level builder.
    roots: list[Any] = []

    def collect(node: Any) -> None:
        if node.type == "call_expression":
            name = _call_callee_name(source_bytes, node)
            if name in {"rootRoute", "defineVirtualSubtreeConfig"}:
                roots.append(node)
                return
        for child in node.children:
            collect(child)

    collect(parsed.root)
    if not roots:
        gaps.append(
            JourneyGap(
                message=(
                    "virtual route module has no rootRoute / "
                    "defineVirtualSubtreeConfig call"
                ),
                source_file=source_file,
                confidence=Confidence.MEDIUM,
            )
        )
        return routes, gaps

    for root in roots:
        r, g = walk_virtual_call(
            source_bytes,
            root,
            parent_path="/",
            project_dir=project_dir,
            routes_dir=routes_dir,
            source_file=source_file,
        )
        routes.extend(r)
        gaps.extend(g)

    # Dedupe by url (first wins)
    seen: set[str] = set()
    deduped: list[RouteNode] = []
    for route in routes:
        if route.url_path in seen:
            continue
        seen.add(route.url_path)
        deduped.append(route)
    return deduped, gaps


def extract_virtual_routes(
    project_dir: Path,
    config: dict[str, Any] | None = None,
    routes_dir: Path | None = None,
) -> tuple[list[RouteNode], list[JourneyGap], dict[str, str]]:
    """Extract routes from ``virtualRouteConfig`` (JSON object or module path)."""
    project_dir = project_dir.resolve()
    config = config if config is not None else load_tsr_config(project_dir)
    routes_dir = routes_dir or find_routes_dir(project_dir, config)
    meta: dict[str, str] = {}
    virtual = config.get("virtualRouteConfig")

    if virtual is None:
        meta["virtual_routes"] = "absent"
        return [], [], meta

    if isinstance(virtual, dict):
        meta["virtual_routes"] = "tsr.config.json"
        routes, gaps = walk_virtual_json(
            virtual,
            parent_path="/",
            project_dir=project_dir,
            routes_dir=routes_dir,
            source_file="tsr.config.json",
        )
        meta["virtual_count"] = str(len(routes))
        return routes, gaps, meta

    if isinstance(virtual, str):
        path = (project_dir / virtual).resolve()
        if not path.is_file():
            return (
                [],
                [
                    JourneyGap(
                        message=f"virtualRouteConfig file not found: {virtual}",
                        confidence=Confidence.MEDIUM,
                    )
                ],
                {"virtual_routes": "missing_file"},
            )
        rel = str(path.relative_to(project_dir)).replace("\\", "/")
        meta["virtual_routes"] = rel
        routes, gaps = parse_virtual_routes_module(path, project_dir, routes_dir)
        meta["virtual_count"] = str(len(routes))
        return routes, gaps, meta

    return (
        [],
        [
            JourneyGap(
                message=f"unsupported virtualRouteConfig type: {type(virtual).__name__}",
                confidence=Confidence.LOW,
            )
        ],
        {"virtual_routes": "unsupported"},
    )


def find_virtual_subtree_files(routes_dir: Path) -> list[Path]:
    """Locate ``__virtual.ts`` / ``__virtual.js`` under routes dir."""
    found: list[Path] = []
    for path in sorted(routes_dir.rglob("__virtual.*")):
        if path.suffix in SOURCE_EXTENSIONS and path.is_file():
            found.append(path)
    return found


def extract_virtual_subtrees(
    project_dir: Path,
    routes_dir: Path,
) -> tuple[list[RouteNode], list[JourneyGap], set[Path]]:
    """Parse in-tree ``__virtual.ts`` subtrees; return covered dirs to skip in FS walk."""
    project_dir = project_dir.resolve()
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    covered: set[Path] = set()

    for virt in find_virtual_subtree_files(routes_dir):
        subtree_dir = virt.parent
        covered.add(subtree_dir.resolve())
        # Parent path from directory segments under routes_dir
        rel = subtree_dir.relative_to(routes_dir)
        segs: list[str] = []
        for part in rel.parts:
            if _is_group_segment(part) or _is_pathless_segment(part):
                continue
            if _is_private_segment(part):
                continue
            segs.append(_strip_layout_opt_out(part))
        parent_path = "/" + "/".join(segs) if segs else "/"

        parsed_routes, parsed_gaps = parse_virtual_routes_module(
            virt, project_dir, subtree_dir
        )
        gaps.extend(parsed_gaps)
        if not parsed_routes and not parsed_gaps:
            gaps.append(
                JourneyGap(
                    message=f"__virtual.ts produced no routes: {virt.name}",
                    source_file=str(virt.relative_to(project_dir)).replace("\\", "/"),
                    confidence=Confidence.MEDIUM,
                )
            )
            continue
        for route in parsed_routes:
            url = (
                route.url_path
                if parent_path in {"", "/"}
                else join_route_paths(parent_path, route.url_path.lstrip("/"))
                if route.url_path != "/"
                else parent_path
            )
            if route.is_index and route.url_path == "/":
                url = parent_path
            routes.append(
                RouteNode(
                    url_path=normalize_url_path(url),
                    component=route.component,
                    source_file=route.source_file,
                    source_line=route.source_line,
                    is_index=route.is_index,
                    is_wildcard=route.is_wildcard,
                    layout=route.layout,
                    confidence=route.confidence,
                    source=RouteSource.CONFIG_AST,
                )
            )
    return routes, gaps, covered


def extract_routes(
    project_dir: Path,
) -> tuple[list[RouteNode], list[JourneyGap], dict[str, str]]:
    """Full route discovery: gen → virtual → FS → createRoute."""
    project_dir = project_dir.resolve()
    config = load_tsr_config(project_dir)
    routes_dir = find_routes_dir(project_dir, config)
    gen_file = find_route_tree_gen(project_dir, config)
    meta: dict[str, str] = {
        "routes_dir": (
            str(routes_dir.relative_to(project_dir)).replace("\\", "/")
            if routes_dir
            else ""
        ),
        "dynamic_form": "tanstack",
    }
    if "tsr_config" in config:
        meta["tsr_config"] = str(config["tsr_config"])
    if "vite_config" in config:
        meta["vite_config"] = str(config["vite_config"])

    if gen_file is not None:
        routes, gaps, gen_meta = extract_generated_routes(
            project_dir, gen_file, routes_dir
        )
        meta.update(gen_meta)
        meta["route_source"] = "generated"
        # Still note virtual config presence for meta
        if config.get("virtualRouteConfig") is not None:
            meta["virtual_routes"] = "superseded_by_gen"
        if routes:
            return routes, gaps, meta

    virtual_routes, virtual_gaps, virtual_meta = extract_virtual_routes(
        project_dir, config, routes_dir
    )
    meta.update(virtual_meta)
    if virtual_routes:
        meta["route_source"] = "virtual"
        return virtual_routes, virtual_gaps, meta
    gaps_acc = list(virtual_gaps)

    if routes_dir is not None:
        subtree_routes, subtree_gaps, covered = extract_virtual_subtrees(
            project_dir, routes_dir
        )
        gaps_acc.extend(subtree_gaps)
        routes, gaps = extract_filesystem_routes(
            project_dir, routes_dir, skip_dirs=covered
        )
        gaps_acc.extend(gaps)
        # Merge subtree virtual routes (override FS for same URL)
        by_url = {r.url_path: r for r in routes}
        for route in subtree_routes:
            by_url[route.url_path] = route
        routes = list(by_url.values())
        meta["route_source"] = "filesystem"
        meta["route_tree_gen"] = meta.get("route_tree_gen", "absent")
        if covered:
            meta["virtual_subtrees"] = str(len(covered))
        if routes:
            return routes, gaps_acc, meta

    routes, gaps = extract_code_based_routes(project_dir)
    gaps_acc.extend(gaps)
    meta["route_source"] = "config_ast"
    return routes, gaps_acc, meta


# --- navigation ----------------------------------------------------------------


def soften_template_to(raw: str, known_routes: set[str]) -> str | None:
    """Map ``/posts/${id}`` → ``/posts/$postId`` when unique soft match."""
    path = normalize_url_path(raw.split("?", 1)[0])
    if "${" not in path:
        return path

    regex_body: list[str] = []
    last = 0
    for match in _TEMPLATE_INTERP_RE.finditer(path):
        regex_body.append(re.escape(path[last : match.start()]))
        regex_body.append(r"\$[^/]+")
        last = match.end()
    regex_body.append(re.escape(path[last:]))
    pattern = re.compile("^" + "".join(regex_body) + "$")
    matches = sorted(r for r in known_routes if pattern.match(r))
    if not matches:
        return None
    return matches[0]


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
    node = _property_node_from_object(source_bytes, obj, prop)
    if node is None:
        return None
    if node.type in {"string", "template_string"}:
        return string_literal_value(source_bytes, node)
    return None


def _property_node_from_object(source_bytes: bytes, obj: Any, prop: str) -> Any | None:
    for child in obj.children:
        if child.type != "pair":
            continue
        key = None
        value_node = None
        for part in child.children:
            if part.type == "property_identifier" and key is None:
                key = node_text(source_bytes, part)
            elif part.type == "string" and key is None:
                key = string_literal_value(source_bytes, part)
            elif part.type in {":", ",", "comment"}:
                continue
            elif key is not None and part.type not in {"comment"}:
                value_node = part
        if key == prop and value_node is not None:
            return value_node
    return None


def resolve_path_expression(
    source_bytes: bytes,
    expr: Any,
    parsed: JsParseResult,
    project_dir: Path | None,
    source_file: str,
) -> str | None:
    """Resolve string / template / ``{ to }`` / const / ``Obj.key`` (miss-path)."""
    if expr.type == "string":
        return string_literal_value(source_bytes, expr)

    if expr.type == "template_string":
        raw = node_text(source_bytes, expr)
        if len(raw) >= 2 and raw[0] == "`" and raw[-1] == "`":
            inner = raw[1:-1]
        else:
            inner = raw
        return inner

    if expr.type == "object":
        to_node = _property_node_from_object(source_bytes, expr, "to")
        if to_node is None:
            return None
        if to_node.type in {"string", "template_string"}:
            return string_literal_value(source_bytes, to_node)
        return resolve_path_expression(
            source_bytes, to_node, parsed, project_dir, source_file
        )

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
        parts = [
            c for c in expr.children if c.type in {"identifier", "property_identifier"}
        ]
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
        # Skip generated route tree (no real nav)
        if path.name.startswith("routeTree.gen"):
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
    """Scan ``Link`` / ``Navigate`` / ``navigate`` / ``redirect`` targets."""
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

            if "${" in to_path:
                softened = soften_template_to(to_path, known_routes)
                if softened is None:
                    gaps.append(
                        JourneyGap(
                            message=f"dynamic to target unresolved: {to_path}",
                            source_file=edge.source_file,
                            source_line=edge.source_line,
                            confidence=Confidence.LOW,
                        )
                    )
                    continue
                to_path = softened
                confidence = Confidence.MEDIUM

            to_path = normalize_url_path(to_path)
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
    """Extract TanStack nav edges from one parsed file."""
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
        edges.append(
            NavEdge(
                from_path=from_path,
                to_path=raw,
                source_file=source_file,
                source_line=line,
                kind=kind,
                confidence=Confidence.HIGH,
            )
        )

    def walk(node: Any) -> None:
        if node.type in {"jsx_self_closing_element", "jsx_opening_element"}:
            name = _jsx_name(source_bytes, node)
            if name in LINK_TAGS:
                kind = "redirect" if name == "Navigate" else "link"
                line = node.start_point[0] + 1
                to_raw = _jsx_attr_string(source_bytes, node, "to")
                if to_raw is not None:
                    emit_path(to_raw, kind, line, f"dynamic {name} to unresolved")
                else:
                    expr = _jsx_attr_expression(source_bytes, node, "to")
                    if expr is not None:
                        resolved = resolve_path_expression(
                            source_bytes, expr, parsed, project_dir, source_file
                        )
                        emit_path(
                            resolved, kind, line, f"dynamic {name} to unresolved"
                        )
                    elif _jsx_has_attr(source_bytes, node, "to"):
                        gaps.append(
                            JourneyGap(
                                message=f"dynamic {name} to unresolved",
                                source_file=source_file,
                                source_line=line,
                                confidence=Confidence.LOW,
                            )
                        )

        if node.type == "call_expression":
            call_kind = _nav_call_kind(source_bytes, node)
            if call_kind is not None:
                line = node.start_point[0] + 1
                target = _nav_call_to_arg(source_bytes, node)
                if target is None:
                    gaps.append(
                        JourneyGap(
                            message=f"dynamic {call_kind} target unresolved",
                            source_file=source_file,
                            source_line=line,
                            confidence=Confidence.LOW,
                        )
                    )
                else:
                    raw = resolve_path_expression(
                        source_bytes, target, parsed, project_dir, source_file
                    )
                    # object arg already resolved via ``to`` inside resolve
                    if raw is None and target.type == "object":
                        raw = _property_from_object(source_bytes, target, "to")
                    emit_path(
                        raw,
                        call_kind,
                        line,
                        f"dynamic {call_kind} target unresolved",
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


def _jsx_attr_string(
    source_bytes: bytes, opening_or_self: Any, attr_name: str
) -> str | None:
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif name == attr_name and part.type == "string":
                return string_literal_value(source_bytes, part)
    return None


def _jsx_attr_expression(
    source_bytes: bytes, opening_or_self: Any, attr_name: str
) -> Any | None:
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif name == attr_name and part.type == "jsx_expression":
                for inner in part.children:
                    if inner.type in {"{", "}"}:
                        continue
                    return inner
    return None


def _nav_call_kind(source_bytes: bytes, call: Any) -> str | None:
    """``navigate`` / ``router.navigate`` → navigate; ``redirect`` → redirect."""
    if not call.children:
        return None
    callee = call.children[0]
    if callee.type == "identifier":
        name = node_text(source_bytes, callee)
        if name == "navigate":
            return "navigate"
        if name == "redirect":
            return "redirect"
        return None
    if callee.type == "member_expression":
        parts = [
            c for c in callee.children if c.type in {"identifier", "property_identifier"}
        ]
        if len(parts) < 2:
            return None
        method = node_text(source_bytes, parts[-1])
        if method == "navigate":
            return "navigate"
        if method == "redirect":
            return "redirect"
    return None


def _nav_call_to_arg(source_bytes: bytes, call: Any) -> Any | None:
    """First arg of navigate/redirect — string or ``{ to: ... }`` object."""
    del source_bytes
    args = next((c for c in call.children if c.type == "arguments"), None)
    if args is None:
        return None
    for child in args.children:
        if child.type in {"(", ")", ","}:
            continue
        return child
    return None


class TanStackRouterExtractor:
    """TanStack Router plugin — gen/FS routes + parse_js navigation."""

    framework = "tanstack-router"

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
        ast_result: AstResult | None = None,
    ) -> JourneyGraph:
        del detection, ast_result
        project_dir = project_dir.resolve()
        routes, gaps, meta = extract_routes(project_dir)

        edges, nav_gaps = extract_navigation(project_dir, routes)
        gaps.extend(nav_gaps)

        return JourneyGraph(
            framework=self.framework,
            project_root=project_dir,
            routes=tuple(routes),
            edges=tuple(edges),
            gaps=tuple(gaps),
            meta={
                **meta,
                "parser": "tree_sitter",
                "edges": str(len(edges)),
            },
        )
