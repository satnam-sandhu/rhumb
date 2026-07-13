"""Rhumb — constant-bearing journeys through your app.

Static user journey graphs from frontend source.

Install::

    pip install rhumb

Library::

    from rhumb import extract_journeys

    for graph in extract_journeys("./my-app"):
        print(graph.framework, graph.journeys)

CLI::

    rhumb ./my-app --journey
"""

from __future__ import annotations

from rhumb.analysis import AnalysisContext, analyze, print_prerequisites, run_prerequisites
from rhumb.cli import main
from rhumb.framework import FrameworkDetection, detect_all_frameworks, format_projects
from rhumb.graphify_runner import (
    OUTPUT_BASE,
    prepare_output_base,
    run_ast_for_project,
    run_ast_for_projects,
)
from rhumb.instrument import run_instrument
from rhumb.journey import extract_journeys, run_journey
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
    # CLI / lower-level
    "main",
    "run_journey",
    "run_instrument",
    "run_prerequisites",
    "print_prerequisites",
    "format_projects",
    "OUTPUT_BASE",
    "prepare_output_base",
    "run_ast_for_project",
    "run_ast_for_projects",
]

__version__ = "0.1.0"
