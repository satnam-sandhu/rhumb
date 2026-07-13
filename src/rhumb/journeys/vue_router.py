"""Vue Router journey plugin (stub).

Future stack:
- tree-sitter / @vue/compiler-sfc for ``.vue`` SFCs
- ``parse_js`` for ``router/index.ts`` route tables
- filesystem only if Nuxt-style (separate ``nuxt`` plugin later)
"""

from __future__ import annotations

from pathlib import Path

from rhumb.framework import FrameworkDetection
from rhumb.journeys.types import Confidence, JourneyGap, JourneyGraph


class VueRouterExtractor:
    framework = "vue-router"

    def extract(
        self,
        project_dir: Path,
        detection: FrameworkDetection,
    ) -> JourneyGraph:
        del detection
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
