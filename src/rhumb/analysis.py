from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graphify.detect import detect

from rhumb.framework import FrameworkDetection, detect_all_frameworks, format_projects
from rhumb.graphify_runner import AstResult, format_ast_results, run_ast_for_projects


@dataclass(frozen=True)
class AnalysisContext:
    project_path: Path
    corpus: dict
    projects: list[FrameworkDetection]
    ast_results: list[AstResult]


def scan_project(path: Path) -> dict:
    result = detect(path)
    code_files = result.get("files", {}).get("code", [])
    if not code_files:
        raise ValueError(f"No supported code files found in: {path}")
    return result


def format_summary(result: dict) -> str:
    files_by_type = result.get("files", {})
    lines = [
        f"Corpus: {result.get('total_files', 0)} files · ~{result.get('total_words', 0):,} words",
    ]

    type_labels = {
        "code": "code",
        "document": "docs",
        "paper": "papers",
        "image": "images",
        "video": "video",
    }

    for key, label in type_labels.items():
        count = len(files_by_type.get(key, []))
        if count:
            lines.append(f"  {label}: {count} files")

    skipped = result.get("skipped_sensitive", [])
    if skipped:
        lines.append(f"  skipped: {len(skipped)} sensitive files")

    return "\n".join(lines)


def analyze(path: str | Path) -> AnalysisContext:
    """Detect frameworks and build AST context for a project (programmatic API).

    Same as :func:`run_prerequisites` — preferred name for library use.
    """
    return run_prerequisites(Path(path))


def run_prerequisites(project_path: Path) -> AnalysisContext:
    """Framework detection and AST generation shared by journey and instrument flows."""
    project_path = project_path.resolve()
    corpus = scan_project(project_path)
    projects = detect_all_frameworks(project_path)
    if not projects:
        raise ValueError("No frontend projects detected in the given path.")

    ast_results = run_ast_for_projects(project_path, projects)
    return AnalysisContext(
        project_path=project_path,
        corpus=corpus,
        projects=projects,
        ast_results=ast_results,
    )


def print_prerequisites(context: AnalysisContext) -> None:
    print(f"Valid project path: {context.project_path}")
    print(format_summary(context.corpus))
    print()
    print(format_projects(context.projects))
    print()
    print(format_ast_results(context.ast_results))
