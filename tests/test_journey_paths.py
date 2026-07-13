"""Journey path enumeration — /a → /b → /c sequences."""

from __future__ import annotations

from pathlib import Path

from rhumb.journeys.paths import (
    build_journeys,
    end_route_map,
    format_journey,
    journeys_by_end,
    serialize_end_routes,
)
from rhumb.journeys.types import (
    Confidence,
    JourneyGap,
    JourneyGraph,
    JourneyPath,
    NavEdge,
    RouteNode,
    RouteSource,
)


def _route(path: str, component: str = "X.tsx", layout: str | None = None) -> RouteNode:
    return RouteNode(
        url_path=path,
        component=component,
        source_file="src/App.tsx",
        source_line=1,
        layout=layout,
        source=RouteSource.CONFIG_AST,
    )


def test_linear_funnel_journey() -> None:
    """Ecommerce-style chain with explicit page→page edges."""
    routes = (
        _route("/search", "Search.tsx"),
        _route("/product-details", "Product.tsx"),
        _route("/cart", "Cart.tsx"),
        _route("/checkout", "Checkout.tsx"),
    )
    edges = (
        NavEdge("/search", "/product-details", "Search.tsx", 10, "link"),
        NavEdge("/product-details", "/cart", "Product.tsx", 20, "link"),
        NavEdge("/cart", "/checkout", "Cart.tsx", 30, "link"),
    )
    graph = JourneyGraph(
        framework="react-router",
        project_root=Path("."),
        routes=routes,
        edges=edges,
    )
    journeys = build_journeys(graph, start="/search")
    assert journeys
    assert format_journey(journeys[0]) == (
        "/search → /product-details → /cart → /checkout"
    )


def test_shared_sidebar_from_home_only() -> None:
    layout = "src/layout/AppLayout.tsx"
    routes = (
        _route("/", "Home.tsx", layout=layout),
        _route("/calendar", "Calendar.tsx", layout=layout),
        _route("/profile", "Profile.tsx", layout=layout),
    )
    edges = (
        NavEdge(None, "/calendar", "src/layout/AppSidebar.tsx", 1, "nav_config"),
        NavEdge(None, "/profile", "src/layout/AppSidebar.tsx", 2, "nav_config"),
    )
    graph = JourneyGraph(
        framework="react-router",
        project_root=Path("."),
        routes=routes,
        edges=edges,
    )
    journeys = build_journeys(graph, start="/")
    texts = {format_journey(j) for j in journeys}
    assert "/ → /calendar" in texts
    assert "/ → /profile" in texts
    # Shared chrome must not create calendar → profile clique by default
    assert "/ → /calendar → /profile" not in texts


def test_journeys_by_end_groups_inbound_paths() -> None:
    journeys = (
        JourneyPath(steps=("/search", "/product-details", "/cart", "/checkout")),
        JourneyPath(steps=("/search", "/cart", "/checkout")),
        JourneyPath(steps=("/", "/profile")),
        JourneyPath(steps=("/search", "/product-details", "/cart", "/checkout")),  # dup
    )
    by_end = journeys_by_end(journeys)
    assert by_end == {
        "/checkout": [
            ["/search", "/product-details", "/cart", "/checkout"],
            ["/search", "/cart", "/checkout"],
        ],
        "/profile": [["/", "/profile"]],
    }


def test_end_route_map_and_serialize_single_vs_multi() -> None:
    routes = (
        _route("/search"),
        _route("/cart"),
        _route("/checkout"),
    )
    edges = (
        NavEdge("/search", "/cart", "a.tsx", 1, "link"),
        NavEdge("/cart", "/checkout", "b.tsx", 2, "link"),
    )
    base = JourneyGraph(
        framework="react-router",
        project_root=Path("/tmp/shop"),
        routes=routes,
        edges=edges,
    )
    graph = JourneyGraph(
        framework=base.framework,
        project_root=base.project_root,
        routes=base.routes,
        edges=base.edges,
        journeys=build_journeys(base, start="/search"),
        gaps=(
            JourneyGap(
                message="nav target not in route tree: /legacy",
                source_file="src/layout/AppSidebar.tsx",
                source_line=48,
                confidence=Confidence.MEDIUM,
            ),
        ),
    )
    single = end_route_map(graph)
    assert "/checkout" in single
    assert ["/search", "/cart", "/checkout"] in single["/checkout"]

    payload = serialize_end_routes([graph])
    assert list(payload.keys()) == ["projects"]
    assert len(payload["projects"]) == 1
    project = payload["projects"][0]
    assert project["framework"] == "react-router"
    assert project["root"] == "shop"
    assert project["ends"] == single
    assert project["gaps"] == [
        {
            "message": "nav target not in route tree: /legacy",
            "confidence": "medium",
            "source_file": "src/layout/AppSidebar.tsx",
            "source_line": 48,
        }
    ]

    other = JourneyGraph(
        framework="expo-router",
        project_root=Path("/tmp/mobile"),
        journeys=(JourneyPath(steps=("/", "/settings")),),
    )
    multi = serialize_end_routes([graph, other])
    assert len(multi["projects"]) == 2
    assert multi["projects"][1]["framework"] == "expo-router"
    assert multi["projects"][1]["ends"]["/settings"] == [["/", "/settings"]]
    assert multi["projects"][1]["gaps"] == []
