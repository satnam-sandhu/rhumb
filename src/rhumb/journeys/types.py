from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RouteSource(str, Enum):
    """How the route was discovered — framework plugins set this."""

    CONFIG_AST = "config_ast"  # react-router, vue-router, angular
    FILESYSTEM = "filesystem"  # next, sveltekit, expo, remix, tanstack
    GENERATED = "generated"  # routeTree.gen.ts etc.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteNode:
    """Framework-agnostic route in the journey graph."""

    url_path: str
    component: str | None
    source_file: str
    source_line: int
    is_index: bool = False
    is_wildcard: bool = False
    layout: str | None = None
    confidence: Confidence = Confidence.HIGH
    source: RouteSource = RouteSource.UNKNOWN


@dataclass(frozen=True)
class NavEdge:
    """Transition between routes (link, navigate, sidebar, redirect)."""

    from_path: str | None
    to_path: str
    source_file: str
    source_line: int
    kind: str  # link | navigate | nav_config | redirect | filesystem
    confidence: Confidence = Confidence.HIGH


@dataclass(frozen=True)
class JourneyGap:
    """Something we could not resolve — prefer flagged gaps over silent wrongness."""

    message: str
    source_file: str | None = None
    source_line: int | None = None
    confidence: Confidence = Confidence.LOW


@dataclass(frozen=True)
class JourneyPath:
    """One concrete user journey: ordered URL steps."""

    steps: tuple[str, ...]

    def __str__(self) -> str:
        return " → ".join(self.steps)


@dataclass(frozen=True)
class JourneyGraph:
    """Shared journey output — every framework plugin returns this shape."""

    framework: str
    project_root: Path
    routes: tuple[RouteNode, ...] = ()
    edges: tuple[NavEdge, ...] = ()
    gaps: tuple[JourneyGap, ...] = ()
    journeys: tuple[JourneyPath, ...] = ()
    meta: dict[str, str] = field(default_factory=dict)
