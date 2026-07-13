from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from rhumb.framework import FrameworkDetection
from rhumb.journeys.types import JourneyGraph


@runtime_checkable
class JourneyExtractor(Protocol):
    """Per-framework journey plugin.

    Implement one module per framework (react_router, vue_router, sveltekit, …).
    Shared JS/TS hybrid parsing lives in ``parse_js`` — plugins call it, not own it.
    File-based frameworks add a filesystem pass; Vue/Svelte add SFC parsers later.
    """

    framework: str

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
    ) -> JourneyGraph:
        """Build a journey graph for one detected project package."""
        ...
