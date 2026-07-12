from __future__ import annotations

from dataclasses import replace

from deterministic_kit.analysis import AnalysisContext
from deterministic_kit.graphify_runner import resolve_project_dir
from deterministic_kit.journeys.paths import build_journeys, format_journey
from deterministic_kit.journeys.registry import get_extractor
from deterministic_kit.journeys.types import JourneyGraph


def run_journey(context: AnalysisContext) -> None:
    print("Mode: journey")
    ast_by_path = {result.project_path.resolve(): result for result in context.ast_results}

    for project in context.projects:
        extractor = get_extractor(project.framework)
        if extractor is None:
            print(f"\n[{project.root}] framework={project.framework} — not registered")
            continue

        project_dir = resolve_project_dir(context.project_path, project.root)
        ast_result = ast_by_path.get(project_dir.resolve())
        graph = extractor.extract(project_dir, project, ast_result)
        journeys = build_journeys(graph)
        graph = replace(
            graph,
            journeys=journeys,
            meta={**graph.meta, "journeys": str(len(journeys))},
        )
        _print_graph(project.root or project_dir.name, graph)


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
