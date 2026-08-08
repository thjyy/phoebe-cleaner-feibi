"""Build compact animated GIF previews for the GitHub README."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "phoebe" / "baked_animation_v6"
OUTPUT_DIR = ROOT / "docs" / "screenshots"
CELL_SIZE = (256, 384)
ATLAS_COLUMNS = 5
FRAME_COUNT = 15
BACKGROUND = (22, 24, 29)
PANEL = (31, 35, 43)
ACCENT = (91, 188, 241)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def atlas_frames(name: str) -> list[Image.Image]:
    atlas = Image.open(ASSET_DIR / f"{name}.png").convert("RGBA")
    return [
        atlas.crop(
            (
                (index % ATLAS_COLUMNS) * CELL_SIZE[0],
                (index // ATLAS_COLUMNS) * CELL_SIZE[1],
                (index % ATLAS_COLUMNS + 1) * CELL_SIZE[0],
                (index // ATLAS_COLUMNS + 1) * CELL_SIZE[1],
            )
        )
        for index in range(FRAME_COUNT)
    ]


def background(size: tuple[int, int], title: str = "") -> Image.Image:
    canvas = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        color = tuple(
            round(BACKGROUND[index] + ratio * (PANEL[index] - BACKGROUND[index]))
            for index in range(3)
        )
        draw.line((0, y, size[0], y), fill=color)
    draw.rounded_rectangle(
        (14, 14, size[0] - 15, size[1] - 15),
        radius=20,
        outline=(56, 64, 76),
        width=2,
    )
    if title:
        title_font = font(22)
        box = draw.textbbox((0, 0), title, font=title_font)
        draw.text(
            ((size[0] - (box[2] - box[0])) / 2, 22),
            title,
            font=title_font,
            fill=(235, 240, 248),
        )
        draw.rounded_rectangle(
            (size[0] / 2 - 38, 57, size[0] / 2 + 38, 60),
            radius=2,
            fill=ACCENT,
        )
    return canvas


def composite_sprite(
    canvas: Image.Image,
    sprite: Image.Image,
    center: tuple[int, int],
    scale: float,
    opacity: float = 1.0,
) -> Image.Image:
    layer = canvas.convert("RGBA")
    size = (round(sprite.width * scale), round(sprite.height * scale))
    resized = sprite.resize(size, Image.Resampling.LANCZOS)
    if opacity < 1.0:
        alpha = resized.getchannel("A").point(lambda value: round(value * opacity))
        resized.putalpha(alpha)
    position = (
        round(center[0] - size[0] / 2),
        round(center[1] - size[1] / 2),
    )
    layer.alpha_composite(resized, position)
    return layer.convert("RGB")


def smooth(sequence: list[Image.Image], between: int = 1) -> list[Image.Image]:
    result: list[Image.Image] = []
    for index, current in enumerate(sequence):
        result.append(current)
        if index + 1 >= len(sequence):
            continue
        following = sequence[index + 1]
        for step in range(1, between + 1):
            result.append(Image.blend(current, following, step / (between + 1)))
    return result


def save_gif(
    frames: list[Image.Image], path: Path, duration_ms: int = 50
) -> None:
    palette_frames = [
        frame.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
        for frame in frames
    ]
    palette_frames[0].save(
        path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )


def build_front_flow() -> None:
    stage_names = (
        "front-skyfall",
        "front-pickup",
        "front-eat",
        "front-wave",
        "front-burp-teleport",
    )
    canvas_size = (520, 430)
    raw: list[Image.Image] = []
    for stage_index, name in enumerate(stage_names):
        for frame_index, sprite in enumerate(atlas_frames(name)):
            base = background(canvas_size, "完整正面流程 · V6")
            opacity = 1.0
            if stage_index == 0:
                opacity = min(1.0, 0.25 + frame_index / 7)
            elif stage_index == len(stage_names) - 1 and frame_index >= 10:
                opacity = max(0.0, (14 - frame_index) / 4)
            raw.append(
                composite_sprite(base, sprite, (260, 245), 0.82, opacity)
            )
    save_gif(
        smooth(raw, between=1), OUTPUT_DIR / "phoebe-front-flow.gif"
    )


def build_easter_eggs() -> None:
    actions = (
        ("front-empty-folder", "空文件夹"),
        ("front-multi-cookie", "多文件饼干"),
        ("front-large-power-bite", "大文件蓄力"),
        ("front-repeat-annoyed", "怎么又是我"),
    )
    sources = [(atlas_frames(name), label) for name, label in actions]
    canvas_size = (640, 620)
    centers = ((165, 190), (475, 190), (165, 465), (475, 465))
    label_font = font(20)
    raw: list[Image.Image] = []
    for frame_index in range(FRAME_COUNT):
        base = background(canvas_size, "V6 彩蛋动作")
        draw = ImageDraw.Draw(base)
        draw.line((320, 78, 320, 598), fill=(55, 62, 74), width=2)
        draw.line((24, 320, 616, 320), fill=(55, 62, 74), width=2)
        for (frames, label), center in zip(sources, centers):
            base = composite_sprite(base, frames[frame_index], center, 0.58)
            draw = ImageDraw.Draw(base)
            box = draw.textbbox((0, 0), label, font=label_font)
            draw.text(
                (
                    center[0] - (box[2] - box[0]) / 2,
                    center[1] + 111,
                ),
                label,
                font=label_font,
                fill=(224, 230, 240),
            )
        raw.append(base)
    save_gif(
        smooth(raw, between=2),
        OUTPUT_DIR / "phoebe-easter-eggs.gif",
        duration_ms=55,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    build_front_flow()
    build_easter_eggs()
    print(f"Wrote README previews to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
