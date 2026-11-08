"""Encode imagegen 4 by 8 action sheets as browser-native GIF clips.

Usage: python scripts/encode_expert_gifs.py <directory of character.png sheets>
Requires Pillow. Source artwork is generated in one imagegen call per character.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

CLIPS = ("idle", "thinking", "working", "reading", "handoff", "waiting", "success", "error")


def encode(source: Path, destination: Path) -> None:
    sheet = Image.open(source).convert("RGBA")
    width, height = sheet.size
    frames = [
        sheet.crop(
            (
                round(col * width / 4),
                round(row * height / 8),
                round((col + 1) * width / 4),
                round((row + 1) * height / 8),
            )
        )
        for row in range(8)
        for col in range(4)
    ]
    # GIF has one-bit alpha. Reserve palette entry 255 for transparent pixels.
    target = destination / "v2" / source.stem
    target.mkdir(parents=True, exist_ok=True)
    for row, clip in enumerate(CLIPS):
        action = []
        for frame in frames[row * 4 : (row + 1) * 4]:
            frame.thumbnail((180, 180), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (192, 192))
            canvas.alpha_composite(frame, ((192 - frame.width) // 2, (192 - frame.height) // 2))
            action.append(canvas)
        action[0].save(target / f"{clip}.png", optimize=True)
        palette_strip = Image.new("RGB", (192 * 4, 192), "white")
        for col, frame in enumerate(action):
            palette_strip.paste(frame, (col * 192, 0), frame)
        palette = palette_strip.quantize(colors=255)
        indexed = []
        for frame in action:
            flattened = Image.new("RGB", frame.size, "white")
            flattened.paste(frame, mask=frame.getchannel("A"))
            image = flattened.quantize(palette=palette, dither=Image.Dither.NONE)
            image.paste(
                255, mask=frame.getchannel("A").point(lambda value: 255 if value < 128 else 0)
            )
            image.info["transparency"] = 255
            indexed.append(image)
        durations = [1800, 180, 180, 500] if clip == "idle" else [240, 240, 300, 240]
        indexed[0].save(
            target / f"{clip}.gif",
            save_all=True,
            append_images=indexed[1:],
            duration=durations,
            loop=0,
            transparency=255,
            disposal=2,
            optimize=False,
        )
    # Stable legacy URLs now serve a new portrait, never an animation atlas.
    Image.open(target / "idle.png").save(destination / f"{source.stem}.webp", quality=90)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dashboard/public/expert-animations"))
    args = parser.parse_args()
    for source in sorted(args.source.glob("*.png")):
        encode(source, args.output)
        print(source.stem)


if __name__ == "__main__":
    main()
