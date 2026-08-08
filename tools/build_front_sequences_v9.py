"""Build three independent 87-frame, front-facing Phoebe V9 stories."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_full_sequence_v8 import (
    RUNTIME_COLUMNS,
    TARGET_FRAME_COUNT,
    add_midpoints,
    median_metrics,
    pack,
    split_generated,
    split_runtime,
    transform_clip,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "assets" / "phoebe" / "generated_front_full_sequences_v9"
REFERENCE_DIR = ROOT / "assets" / "phoebe" / "baked_animation_v6"
OUTPUT_DIR = ROOT / "assets" / "phoebe" / "baked_front_sequences_v9"
PREVIEW_DIR = ROOT / "docs" / "previews"

SEQUENCES = (
    ("sleepy-cloud", "睡云召唤", 1650, 1900, 1600),
    ("portal-peek", "传送门探头", 1600, 1850, 1550),
    ("star-drop", "星光降落", 1550, 1850, 1450),
)

STABLE_INDICES = {
    "entry": (5, 6, 7, 12, 13, 14),
    "eat": tuple(range(15)),
    "exit": (0, 1, 2, 3, 4),
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
        PREVIEW_DIR / f"front-v9-{slug}-full-flow.gif",
        save_all=True,
        append_images=paletted[1:],
        duration=55,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reference = split_runtime(REFERENCE_DIR / "front-eat.png")
    target = median_metrics(reference, tuple(range(15)))
    report: dict[str, object] = {
        "frame_count_per_stage": TARGET_FRAME_COUNT,
        "stages_per_sequence": 3,
        "atlas_columns": RUNTIME_COLUMNS,
        "sequences": {},
    }

    for slug, label, entry_ms, eat_ms, exit_ms in SEQUENCES:
        details: dict[str, object] = {
            "label": label,
            "durations_ms": [entry_ms, eat_ms, exit_ms],
            "clips": {},
        }
        base_clips: list[list[Image.Image]] = []
        for stage in ("entry", "eat", "exit"):
            name = f"front-{slug}-{stage}"
            frames = split_generated(SOURCE_DIR / f"{name}.png")
            transformed, transform = transform_clip(
                frames, STABLE_INDICES[stage], target
            )
            base_clips.append(transformed)
            details["clips"][stage] = transform  # type: ignore[index]

        # Each story owns its boundaries: no random pose or foreign sheet is
        # inserted between these exact images.
        base_clips[1][0] = base_clips[0][-1].copy()
        base_clips[2][0] = base_clips[1][-1].copy()
        runtime_clips = [add_midpoints(clip) for clip in base_clips]

        for stage, frames in zip(("entry", "eat", "exit"), runtime_clips):
            pack(frames, RUNTIME_COLUMNS).save(
                OUTPUT_DIR / f"front-{slug}-{stage}.png", optimize=True
            )
        save_preview(slug, label, runtime_clips)
        report["sequences"][slug] = details  # type: ignore[index]

    (OUTPUT_DIR / "front-sequences-v9-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote V9 runtime atlases to {OUTPUT_DIR}")
    print(f"Wrote V9 previews to {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
