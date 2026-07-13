"""Rhumb — constant-bearing journeys through your app.

Static user journey graphs from frontend source.

Install::

    pip install rhumb

Library::

    from rhumb import extract_end_routes

    print(extract_end_routes("./my-app"))

CLI::

    rhumb ./my-app --journey
"""

from __future__ import annotations

from rhumb.analysis import AnalysisContext, analyze, print_prerequisites, run_prerequisites
from rhumb.cli import main
from rhumb.framework import FrameworkDetection, detect_all_frameworks, format_projects
from rhumb.instrument import run_instrument
from rhumb.journey import extract_end_routes, extract_journeys, run_journey
from rhumb.journeys.paths import (
    EndRouteMap,
    end_route_map,
    journeys_by_end,
    serialize_end_routes,
)
from rhumb.journeys.registry import get_extractor
from rhumb.journeys.types import (
    Confidence,
    JourneyGap,
    JourneyGraph,
    JourneyPath,
    NavEdge,
    RouteNode,
    RouteSource,
)

__all__ = [
    # Primary API
    "extract_end_routes",
    "extract_journeys",
    "analyze",
    "JourneyGraph",
    "JourneyPath",
    "RouteNode",
    "NavEdge",
    "JourneyGap",
    "Confidence",
    "RouteSource",
    "FrameworkDetection",
    "detect_all_frameworks",
    "get_extractor",
    "AnalysisContext",
    "EndRouteMap",
    "end_route_map",
    "journeys_by_end",
    "serialize_end_routes",
    # CLI / lower-level
    "main",
    "run_journey",
    "run_instrument",
    "run_prerequisites",
    "print_prerequisites",
    "format_projects",
]

__version__ = "0.1.0"
