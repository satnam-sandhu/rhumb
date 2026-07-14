#!/usr/bin/env python3
"""Render examples/tanstack-kitchen-sink/demo.gif from journeys.json (no browser).

Usage (from repo root):
  uv run --with pillow python examples/tanstack-kitchen-sink/render_gif.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "journeys.json"
OUT_GIF = HERE / "demo.gif"

BG = (30, 30, 46)  # catppuccin mocha base
FG = (205, 214, 244)
MUTED = (108, 112, 134)
GREEN = (166, 227, 161)
YELLOW = (249, 226, 175)
PEACH = (250, 179, 135)
WIDTH, HEIGHT = 720, 420
PAD = 20
LINE_H = 18


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/Library/Fonts/SF-Mono-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    if draw.textlength(text, font=font) <= max_w:
        return [text]
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else f"{cur} {word}"
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


def color_for(line: str) -> tuple[int, int, int]:
    s = line.lstrip()
    if s.startswith("#") or s.startswith("$"):
        return MUTED if s.startswith("#") else GREEN
    if '"ends"' in s or '"gaps"' in s or '"projects"' in s:
        return PEACH
    if '"message"' in s or '"confidence"' in s:
        return YELLOW
    if s.startswith("/") and "→" in s:
        return GREEN
    return FG


def build_script(payload: dict) -> list[str]:
    pretty = json.dumps(payload, indent=2)
    lines = [
        "# Public app: TanStack Router kitchen-sink-file-based",
        "$ uv run rhumb ./kitchen-sink-file-based --journey",
        "",
        *pretty.splitlines(),
        "",
        "# ends = inbound journeys · gaps = unresolved (honest)",
    ]
    return lines


def render_frames(script: list[str]) -> list[Image.Image]:
    font = load_font(14)
    prompt_font = load_font(13)
    frames: list[Image.Image] = []
    max_w = WIDTH - 2 * PAD

    probe = Image.new("RGB", (WIDTH, HEIGHT), BG)
    probe_draw = ImageDraw.Draw(probe)

    expanded: list[str] = []
    for raw in script:
        expanded.extend(wrap_line(probe_draw, raw, font, max_w))

    # Reveal 2 lines per frame to keep GIF small
    step = 2
    for i in range(0, len(expanded), step):
        visible = expanded[: i + step]
        window = visible[-16:]
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        draw.text((PAD, 10), "rhumb · journey map", font=prompt_font, fill=MUTED)
        y = 32
        for line in window:
            draw.text((PAD, y), line, font=font, fill=color_for(line))
            y += LINE_H
        frames.append(img)

    frames.extend([frames[-1]] * 10)
    return frames


def main() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    # Palette-quantize for smaller checked-in GIF
    frames = [
        f.convert("P", palette=Image.Palette.ADAPTIVE, colors=48)
        for f in render_frames(build_script(payload))
    ]
    frames[0].save(
        OUT_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=110,
        loop=0,
        optimize=True,
    )
    print(f"wrote {OUT_GIF} ({len(frames)} frames, {OUT_GIF.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
