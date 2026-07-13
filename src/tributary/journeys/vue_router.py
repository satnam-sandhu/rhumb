"""Vue Router journey plugin (stub).

Future stack:
- tree-sitter / @vue/compiler-sfc for ``.vue`` SFCs
- ``parse_js`` for ``router/index.ts`` route tables
- filesystem only if Nuxt-style (separate ``nuxt`` plugin later)
"""

from __future__ import annotations

from pathlib import Path

from tributary.framework import FrameworkDetection
from tributary.graphify_runner import AstResult
from tributary.journeys.types import Confidence, JourneyGap, JourneyGraph


class VueRouterExtractor:
    framework = "vue-router"

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
                    message="vue-router extractor not implemented yet (SFC + router TS planned)",
                    confidence=Confidence.LOW,
                ),
            ),
        )
