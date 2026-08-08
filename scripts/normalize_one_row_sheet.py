"""Normalize an AI-authored one-row sprite strip into Phoebe Cleaner's 5x3 atlas."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-frames", type=int, default=8)
    parser.add_argument("--cell-width", type=int, default=256)
    parser.add_argument("--cell-height", type=int, default=384)
    parser.add_argument("--output-frames", type=int, default=15)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--vertical-padding", type=float, default=0.18)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Image.open(args.input).convert("RGBA")
    alpha_bbox = source.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise SystemExit("Input sheet has no visible pixels")

    _, visible_top, _, visible_bottom = alpha_bbox
    visible_height = visible_bottom - visible_top
    padding = max(8, round(visible_height * args.vertical_padding))
    crop_top = max(0, visible_top - padding)
    crop_bottom = min(source.height, visible_bottom + padding)

    normalized: list[Image.Image] = []
    for index in range(args.source_frames):
        left = round(index * source.width / args.source_frames)
        right = round((index + 1) * source.width / args.source_frames)
        frame = source.crop((left, crop_top, right, crop_bottom))
        scale = min(args.cell_width / frame.width, args.cell_height / frame.height)
        resized_width = max(1, round(frame.width * scale))
        resized_height = max(1, round(frame.height * scale))
        frame = frame.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

        cell = Image.new("RGBA", (args.cell_width, args.cell_height), (0, 0, 0, 0))
        x = (args.cell_width - resized_width) // 2
        y = (args.cell_height - resized_height) // 2
        cell.alpha_composite(frame, (x, y))
        normalized.append(cell)

    rows = math.ceil(args.output_frames / args.columns)
    atlas = Image.new(
        "RGBA",
        (args.columns * args.cell_width, rows * args.cell_height),
        (0, 0, 0, 0),
    )
    for output_index in range(args.output_frames):
        frame = normalized[output_index % len(normalized)]
        x = (output_index % args.columns) * args.cell_width
        y = (output_index // args.columns) * args.cell_height
        atlas.alpha_composite(frame, (x, y))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(args.output, optimize=True)
    print(
        f"Wrote {args.output} ({atlas.width}x{atlas.height}); "
        f"source vertical crop={crop_top}:{crop_bottom}"
    )


if __name__ == "__main__":
    main()
