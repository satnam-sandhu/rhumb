"""Deterministic user journey mapping and PostHog instrumentation analysis."""

from deterministic_kit.analysis import AnalysisContext, print_prerequisites, run_prerequisites
from deterministic_kit.cli import main
from deterministic_kit.framework import detect_all_frameworks, format_projects
from deterministic_kit.graphify_runner import (
    OUTPUT_BASE,
    prepare_output_base,
    run_ast_for_project,
    run_ast_for_projects,
)
from deterministic_kit.instrument import run_instrument
from deterministic_kit.journey import run_journey

__all__ = [
    "main",
    "AnalysisContext",
    "detect_all_frameworks",
    "format_projects",
    "OUTPUT_BASE",
    "prepare_output_base",
    "run_ast_for_project",
    "run_ast_for_projects",
    "run_prerequisites",
    "print_prerequisites",
    "run_journey",
    "run_instrument",
]
