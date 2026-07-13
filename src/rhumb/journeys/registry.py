from __future__ import annotations

from rhumb.journeys.base import JourneyExtractor
from rhumb.journeys.expo_router import ExpoRouterExtractor
from rhumb.journeys.react_router import ReactRouterExtractor
from rhumb.journeys.sveltekit import SvelteKitExtractor
from rhumb.journeys.tanstack_router import TanStackRouterExtractor
from rhumb.journeys.vue_router import VueRouterExtractor

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
