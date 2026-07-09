from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".venv", "graphify-out"}


@dataclass(frozen=True)
class FrameworkDetection:
    framework: str
    routing_style: str
    confidence: str
    signals: list[str] = field(default_factory=list)
    root: str | None = None
    package_name: str | None = None


def detect_framework(project_path: Path) -> FrameworkDetection:
    """Detect primary frontend framework + routing style from project files."""
    detected = detect_all_frameworks(project_path)
    if not detected:
        return FrameworkDetection(
            framework="unknown",
            routing_style="unknown",
            confidence="low",
            signals=["no known router framework detected"],
        )
    return max(detected, key=_rank)


def detect_all_frameworks(project_path: Path) -> list[FrameworkDetection]:
    """Detect frameworks across a repo, including monorepo subpackages."""
    root = project_path.resolve()
    package_files = _find_package_json_files(root)

    if not package_files:
        return []

    detected: list[FrameworkDetection] = []
    for package_json in package_files:
        candidate = _detect_from_package(package_json, root)
        if candidate.framework != "unknown":
            detected.append(candidate)

    return sorted(detected, key=lambda item: (item.root or "", item.framework))


def _find_package_json_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("package.json"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        found.append(path)
    return sorted(found)


def _detect_from_package(package_json: Path, scan_root: Path) -> FrameworkDetection:
    package_data = json.loads(package_json.read_text(encoding="utf-8"))
    deps = {**package_data.get("dependencies", {}), **package_data.get("devDependencies", {})}
    package_name = package_data.get("name")
    project_root = package_json.parent
    rel_root = project_root.relative_to(scan_root).as_posix()
    if rel_root == ".":
        rel_root = scan_root.name

    signals: list[str] = []
    has_app_dir = _has_routing_dir(project_root, "app")
    has_pages_dir = _has_routing_dir(project_root, "pages")
    has_angular_json = (project_root / "angular.json").is_file() or (scan_root / "angular.json").is_file()

    def result(**kwargs: object) -> FrameworkDetection:
        return FrameworkDetection(
            package_name=package_name if isinstance(package_name, str) else None,
            root=rel_root,
            signals=signals,
            **kwargs,
        )

    if "expo-router" in deps:
        signals.append("dependency: expo-router")
        if has_app_dir:
            signals.append("directory: app/")
        return result(
            framework="expo-router",
            routing_style="file-based",
            confidence="high" if has_app_dir else "medium",
        )

    if "next" in deps:
        signals.append("dependency: next")
        if (project_root / "app").is_dir():
            signals.append("directory: app/")
        elif (project_root / "src" / "app").is_dir():
            signals.append("directory: src/app/")
        elif (project_root / "pages").is_dir():
            signals.append("directory: pages/")
        elif (project_root / "src" / "pages").is_dir():
            signals.append("directory: src/pages/")
        return result(
            framework="next",
            routing_style="file-based",
            confidence="high" if (has_app_dir or has_pages_dir) else "medium",
        )

    if has_angular_json or "@angular/router" in deps:
        if has_angular_json:
            signals.append("file: angular.json")
        if "@angular/router" in deps:
            signals.append("dependency: @angular/router")
        return result(
            framework="angular",
            routing_style="config",
            confidence="high",
        )

    if "vue-router" in deps:
        signals.append("dependency: vue-router")
        return result(
            framework="vue-router",
            routing_style="config",
            confidence="high",
        )

    if "@sveltejs/kit" in deps:
        signals.append("dependency: @sveltejs/kit")
        return result(
            framework="sveltekit",
            routing_style="file-based",
            confidence="high" if (project_root / "src" / "routes").is_dir() else "medium",
        )

    if "@remix-run/react" in deps or "@remix-run/node" in deps:
        signals.append("dependency: remix")
        return result(
            framework="remix",
            routing_style="file-based",
            confidence="high",
        )

    if "@tanstack/react-router" in deps:
        signals.append("dependency: @tanstack/react-router")
        if (project_root / "src" / "routes").is_dir():
            signals.append("directory: src/routes/")
        if (project_root / "src" / "routeTree.gen.ts").is_file():
            signals.append("file: src/routeTree.gen.ts")
        return result(
            framework="tanstack-router",
            routing_style="file-based",
            confidence="high"
            if (project_root / "src" / "routes").is_dir()
            else "medium",
        )

    if "react-router-dom" in deps or "react-router" in deps:
        dep = "react-router-dom" if "react-router-dom" in deps else "react-router"
        signals.append(f"dependency: {dep}")
        return result(
            framework="react-router",
            routing_style="config",
            confidence="high",
        )

    if "react" in deps and "vite" in deps:
        signals.append("dependency: vite + react")
        if any(key.startswith("@tauri-apps/") for key in deps):
            signals.append("platform: tauri")
        return result(
            framework="vite-react",
            routing_style="single-page",
            confidence="medium",
        )

    signals.append("no router dependency matched")
    return result(
        framework="unknown",
        routing_style="unknown",
        confidence="low",
    )


def _has_routing_dir(project_root: Path, name: str) -> bool:
    return (project_root / name).is_dir() or (project_root / "src" / name).is_dir()


def _rank(detection: FrameworkDetection | None) -> int:
    if detection is None or detection.framework == "unknown":
        return 0
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(detection.confidence, 0)
    framework_score = {
        "expo-router": 7,
        "next": 6,
        "angular": 6,
        "vue-router": 5,
        "sveltekit": 5,
        "remix": 5,
        "tanstack-router": 5,
        "react-router": 4,
        "vite-react": 2,
    }.get(detection.framework, 0)
    return framework_score + confidence_score


def format_projects(detections: list[FrameworkDetection]) -> str:
    if not detections:
        return "Projects found: 0\nNo known frontend projects detected."

    total = len(detections)
    blocks = [_format_project_block(index, total, detection) for index, detection in enumerate(detections, start=1)]
    return f"Projects found: {total}\n\n" + "\n\n".join(blocks)


def _format_project_block(index: int, total: int, detection: FrameworkDetection) -> str:
    title = detection.package_name or detection.root or f"project-{index}"
    lines = [
        "=" * 60,
        f"Project {index}/{total}: {title}",
        "=" * 60,
        f"Path:       {detection.root}",
    ]
    if detection.package_name and detection.package_name != title:
        lines.append(f"Package:    {detection.package_name}")
    lines.extend(
        [
            f"Framework:  {detection.framework}",
            f"Routing:    {detection.routing_style}",
            f"Confidence: {detection.confidence}",
        ]
    )
    if detection.signals:
        lines.append("Signals:")
        lines.extend(f"  - {signal}" for signal in detection.signals)
    return "\n".join(lines)


def format_framework(detection: FrameworkDetection) -> str:
    return format_projects([detection])
