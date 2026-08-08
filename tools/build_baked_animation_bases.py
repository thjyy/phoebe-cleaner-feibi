"""Build stable single-source key atlases for the production animation flow."""

from __future__ import annotations

import json
from pathlib import Path

from normalize_sprite_anchors import (
    SOURCE_COLUMNS,
    match_character_scale,
    normalize,
    pack,
    split_atlas,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = PROJECT_ROOT / "assets" / "phoebe" / "spritesheets_v2"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_inbetweens_v1"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v1_base"

PRODUCTION_CLIPS = (
    "entry-run",
    "eat-bite",
    "satisfied-bellypat",
    "exit-run",
)


def edge_pixel_count(frame) -> int:
    alpha = frame.getchannel("A")
    edges = (
        alpha.crop((0, 0, alpha.width, 1)),
        alpha.crop((0, alpha.height - 1, alpha.width, alpha.height)),
        alpha.crop((0, 0, 1, alpha.height)),
        alpha.crop((alpha.width - 1, 0, alpha.width, alpha.height)),
    )
    return sum(1 for edge in edges for value in edge.getdata() if value > 8)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    for clip in PRODUCTION_CLIPS:
        reference_frames = split_atlas(REFERENCE_DIR / f"{clip}.png")
        _, target_anchor, _ = normalize(reference_frames)
        generated_frames = split_atlas(GENERATED_DIR / f"{clip}-inbetweens.png")
        generated_frames = match_character_scale(generated_frames, reference_frames)
        normalized_frames, _, offsets = normalize(generated_frames, target_anchor)
        clipped = [index for index, frame in enumerate(normalized_frames) if edge_pixel_count(frame)]
        if clipped:
            raise RuntimeError(f"{clip}: visible pixels touch cell edge in frames {clipped}")
        output = OUTPUT_DIR / f"{clip}.png"
        pack(normalized_frames, SOURCE_COLUMNS).save(output, optimize=True)
        report[clip] = {
            "source": str(GENERATED_DIR / f"{clip}-inbetweens.png"),
            "reference": str(REFERENCE_DIR / f"{clip}.png"),
            "target_anchor": list(target_anchor),
            "offsets": offsets,
            "frames": len(normalized_frames),
        }
        print(f"Wrote {output}: {len(normalized_frames)} single-source keys")
    (OUTPUT_DIR / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
