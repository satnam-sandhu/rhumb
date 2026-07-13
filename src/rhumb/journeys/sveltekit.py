"""SvelteKit journey plugin (stub).

Future stack:
- filesystem: ``src/routes`` (+layout / +page conventions)
- Svelte parser for ``.svelte`` nav (``goto``, ``<a href>``)
- ``parse_js`` for ``.ts`` load / hooks only
"""

from __future__ import annotations

from pathlib import Path

from rhumb.framework import FrameworkDetection
from rhumb.graphify_runner import AstResult
from rhumb.journeys.types import Confidence, JourneyGap, JourneyGraph


class SvelteKitExtractor:
    framework = "sveltekit"

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
        ast_result: AstResult | None = None,
    ) -> JourneyGraph:
        del detection, ast_result
        return JourneyGraph(
            framework=self.framework,
            project_root=project_dir,
            gaps=(
                JourneyGap(
                    message="sveltekit extractor not implemented yet (filesystem + Svelte parser planned)",
                    confidence=Confidence.LOW,
                ),
            ),
        )
