"""Build six mechanically distinct, front-facing Phoebe V10 stories.

Each story owns its entry, deletion and exit artwork.  The generated 15-pose
atlases are normalized once per clip, boundary poses are reused verbatim, and
optical-flow midpoint frames turn every stage into a 29-frame runtime atlas.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_full_sequence_v8 import (
    CELL_SIZE,
    RUNTIME_COLUMNS,
    alpha_midpoint,
    median_metrics,
    pack,
    split_generated,
    split_runtime,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "assets" / "phoebe" / "generated_motion_families_v10"
REFERENCE_DIR = ROOT / "assets" / "phoebe" / "baked_animation_v6"
OUTPUT_DIR = ROOT / "assets" / "phoebe" / "baked_motion_families_v10"
PREVIEW_DIR = ROOT / "docs" / "previews"
V10_FRAME_COUNT = 57

# The final number is a per-story fit factor.  Stories with a cart, giant cup
# or oversized file need more transparent margin than character-only clips.
SEQUENCES = (
    ("greedy-hat", "贪吃帽子", 1750, 2100, 1650, 0.88),
    ("file-juice", "文件果汁车", 1650, 2200, 1700, 0.75),
    ("runaway-chase", "逃跑文件追逐", 1800, 2300, 1700, 0.80),
    ("afternoon-tea", "魔法下午茶", 1700, 2200, 1800, 0.72),
    ("acrobat-toss", "空中特技投食", 1650, 2200, 1600, 0.88),
    ("giant-file", "大文件 Boss", 1800, 2500, 2000, 0.68),
)

STABLE_INDICES = {
    "entry": (11, 12, 13, 14),
    "core": (0, 1, 2),
    "exit": (0, 1),
}


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def preview_frame(sprite: Image.Image, title: str) -> Image.Image:
    canvas = Image.new("RGB", (520, 430), (22, 24, 29))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (14, 14, 505, 415), radius=20, outline=(56, 64, 76), width=2
    )
    title_font = font(22)
    box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((520 - (box[2] - box[0])) / 2, 22),
        title,
        font=title_font,
        fill=(235, 240, 248),
    )
    draw.rounded_rectangle((222, 57, 298, 60), radius=2, fill=(91, 188, 241))
    scaled = sprite.resize((215, 323), Image.Resampling.LANCZOS)
    layer = canvas.convert("RGBA")
    layer.alpha_composite(scaled, (153, 80))
    return layer.convert("RGB")


def save_preview(slug: str, label: str, clips: list[list[Image.Image]]) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    frames = [
        preview_frame(sprite, f"正面完整流程 · {label}")
        for clip in clips
        for sprite in clip
    ]
    paletted = [
        frame.quantize(colors=192, method=Image.Quantize.MEDIANCUT) for frame in frames
    ]
    paletted[0].save(
        PREVIEW_DIR / f"front-v10-{slug}-full-flow.gif",
        save_all=True,
        append_images=paletted[1:],
        duration=42,
        loop=0,
        optimize=True,
        disposal=2,
    )


def add_v10_interframes(frames: list[Image.Image]) -> list[Image.Image]:
    """Add three motion-aware frames between every pair of authored poses."""

    result: list[Image.Image] = []
    for index, left in enumerate(frames[:-1]):
        right = frames[index + 1]
        middle = alpha_midpoint(left, right)
        quarter = alpha_midpoint(left, middle)
        three_quarters = alpha_midpoint(middle, right)
        result.extend((left, quarter, middle, three_quarters))
    result.append(frames[-1])
    assert len(result) == V10_FRAME_COUNT
    return result


def transform_clip_contained(
    frames: list[Image.Image],
    stable_indices: tuple[int, ...],
    target: tuple[float, float, float, float],
) -> tuple[list[Image.Image], dict[str, object]]:
    """Normalize Phoebe while keeping every authored prop inside the window."""

    source = median_metrics(frames, stable_indices)
    width_ratio = target[2] / source[2]
    height_ratio = target[3] / source[3]
    scale = max(0.45, min(1.35, (width_ratio + height_ratio * 2.0) / 3.0))

    boxes = [frame.getchannel("A").getbbox() for frame in frames]
    visible = [box for box in boxes if box is not None]
    if not visible:
        raise RuntimeError("Generated clip has no visible frames")
    union = (
        min(box[0] for box in visible),
        min(box[1] for box in visible),
        max(box[2] for box in visible),
        max(box[3] for box in visible),
    )
    margin = 7
    scale = min(
        scale,
        (CELL_SIZE[0] - margin * 2) / max(1, union[2] - union[0]),
        (CELL_SIZE[1] - margin * 2) / max(1, union[3] - union[1]),
    )
    scale = max(0.45, scale)

    desired_x = target[0] - source[0] * scale
    desired_y = target[1] - source[1] * scale
    min_x = margin - union[0] * scale
    max_x = CELL_SIZE[0] - margin - union[2] * scale
    min_y = margin - union[1] * scale
    max_y = CELL_SIZE[1] - margin - union[3] * scale
    offset = (
        round(min(max(desired_x, min_x), max_x)),
        round(min(max(desired_y, min_y), max_y)),
    )

    result: list[Image.Image] = []
    for frame in frames:
        resized = frame.resize(
            (round(frame.width * scale), round(frame.height * scale)),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
        canvas.alpha_composite(resized, offset)
        result.append(canvas)
    return result, {
        "source_anchor": [round(value, 3) for value in source],
        "target_anchor": [round(value, 3) for value in target],
        "source_union": list(union),
        "scale": round(scale, 5),
        "offset": list(offset),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reference = split_runtime(REFERENCE_DIR / "front-eat.png")
    base_target = median_metrics(reference, tuple(range(15)))
    report: dict[str, object] = {
        "frame_count_per_stage": V10_FRAME_COUNT,
        "stages_per_sequence": 3,
        "atlas_columns": RUNTIME_COLUMNS,
        "sequences": {},
    }

    for slug, label, entry_ms, core_ms, exit_ms, fit in SEQUENCES:
        target = (
            base_target[0],
            base_target[1],
            base_target[2] * fit,
            base_target[3] * fit,
        )
        details: dict[str, object] = {
            "label": label,
            "durations_ms": [entry_ms, core_ms, exit_ms],
            "fit_factor": fit,
            "clips": {},
        }
        base_clips: list[list[Image.Image]] = []
        stage_target = target
        for stage in ("entry", "core", "exit"):
            name = f"front-{slug}-{stage}"
            frames = split_generated(SOURCE_DIR / f"{name}.png")
            transformed, transform = transform_clip_contained(
                frames, STABLE_INDICES[stage], stage_target
            )
            base_clips.append(transformed)
            details["clips"][stage] = transform  # type: ignore[index]
            try:
                stage_target = median_metrics([transformed[-1]], (0,))
            except RuntimeError:
                # Some handoff poses are mostly a white prop or hat, leaving
                # too few warm-color landmarks for the character detector.
                stage_target = target

        # Exact pose reuse prevents a one-frame scale/anchor reset at stage cuts.
        base_clips[1][0] = base_clips[0][-1].copy()
        base_clips[2][0] = base_clips[1][-1].copy()
        runtime_clips = [add_v10_interframes(clip) for clip in base_clips]

        for stage, frames in zip(("entry", "core", "exit"), runtime_clips):
            pack(frames, RUNTIME_COLUMNS).save(
                OUTPUT_DIR / f"front-{slug}-{stage}.png", optimize=True
            )
        save_preview(slug, label, runtime_clips)
        report["sequences"][slug] = details  # type: ignore[index]

    (OUTPUT_DIR / "motion-families-v10-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote V10 runtime atlases to {OUTPUT_DIR}")
    print(f"Wrote six V10 animated previews to {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
