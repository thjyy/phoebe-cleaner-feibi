"""Build a front-facing pipeline that never swaps to the side model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from normalize_sprite_anchors import pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V4_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v4"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_front_pipeline_v5"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v5"

EXCLUDED_V4 = {"side-to-front.png", "front-to-side.png"}
FRONT_GENERATED = (
    "front-skyfall",
    "front-pickup",
    "front-eat",
    "front-burp-teleport",
    "front-failure",
)
FRONT_BIG_EAT_ORDER = (0, 1, 2, 3, 4, 5, 3, 4, 5, 6, 7, 8, 9, 10, 14)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in V4_DIR.glob("*.png"):
        if source.name not in EXCLUDED_V4:
            shutil.copy2(source, OUTPUT_DIR / source.name)

    report: dict[str, object] = {}
    for name in FRONT_GENERATED:
        frames = split_atlas(GENERATED_DIR / f"{name}.png")
        pack(frames, 5).save(OUTPUT_DIR / f"{name}.png", optimize=True)
        report[name] = {"source": str(GENERATED_DIR / f"{name}.png"), "frames": 15}

    front_wave = split_atlas(V4_DIR / "front-wave.png")
    pack([front_wave[0].copy() for _ in range(15)], 5).save(
        OUTPUT_DIR / "front-neutral-hold.png", optimize=True
    )
    report["front-neutral-hold"] = {"source": "front-wave frame 0", "frames": 15}

    front_eat = split_atlas(GENERATED_DIR / "front-eat.png")
    front_big_eat = [front_eat[index].copy() for index in FRONT_BIG_EAT_ORDER]
    pack(front_big_eat, 5).save(OUTPUT_DIR / "front-eat-big.png", optimize=True)
    report["front-eat-big"] = {
        "source": "front-eat",
        "order": list(FRONT_BIG_EAT_ORDER),
    }

    (OUTPUT_DIR / "front-pipeline-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote distortion-free front pipeline to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
