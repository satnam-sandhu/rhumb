"""Tributary — static user journey graphs from frontend source.

Install::

    pip install tributary

Library::

    from tributary import extract_journeys

    for graph in extract_journeys("./my-app"):
        print(graph.framework, graph.journeys)

CLI::

    tributary ./my-app --journey
"""

from __future__ import annotations

from tributary.analysis import AnalysisContext, analyze, print_prerequisites, run_prerequisites
from tributary.cli import main
from tributary.framework import FrameworkDetection, detect_all_frameworks, format_projects
from tributary.graphify_runner import (
    OUTPUT_BASE,
    prepare_output_base,
    run_ast_for_project,
    run_ast_for_projects,
)
from tributary.instrument import run_instrument
from tributary.journey import extract_journeys, run_journey
from tributary.journeys.registry import get_extractor
from tributary.journeys.types import (
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
