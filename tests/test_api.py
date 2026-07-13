"""Public API smoke tests for library install / programmatic use."""

from __future__ import annotations

from pathlib import Path

import rhumb
from rhumb import (
    JourneyGraph,
    analyze,
    extract_journeys,
)


def _mini_tanstack(tmp: Path) -> Path:
    routes = tmp / "src" / "routes"
    routes.mkdir(parents=True)
    (routes / "index.tsx").write_text(
        'import { createFileRoute, Link } from "@tanstack/react-router";\n'
        "export const Route = createFileRoute('/')({});\n"
        "export function Home() { return <Link to=\"/about\">About</Link>; }\n",
        encoding="utf-8",
    )
    (routes / "about.tsx").write_text(
        'import { createFileRoute } from "@tanstack/react-router";\n'
        "export const Route = createFileRoute('/about')({});\n",
        encoding="utf-8",
    )
    (tmp / "package.json").write_text(
        '{"name":"demo","dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )
    return tmp


def test_package_version_and_exports() -> None:
    assert rhumb.__version__ == "0.1.0"
    assert callable(extract_journeys)
    assert callable(analyze)


def test_extract_journeys_programmatic(tmp_path: Path) -> None:
    _mini_tanstack(tmp_path)
    graphs = extract_journeys(tmp_path)
    assert len(graphs) == 1
    graph = graphs[0]
    assert isinstance(graph, JourneyGraph)
    assert graph.framework == "tanstack-router"
    urls = {r.url_path for r in graph.routes}
    assert "/" in urls and "/about" in urls
    assert any(e.to_path == "/about" for e in graph.edges)


def test_analyze_then_extract(tmp_path: Path) -> None:
    _mini_tanstack(tmp_path)
    ctx = analyze(tmp_path)
    assert ctx.projects
    assert ctx.projects[0].framework == "tanstack-router"
    graphs = extract_journeys(ctx)
    assert graphs[0].journeys or graphs[0].edges
