"""Build production-ready randomized Phoebe animation atlases."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from normalize_sprite_anchors import normalize, pack, split_atlas


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v2"
GENERATED_DIR = PROJECT_ROOT / "assets" / "phoebe" / "generated_variants_v3"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "phoebe" / "baked_animation_v3"

CORE_SHEETS = ("entry-run", "run-to-pickup", "eat-bite", "stand-to-run")
GROUNDED_SHEETS = (
    "entry-sleepy",
    "exit-belly-fade",
    "exit-burp-teleport",
    "exit-overfull",
)
FREE_MOTION_SHEETS = ("entry-peek", "entry-skyfall", "exit-roll")


def alpha_edge_pixels(frame) -> int:
    alpha = frame.getchannel("A")
    edges = (
        alpha.crop((0, 0, alpha.width, 1)),
        alpha.crop((0, alpha.height - 1, alpha.width, alpha.height)),
        alpha.crop((0, 0, 1, alpha.height)),
        alpha.crop((alpha.width - 1, 0, alpha.width, alpha.height)),
    )
    return sum(value > 8 for edge in edges for value in edge.getdata())


def reordered(frames, order: tuple[int, ...]):
    return [frames[index].copy() for index in order]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in CORE_SHEETS:
        shutil.copy2(CORE_DIR / f"{name}.png", OUTPUT_DIR / f"{name}.png")

    reference = split_atlas(CORE_DIR / "stand-to-run.png")
    _, target_anchor, _ = normalize(reference)
    report: dict[str, object] = {}

    for name in GROUNDED_SHEETS + FREE_MOTION_SHEETS:
        frames = split_atlas(GENERATED_DIR / f"{name}.png")
        offsets: list[tuple[int, int]] = [(0, 0)] * len(frames)
        if name in GROUNDED_SHEETS:
            frames, _, offsets = normalize(frames, target_anchor)
        if name == "exit-burp-teleport":
            # The generated last cell returned to a neutral pose after vanishing.
            # Keep the empty teleport ring instead so the disappearance is final.
            frames = reordered(frames, tuple(range(14)) + (13,))
            offsets = [offsets[index] for index in tuple(range(14)) + (13,)]
        output = OUTPUT_DIR / f"{name}.png"
        pack(frames, 5).save(output, optimize=True)
        report[name] = {
            "source": str(GENERATED_DIR / f"{name}.png"),
            "target_anchor": list(target_anchor),
            "offsets": offsets,
            "edge_frames": [index for index, frame in enumerate(frames) if alpha_edge_pixels(frame)],
        }

    eat_frames = split_atlas(CORE_DIR / "eat-bite.png")
    stand_frames = split_atlas(CORE_DIR / "stand-to-run.png")
    pack([stand_frames[0].copy() for _ in range(15)], 5).save(
        OUTPUT_DIR / "neutral-hold.png", optimize=True
    )
    happy_order = (10, 11, 12, 13, 13, 12, 11, 10, 11, 12, 13, 14, 14, 14, 14)
    pack(reordered(eat_frames, happy_order), 5).save(
        OUTPUT_DIR / "satisfaction-happy.png", optimize=True
    )

    big_bite_order = (0, 1, 2, 3, 4, 5, 6, 7, 5, 6, 7, 8, 9, 10, 14)
    pack(reordered(eat_frames, big_bite_order), 5).save(
        OUTPUT_DIR / "eat-big-file.png", optimize=True
    )

    report["satisfaction-happy"] = {"source": "eat-bite", "order": happy_order}
    report["eat-big-file"] = {"source": "eat-bite", "order": big_bite_order}
    report["neutral-hold"] = {"source": "stand-to-run", "order": [0] * 15}
    (OUTPUT_DIR / "variant-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(CORE_SHEETS) + len(report) - 2 + 2} production atlases to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
