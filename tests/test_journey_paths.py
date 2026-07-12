"""Journey path enumeration — /a → /b → /c sequences."""

from __future__ import annotations

from pathlib import Path

from deterministic_kit.journeys.paths import build_journeys, format_journey
from deterministic_kit.journeys.types import (
    Confidence,
    JourneyGraph,
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
