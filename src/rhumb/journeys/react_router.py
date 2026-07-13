from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rhumb.framework import FrameworkDetection
from rhumb.journeys.parse_js import (
    JsParseResult,
    extract_imports,
    find_exported_initializer,
    follow_export,
    node_text,
    parse_js_ts,
    string_literal_value,
)
from rhumb.journeys.types import (
    Confidence,
    JourneyGap,
    JourneyGraph,
    NavEdge,
    RouteNode,
    RouteSource,
)

ROUTER_PACKAGES = {"react-router", "react-router-dom"}
ROUTE_MARKERS = (
    "createBrowserRouter",
    "createHashRouter",
    "createMemoryRouter",
    "createRoutesFromElements",
    "<Routes",
    "<Route",
)
IMPORT_RE = re.compile(
    r"""from\s+["'](react-router(?:-dom)?)["']""",
)
ROUTE_PATH_RE = re.compile(
    r"""<Route\b[^>]*\bpath\s*=\s*["']([^"']+)["']""",
)
ROUTE_ELEMENT_RE = re.compile(
    r"""element\s*=\s*\{<(\w+)\s*/>\}""",
)
SOURCE_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js")
NAV_SCAN_MARKERS = ("<Link", "<NavLink", "navigate(", "redirect(", "path:")
LINK_TAGS = frozenset({"Link", "NavLink"})
CALL_NAV_KINDS = {"navigate": "navigate", "redirect": "redirect"}
DATA_ROUTER_FNS = frozenset(
    {"createBrowserRouter", "createHashRouter", "createMemoryRouter"}
)


@dataclass(frozen=True)
class RouteCandidate:
    """Source file likely containing React Router configuration."""

    path: Path
    markers: tuple[str, ...]
    imports_router: bool


def find_route_candidates(project_dir: Path) -> list[RouteCandidate]:
    """Heuristic scan for files that define React Router routes."""
    project_dir = project_dir.resolve()
    candidates: list[RouteCandidate] = []

    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in {".tsx", ".ts", ".jsx", ".js"}:
            continue
        if any(part in path.parts for part in {"node_modules", "dist", "build"}):
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue

        imports_router = bool(IMPORT_RE.search(source))
        markers = tuple(marker for marker in ROUTE_MARKERS if marker in source)
        if imports_router and markers:
            candidates.append(
                RouteCandidate(
                    path=path.relative_to(project_dir),
                    markers=markers,
                    imports_router=True,
                )
            )

    return sorted(candidates, key=lambda item: (len(item.markers), str(item.path)), reverse=True)


def join_route_paths(parent_prefix: str, child_path: str | None, is_index: bool) -> str:
    """Join parent prefix with a child path segment (absolute child wins)."""
    if child_path == "*":
        return "*"
    if child_path and child_path.startswith("/"):
        return child_path

    parent = parent_prefix or ""
    if parent and not parent.startswith("/") and parent != "*":
        parent = "/" + parent

    if is_index and not child_path:
        return parent or "/"

    if not child_path:
        return parent or "/"

    if not parent or parent == "/":
        return "/" + child_path.lstrip("/")

    return parent.rstrip("/") + "/" + child_path.lstrip("/")


def extract_routes_regex(source: str, source_file: str) -> list[RouteNode]:
    """Regex fallback when tree-sitter parse fails."""
    routes: list[RouteNode] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        path_match = ROUTE_PATH_RE.search(line)
        if not path_match:
            continue
        url_path = path_match.group(1)
        element_match = ROUTE_ELEMENT_RE.search(line)
        component = element_match.group(1) if element_match else None
        routes.append(
            RouteNode(
                url_path=url_path,
                component=component,
                source_file=source_file,
                source_line=line_no,
                is_index="index" in line,
                is_wildcard=url_path == "*",
                confidence=Confidence.MEDIUM,
                source=RouteSource.CONFIG_AST,
            )
        )
    return routes


def extract_routes_from_parse(
    parsed: JsParseResult,
    source_file: str,
    project_dir: Path,
) -> tuple[list[RouteNode], list[JourneyGap]]:
    """Extract routes from JSX ``<Route>`` trees and data-router object configs."""
    if not parsed.ok or parsed.root is None:
        return [], [
            JourneyGap(
                message=f"parse_js failed for {source_file}: {parsed.detail}",
                source_file=source_file,
                confidence=Confidence.LOW,
            )
        ]

    local_imports = extract_imports(parsed)
    routes: list[RouteNode] = []
    gaps: list[JourneyGap] = []
    source_bytes = parsed.source_bytes
    seen_modules: set[str] = set()

    def resolve_component(name: str | None) -> str | None:
        if not name:
            return None
        module = local_imports.get(name)
        if not module:
            return name
        resolved = _resolve_module_path(project_dir, Path(source_file), module)
        return resolved or name

    def resolve_lazy(node: Any) -> str | None:
        module = _lazy_import_module(source_bytes, node)
        if not module:
            return None
        return _resolve_module_path(project_dir, Path(source_file), module) or module

    # --- JSX Route tree (incl. createRoutesFromElements children) ---
    def walk_jsx(node: Any, parent_prefix: str, layout: str | None) -> None:
        if node.type == "jsx_self_closing_element" and _jsx_name(source_bytes, node) == "Route":
            attrs = _jsx_attrs(source_bytes, node)
            _emit_jsx_leaf(attrs, node, parent_prefix, layout)
            return

        if node.type == "jsx_element":
            opening = next((c for c in node.children if c.type == "jsx_opening_element"), None)
            if opening is not None and _jsx_name(source_bytes, opening) == "Route":
                attrs = _jsx_attrs(source_bytes, opening)
                child_routes = [
                    c
                    for c in node.children
                    if c.type in {"jsx_element", "jsx_self_closing_element"}
                    and _is_route_node(source_bytes, c)
                ]
                element_name = attrs.get("element")
                path_info = _path_from_jsx_attrs(attrs, source_bytes, opening, gaps, source_file)
                path, is_index, confidence = path_info
                full = join_route_paths(parent_prefix, path, is_index) if path is not None or is_index else parent_prefix

                if child_routes:
                    child_layout = element_name or layout
                    child_prefix = parent_prefix if path is None and not is_index else full
                    for child in child_routes:
                        walk_jsx(child, child_prefix, child_layout)
                    if path is not None or is_index:
                        routes.append(
                            _make_route(
                                url_path=full,
                                component=resolve_component(element_name),
                                source_file=source_file,
                                source_line=opening.start_point[0] + 1,
                                is_index=is_index,
                                layout=resolve_component(layout) if layout else None,
                                confidence=confidence,
                            )
                        )
                else:
                    _emit_jsx_leaf(attrs, opening, parent_prefix, layout)
                return

        for child in node.children:
            walk_jsx(child, parent_prefix, layout)

    def _emit_jsx_leaf(
        attrs: dict[str, str | None],
        node: Any,
        parent_prefix: str,
        layout: str | None,
    ) -> None:
        path_info = _path_from_jsx_attrs(attrs, source_bytes, node, gaps, source_file)
        path, is_index, confidence = path_info
        element_name = attrs.get("element")
        lazy_comp = None
        if not element_name and "lazy" in attrs:
            # rare on JSX; ignore string placeholder
            pass
        if path is None and not is_index and not element_name:
            return
        full = join_route_paths(parent_prefix, path, is_index)
        component = resolve_component(element_name) or lazy_comp
        if element_name and component == element_name and element_name not in local_imports:
            gaps.append(
                JourneyGap(
                    message=f"unresolved component import: {element_name}",
                    source_file=source_file,
                    source_line=node.start_point[0] + 1,
                    confidence=Confidence.MEDIUM,
                )
            )
        routes.append(
            _make_route(
                url_path=full,
                component=component,
                source_file=source_file,
                source_line=node.start_point[0] + 1,
                is_index=is_index,
                layout=resolve_component(layout) if layout else None,
                confidence=confidence,
            )
        )

    walk_jsx(parsed.root, "", None)

    # --- Data-router object configs ---
    def walk_calls(node: Any) -> None:
        if node.type == "call_expression" and node.children:
            callee = node.children[0]
            if callee.type == "identifier":
                fn = node_text(source_bytes, callee)
                if fn in DATA_ROUTER_FNS:
                    args = next((c for c in node.children if c.type == "arguments"), None)
                    array = _first_arg_array(args)
                    if array is not None:
                        walk_route_array(
                            array,
                            parent_prefix="",
                            layout=None,
                            file_parsed=parsed,
                            file_rel=source_file,
                            file_imports=local_imports,
                        )
                    else:
                        arg = _first_arg_node(args)
                        if arg is not None and arg.type == "identifier":
                            # createBrowserRouter(routes) — miss-path follow
                            handle_spread_ident(
                                node_text(source_bytes, arg),
                                node,
                                parent_prefix="",
                                layout=None,
                                file_parsed=parsed,
                                file_rel=source_file,
                                file_imports=local_imports,
                            )
                        elif arg is not None and arg.type == "call_expression":
                            # createRoutesFromElements(...) handled by JSX walk
                            pass
                        else:
                            gaps.append(
                                JourneyGap(
                                    message=f"{fn} routes arg not a static array",
                                    source_file=source_file,
                                    source_line=node.start_point[0] + 1,
                                    confidence=Confidence.MEDIUM,
                                )
                            )
        for child in node.children:
            walk_calls(child)

    def walk_route_array(
        array_node: Any,
        parent_prefix: str,
        layout: str | None,
        file_parsed: JsParseResult,
        file_rel: str,
        file_imports: dict[str, str],
    ) -> None:
        for child in array_node.children:
            if child.type == "object":
                walk_route_object(
                    child, parent_prefix, layout, file_parsed, file_rel, file_imports
                )
            elif child.type == "spread_element":
                handle_spread(child, parent_prefix, layout, file_parsed, file_rel, file_imports)

    def handle_spread_ident(
        ident: str,
        at_node: Any,
        parent_prefix: str,
        layout: str | None,
        file_parsed: JsParseResult,
        file_rel: str,
        file_imports: dict[str, str],
    ) -> None:
        miss = follow_export(
            project_dir,
            Path(file_rel),
            ident,
            file_imports,
            resolve_file=lambda pd, importer, mod: _resolve_module_path(pd, importer, mod),
        )
        if not miss.ok or miss.binding_node is None or miss.parsed is None:
            # Also try local const in same file
            local_init = find_local_or_fail(file_parsed, ident)
            if local_init is not None and local_init.type == "array":
                walk_route_array(
                    local_init, parent_prefix, layout, file_parsed, file_rel, file_imports
                )
                return
            gaps.append(
                JourneyGap(
                    message=f"unresolved route module {ident}: {miss.detail}",
                    source_file=file_rel,
                    source_line=at_node.start_point[0] + 1,
                    confidence=Confidence.MEDIUM,
                )
            )
            return

        module_key = str(miss.module_path)
        if module_key in seen_modules:
            return
        seen_modules.add(module_key)

        try:
            rel = str(miss.module_path.resolve().relative_to(project_dir)).replace("\\", "/")
        except ValueError:
            rel = module_key

        binding = miss.binding_node
        if binding.type == "identifier":
            name = node_text(miss.parsed.source_bytes, binding)
            binding = find_local_or_fail(miss.parsed, name) or binding

        nested_imports = extract_imports(miss.parsed)
        if binding.type == "array":
            walk_route_array(binding, parent_prefix, layout, miss.parsed, rel, nested_imports)
        elif binding.type == "object":
            walk_route_object(binding, parent_prefix, layout, miss.parsed, rel, nested_imports)
        else:
            gaps.append(
                JourneyGap(
                    message=f"route module {ident} resolved to non-array ({binding.type})",
                    source_file=file_rel,
                    source_line=at_node.start_point[0] + 1,
                    confidence=Confidence.MEDIUM,
                )
            )

    def handle_spread(
        spread: Any,
        parent_prefix: str,
        layout: str | None,
        file_parsed: JsParseResult,
        file_rel: str,
        file_imports: dict[str, str],
    ) -> None:
        ident = None
        for child in spread.children:
            if child.type == "identifier":
                ident = node_text(file_parsed.source_bytes, child)
        if not ident:
            gaps.append(
                JourneyGap(
                    message="unresolved route spread (non-identifier)",
                    source_file=file_rel,
                    source_line=spread.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
            return
        handle_spread_ident(
            ident, spread, parent_prefix, layout, file_parsed, file_rel, file_imports
        )

    def walk_route_object(
        obj: Any,
        parent_prefix: str,
        layout: str | None,
        file_parsed: JsParseResult,
        file_rel: str,
        file_imports: dict[str, str],
    ) -> None:
        sb = file_parsed.source_bytes
        props = _object_props(sb, obj)
        path, path_conf, path_dynamic = _path_from_object_prop(sb, props.get("path"), gaps, file_rel, obj)
        is_index = _truthy_prop(sb, props.get("index"))
        component_name = _identifier_prop(sb, props.get("Component"))
        if component_name is None and props.get("element") is not None:
            el = props["element"]
            if el.type == "identifier":
                component_name = node_text(sb, el)
            elif el.type == "jsx_expression":
                component_name = _component_from_jsx_expression(sb, el)
            elif el.type == "jsx_self_closing_element":
                component_name = _jsx_name(sb, el)
            elif el.type == "jsx_element":
                opening = next((c for c in el.children if c.type == "jsx_opening_element"), None)
                if opening is not None:
                    component_name = _jsx_name(sb, opening)

        lazy_path = None
        if "lazy" in props:
            lazy_path = _lazy_import_module(sb, props["lazy"])
            if lazy_path:
                lazy_path = _resolve_module_path(project_dir, Path(file_rel), lazy_path) or lazy_path
            else:
                gaps.append(
                    JourneyGap(
                        message="lazy route without static import() path",
                        source_file=file_rel,
                        source_line=obj.start_point[0] + 1,
                        confidence=Confidence.MEDIUM,
                    )
                )

        def resolve_name(name: str | None) -> str | None:
            if not name:
                return None
            module = file_imports.get(name)
            if not module:
                return name
            return _resolve_module_path(project_dir, Path(file_rel), module) or name

        component = resolve_name(component_name) or lazy_path
        confidence = path_conf
        if lazy_path and not component_name:
            confidence = Confidence.HIGH if not path_dynamic else Confidence.LOW

        children = props.get("children")
        has_children = children is not None and children.type == "array"

        full = join_route_paths(parent_prefix, path, is_index) if (path is not None or is_index) else parent_prefix

        if has_children:
            child_layout = component_name or layout
            child_prefix = parent_prefix if path is None and not is_index else full
            walk_route_array(
                children, child_prefix, child_layout, file_parsed, file_rel, file_imports
            )
            # pathless layout wrappers are not journey steps
            if path is not None or is_index:
                routes.append(
                    _make_route(
                        url_path=full,
                        component=component,
                        source_file=file_rel,
                        source_line=obj.start_point[0] + 1,
                        is_index=is_index,
                        layout=resolve_name(layout) if layout else None,
                        confidence=confidence,
                    )
                )
            return

        if path is None and not is_index and not component and not lazy_path:
            return

        if path is None and not is_index and (component or lazy_path):
            # pathless leaf — unusual; still record under parent
            full = parent_prefix or "/"

        routes.append(
            _make_route(
                url_path=full if (path is not None or is_index) else (parent_prefix or "/"),
                component=component,
                source_file=file_rel,
                source_line=obj.start_point[0] + 1,
                is_index=is_index,
                layout=resolve_name(layout) if layout else None,
                confidence=confidence,
            )
        )

    walk_calls(parsed.root)
    return routes, gaps


def find_local_or_fail(parsed: JsParseResult, name: str) -> Any | None:
    return find_exported_initializer(parsed, name)


def _path_from_jsx_attrs(
    attrs: dict[str, str | None],
    source_bytes: bytes,
    node: Any,
    gaps: list[JourneyGap],
    source_file: str,
) -> tuple[str | None, bool, Confidence]:
    is_index = attrs.get("index") == "true"
    path = attrs.get("path")
    # Dynamic path={expr} leaves path None from string-only attr helper — check raw
    if path is None and not is_index:
        for child in node.children:
            if child.type != "jsx_attribute":
                continue
            name = None
            for part in child.children:
                if part.type == "property_identifier":
                    name = node_text(source_bytes, part)
            if name != "path":
                continue
            # had path attr but not static string
            gaps.append(
                JourneyGap(
                    message="dynamic route path (non-literal)",
                    source_file=source_file,
                    source_line=node.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
            return (None, is_index, Confidence.LOW)
    return (path, is_index, Confidence.HIGH)


def _path_from_object_prop(
    source_bytes: bytes,
    path_node: Any | None,
    gaps: list[JourneyGap],
    source_file: str,
    obj: Any,
) -> tuple[str | None, Confidence, bool]:
    if path_node is None:
        return (None, Confidence.HIGH, False)
    if path_node.type == "string":
        return (string_literal_value(source_bytes, path_node), Confidence.HIGH, False)
    if path_node.type == "template_string":
        raw = node_text(source_bytes, path_node)
        if "${" in raw:
            gaps.append(
                JourneyGap(
                    message=f"dynamic template route path: {raw.strip()}",
                    source_file=source_file,
                    source_line=obj.start_point[0] + 1,
                    confidence=Confidence.LOW,
                )
            )
            return (raw.strip("`"), Confidence.LOW, True)
        val = string_literal_value(source_bytes, path_node)
        return (val, Confidence.HIGH, False)
    gaps.append(
        JourneyGap(
            message="dynamic route path (non-literal)",
            source_file=source_file,
            source_line=obj.start_point[0] + 1,
            confidence=Confidence.LOW,
        )
    )
    return (None, Confidence.LOW, True)


def _object_props(source_bytes: bytes, obj: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for child in obj.children:
        if child.type != "pair":
            continue
        key = None
        value = None
        for part in child.children:
            if part.type == "property_identifier" and key is None:
                key = node_text(source_bytes, part)
            elif part.type == ":":
                continue
            elif key is not None and value is None:
                value = part
        if key and value is not None:
            props[key] = value
    return props


def _identifier_prop(source_bytes: bytes, node: Any | None) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node_text(source_bytes, node)
    return None


def _truthy_prop(source_bytes: bytes, node: Any | None) -> bool:
    if node is None:
        return False
    text = node_text(source_bytes, node).strip()
    return text in {"true", "True"}


def _first_arg_array(args: Any | None) -> Any | None:
    if args is None:
        return None
    for child in args.children:
        if child.type == "array":
            return child
    return None


def _first_arg_node(args: Any | None) -> Any | None:
    if args is None:
        return None
    for child in args.children:
        if child.type in {"(", ")", ","}:
            continue
        return child
    return None


def _lazy_import_module(source_bytes: bytes, node: Any) -> str | None:
    """Find ``import("...")`` module string under a lazy arrow/fn."""
    found: str | None = None

    def walk(n: Any) -> None:
        nonlocal found
        if found is not None:
            return
        if n.type == "call_expression" and n.children:
            callee = n.children[0]
            if callee.type == "import" or (
                callee.type == "identifier" and node_text(source_bytes, callee) == "import"
            ):
                args = next((c for c in n.children if c.type == "arguments"), None)
                if args is not None:
                    for child in args.children:
                        if child.type == "string":
                            found = string_literal_value(source_bytes, child)
                            return
        for child in n.children:
            walk(child)

    walk(node)
    return found


def _make_route(
    *,
    url_path: str,
    component: str | None,
    source_file: str,
    source_line: int,
    is_index: bool,
    layout: str | None,
    confidence: Confidence = Confidence.HIGH,
) -> RouteNode:
    return RouteNode(
        url_path=url_path,
        component=component,
        source_file=source_file,
        source_line=source_line,
        is_index=is_index,
        is_wildcard=url_path == "*",
        layout=layout,
        confidence=confidence,
        source=RouteSource.CONFIG_AST,
    )


def _jsx_name(source_bytes: bytes, node: Any) -> str | None:
    for child in node.children:
        if child.type == "identifier":
            return node_text(source_bytes, child)
        if child.type == "member_expression":
            return node_text(source_bytes, child)
    return None


def _is_route_node(source_bytes: bytes, node: Any) -> bool:
    if node.type == "jsx_self_closing_element":
        return _jsx_name(source_bytes, node) == "Route"
    if node.type == "jsx_element":
        opening = next((c for c in node.children if c.type == "jsx_opening_element"), None)
        return opening is not None and _jsx_name(source_bytes, opening) == "Route"
    return False


def _jsx_attrs(source_bytes: bytes, opening_or_self: Any) -> dict[str, str | None]:
    attrs: dict[str, str | None] = {}
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        value: str | None = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif part.type == "string":
                value = string_literal_value(source_bytes, part)
            elif part.type == "jsx_expression":
                value = _component_from_jsx_expression(source_bytes, part)
            elif part.type == "=":
                continue
        if name is None:
            continue
        if len(child.children) == 1:
            # boolean attribute e.g. `index`
            attrs[name] = "true"
        else:
            attrs[name] = value
    return attrs


def _component_from_jsx_expression(source_bytes: bytes, expr: Any) -> str | None:
    for child in expr.children:
        if child.type == "jsx_self_closing_element":
            return _jsx_name(source_bytes, child)
        if child.type == "jsx_element":
            opening = next((c for c in child.children if c.type == "jsx_opening_element"), None)
            if opening is not None:
                return _jsx_name(source_bytes, opening)
        if child.type == "identifier":
            return node_text(source_bytes, child)
        if child.type == "member_expression":
            idents = [c for c in child.children if c.type == "identifier"]
            if idents:
                return node_text(source_bytes, idents[-1])
    return None


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
    # Prefer the conventional .tsx relative path even if file missing (monorepo lag).
    guess = base.with_suffix(".tsx") if not base.suffix else base
    try:
        return str(guess.relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        return None


def build_file_route_index(routes: list[RouteNode] | tuple[RouteNode, ...]) -> dict[str, list[str]]:
    """Map source files (page component or layout) → route url_paths."""
    index: dict[str, list[str]] = {}
    for route in routes:
        for key in (route.component, route.layout):
            if not key:
                continue
            index.setdefault(key, []).append(route.url_path)
    return index


def from_path_for_file(source_file: str, file_routes: dict[str, list[str]]) -> str | None:
    """Single owning route for a file; None if shared layout / unknown."""
    paths = file_routes.get(source_file)
    if not paths:
        return None
    unique = list(dict.fromkeys(paths))
    if len(unique) == 1:
        return unique[0]
    return None


def iter_nav_candidate_files(project_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.suffix not in set(SOURCE_EXTENSIONS):
            continue
        if any(part in path.parts for part in {"node_modules", "dist", "build"}):
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
    """Scan project for Link / NavLink / navigate / redirect / nav config paths."""
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
        for edge in extract_nav_from_parse(parsed, source_file, from_path):
            key = (edge.from_path, edge.to_path, edge.kind, edge.source_file)
            if key in seen:
                continue
            seen.add(key)
            edges.append(edge)
            if (
                edge.kind == "nav_config"
                and known_routes
                and edge.to_path not in known_routes
                and edge.to_path != "*"
            ):
                gaps.append(
                    JourneyGap(
                        message=f"nav config path not in route tree: {edge.to_path}",
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
) -> list[NavEdge]:
    """Extract static navigation edges from one parsed file."""
    if not parsed.ok or parsed.root is None:
        return []

    source_bytes = parsed.source_bytes
    edges: list[NavEdge] = []

    def walk(node: Any) -> None:
        if node.type in {"jsx_self_closing_element", "jsx_opening_element"}:
            name = _jsx_name(source_bytes, node)
            if name in LINK_TAGS:
                to_path = _jsx_string_attr(source_bytes, node, "to")
                if to_path is not None and _looks_like_route_path(to_path):
                    edges.append(
                        NavEdge(
                            from_path=from_path,
                            to_path=to_path,
                            source_file=source_file,
                            source_line=node.start_point[0] + 1,
                            kind="link",
                            confidence=Confidence.HIGH,
                        )
                    )

        if node.type == "call_expression":
            edge = _nav_call_edge(source_bytes, node, source_file, from_path)
            if edge is not None:
                edges.append(edge)

        if node.type == "pair":
            edge = _nav_config_path_edge(source_bytes, node, source_file, from_path)
            if edge is not None:
                edges.append(edge)

        for child in node.children:
            walk(child)

    walk(parsed.root)
    return edges


def _jsx_string_attr(source_bytes: bytes, opening_or_self: Any, attr_name: str) -> str | None:
    """Static string attribute only (skip dynamic ``to={expr}``)."""
    for child in opening_or_self.children:
        if child.type != "jsx_attribute":
            continue
        name = None
        value: str | None = None
        for part in child.children:
            if part.type == "property_identifier":
                name = node_text(source_bytes, part)
            elif part.type == "string":
                value = string_literal_value(source_bytes, part)
            elif part.type == "jsx_expression":
                for inner in part.children:
                    if inner.type == "string":
                        value = string_literal_value(source_bytes, inner)
                    elif inner.type == "template_string":
                        value = string_literal_value(source_bytes, inner)
        if name == attr_name:
            return value
    return None


def _nav_call_edge(
    source_bytes: bytes,
    node: Any,
    source_file: str,
    from_path: str | None,
) -> NavEdge | None:
    if not node.children:
        return None
    callee = node.children[0]
    if callee.type != "identifier":
        return None
    fn_name = node_text(source_bytes, callee)
    kind = CALL_NAV_KINDS.get(fn_name)
    if kind is None:
        return None

    args = next((c for c in node.children if c.type == "arguments"), None)
    if args is None:
        return None
    first = None
    for child in args.children:
        if child.type in {"(", ")", ","}:
            continue
        first = child
        break
    if first is None:
        return None
    to_path = string_literal_value(source_bytes, first)
    if to_path is None or not _looks_like_route_path(to_path):
        return None
    return NavEdge(
        from_path=from_path,
        to_path=to_path,
        source_file=source_file,
        source_line=node.start_point[0] + 1,
        kind=kind,
        confidence=Confidence.HIGH,
    )


def _nav_config_path_edge(
    source_bytes: bytes,
    pair: Any,
    source_file: str,
    from_path: str | None,
) -> NavEdge | None:
    """``path: "/foo"`` in object literals (sidebar / nav config)."""
    key = None
    value_node = None
    for child in pair.children:
        if child.type == "property_identifier" and key is None:
            key = node_text(source_bytes, child)
        elif child.type == "string":
            value_node = child
    if key != "path" or value_node is None:
        return None
    to_path = string_literal_value(source_bytes, value_node)
    if to_path is None or not _looks_like_route_path(to_path):
        return None
    return NavEdge(
        from_path=from_path,
        to_path=to_path,
        source_file=source_file,
        source_line=pair.start_point[0] + 1,
        kind="nav_config",
        confidence=Confidence.HIGH,
    )


def _looks_like_route_path(value: str) -> bool:
    return value == "*" or value.startswith("/")


class ReactRouterExtractor:
    """React Router plugin — route tree + navigation via shared parse_js."""

    framework = "react-router"

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
    ) -> JourneyGraph:
        del detection
        project_dir = project_dir.resolve()
        candidates = find_route_candidates(project_dir)
        routes: list[RouteNode] = []
        gaps: list[JourneyGap] = []
        parser_used = "tree_sitter"

        for candidate in candidates:
            abs_path = project_dir / candidate.path
            source_file = str(candidate.path).replace("\\", "/")
            parsed = parse_js_ts(abs_path)

            if parsed.ok:
                file_routes, file_gaps = extract_routes_from_parse(
                    parsed,
                    source_file,
                    project_dir,
                )
                routes.extend(file_routes)
                gaps.extend(file_gaps)
            else:
                parser_used = "regex"
                gaps.append(
                    JourneyGap(
                        message=f"parse_js failed; regex fallback for {source_file}: {parsed.detail}",
                        source_file=source_file,
                        confidence=Confidence.MEDIUM,
                    )
                )
                source = abs_path.read_text(encoding="utf-8")
                routes.extend(extract_routes_regex(source, source_file))

        if not candidates:
            gaps.append(
                JourneyGap(
                    message="no react-router route candidate files found",
                    confidence=Confidence.LOW,
                )
            )

        edges, nav_gaps = extract_navigation(project_dir, routes)
        gaps.extend(nav_gaps)

        return JourneyGraph(
            framework=self.framework,
            project_root=project_dir,
            routes=tuple(routes),
            edges=tuple(edges),
            gaps=tuple(gaps),
            meta={
                "candidates": str(len(candidates)),
                "parser": parser_used,
                "edges": str(len(edges)),
            },
        )
