"""Build the fixed front-facing V8 story and its animated review.

The ImageGen atlases are square-cell contact sheets.  Runtime atlases use a
256x384 cell, so this builder preserves the source aspect ratio, applies one
stable transform to each whole clip, and adds alpha-aware midpoint frames.
Applying one transform per clip keeps authored portal motion intact while
preventing per-frame anchor correction from turning crouches into jitter.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "assets" / "phoebe" / "generated_full_sequences_v8"
V6_DIR = ROOT / "assets" / "phoebe" / "baked_animation_v6"
OUTPUT_DIR = ROOT / "assets" / "phoebe" / "baked_full_sequence_v8"
PREVIEW_PATH = ROOT / "docs" / "previews" / "front-v8-magic-snack-full-flow.gif"

CELL_SIZE = (256, 384)
SOURCE_COLUMNS = 5
SOURCE_ROWS = 3
SOURCE_FRAME_COUNT = 15
RUNTIME_COLUMNS = 10
TARGET_FRAME_COUNT = 29

SHEETS = (
    ("front-magic-snack-entry-pickup", (5, 6, 7, 12, 13, 14)),
    ("front-magic-snack-eat-satisfy", tuple(range(15))),
    ("front-magic-snack-exit", (0, 1, 2, 3, 4)),
)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def split_generated(path: Path) -> list[Image.Image]:
    atlas = Image.open(path).convert("RGBA")
    width, height = atlas.size
    frames: list[Image.Image] = []
    for index in range(SOURCE_FRAME_COUNT):
        column = index % SOURCE_COLUMNS
        row = index // SOURCE_COLUMNS
        left = round(column * width / SOURCE_COLUMNS)
        top = round(row * height / SOURCE_ROWS)
        right = round((column + 1) * width / SOURCE_COLUMNS)
        bottom = round((row + 1) * height / SOURCE_ROWS)

        # ImageGen draws thin white contact-sheet rules.  Remove them before
        # scaling; otherwise they become visible seams in the transparent pet.
        inset = 3
        cell = atlas.crop((left + inset, top + inset, right - inset, bottom - inset))
        frames.append(cell.resize((320, 320), Image.Resampling.LANCZOS))
    return frames


def split_runtime(path: Path, columns: int = 5, count: int = 15) -> list[Image.Image]:
    atlas = Image.open(path).convert("RGBA")
    return [
        atlas.crop(
            (
                (index % columns) * CELL_SIZE[0],
                (index // columns) * CELL_SIZE[1],
                (index % columns + 1) * CELL_SIZE[0],
                (index // columns + 1) * CELL_SIZE[1],
            )
        )
        for index in range(count)
    ]


def character_metrics(frame: Image.Image) -> tuple[float, float, float, float] | None:
    pixels = frame.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(frame.height):
        for x in range(frame.width):
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
    low = round(len(xs) * 0.05)
    high = min(len(xs) - 1, round(len(xs) * 0.95))
    return (
        float(xs[len(xs) // 2]),
        float(ys[len(ys) // 2]),
        float(max(1, xs[high] - xs[low])),
        float(max(1, ys[high] - ys[low])),
    )


def median_metrics(
    frames: list[Image.Image], indices: tuple[int, ...]
) -> tuple[float, float, float, float]:
    metrics = [character_metrics(frames[index]) for index in indices]
    valid = [value for value in metrics if value is not None]
    if not valid:
        raise RuntimeError("No Phoebe landmark found in stable frames")
    return tuple(median([value[position] for value in valid]) for position in range(4))  # type: ignore[return-value]


def transform_clip(
    frames: list[Image.Image],
    stable_indices: tuple[int, ...],
    target: tuple[float, float, float, float],
) -> tuple[list[Image.Image], dict[str, object]]:
    source = median_metrics(frames, stable_indices)
    width_ratio = target[2] / source[2]
    height_ratio = target[3] / source[3]
    scale = (width_ratio + height_ratio * 2.0) / 3.0
    scale = max(0.72, min(1.35, scale))
    offset = (
        round(target[0] - source[0] * scale),
        round(target[1] - source[1] * scale),
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
        "scale": round(scale, 5),
        "offset": list(offset),
    }


def alpha_midpoint(left: Image.Image, right: Image.Image) -> Image.Image:
    """Move both key poses toward their optical midpoint before blending."""
    left_rgba = np.asarray(left, dtype=np.uint8)
    right_rgba = np.asarray(right, dtype=np.uint8)

    def motion_gray(rgba: np.ndarray) -> np.ndarray:
        alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
        # A mid-gray matte gives transparent regions a stable value while the
        # black outline and bright costume still provide strong flow features.
        rgb = rgba[:, :, :3].astype(np.float32) * alpha + 96.0 * (1.0 - alpha)
        return cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)

    left_gray = motion_gray(left_rgba)
    right_gray = motion_gray(right_rgba)
    flow_left = cv2.calcOpticalFlowFarneback(
        left_gray, right_gray, None, 0.5, 4, 21, 4, 7, 1.5, 0
    )
    flow_right = cv2.calcOpticalFlowFarneback(
        right_gray, left_gray, None, 0.5, 4, 21, 4, 7, 1.5, 0
    )
    grid_x, grid_y = np.meshgrid(
        np.arange(CELL_SIZE[0], dtype=np.float32),
        np.arange(CELL_SIZE[1], dtype=np.float32),
    )

    def halfway(rgba: np.ndarray, flow: np.ndarray) -> np.ndarray:
        return cv2.remap(
            rgba,
            grid_x - flow[:, :, 0] * 0.5,
            grid_y - flow[:, :, 1] * 0.5,
            interpolation=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )

    warped_left = halfway(left_rgba, flow_left).astype(np.float32)
    warped_right = halfway(right_rgba, flow_right).astype(np.float32)
    alpha_left = warped_left[:, :, 3:4] / 255.0
    alpha_right = warped_right[:, :, 3:4] / 255.0
    alpha = (alpha_left + alpha_right) * 0.5
    premultiplied = (
        warped_left[:, :, :3] * alpha_left + warped_right[:, :, :3] * alpha_right
    ) * 0.5
    rgb = np.divide(
        premultiplied,
        np.maximum(alpha, 1.0 / 255.0),
        out=np.zeros_like(premultiplied),
        where=alpha > 0,
    )
    result = np.concatenate((rgb, alpha * 255.0), axis=2)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGBA")


def add_midpoints(frames: list[Image.Image]) -> list[Image.Image]:
    result: list[Image.Image] = []
    for index, frame in enumerate(frames[:-1]):
        result.extend((frame, alpha_midpoint(frame, frames[index + 1])))
    result.append(frames[-1])
    assert len(result) == TARGET_FRAME_COUNT
    return result


def pack(frames: list[Image.Image], columns: int) -> Image.Image:
    rows = (len(frames) + columns - 1) // columns
    atlas = Image.new(
        "RGBA", (columns * CELL_SIZE[0], rows * CELL_SIZE[1]), (0, 0, 0, 0)
    )
    for index, frame in enumerate(frames):
        atlas.alpha_composite(
            frame, ((index % columns) * CELL_SIZE[0], (index // columns) * CELL_SIZE[1])
        )
    return atlas


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/segoeui.ttf")):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def preview_frame(sprite: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (520, 430), (22, 24, 29))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((14, 14, 505, 415), radius=20, outline=(56, 64, 76), width=2)
    title = "正面完整流程 · 法阵点心"
    title_font = font(22)
    box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((520 - (box[2] - box[0])) / 2, 22), title, font=title_font, fill=(235, 240, 248))
    draw.rounded_rectangle((222, 57, 298, 60), radius=2, fill=(91, 188, 241))
    scaled = sprite.resize((215, 323), Image.Resampling.LANCZOS)
    layer = canvas.convert("RGBA")
    layer.alpha_composite(scaled, (153, 80))
    return layer.convert("RGB")


def save_preview(clips: list[list[Image.Image]]) -> None:
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames = [preview_frame(sprite) for clip in clips for sprite in clip]
    paletted = [frame.quantize(colors=192, method=Image.Quantize.MEDIANCUT) for frame in frames]
    paletted[0].save(
        PREVIEW_PATH,
        save_all=True,
        append_images=paletted[1:],
        duration=55,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    reference = split_runtime(V6_DIR / "front-eat.png")
    target = median_metrics(reference, tuple(range(15)))
    report: dict[str, object] = {
        "frame_count": TARGET_FRAME_COUNT,
        "atlas_columns": RUNTIME_COLUMNS,
        "preview_frame_ms": 55,
        "clips": {},
    }
    base_clips: list[list[Image.Image]] = []
    for name, stable_indices in SHEETS:
        source = split_generated(SOURCE_DIR / f"{name}.png")
        transformed, details = transform_clip(source, stable_indices, target)
        base_clips.append(transformed)
        report["clips"][name] = details  # type: ignore[index]

    # Reuse the exact boundary image at each cut.  The following generated
    # frame already advances the gesture, so no visible reset is introduced.
    base_clips[1][0] = base_clips[0][-1].copy()
    base_clips[2][0] = base_clips[1][-1].copy()

    runtime_clips = [add_midpoints(clip) for clip in base_clips]
    for (name, _), frames in zip(SHEETS, runtime_clips):
        pack(frames, RUNTIME_COLUMNS).save(OUTPUT_DIR / f"{name}.png", optimize=True)

    save_preview(runtime_clips)
    (OUTPUT_DIR / "full-sequence-v8-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote V8 runtime atlases to {OUTPUT_DIR}")
    print(f"Wrote {len(runtime_clips) * TARGET_FRAME_COUNT}-frame preview to {PREVIEW_PATH}")


if __name__ == "__main__":
    main()
