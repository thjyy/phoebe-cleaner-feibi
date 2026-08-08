"""Normalize Phoebe sprite pivots and optionally build 30-frame atlases.

The generated source atlases contain changing whitespace from cell to cell.  A
renderer that draws every cell from its top-left corner therefore makes the
character jump even when the pose itself is valid.  This tool finds a stable
landmark in Phoebe's blonde hair/skin palette, aligns that landmark across the
sequence, and keeps props/effects attached by translating the whole frame.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


CELL_WIDTH = 256
CELL_HEIGHT = 384
SOURCE_COLUMNS = 5
SOURCE_FRAME_COUNT = 15
BLEND_ONLY_SHEETS = {"exit-sparkle.png", "exit-teleport.png"}


def split_atlas(path: Path) -> list[Image.Image]:
    atlas = Image.open(path).convert("RGBA")
    expected = (SOURCE_COLUMNS * CELL_WIDTH, 3 * CELL_HEIGHT)
    if atlas.size != expected:
        atlas = atlas.resize(expected, Image.Resampling.LANCZOS)
    return [
        atlas.crop(
            (
                (index % SOURCE_COLUMNS) * CELL_WIDTH,
                (index // SOURCE_COLUMNS) * CELL_HEIGHT,
                (index % SOURCE_COLUMNS + 1) * CELL_WIDTH,
                (index // SOURCE_COLUMNS + 1) * CELL_HEIGHT,
            )
        )
        for index in range(SOURCE_FRAME_COUNT)
    ]


def character_metrics(frame: Image.Image) -> tuple[float, float, float, float] | None:
    """Return a prop-independent center and size from Phoebe's warm palette."""
    pixels = frame.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(CELL_HEIGHT):
        for x in range(CELL_WIDTH):
            red, green, blue, alpha = pixels[x, y]
            if (
                alpha >= 96
                and red >= 170
                and green >= 130
                and blue <= 210
                and red >= blue + 18
                and green >= blue + 4
            ):
                xs.append(x)
                ys.append(y)
    if len(xs) < 80:
        return None
    xs.sort()
    ys.sort()
    # Medians/percentiles resist moving hair tips, hands, and the paper prop.
    low = max(0, round(len(xs) * 0.05))
    high = min(len(xs) - 1, round(len(xs) * 0.95))
    return (
        float(xs[len(xs) // 2]),
        float(ys[len(ys) // 2]),
        float(max(1, xs[high] - xs[low])),
        float(max(1, ys[high] - ys[low])),
    )


def character_anchor(frame: Image.Image) -> tuple[float, float] | None:
    metrics = character_metrics(frame)
    return None if metrics is None else (metrics[0], metrics[1])


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def fill_missing_offsets(values: list[tuple[int, int] | None]) -> list[tuple[int, int]]:
    valid = [index for index, value in enumerate(values) if value is not None]
    if not valid:
        return [(0, 0)] * len(values)
    result: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        if value is not None:
            result.append(value)
            continue
        before = max((candidate for candidate in valid if candidate < index), default=None)
        after = min((candidate for candidate in valid if candidate > index), default=None)
        if before is None:
            result.append(values[after])  # type: ignore[arg-type]
        elif after is None:
            result.append(values[before])  # type: ignore[arg-type]
        else:
            ratio = (index - before) / (after - before)
            left = values[before]
            right = values[after]
            assert left is not None and right is not None
            result.append(
                (
                    round(left[0] + (right[0] - left[0]) * ratio),
                    round(left[1] + (right[1] - left[1]) * ratio),
                )
            )
    return result


def translate(frame: Image.Image, offset: tuple[int, int]) -> Image.Image:
    shifted = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    shifted.alpha_composite(frame, offset)
    return shifted


def match_character_scale(
    frames: list[Image.Image], reference_frames: list[Image.Image]
) -> list[Image.Image]:
    """Match every drawn in-between to the size of its neighboring key poses."""
    matched: list[Image.Image] = []
    for index, frame in enumerate(frames):
        metrics = character_metrics(frame)
        left = character_metrics(reference_frames[index])
        right = character_metrics(reference_frames[min(index + 1, len(reference_frames) - 1)])
        if metrics is None or left is None or right is None:
            matched.append(frame)
            continue
        target_width = (left[2] + right[2]) / 2.0
        target_height = (left[3] + right[3]) / 2.0
        width_ratio = target_width / metrics[2]
        height_ratio = target_height / metrics[3]
        scale = max(0.86, min(1.14, (width_ratio + height_ratio * 2.0) / 3.0))
        if abs(scale - 1.0) < 0.015:
            matched.append(frame)
            continue
        resized = frame.resize(
            (max(1, round(CELL_WIDTH * scale)), max(1, round(CELL_HEIGHT * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
        offset = (round(metrics[0] * (1.0 - scale)), round(metrics[1] * (1.0 - scale)))
        canvas.alpha_composite(resized, offset)
        matched.append(canvas)
    return matched


def normalize(
    frames: list[Image.Image],
    target: tuple[float, float] | None = None,
) -> tuple[list[Image.Image], tuple[float, float], list[tuple[int, int]]]:
    anchors = [character_anchor(frame) for frame in frames]
    valid = [anchor for anchor in anchors if anchor is not None]
    if not valid:
        raise RuntimeError("No Phoebe character landmark found in atlas")
    if target is None:
        target = (median([anchor[0] for anchor in valid]), median([anchor[1] for anchor in valid]))
    raw_offsets: list[tuple[int, int] | None] = [
        None
        if anchor is None
        else (
            max(-80, min(80, round(target[0] - anchor[0]))),
            max(-80, min(80, round(target[1] - anchor[1]))),
        )
        for anchor in anchors
    ]
    offsets = fill_missing_offsets(raw_offsets)
    safe_offsets: list[tuple[int, int]] = []
    margin = 3
    for frame, (offset_x, offset_y) in zip(frames, offsets):
        bounds = frame.getchannel("A").getbbox()
        if bounds is not None:
            left, top, right, bottom = bounds
            offset_x = max(margin - left, min(offset_x, CELL_WIDTH - margin - right))
            offset_y = max(margin - top, min(offset_y, CELL_HEIGHT - margin - bottom))
        safe_offsets.append((offset_x, offset_y))
    offsets = safe_offsets
    return [translate(frame, offset) for frame, offset in zip(frames, offsets)], target, offsets


def pack(frames: list[Image.Image], columns: int) -> Image.Image:
    rows = (len(frames) + columns - 1) // columns
    atlas = Image.new("RGBA", (columns * CELL_WIDTH, rows * CELL_HEIGHT), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        atlas.alpha_composite(frame, ((index % columns) * CELL_WIDTH, (index // columns) * CELL_HEIGHT))
    return atlas


def opacity_midpoints(frames: list[Image.Image]) -> list[Image.Image]:
    """Use a clean dissolve midpoint for effects that already share a pivot."""
    transparent = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    return [
        Image.blend(frame, frames[index + 1] if index + 1 < len(frames) else transparent, 0.5)
        for index, frame in enumerate(frames)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--anchored-dir", type=Path, required=True)
    parser.add_argument("--inbetween-dir", type=Path)
    parser.add_argument("--thirty-dir", type=Path)
    args = parser.parse_args()

    args.anchored_dir.mkdir(parents=True, exist_ok=True)
    if args.thirty_dir:
        args.thirty_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {}
    for source_path in sorted(args.source_dir.glob("*.png")):
        source_frames = split_atlas(source_path)
        anchored, target, offsets = normalize(source_frames)
        pack(anchored, SOURCE_COLUMNS).save(args.anchored_dir / source_path.name)
        entry: dict[str, object] = {
            "target_anchor": [target[0], target[1]],
            "source_offsets": offsets,
        }

        if args.inbetween_dir and args.thirty_dir:
            candidate = args.inbetween_dir / f"{source_path.stem}-inbetweens.png"
            if candidate.exists():
                if source_path.name in BLEND_ONLY_SHEETS:
                    normalized_inbetweens = opacity_midpoints(anchored)
                    inbetween_offsets = [(0, 0)] * SOURCE_FRAME_COUNT
                    entry["inbetween_mode"] = "opacity-blend"
                else:
                    inbetween_frames = split_atlas(candidate)
                    inbetween_frames = match_character_scale(inbetween_frames, source_frames)
                    normalized_inbetweens, _, inbetween_offsets = normalize(inbetween_frames, target)
                    entry["inbetween_mode"] = "drawn"
                interleaved: list[Image.Image] = []
                for source_frame, inbetween_frame in zip(anchored, normalized_inbetweens):
                    interleaved.extend((source_frame, inbetween_frame))
                pack(interleaved, 10).save(args.thirty_dir / source_path.name)
                entry["inbetween_offsets"] = inbetween_offsets
                entry["frame_count"] = 30
        report[source_path.name] = entry

    (args.anchored_dir / "anchor-offsets.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
