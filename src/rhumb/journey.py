from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from rhumb.analysis import AnalysisContext, run_prerequisites
from rhumb.framework import resolve_project_dir
from rhumb.journeys.paths import (
    build_journeys,
    format_journey,
    serialize_end_routes,
)
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

    graphs: list[JourneyGraph] = []

    for project in context.projects:
        extractor = get_extractor(project.framework)
        if extractor is None:
            continue

        project_dir = resolve_project_dir(context.project_path, project.root)
        graph = extractor.extract(project_dir, project)
        if build_paths:
            journeys = build_journeys(graph)
            graph = replace(
                graph,
                journeys=journeys,
                meta={**graph.meta, "journeys": str(len(journeys))},
            )
        graphs.append(graph)

    return graphs


def extract_end_routes(
    path: str | Path | AnalysisContext,
    *,
    build_paths: bool = True,
) -> Mapping[str, object]:
    """JSON-ready map: end route → all inbound journey paths.

    Framework-agnostic wrapper around :func:`extract_journeys` +
    :func:`~rhumb.journeys.paths.serialize_end_routes`. New framework
    plugins need no changes here — they only return ``JourneyGraph``.

    Single project::

        {
          "/checkout": [
            ["/search", "/product-details", "/cart", "/checkout"]
          ]
        }

    Monorepo (multiple detected apps)::

        {
          "web:tanstack-router": { "/about": [["/", "/about"]] },
          "mobile:expo-router": { "/settings": [["/", "/settings"]] }
        }
    """
    return serialize_end_routes(extract_journeys(path, build_paths=build_paths))


def run_journey(context: AnalysisContext, *, verbose: bool = False) -> None:
    """CLI printer — JSON end-route map on stdout."""
    graphs = extract_journeys(context)
    payload = serialize_end_routes(graphs)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if not verbose:
        return

    print("Mode: journey (verbose)", file=sys.stderr)
    for project in context.projects:
        if get_extractor(project.framework) is None:
            print(
                f"\n[{project.root}] framework={project.framework} — not registered",
                file=sys.stderr,
            )

    for graph in graphs:
        label = graph.project_root.name
        for project in context.projects:
            project_dir = resolve_project_dir(context.project_path, project.root)
            if project_dir.resolve() == graph.project_root.resolve():
                label = project.root or project_dir.name
                break
        _print_graph_verbose(label, graph)


def _print_graph_verbose(label: str, graph: JourneyGraph) -> None:
    print(f"\n[{label}] framework={graph.framework}", file=sys.stderr)
    if graph.meta:
        meta = ", ".join(f"{k}={v}" for k, v in graph.meta.items())
        print(f"  meta: {meta}", file=sys.stderr)

    if graph.journeys:
        print(f"  journeys: {len(graph.journeys)}", file=sys.stderr)
        for journey in graph.journeys:
            print(f"    {format_journey(journey)}", file=sys.stderr)
    else:
        print("  journeys: 0", file=sys.stderr)

    if graph.routes:
        print(f"  routes: {len(graph.routes)}", file=sys.stderr)
        for route in graph.routes:
            component = route.component or "?"
            layout = f"  layout={route.layout}" if route.layout else ""
            print(
                f"    {route.url_path:20} → {component}  "
                f"(L{route.source_line}, {route.confidence.value}){layout}",
                file=sys.stderr,
            )
    else:
        print("  routes: 0", file=sys.stderr)

    if graph.edges:
        print(f"  edges: {len(graph.edges)}", file=sys.stderr)
        for edge in graph.edges:
            src = edge.from_path if edge.from_path is not None else "(shared)"
            loc = f"{edge.source_file}:{edge.source_line}"
            print(f"    {src} → {edge.to_path}  [{edge.kind}]  {loc}", file=sys.stderr)

    if graph.gaps:
        print(f"  gaps: {len(graph.gaps)}", file=sys.stderr)
        for gap in graph.gaps:
            loc = ""
            if gap.source_file:
                loc = f"  ({gap.source_file}"
                if gap.source_line is not None:
                    loc += f":{gap.source_line}"
                loc += ")"
            print(f"    - {gap.message}{loc}", file=sys.stderr)
