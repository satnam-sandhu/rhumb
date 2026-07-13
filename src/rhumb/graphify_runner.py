from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from graphify.build import build_from_json
from graphify.cluster import cluster
from graphify.detect import detect
from graphify.export import to_json
from graphify.extract import collect_files, extract

OUTPUT_BASE = Path(tempfile.gettempdir()) / "rhumb"


@dataclass(frozen=True)
class AstResult:
    project_path: Path
    output_dir: Path
    nodes: int
    edges: int
    communities: int
    code_files: int
    graph_path: Path


def resolve_project_dir(scan_root: Path, project_root: str | None) -> Path:
    if not project_root or project_root == scan_root.name:
        return scan_root
    return scan_root / project_root


def prepare_output_base(output_base: Path = OUTPUT_BASE) -> Path:
    """Remove previous scan output and recreate the system temp output directory."""
    output_base = output_base.resolve()
    if output_base.exists():
        shutil.rmtree(output_base)
    output_base.mkdir(parents=True, exist_ok=True)
    return output_base


def run_ast_for_project(project_dir: Path, output_dir: Path) -> AstResult:
    """Run graphify detect + AST extract + graph build for one project."""
    project_dir = project_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    detection = detect(project_dir)
    code_files: list[Path] = []
    for file_path in detection.get("files", {}).get("code", []):
        path = Path(file_path)
        code_files.extend(collect_files(path) if path.is_dir() else [path])

    if not code_files:
        graph_path = output_dir / "graph.json"
        graph_path.write_text(
            json.dumps({"nodes": [], "edges": [], "communities": {}}, indent=2),
            encoding="utf-8",
        )
        return AstResult(
            project_path=project_dir,
            output_dir=output_dir,
            nodes=0,
            edges=0,
            communities=0,
            code_files=0,
            graph_path=graph_path,
        )

    ast_result = extract(code_files, cache_root=project_dir)
    (output_dir / "ast.json").write_text(
        json.dumps(ast_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    graph = build_from_json(ast_result)
    communities = cluster(graph)
    graph_path = output_dir / "graph.json"
    to_json(graph, communities, str(graph_path))

    return AstResult(
        project_path=project_dir,
        output_dir=output_dir,
        nodes=graph.number_of_nodes(),
        edges=graph.number_of_edges(),
        communities=len(communities),
        code_files=len(code_files),
        graph_path=graph_path,
    )


def run_ast_for_projects(
    scan_root: Path,
    projects: list,
    output_base: Path | None = None,
) -> list[AstResult]:
    base = prepare_output_base(output_base or OUTPUT_BASE)
    results: list[AstResult] = []
    for project in projects:
        project_dir = resolve_project_dir(scan_root, project.root)
        output_dir = base / (project.root or project_dir.name)
        results.append(run_ast_for_project(project_dir, output_dir))
    return results


def format_ast_results(results: list[AstResult]) -> str:
    if not results:
        return "AST: no projects processed."

    lines = [f"AST graphs generated: {len(results)}", ""]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                "=" * 60,
                f"AST {index}/{len(results)}: {result.project_path.name}",
                "=" * 60,
                f"Input:  {result.project_path}",
                f"Output: {result.output_dir}",
                f"Graph:  {result.nodes} nodes, {result.edges} edges, {result.communities} communities",
                f"Files:  {result.code_files} code files",
                f"Saved:  {result.graph_path}",
            ]
        )
    return "\n".join(lines)
