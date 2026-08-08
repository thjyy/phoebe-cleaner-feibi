"""Build the front-facing branch and stationary pickup transition."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from normalize_sprite_anchors import normalize, pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v3"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_front_v4"
LEGACY_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v1_base"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v4"

STAND_TO_PICKUP_ORDER = (10, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 14, 14, 14, 14)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in V3_DIR.glob("*.png"):
        shutil.copy2(source, OUTPUT_DIR / source.name)

    report: dict[str, object] = {}
    side_to_front = split_atlas(GENERATED_DIR / "side-to-front.png")
    side_to_front, transition_anchor, transition_offsets = normalize(side_to_front)
    pack(side_to_front, 5).save(OUTPUT_DIR / "side-to-front.png", optimize=True)
    pack(list(reversed(side_to_front)), 5).save(OUTPUT_DIR / "front-to-side.png", optimize=True)
    report["side-to-front"] = {
        "source": str(GENERATED_DIR / "side-to-front.png"),
        "anchor": list(transition_anchor),
        "offsets": transition_offsets,
    }
    report["front-to-side"] = {"source": "side-to-front reversed"}

    for name, source in (
        ("front-wave", GENERATED_DIR / "front-wave.png"),
        ("front-bellypat", LEGACY_DIR / "satisfied-bellypat.png"),
    ):
        frames = split_atlas(source)
        frames, anchor, offsets = normalize(frames)
        pack(frames, 5).save(OUTPUT_DIR / f"{name}.png", optimize=True)
        report[name] = {"source": str(source), "anchor": list(anchor), "offsets": offsets}

    pickup_source = split_atlas(V3_DIR / "run-to-pickup.png")
    stand_to_pickup = [pickup_source[index].copy() for index in STAND_TO_PICKUP_ORDER]
    pack(stand_to_pickup, 5).save(OUTPUT_DIR / "stand-to-pickup.png", optimize=True)
    report["stand-to-pickup"] = {
        "source": "run-to-pickup",
        "order": list(STAND_TO_PICKUP_ORDER),
    }

    (OUTPUT_DIR / "front-branch-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote front-facing production branch to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
