"""Normalize the dedicated side-view handoff animations for production."""

from __future__ import annotations

import json
from pathlib import Path

from normalize_sprite_anchors import match_character_scale, normalize, pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v1_base"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_transitions_v2"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v2"
TRANSITIONS = ("run-to-pickup", "eat-to-run")


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
    reference_frames = split_atlas(REFERENCE_DIR / "entry-run.png")
    _, target_anchor, _ = normalize(reference_frames)
    report: dict[str, object] = {}
    for name in TRANSITIONS:
        frames = split_atlas(GENERATED_DIR / f"{name}.png")
        frames = match_character_scale(frames, reference_frames)
        frames, _, offsets = normalize(frames, target_anchor)
        clipped = [index for index, frame in enumerate(frames) if edge_pixel_count(frame)]
        if clipped:
            raise RuntimeError(f"{name}: pixels touch frame edge in {clipped}")
        output = OUTPUT_DIR / f"{name}.png"
        pack(frames, 5).save(output, optimize=True)
        report[name] = {
            "source": str(GENERATED_DIR / f"{name}.png"),
            "target_anchor": list(target_anchor),
            "offsets": offsets,
            "frames": len(frames),
        }
        print(f"Wrote {output}: {len(frames)} normalized transition frames")
    (OUTPUT_DIR / "transition-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
