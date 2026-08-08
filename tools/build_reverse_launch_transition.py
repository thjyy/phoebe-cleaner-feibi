"""Derive a clean stand-to-run launch from the approved run-to-pickup clip."""

from __future__ import annotations

from pathlib import Path

from normalize_sprite_anchors import pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v2"

# The approved clip reaches a neutral side stance around key 10.  Reversing
# only that neutral-to-run section avoids replaying the final receiving pose.
FRAME_ORDER = (10, 10, 9, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 0, 0)


def main() -> None:
    source = split_atlas(ASSET_DIR / "run-to-pickup.png")
    frames = [source[index] for index in FRAME_ORDER]
    output = ASSET_DIR / "stand-to-run.png"
    pack(frames, 5).save(output, optimize=True)
    print(f"Wrote {output}: {len(frames)} same-source launch frames")


if __name__ == "__main__":
    main()
