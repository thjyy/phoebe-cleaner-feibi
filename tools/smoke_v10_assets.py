"""Load every complete story offscreen without deleting the target file."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_app"))

import phoebe_cleaner.app as cleaner  # noqa: E402


def main() -> None:
    app = QApplication([])
    target = ROOT / "README.md"
    results: list[tuple[str, int, list[int], int]] = []
    with tempfile.TemporaryDirectory(prefix="phoebe-v10-smoke-") as temp:
        cleaner.APP_DATA_DIR = Path(temp)
        cleaner.SETTINGS_FILE = Path(temp) / "settings.json"
        cleaner.STATE_FILE = Path(temp) / "state.json"
        for name in cleaner.FULL_SEQUENCE_WEIGHTS:
            window = cleaner.PetWindow(
                target,
                QPoint(900, 500),
                forced_entry=name,
            )
            results.append(
                (
                    name,
                    len(window.stages),
                    [len(window.frames[stage.animation.name]) for stage in window.stages],
                    sum(stage.animation.duration_ms for stage in window.stages),
                )
            )
            window.executor.shutdown(wait=False, cancel_futures=True)
            window.close()
        large_target = Path(temp) / "large-file-smoke.bin"
        with large_target.open("wb") as handle:
            handle.seek(256 * 1024 * 1024 - 1)
            handle.write(b"\0")
        large_window = cleaner.PetWindow(large_target, QPoint(900, 500))
        assert large_window.full_sequence_name == "full-giant-file-boss"
        assert [
            len(large_window.frames[stage.animation.name])
            for stage in large_window.stages
        ] == [57, 57, 57]
        print(
            "large-file-auto: "
            f"story={large_window.full_sequence_name}, "
            f"duration={sum(stage.animation.duration_ms for stage in large_window.stages) / 1000:.2f}s"
        )
        large_window.executor.shutdown(wait=False, cancel_futures=True)
        large_window.close()
    app.quit()
    for name, stage_count, frame_counts, duration_ms in results:
        expected = 57 if name.startswith("full-") and name in {
            "full-greedy-hat",
            "full-file-juice",
            "full-runaway-chase",
            "full-afternoon-tea",
            "full-acrobat-toss",
            "full-giant-file-boss",
        } else 29
        assert frame_counts == [expected, expected, expected]
        print(
            f"{name}: stages={stage_count}, frames={frame_counts}, "
            f"duration={duration_ms / 1000:.2f}s"
        )


if __name__ == "__main__":
    main()
