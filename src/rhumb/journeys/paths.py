"""Turn route+nav edges into concrete journey path sequences.

Framework-agnostic: every plugin returns ``JourneyGraph``; this module
only consumes routes/edges/journeys — no per-framework branches.

JSON envelope (CLI / ``extract_end_routes``)::

    {
      "projects": [
        {
          "framework": "tanstack-router",
          "root": "my-app",
          "ends": {
            "/checkout": [["/search", "/cart", "/checkout"]]
          },
          "gaps": [
            {
              "message": "…",
              "source_file": "src/App.tsx",
              "source_line": 42,
              "confidence": "medium"
            }
          ]
        }
      ]
    }
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rhumb.journeys.types import (
    JourneyGap,
    JourneyGraph,
    JourneyPath,
    NavEdge,
    RouteNode,
)

# JSON-ready: end route → list of step lists that terminate there
EndRouteMap = dict[str, list[list[str]]]


def build_journeys(
    graph: JourneyGraph,
    *,
    start: str | None = None,
    max_depth: int = 5,
    max_paths: int = 40,
) -> tuple[JourneyPath, ...]:
    """Enumerate simple paths from a start route through expanded nav edges."""
    route_paths = {r.url_path for r in graph.routes if not r.is_wildcard}
    if not route_paths:
        return ()

    start_path = start or _default_start(graph.routes)
    if start_path not in route_paths:
        return ()

    adj = _adjacency(graph.routes, graph.edges, start_path)
    raw = _enumerate_simple_paths(adj, start_path, max_depth=max_depth, max_paths=max_paths)
    # Prefer longer funnels first (ecommerce-style), then lexical for stability.
    raw.sort(key=lambda steps: (-len(steps), steps))
    return tuple(JourneyPath(steps=steps) for steps in raw)


def journeys_by_end(journeys: Iterable[JourneyPath]) -> EndRouteMap:
    """Group journey step lists by their terminal route.

    Pure transform — framework-independent. Same shape for React Router,
    TanStack, Expo, and future plugins.

    Returns
    -------
    dict[str, list[list[str]]]
        ``{ "/checkout": [["/search", …, "/checkout"], …], … }``
        Keys sorted; each destination's paths keep input order (deduped).
    """
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    seen: dict[str, set[tuple[str, ...]]] = defaultdict(set)

    for journey in journeys:
        steps = tuple(journey.steps)
        if len(steps) < 2:
            continue
        end = steps[-1]
        if steps in seen[end]:
            continue
        seen[end].add(steps)
        grouped[end].append(list(steps))

    return {end: grouped[end] for end in sorted(grouped)}


def end_route_map(graph: JourneyGraph) -> EndRouteMap:
    """``journeys_by_end`` for one ``JourneyGraph`` (uses ``graph.journeys``)."""
    return journeys_by_end(graph.journeys)


def gaps_to_json(gaps: Iterable[JourneyGap]) -> list[dict[str, Any]]:
    """Serialize ``JourneyGap`` rows for JSON (stable keys)."""
    rows: list[dict[str, Any]] = []
    for gap in gaps:
        row: dict[str, Any] = {
            "message": gap.message,
            "confidence": gap.confidence.value,
        }
        if gap.source_file is not None:
            row["source_file"] = gap.source_file
        if gap.source_line is not None:
            row["source_line"] = gap.source_line
        rows.append(row)
    return rows


def project_payload(graph: JourneyGraph) -> dict[str, Any]:
    """One detected app: ends + gaps (+ framework/root)."""
    root = graph.project_root
    return {
        "framework": graph.framework,
        "root": root.name or str(root),
        "ends": end_route_map(graph),
        "gaps": gaps_to_json(graph.gaps),
    }


def serialize_end_routes(graphs: Sequence[JourneyGraph]) -> Mapping[str, object]:
    """JSON-ready envelope for one or many detected projects.

    Always::

        {"projects": [{"framework", "root", "ends", "gaps"}, …]}

    ``ends`` alone can look complete while extraction quietly missed
    links/routes — ``gaps`` carry that audit trail for API/CLI consumers.
    """
    return {"projects": [project_payload(graph) for graph in graphs]}


def _default_start(routes: tuple[RouteNode, ...]) -> str:
    for route in routes:
        if route.url_path == "/":
            return route.url_path
    for route in routes:
        if route.is_index and not route.is_wildcard:
            return route.url_path
    for route in routes:
        if not route.is_wildcard:
            return route.url_path
    return "/"


def _adjacency(
    routes: tuple[RouteNode, ...],
    edges: tuple[NavEdge, ...],
    start_path: str,
) -> dict[str, list[str]]:
    """Build from→[to…] including expansion of shared (from_path=None) edges."""
    layout_routes: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        if route.is_wildcard:
            continue
        if route.layout:
            layout_routes[route.layout].append(route.url_path)

    known = {r.url_path for r in routes}
    adj: dict[str, set[str]] = defaultdict(set)

    for edge in edges:
        if edge.to_path not in known:
            continue

        sources = _resolve_from_paths(edge, routes, layout_routes, start_path)
        for src in sources:
            if src == edge.to_path:
                continue
            if src not in known:
                continue
            adj[src].add(edge.to_path)

    return {src: sorted(dests) for src, dests in adj.items()}


def _resolve_from_paths(
    edge: NavEdge,
    routes: tuple[RouteNode, ...],
    layout_routes: dict[str, list[str]],
    start_path: str,
) -> list[str]:
    if edge.from_path is not None:
        return [edge.from_path]

    # Shared chrome: if edge lives next to a layout file, treat as global nav
    # from the app entry (start). Avoids exploding into a full clique among
    # every layout sibling (admin sidebars).
    layout = _layout_near_source(edge.source_file, layout_routes)
    if layout is not None:
        return [start_path]

    # Auth forms / misc shared components → from entry as well
    return [start_path]


def _layout_near_source(source_file: str, layout_routes: dict[str, list[str]]) -> str | None:
    src_dir = str(Path(source_file).parent).replace("\\", "/")
    for layout in layout_routes:
        layout_dir = str(Path(layout).parent).replace("\\", "/")
        if src_dir == layout_dir:
            return layout
    return None


def _enumerate_simple_paths(
    adj: dict[str, list[str]],
    start: str,
    *,
    max_depth: int,
    max_paths: int,
) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []

    def dfs(current: list[str]) -> None:
        if len(paths) >= max_paths:
            return
        if len(current) >= 2:
            paths.append(tuple(current))
        if len(current) > max_depth:
            return
        for nxt in adj.get(current[-1], []):
            if nxt in current:
                continue
            dfs(current + [nxt])
            if len(paths) >= max_paths:
                return

    dfs([start])
    return paths


def format_journey(path: JourneyPath) -> str:
    return " → ".join(path.steps)
