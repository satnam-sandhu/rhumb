from __future__ import annotations

from tributary.journeys.base import JourneyExtractor
from tributary.journeys.expo_router import ExpoRouterExtractor
from tributary.journeys.react_router import ReactRouterExtractor
from tributary.journeys.sveltekit import SvelteKitExtractor
from tributary.journeys.tanstack_router import TanStackRouterExtractor
from tributary.journeys.vue_router import VueRouterExtractor

# Framework id from FrameworkDetection.framework → plugin.
# Unlisted frameworks → run_journey reports "not implemented".
EXTRACTORS: dict[str, JourneyExtractor] = {
    "react-router": ReactRouterExtractor(),
    "expo-router": ExpoRouterExtractor(),
    "tanstack-router": TanStackRouterExtractor(),
    # Future / stub — same registry, swap impl when ready:
    "vue-router": VueRouterExtractor(),
    "sveltekit": SvelteKitExtractor(),
}


def get_extractor(framework: str) -> JourneyExtractor | None:
    return EXTRACTORS.get(framework)
