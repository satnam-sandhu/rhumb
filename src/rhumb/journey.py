from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rhumb.analysis import AnalysisContext, run_prerequisites
from rhumb.graphify_runner import resolve_project_dir
from rhumb.journeys.paths import build_journeys, format_journey
from rhumb.journeys.registry import get_extractor
from rhumb.journeys.types import JourneyGraph


def extract_journeys(
    path: str | Path | AnalysisContext,
    *,
    build_paths: bool = True,
) -> list[JourneyGraph]:
    """Extract journey graphs from a project path (programmatic API).

    Parameters
    ----------
    path:
        Project root, or an existing :class:`AnalysisContext` from
        :func:`rhumb.analyze`.
    build_paths:
        When True (default), enumerate concrete journey sequences via
        :func:`~rhumb.journeys.paths.build_journeys`.

    Returns
    -------
    list[JourneyGraph]
        One graph per detected frontend package that has a registered
        journey extractor. Unregistered frameworks are skipped.

    Example
    -------
    >>> from rhumb import extract_journeys
    >>> graphs = extract_journeys("./my-app")
    >>> for g in graphs:
    ...     print(g.framework, len(g.routes), len(g.journeys))
    """
    if isinstance(path, AnalysisContext):
        context = path
    else:
        context = run_prerequisites(Path(path))

    ast_by_path = {
        result.project_path.resolve(): result for result in context.ast_results
    }
    graphs: list[JourneyGraph] = []

    for project in context.projects:
        extractor = get_extractor(project.framework)
        if extractor is None:
            continue

        project_dir = resolve_project_dir(context.project_path, project.root)
        ast_result = ast_by_path.get(project_dir.resolve())
        graph = extractor.extract(project_dir, project, ast_result)
        if build_paths:
            journeys = build_journeys(graph)
            graph = replace(
                graph,
                journeys=journeys,
                meta={**graph.meta, "journeys": str(len(journeys))},
            )
        graphs.append(graph)

    return graphs


def run_journey(context: AnalysisContext) -> None:
    """CLI printer — prefer :func:`extract_journeys` in application code."""
    print("Mode: journey")

    for project in context.projects:
        if get_extractor(project.framework) is None:
            print(f"\n[{project.root}] framework={project.framework} — not registered")

    for graph in extract_journeys(context):
        label = graph.project_root.name
        for project in context.projects:
            project_dir = resolve_project_dir(context.project_path, project.root)
            if project_dir.resolve() == graph.project_root.resolve():
                label = project.root or project_dir.name
                break
        _print_graph(label, graph)


def _print_graph(label: str, graph: JourneyGraph) -> None:
    print(f"\n[{label}] framework={graph.framework}")
    if graph.meta:
        meta = ", ".join(f"{k}={v}" for k, v in graph.meta.items())
        print(f"  meta: {meta}")

    if graph.journeys:
        print(f"  journeys: {len(graph.journeys)}")
        for journey in graph.journeys:
            print(f"    {format_journey(journey)}")
    else:
        print("  journeys: 0")

    if graph.routes:
        print(f"  routes: {len(graph.routes)}")
        for route in graph.routes:
            component = route.component or "?"
            layout = f"  layout={route.layout}" if route.layout else ""
            print(
                f"    {route.url_path:20} → {component}  "
                f"(L{route.source_line}, {route.confidence.value}){layout}"
            )
    else:
        print("  routes: 0")

    if graph.edges:
        print(f"  edges: {len(graph.edges)}")
        for edge in graph.edges:
            src = edge.from_path if edge.from_path is not None else "(shared)"
            loc = f"{edge.source_file}:{edge.source_line}"
            print(f"    {src} → {edge.to_path}  [{edge.kind}]  {loc}")

    if graph.gaps:
        print(f"  gaps: {len(graph.gaps)}")
        for gap in graph.gaps:
            loc = ""
            if gap.source_file:
                loc = f"  ({gap.source_file}"
                if gap.source_line is not None:
                    loc += f":{gap.source_line}"
                loc += ")"
            print(f"    - {gap.message}{loc}")
