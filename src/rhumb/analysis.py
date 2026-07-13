from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rhumb.framework import (
    CODE_EXTENSIONS,
    SKIP_DIRS,
    FrameworkDetection,
    detect_all_frameworks,
    format_projects,
)


@dataclass(frozen=True)
class AnalysisContext:
    project_path: Path
    corpus: dict
    projects: list[FrameworkDetection]


def scan_project(path: Path) -> dict:
    """Walk the tree for frontend-ish source files (no external indexer)."""
    root = path.resolve()
    code_files: list[str] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if any(part in SKIP_DIRS for part in candidate.parts):
            continue
        if candidate.suffix.lower() not in CODE_EXTENSIONS:
            continue
        code_files.append(str(candidate))

    if not code_files:
        raise ValueError(f"No supported code files found in: {path}")

    return {
        "total_files": len(code_files),
        "files": {"code": sorted(code_files)},
    }


def format_summary(result: dict) -> str:
    files_by_type = result.get("files", {})
    lines = [
        f"Corpus: {result.get('total_files', 0)} files",
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

    return "\n".join(lines)


def analyze(path: str | Path) -> AnalysisContext:
    """Detect frameworks for a project (programmatic API).

    Same as :func:`run_prerequisites` — preferred name for library use.
    """
    return run_prerequisites(Path(path))


def run_prerequisites(project_path: Path) -> AnalysisContext:
    """Framework detection shared by journey and instrument flows."""
    project_path = project_path.resolve()
    corpus = scan_project(project_path)
    projects = detect_all_frameworks(project_path)
    if not projects:
        raise ValueError("No frontend projects detected in the given path.")

    return AnalysisContext(
        project_path=project_path,
        corpus=corpus,
        projects=projects,
    )


def print_prerequisites(context: AnalysisContext) -> None:
    print(f"Valid project path: {context.project_path}")
    print(format_summary(context.corpus))
    print()
    print(format_projects(context.projects))
