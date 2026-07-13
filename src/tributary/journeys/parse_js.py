"""Shared JS/TS parsing shell (hybrid A+B).

Framework plugins for react-router, angular, vue-router (TS config), and
navigation extraction should call into this module instead of owning parsers.

v1: tree-sitter TS/TSX/JS/JSX (option A).
v1.1: TypeScript binder miss-path (option B) — same interface, optional backend.

Vue SFC / Svelte parsers are NOT here — those live in framework plugins
(``vue_router``, ``sveltekit``) and may call this only for ``.ts``/``.js`` slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class JsParseResult:
    """Syntax tree from the hybrid engine (tree-sitter today)."""

    path: Path
    backend: str  # tree_sitter | typescript | regex
    ok: bool
    detail: str = ""
    source: str = ""
    source_bytes: bytes = b""
    _tree: Any = field(default=None, repr=False, compare=False)

    @property
    def root(self) -> Any | None:
        if self._tree is None:
            return None
        return self._tree.root_node


def parse_js_ts(path: Path, source: str | None = None) -> JsParseResult:
    """Parse a .ts/.tsx/.js/.jsx file via the hybrid engine.

    Layer A (tree-sitter) is the default. Layer B (TypeScript binder) plugs in
    later behind this same entry for unresolved symbols only.
    """
    path = Path(path)
    try:
        text = source if source is not None else path.read_text(encoding="utf-8")
    except OSError as exc:
        return JsParseResult(
            path=path,
            backend="tree_sitter",
            ok=False,
            detail=f"read failed: {exc}",
        )

    source_bytes = text.encode("utf-8")

    try:
        from tree_sitter import Language, Parser
        import tree_sitter_javascript as ts_js
        import tree_sitter_typescript as ts_ts
    except ImportError as exc:
        return JsParseResult(
            path=path,
            backend="tree_sitter",
            ok=False,
            detail=f"tree-sitter not available: {exc}",
            source=text,
            source_bytes=source_bytes,
        )

    suffix = path.suffix.lower()
    if suffix == ".tsx":
        language = Language(ts_ts.language_tsx())
    elif suffix == ".ts":
        language = Language(ts_ts.language_typescript())
    elif suffix in {".jsx", ".js", ".mjs", ".cjs"}:
        language = Language(ts_js.language())
    else:
        return JsParseResult(
            path=path,
            backend="tree_sitter",
            ok=False,
            detail=f"unsupported suffix: {suffix}",
            source=text,
            source_bytes=source_bytes,
        )

    parser = Parser(language)
    tree = parser.parse(source_bytes)
    return JsParseResult(
        path=path,
        backend="tree_sitter",
        ok=True,
        detail="",
        source=text,
        source_bytes=source_bytes,
        _tree=tree,
    )


def node_text(source_bytes: bytes, node: Any) -> str:
    """Decode node span using tree-sitter byte offsets (UTF-8 safe)."""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8")


def string_literal_value(source_bytes: bytes, node: Any) -> str | None:
    """Unwrap a tree-sitter string / template_string node to its content."""
    if node is None:
        return None
    if node.type == "string":
        raw = node_text(source_bytes, node)
        if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] == raw[0]:
            return raw[1:-1]
        return raw
    if node.type == "template_string":
        raw = node_text(source_bytes, node)
        if "${" in raw:
            return None
        if len(raw) >= 2 and raw[0] == "`" and raw[-1] == "`":
            return raw[1:-1]
        return raw
    return None


def extract_imports(result: JsParseResult) -> dict[str, str]:
    """Map local binding name → module specifier (e.g. Home → ./pages/Home)."""
    if not result.ok or result.root is None:
        return {}

    source_bytes = result.source_bytes
    imports: dict[str, str] = {}

    def walk(node: Any) -> None:
        if node.type == "import_statement":
            module = None
            for child in node.children:
                if child.type == "string":
                    module = string_literal_value(source_bytes, child)
            if not module:
                return
            for child in node.children:
                if child.type != "import_clause":
                    continue
                _collect_import_clause(source_bytes, child, module, imports)
            return
        for child in node.children:
            walk(child)

    walk(result.root)
    return imports


@dataclass(frozen=True)
class MissPathResult:
    """Layer B lite — follow one import to its defining module (no full typecheck)."""

    ok: bool
    module_path: Path | None = None
    parsed: JsParseResult | None = None
    binding_node: Any | None = field(default=None, hash=False, compare=False)
    detail: str = ""


def follow_export(
    project_dir: Path,
    importer_file: Path,
    local_name: str,
    imports: dict[str, str],
    *,
    resolve_file: Any = None,
) -> MissPathResult:
    """Resolve ``local_name`` via import map → re-parse target → find export init node.

    This is the hybrid miss-path (architecture option B) without a full ``tsc`` project
    typecheck. Callers pass ``resolve_file`` to map a module specifier to a relative path.
    """
    module = imports.get(local_name)
    if not module:
        return MissPathResult(ok=False, detail=f"no import for {local_name}")
    if resolve_file is None:
        return MissPathResult(ok=False, detail="resolve_file callback required")

    target = resolve_file(project_dir, importer_file, module)
    if target is None:
        return MissPathResult(ok=False, detail=f"cannot resolve module {module}")

    abs_target = Path(target)
    if not abs_target.is_absolute():
        abs_target = (project_dir / target).resolve()
    if not abs_target.is_file():
        return MissPathResult(ok=False, detail=f"module file missing: {target}")

    parsed = parse_js_ts(abs_target)
    if not parsed.ok or parsed.root is None:
        return MissPathResult(
            ok=False,
            module_path=abs_target,
            parsed=parsed,
            detail=parsed.detail or "parse failed",
        )

    binding = find_exported_initializer(parsed, local_name)
    if binding is None:
        binding = find_exported_initializer(parsed, None, default=True)

    if binding is None:
        return MissPathResult(
            ok=False,
            module_path=abs_target,
            parsed=parsed,
            detail=f"export binding not found: {local_name}",
        )

    return MissPathResult(
        ok=True,
        module_path=abs_target,
        parsed=parsed,
        binding_node=binding,
        detail="",
    )


def find_exported_initializer(
    parsed: JsParseResult,
    name: str | None,
    *,
    default: bool = False,
) -> Any | None:
    """Return the RHS node of ``export const name = <node>`` or ``export default <node>``."""
    if not parsed.ok or parsed.root is None:
        return None
    source_bytes = parsed.source_bytes
    found: Any | None = None

    def walk(node: Any) -> None:
        nonlocal found
        if found is not None:
            return
        if node.type == "export_statement":
            children = list(node.children)
            raw = node_text(source_bytes, node)
            is_default_export = raw.lstrip().startswith("export default")
            if default and is_default_export:
                for child in children:
                    if child.type in {"array", "object", "call_expression"}:
                        found = child
                        return
                    if child.type == "identifier":
                        found = _find_local_initializer(parsed, node_text(source_bytes, child))
                        return
                return
            if name and not is_default_export:
                init = _declarator_init_for_name(source_bytes, node, name)
                if init is not None:
                    found = init
                    return
        for child in node.children:
            walk(child)

    if not default:
        walk(parsed.root)
        if found is None and name:
            found = _find_local_initializer(parsed, name)
    else:
        walk(parsed.root)
    return found


def _find_local_initializer(parsed: JsParseResult, name: str) -> Any | None:
    source_bytes = parsed.source_bytes
    found: Any | None = None

    def walk(node: Any) -> None:
        nonlocal found
        if found is not None:
            return
        if node.type == "variable_declarator":
            init = _declarator_init_for_name(source_bytes, node, name)
            if init is not None:
                found = init
                return
        for child in node.children:
            walk(child)

    walk(parsed.root)
    return found


def _declarator_init_for_name(source_bytes: bytes, node: Any, name: str) -> Any | None:
    """Inside variable_declarator or export subtree, find ``name = <init>``."""
    if node.type == "variable_declarator":
        ident = None
        init = None
        for child in node.children:
            if child.type == "identifier" and ident is None:
                ident = node_text(source_bytes, child)
            elif child.type == "=":
                continue
            elif child.type == "type_annotation":
                continue
            elif ident is not None and init is None and child.type not in {":"}:
                init = child
        if ident == name:
            return init
        return None

    for child in node.children:
        got = _declarator_init_for_name(source_bytes, child, name)
        if got is not None:
            return got
    return None


def _collect_import_clause(
    source_bytes: bytes,
    clause: Any,
    module: str,
    imports: dict[str, str],
) -> None:
    for child in clause.children:
        if child.type == "identifier":
            imports[node_text(source_bytes, child)] = module
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type != "import_specifier":
                    continue
                names = [c for c in spec.children if c.type == "identifier"]
                if not names:
                    continue
                # `Foo as Bar` → bind Bar; else Foo
                local = node_text(source_bytes, names[-1])
                imports[local] = module
        elif child.type == "namespace_import":
            for ident in child.children:
                if ident.type == "identifier":
                    imports[node_text(source_bytes, ident)] = module
