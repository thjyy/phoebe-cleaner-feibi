"""Build V6 with dedicated front/side Easter-egg animation atlases."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from normalize_sprite_anchors import normalize, pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V5_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v5"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_easter_eggs_v6"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v6"

EASTER_EGG_SHEETS = (
    "front-empty-folder",
    "front-multi-cookie",
    "front-large-power-bite",
    "front-repeat-annoyed",
    "side-empty-folder",
    "side-multi-cookie",
    "side-large-power-bite",
    "side-repeat-annoyed",
)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in V5_DIR.glob("*.png"):
        shutil.copy2(source, OUTPUT_DIR / source.name)

    report: dict[str, object] = {}
    for name in EASTER_EGG_SHEETS:
        source = GENERATED_DIR / f"{name}.png"
        frames = split_atlas(source)
        anchored, target, offsets = normalize(frames)
        destination = OUTPUT_DIR / f"{name}.png"
        pack(anchored, 5).save(destination, optimize=True)
        report[name] = {
            "source": str(source),
            "frames": 15,
            "target_anchor": [target[0], target[1]],
            "offsets": offsets,
        }

    (OUTPUT_DIR / "easter-eggs-v6-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote V6 Easter-egg atlases to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
