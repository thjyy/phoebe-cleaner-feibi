"""Bake clean squash-turn transitions without cross-fading two drawings."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from normalize_sprite_anchors import CELL_HEIGHT, CELL_WIDTH, pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v1_base"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v1_base"
FRAME_COUNT = 15


def squash(frame: Image.Image, amount: float) -> Image.Image:
    bounds = frame.getchannel("A").getbbox()
    if bounds is None:
        return Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    left, top, right, bottom = bounds
    content = frame.crop(bounds)
    width = max(3, round(content.width * amount))
    compressed = content.resize((width, content.height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    target_x = round(CELL_WIDTH / 2 - width / 2)
    target_y = round(CELL_HEIGHT * 0.86 - content.height)
    canvas.alpha_composite(compressed, (target_x, target_y))
    return canvas


def build(source: Image.Image, target: Image.Image) -> list[Image.Image]:
    frames: list[Image.Image] = []
    half = FRAME_COUNT // 2
    for index in range(FRAME_COUNT):
        if index <= half:
            progress = index / half
            amount = 1.0 - 0.92 * (progress * progress * (3.0 - 2.0 * progress))
            frames.append(squash(source, amount))
        else:
            progress = (index - half) / (FRAME_COUNT - 1 - half)
            amount = 0.08 + 0.92 * (progress * progress * (3.0 - 2.0 * progress))
            frames.append(squash(target, amount))
    return frames


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    eat = split_atlas(BASE_DIR / "eat-bite.png")
    satisfied = split_atlas(BASE_DIR / "satisfied-bellypat.png")
    exit_run = split_atlas(BASE_DIR / "exit-run.png")
    transitions = {
        "turn-to-front.png": build(eat[-1], satisfied[0]),
        "turn-to-exit.png": build(satisfied[-1], exit_run[0]),
    }
    for name, frames in transitions.items():
        output = OUTPUT_DIR / name
        pack(frames, 5).save(output, optimize=True)
        print(f"Wrote {output}: {len(frames)} squash-turn frames")


if __name__ == "__main__":
    main()
