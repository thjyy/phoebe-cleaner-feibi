from __future__ import annotations

import concurrent.futures
import ctypes
from bisect import bisect_right
import json
import math
import os
import random
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import QElapsedTimer, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from pywinauto import Desktop
from send2trash import send2trash
from win32com.client import Dispatch


CELL_WIDTH = 256
CELL_HEIGHT = 384
ATLAS_COLUMNS = 5
DEFAULT_FRAME_COUNT = 15
DISPLAY_SCALE = 0.68
DISPLAY_WIDTH = round(CELL_WIDTH * DISPLAY_SCALE)
DISPLAY_HEIGHT = round(CELL_HEIGHT * DISPLAY_SCALE)
RENDER_INTERVAL_MS = 16
SERVER_NAME = "PhoebeCleanerFeibi"
SERVER_IDLE_TIMEOUT_MS = 10 * 60 * 1000
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PhoebeCleaner"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
STATE_FILE = APP_DATA_DIR / "animation-state.json"
SPEED_FACTORS = {"concise": 0.78, "standard": 1.0, "dramatic": 1.28}
SPEED_LABELS = {"concise": "简洁", "standard": "标准", "dramatic": "戏剧化"}
ENTRY_WEIGHTS = {
    "run": 35,
    "light": 22,
    "skyfall": 18,
    "sleepy": 12,
    "peek": 8,
    "teleport-miss": 5,
}
SATISFACTION_WEIGHTS = {
    "side-happy": 30,
    "side-belly": 20,
    "side-bounce": 10,
    "front-wave": 25,
    "front-belly": 15,
}
SIDE_SATISFACTION_WEIGHTS = {
    name: weight for name, weight in SATISFACTION_WEIGHTS.items() if name.startswith("side-")
}
FRONT_SATISFACTION_WEIGHTS = {
    name: weight for name, weight in SATISFACTION_WEIGHTS.items() if name.startswith("front-")
}
EXIT_WEIGHTS = {
    "belly-fade": 30,
    "bounce": 25,
    "light": 18,
    "burp-teleport": 12,
    "overfull": 10,
    "roll": 5,
}
FRONT_EXIT_WEIGHTS = {"belly-fade": 45, "light": 35, "burp-teleport": 20}
LARGE_FILE_BYTES = 256 * 1024 * 1024
FULL_SEQUENCE_NAME = "full-magic-snack"
FULL_SEQUENCE_CHANCE = 0.45
FULL_SEQUENCE_WEIGHTS = {
    "full-magic-snack": 35,
    "full-sleepy-cloud": 25,
    "full-portal-peek": 22,
    "full-star-drop": 18,
}
FULL_SEQUENCE_FRAME_COUNT = 29
FULL_SEQUENCE_COLUMNS = 10

LINEAR_FRAME_ONSETS = tuple(index / DEFAULT_FRAME_COUNT for index in range(DEFAULT_FRAME_COUNT))
EAT_FRAME_ONSETS = (
    0.00,
    0.05,
    0.10,
    0.16,
    0.22,
    0.29,
    0.37,
    0.45,
    0.53,
    0.61,
    0.68,
    0.74,
    0.81,
    0.89,
    0.96,
)
REACTION_FRAME_ONSETS = (
    0.00,
    0.06,
    0.12,
    0.18,
    0.25,
    0.32,
    0.39,
    0.46,
    0.53,
    0.60,
    0.68,
    0.76,
    0.84,
    0.91,
    0.97,
)
FULL_SEQUENCE_FRAME_ONSETS = tuple(
    index / FULL_SEQUENCE_FRAME_COUNT for index in range(FULL_SEQUENCE_FRAME_COUNT)
)


@dataclass(frozen=True)
class Animation:
    name: str
    sheet: Path
    duration_ms: int
    delete_trigger_progress: float | None = None
    frame_onsets: tuple[float, ...] = LINEAR_FRAME_ONSETS
    frame_count: int = DEFAULT_FRAME_COUNT
    atlas_columns: int = ATLAS_COLUMNS
    reverse_mirror: bool = False
    fixed_orientation: bool = False


@dataclass(frozen=True)
class Stage:
    animation: Animation
    start: QPointF
    end: QPointF
    motion: str = "smooth"
    effect: str = ""


def read_json(path: Path, default: dict[str, object]) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default.copy()
    except (OSError, ValueError):
        return default.copy()


def write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def choose_weighted(weights: dict[str, int], previous: str = "") -> str:
    candidates = [(name, weight) for name, weight in weights.items() if name != previous]
    if not candidates:
        candidates = list(weights.items())
    return random.choices(
        [name for name, _ in candidates],
        weights=[weight for _, weight in candidates],
        k=1,
    )[0]


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def frame_for_progress(animation: Animation, progress: float) -> int:
    return min(
        animation.frame_count - 1,
        max(0, bisect_right(animation.frame_onsets, progress) - 1),
    )


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


class _WinPoint(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def physical_to_qt_point(point: QPoint) -> tuple[object, QPoint]:
    """Map Win32/UIA physical pixels into Qt's device-independent coordinates."""
    user32 = ctypes.windll.user32
    monitor = user32.MonitorFromPoint(_WinPoint(point.x(), point.y()), 2)
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        physical_width = info.rcMonitor.right - info.rcMonitor.left
        physical_height = info.rcMonitor.bottom - info.rcMonitor.top
        screens = QGuiApplication.screens()
        screen = min(
            screens,
            key=lambda candidate: (
                abs(candidate.geometry().width() * candidate.devicePixelRatio() - physical_width)
                + abs(candidate.geometry().height() * candidate.devicePixelRatio() - physical_height)
                + abs(candidate.geometry().left() * candidate.devicePixelRatio() - info.rcMonitor.left) * 0.1
                + abs(candidate.geometry().top() * candidate.devicePixelRatio() - info.rcMonitor.top) * 0.1
            ),
        )
        ratio = max(1.0, float(screen.devicePixelRatio()))
        geometry = screen.geometry()
        logical = QPoint(
            round(geometry.left() + (point.x() - info.rcMonitor.left) / ratio),
            round(geometry.top() + (point.y() - info.rcMonitor.top) / ratio),
        )
        return screen, logical

    screen = QGuiApplication.primaryScreen()
    ratio = max(1.0, float(screen.devicePixelRatio())) if screen else 1.0
    return screen, QPoint(round(point.x() / ratio), round(point.y() / ratio))


def selected_explorer_item_rect(target_path: Path, preferred_view_hwnd: int = 0) -> QRect | None:
    """Locate the selected row, preferring the exact Shell view from the native bridge."""
    normalized_target = os.path.normcase(os.path.normpath(str(target_path)))
    target_names = {target_path.name.casefold(), target_path.stem.casefold()}

    if preferred_view_hwnd:
        try:
            view = Desktop(backend="uia").window(handle=preferred_view_hwnd)
            for control_type in ("DataItem", "ListItem"):
                for item in view.descendants(control_type=control_type):
                    try:
                        if not item.is_selected():
                            continue
                        rect = item.rectangle()
                        if rect.width() > 0 and rect.height() > 0:
                            return QRect(rect.left, rect.top, rect.width(), rect.height())
                    except Exception:
                        continue
        except Exception:
            pass

    try:
        for shell_window in Dispatch("Shell.Application").Windows():
            try:
                if not str(shell_window.FullName).casefold().endswith("explorer.exe"):
                    continue
                selected_paths = {
                    os.path.normcase(os.path.normpath(str(item.Path)))
                    for item in shell_window.Document.SelectedItems()
                }
                if normalized_target not in selected_paths:
                    continue
                window = Desktop(backend="uia").window(handle=int(shell_window.HWND))
            except Exception:
                continue

            for control_type in ("DataItem", "ListItem"):
                for item in window.descendants(control_type=control_type):
                    try:
                        if item.window_text().strip().casefold() not in target_names:
                            continue
                        rect = item.rectangle()
                        if rect.width() > 0 and rect.height() > 0:
                            return QRect(rect.left, rect.top, rect.width(), rect.height())
                    except Exception:
                        continue

            for control_type in ("DataItem", "ListItem"):
                for item in window.descendants(control_type=control_type):
                    try:
                        if not item.is_selected():
                            continue
                        rect = item.rectangle()
                        if rect.width() > 0 and rect.height() > 0:
                            return QRect(rect.left, rect.top, rect.width(), rect.height())
                    except Exception:
                        continue
    except Exception:
        return None
    return None


class FileTokenWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.token_size = 22.0
        self.stack_count = 1
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
        self.resize(40, 48)

    def set_token(self, center: QPointF, size: float) -> None:
        self.token_size = size
        self.move(round(center.x() - self.width() / 2), round(center.y() - self.height() / 2))
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = self.token_size
        layers = min(3, self.stack_count)
        for layer in reversed(range(layers)):
            offset_x = (layer - (layers - 1) / 2) * 3.2
            offset_y = -layer * 2.2
            icon = QRectF(
                (self.width() - size) / 2 + offset_x,
                (self.height() - size * 1.24) / 2 + offset_y,
                size,
                size * 1.24,
            )
            painter.setPen(QPen(QColor(50, 70, 88, 230), 1.5))
            painter.setBrush(QColor(245, 249, 252, 245))
            painter.drawRoundedRect(icon, 1.5, 1.5)
            fold = QRectF(icon.right() - size * 0.28, icon.top(), size * 0.28, size * 0.28)
            painter.setBrush(QColor(91, 188, 241, 245))
            painter.drawRect(fold)


class SettingsDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("菲比清理设置")
        self.setMinimumWidth(320)
        settings = read_json(SETTINGS_FILE, {"speed_profile": "standard"})

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("动画节奏"))
        self.speed_combo = QComboBox(self)
        for key in ("concise", "standard", "dramatic"):
            self.speed_combo.addItem(SPEED_LABELS[key], key)
        current = str(settings.get("speed_profile", "standard"))
        index = self.speed_combo.findData(current)
        self.speed_combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.speed_combo)
        layout.addWidget(QLabel("简洁更快，标准为默认节奏，戏剧化会给动作更多停顿和回弹时间。"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        write_json(SETTINGS_FILE, {"speed_profile": self.speed_combo.currentData()})
        self.accept()


class PetWindow(QWidget):
    finished = Signal()

    def __init__(
        self,
        target_path: Path,
        global_anchor: QPoint | None = None,
        preferred_view_hwnd: int = 0,
        forced_entry: str = "",
        forced_satisfaction: str = "",
        forced_exit: str = "",
        target_paths: list[Path] | None = None,
    ) -> None:
        super().__init__()
        self.target_path = target_path
        self.target_paths = target_paths or [target_path]
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.delete_future: concurrent.futures.Future[None] | None = None
        self.delete_triggered = False
        self.delete_failed = False
        self.stage_index = 0
        self.stage_progress = 0.0
        self.frame_index = 0
        self.pet_position = QPointF()
        self.clock = QElapsedTimer()
        self.file_token = FileTokenWindow()
        self.file_token.stack_count = len(self.target_paths)
        self.is_multi_select = len(self.target_paths) > 1
        settings = read_json(SETTINGS_FILE, {"speed_profile": "standard"})
        self.speed_profile = str(settings.get("speed_profile", "standard"))
        self.speed_factor = SPEED_FACTORS.get(self.speed_profile, 1.0)
        state = read_json(
            STATE_FILE,
            {"invocation_count": 0, "last_entry": "", "last_satisfaction": "", "last_exit": ""},
        )
        invocation_count = int(state.get("invocation_count", 0)) + 1
        try:
            total_file_bytes = sum(
                path.stat().st_size for path in self.target_paths if path.is_file()
            )
            self.is_large_file = total_file_bytes >= LARGE_FILE_BYTES
            self.is_empty_directory = (
                len(self.target_paths) == 1
                and target_path.is_dir()
                and next(target_path.iterdir(), None) is None
            )
        except OSError:
            self.is_large_file = False
            self.is_empty_directory = False

        previous_entry = str(state.get("last_entry", ""))
        repeat_due = invocation_count % 5 == 0
        ordinary_single_file = not (
            self.is_multi_select or self.is_large_file or self.is_empty_directory
        )
        self.full_sequence_name = (
            forced_entry if forced_entry in FULL_SEQUENCE_WEIGHTS else ""
        )
        if (
            not self.full_sequence_name
            and not forced_entry
            and ordinary_single_file
            and not repeat_due
            and random.random() < FULL_SEQUENCE_CHANCE
        ):
            self.full_sequence_name = choose_weighted(
                FULL_SEQUENCE_WEIGHTS, previous_entry
            )
        self.full_sequence = bool(self.full_sequence_name)

        if self.full_sequence:
            self.entry_variant = self.full_sequence_name
            self.repeat_annoyed = False
            self.front_pipeline = True
            self.satisfaction_variant = "front-integrated"
            self.exit_variant = "front-integrated"
        else:
            self.entry_variant = (
                forced_entry
                if forced_entry in ENTRY_WEIGHTS
                else choose_weighted(ENTRY_WEIGHTS, previous_entry)
            )
            self.repeat_annoyed = repeat_due
            self.front_pipeline = self.entry_variant in {"light", "skyfall"}
            satisfaction_weights = (
                FRONT_SATISFACTION_WEIGHTS
                if self.front_pipeline
                else SIDE_SATISFACTION_WEIGHTS
            )
            self.satisfaction_variant = (
                forced_satisfaction
                if forced_satisfaction in satisfaction_weights
                else choose_weighted(
                    satisfaction_weights, str(state.get("last_satisfaction", ""))
                )
            )
            exit_weights = FRONT_EXIT_WEIGHTS if self.front_pipeline else EXIT_WEIGHTS
            self.exit_variant = (
                forced_exit
                if forced_exit in exit_weights
                else choose_weighted(exit_weights, str(state.get("last_exit", "")))
            )
            if (
                not self.front_pipeline
                and (self.is_large_file or self.is_multi_select)
                and not forced_exit
            ):
                self.exit_variant = "overfull"
        write_json(
            STATE_FILE,
            {
                "invocation_count": invocation_count,
                "last_entry": self.entry_variant,
                "last_satisfaction": (
                    state.get("last_satisfaction", "")
                    if self.full_sequence
                    else self.satisfaction_variant
                ),
                "last_exit": (
                    state.get("last_exit", "") if self.full_sequence else self.exit_variant
                ),
            },
        )

        if global_anchor is None:
            selected_rect = selected_explorer_item_rect(target_path, preferred_view_hwnd)
            if selected_rect is None:
                raise RuntimeError(f"Unable to locate selected Explorer item: {target_path}")
            global_anchor = QPoint(
                selected_rect.left() + min(42, max(18, selected_rect.width() // 6)),
                selected_rect.center().y(),
            )
        self.screen, global_anchor = physical_to_qt_point(global_anchor)
        self.screen_geometry = self.screen.availableGeometry() if self.screen else QRect(0, 0, 1920, 1080)
        self.target_anchor = QPointF(global_anchor)

        self.mirror = self.target_anchor.x() > self.screen_geometry.center().x()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
        self.resize(DISPLAY_WIDTH, DISPLAY_HEIGHT)

        self.stages = self._build_stages()
        self.frames = {
            stage.animation.name: self._load_frames(stage.animation)
            for stage in self.stages
        }

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(RENDER_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

    def _asset(self, relative: str) -> Path:
        return runtime_root() / "assets" / "phoebe" / relative

    def _pet_target_position(self) -> QPointF:
        if self.mirror:
            x = self.target_anchor.x() - DISPLAY_WIDTH - 18
        else:
            x = self.target_anchor.x() + 18
        y = self.target_anchor.y() - DISPLAY_HEIGHT + 26
        if y < self.screen_geometry.top() + 4:
            y = self.target_anchor.y() + 14
        x = max(
            self.screen_geometry.left() + 4.0,
            min(x, self.screen_geometry.right() - DISPLAY_WIDTH - 3.0),
        )
        y = max(
            self.screen_geometry.top() + 4.0,
            min(y, self.screen_geometry.bottom() - DISPLAY_HEIGHT - 3.0),
        )
        return QPointF(x, y)

    def _build_stages(self) -> list[Stage]:
        target = self._pet_target_position()
        if self.mirror:
            entry_start = QPointF(self.screen_geometry.left() - DISPLAY_WIDTH - 8, target.y())
            exit_end = QPointF(self.screen_geometry.right() + 8, target.y())
            side = -1.0
        else:
            entry_start = QPointF(self.screen_geometry.right() + 8, target.y())
            exit_end = QPointF(self.screen_geometry.left() - DISPLAY_WIDTH - 8, target.y())
            side = 1.0

        staging_x = max(
            self.screen_geometry.left() + 8.0,
            min(
                target.x() + side * 300.0,
                self.screen_geometry.right() - DISPLAY_WIDTH - 8.0,
            ),
        )
        staging = QPointF(staging_x, target.y())

        def animation(
            name: str,
            sheet: str,
            duration_ms: int,
            delete_trigger: float | None = None,
            frame_onsets: tuple[float, ...] = LINEAR_FRAME_ONSETS,
            fixed_orientation: bool = False,
            asset_directory: str = "baked_animation_v6",
            frame_count: int = DEFAULT_FRAME_COUNT,
            atlas_columns: int = ATLAS_COLUMNS,
        ) -> Animation:
            return Animation(
                name,
                self._asset(f"{asset_directory}/{sheet}.png"),
                max(180, round(duration_ms * self.speed_factor)),
                delete_trigger,
                frame_onsets,
                frame_count=frame_count,
                atlas_columns=atlas_columns,
                fixed_orientation=fixed_orientation,
            )

        stages: list[Stage] = []
        if self.full_sequence:
            sequence_specs = {
                "full-magic-snack": (
                    "baked_full_sequence_v8",
                    "front-full-magic-snack-entry-pickup",
                    "front-magic-snack-entry-pickup",
                    1600,
                    "front-full-magic-snack-eat-satisfy",
                    "front-magic-snack-eat-satisfy",
                    1900,
                    "exit-front-full-magic-snack",
                    "front-magic-snack-exit",
                    1500,
                ),
                "full-sleepy-cloud": (
                    "baked_front_sequences_v9",
                    "front-full-sleepy-cloud-entry",
                    "front-sleepy-cloud-entry",
                    1650,
                    "front-full-sleepy-cloud-eat",
                    "front-sleepy-cloud-eat",
                    1900,
                    "exit-front-full-sleepy-cloud",
                    "front-sleepy-cloud-exit",
                    1600,
                ),
                "full-portal-peek": (
                    "baked_front_sequences_v9",
                    "front-full-portal-peek-entry",
                    "front-portal-peek-entry",
                    1600,
                    "front-full-portal-peek-eat",
                    "front-portal-peek-eat",
                    1850,
                    "exit-front-full-portal-peek",
                    "front-portal-peek-exit",
                    1550,
                ),
                "full-star-drop": (
                    "baked_front_sequences_v9",
                    "front-full-star-drop-entry",
                    "front-star-drop-entry",
                    1550,
                    "front-full-star-drop-eat",
                    "front-star-drop-eat",
                    1850,
                    "exit-front-full-star-drop",
                    "front-star-drop-exit",
                    1450,
                ),
            }
            (
                asset_directory,
                entry_name,
                entry_sheet,
                entry_duration,
                eat_name,
                eat_sheet,
                eat_duration,
                exit_name,
                exit_sheet,
                exit_duration,
            ) = sequence_specs[self.full_sequence_name]
            full_options = {
                "frame_onsets": FULL_SEQUENCE_FRAME_ONSETS,
                "fixed_orientation": True,
                "asset_directory": asset_directory,
                "frame_count": FULL_SEQUENCE_FRAME_COUNT,
                "atlas_columns": FULL_SEQUENCE_COLUMNS,
            }
            return [
                Stage(
                    animation(
                        entry_name,
                        entry_sheet,
                        entry_duration,
                        **full_options,
                    ),
                    target,
                    target,
                ),
                Stage(
                    animation(
                        eat_name,
                        eat_sheet,
                        eat_duration,
                        18 / 28,
                        **full_options,
                    ),
                    target,
                    target,
                ),
                Stage(
                    animation(
                        exit_name,
                        exit_sheet,
                        exit_duration,
                        **full_options,
                    ),
                    target,
                    target,
                ),
            ]

        if self.front_pipeline:
            if self.entry_variant == "light":
                stages.append(
                    Stage(
                        animation(
                            "front-entry-light",
                            "front-neutral-hold",
                            850,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                        effect="materialize",
                    )
                )
            else:
                stages.append(
                    Stage(
                        animation(
                            "front-entry-skyfall",
                            "front-skyfall",
                            1200,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                        effect="landing-sparkles",
                    )
                )

            if self.repeat_annoyed:
                stages.append(
                    Stage(
                        animation(
                            "front-repeat-annoyed",
                            "front-repeat-annoyed",
                            1700,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                    )
                )

            stages.append(
                Stage(
                    animation(
                        "front-pickup",
                        "front-pickup",
                        900,
                        fixed_orientation=True,
                    ),
                    target,
                    target,
                )
            )

            if self.is_multi_select:
                front_eat = animation(
                    "front-multi-cookie",
                    "front-multi-cookie",
                    2450,
                    13 / 14,
                    EAT_FRAME_ONSETS,
                    fixed_orientation=True,
                )
                front_eat_motion = "smooth"
            elif self.is_large_file:
                front_eat = animation(
                    "front-large-power-bite",
                    "front-large-power-bite",
                    2600,
                    13 / 14,
                    EAT_FRAME_ONSETS,
                    fixed_orientation=True,
                )
                front_eat_motion = "shake"
            elif self.is_empty_directory:
                front_eat = animation(
                    "front-empty-folder",
                    "front-empty-folder",
                    2350,
                    13 / 14,
                    EAT_FRAME_ONSETS,
                    fixed_orientation=True,
                )
                front_eat_motion = "smooth"
            else:
                front_eat = animation(
                    "front-eat",
                    "front-eat",
                    1650,
                    10 / 14,
                    EAT_FRAME_ONSETS,
                    fixed_orientation=True,
                )
                front_eat_motion = "smooth"
            stages.append(Stage(front_eat, target, target, motion=front_eat_motion))

            satisfaction_sheet = (
                "front-wave"
                if self.satisfaction_variant == "front-wave"
                else "front-bellypat"
            )
            stages.append(
                Stage(
                    animation(
                        self.satisfaction_variant,
                        satisfaction_sheet,
                        1150,
                        fixed_orientation=True,
                    ),
                    target,
                    target,
                )
            )

            if self.exit_variant == "belly-fade":
                stages.append(
                    Stage(
                        animation(
                            "exit-front-belly-fade",
                            "front-bellypat",
                            1300,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                        effect="fade-out",
                    )
                )
            elif self.exit_variant == "light":
                stages.append(
                    Stage(
                        animation(
                            "exit-front-light",
                            "front-neutral-hold",
                            1050,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                        effect="dissolve",
                    )
                )
            else:
                stages.append(
                    Stage(
                        animation(
                            "exit-front-burp-teleport",
                            "front-burp-teleport",
                            1700,
                            fixed_orientation=True,
                        ),
                        target,
                        target,
                        effect="teleport-out",
                    )
                )
            return stages

        ran_to_target = True
        if self.entry_variant == "run":
            stages.append(Stage(animation("entry-run", "entry-run", 1200), entry_start, target))
        else:
            if self.entry_variant == "light":
                ran_to_target = False
                stages.append(
                    Stage(
                        animation("entry-light", "neutral-hold", 850),
                        target,
                        target,
                        effect="materialize",
                    )
                )
            elif self.entry_variant == "skyfall":
                ran_to_target = False
                stages.append(
                    Stage(
                        animation("entry-skyfall", "entry-skyfall", 1150),
                        target,
                        target,
                        effect="landing-sparkles",
                    )
                )
            elif self.entry_variant == "sleepy":
                stages.append(
                    Stage(
                        animation("entry-sleepy", "entry-sleepy", 1500),
                        entry_start,
                        staging,
                    )
                )
            elif self.entry_variant == "peek":
                peek_start = QPointF(
                    self.screen_geometry.left() - DISPLAY_WIDTH + 46
                    if self.mirror
                    else self.screen_geometry.right() - 46,
                    target.y(),
                )
                stages.append(
                    Stage(
                        animation("entry-peek", "entry-peek", 1250),
                        peek_start,
                        staging,
                    )
                )
            else:
                miss = QPointF(target.x() + side * 235.0, target.y())
                stages.append(
                    Stage(
                        animation("entry-teleport-miss", "neutral-hold", 650),
                        miss,
                        miss,
                        effect="teleport-in",
                    )
                )
                staging = miss

            if ran_to_target:
                stages.append(
                    Stage(animation("entry-launch", "stand-to-run", 700), staging, staging)
                )
                stages.append(
                    Stage(animation("entry-common-run", "entry-run", 900), staging, target)
                )

        if self.repeat_annoyed:
            stages.append(
                Stage(
                    animation("side-repeat-annoyed", "side-repeat-annoyed", 1700),
                    target,
                    target,
                )
            )

        pickup_name = "run-to-pickup" if ran_to_target else "stand-to-pickup"
        stages.append(Stage(animation(pickup_name, pickup_name, 750), target, target))

        if self.is_multi_select:
            eat = animation(
                "side-multi-cookie", "side-multi-cookie", 2450, 13 / 14, EAT_FRAME_ONSETS
            )
            eat_motion = "smooth"
        elif self.is_large_file:
            eat = animation(
                "side-large-power-bite",
                "side-large-power-bite",
                2600,
                13 / 14,
                EAT_FRAME_ONSETS,
            )
            eat_motion = "shake"
        elif self.is_empty_directory:
            eat = animation(
                "side-empty-folder", "side-empty-folder", 2350, 13 / 14, EAT_FRAME_ONSETS
            )
            eat_motion = "smooth"
        else:
            eat = animation("eat-bite", "eat-bite", 1550, 10 / 14, EAT_FRAME_ONSETS)
            eat_motion = "smooth"
        stages.append(Stage(eat, target, target, motion=eat_motion))

        if self.satisfaction_variant.startswith("front-"):
            stages.append(
                Stage(animation("side-to-front", "side-to-front", 900), target, target)
            )
            front_sheet = (
                "front-wave" if self.satisfaction_variant == "front-wave" else "front-bellypat"
            )
            stages.append(
                Stage(animation(self.satisfaction_variant, front_sheet, 1150), target, target)
            )
            stages.append(
                Stage(animation("front-to-side", "front-to-side", 900), target, target)
            )
        elif self.satisfaction_variant == "side-belly":
            stages.append(
                Stage(animation("satisfaction-belly", "exit-belly-fade", 1100), target, target)
            )
        elif self.satisfaction_variant == "side-bounce":
            stages.append(
                Stage(
                    animation("satisfaction-bounce", "neutral-hold", 700),
                    target,
                    target,
                    motion="happy-bounce",
                )
            )
        else:
            stages.append(
                Stage(animation("satisfaction-happy", "satisfaction-happy", 850), target, target)
            )

        if self.exit_variant == "belly-fade":
            stages.append(
                Stage(
                    animation("exit-belly-fade", "exit-belly-fade", 1300),
                    target,
                    target,
                    effect="fade-out",
                )
            )
        elif self.exit_variant == "bounce":
            stages.extend(
                (
                    Stage(animation("exit-launch", "stand-to-run", 700), target, target),
                    Stage(
                        animation("exit-bounce", "entry-run", 1500),
                        target,
                        exit_end,
                        motion="bouncy-travel",
                    ),
                )
            )
        elif self.exit_variant == "light":
            stages.append(
                Stage(
                    animation("exit-light", "neutral-hold", 1050),
                    target,
                    target,
                    effect="dissolve",
                )
            )
        elif self.exit_variant == "burp-teleport":
            stages.append(
                Stage(
                    animation("exit-burp-teleport", "exit-burp-teleport", 1650),
                    target,
                    target,
                    effect="teleport-out",
                )
            )
        elif self.exit_variant == "roll":
            stages.append(
                Stage(
                    animation("exit-roll", "exit-roll", 1900),
                    target,
                    exit_end,
                    motion="linear",
                )
            )
        else:
            stages.append(
                Stage(
                    animation("exit-overfull", "exit-overfull", 2700),
                    target,
                    exit_end,
                    motion="linear",
                )
            )
        return stages

    def _load_frames(self, animation: Animation) -> list[QImage]:
        atlas = QImage(str(animation.sheet))
        if atlas.isNull():
            raise RuntimeError(f"Unable to load animation sheet: {animation.sheet}")
        frames: list[QImage] = []
        for index in range(animation.frame_count):
            column = index % animation.atlas_columns
            row = index // animation.atlas_columns
            frame = atlas.copy(column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)
            should_mirror = (
                False
                if animation.fixed_orientation
                else (not self.mirror if animation.reverse_mirror else self.mirror)
            )
            frames.append(frame.mirrored(True, False) if should_mirror else frame)
        return frames

    def start(self) -> None:
        self.pet_position = self.stages[0].start
        self.move(round(self.pet_position.x()), round(self.pet_position.y()))
        self.show()
        self.raise_()
        self.clock.start()
        self.timer.start()
        self._tick()

    def _trigger_delete(self) -> None:
        if self.delete_triggered:
            return
        self.delete_triggered = True
        self.delete_future = self.executor.submit(self._delete_targets)

    def _delete_targets(self) -> None:
        for path in self.target_paths:
            send2trash(str(path))

    def _advance_stage(self) -> None:
        current_animation = self.stages[self.stage_index].animation
        if current_animation.delete_trigger_progress is not None and self.delete_future is not None:
            if not self.delete_future.done():
                return
            try:
                self.delete_future.result()
            except Exception:
                self.delete_failed = True
            if self.delete_failed:
                target = self.stages[self.stage_index].end
                failure = (
                    Animation(
                        "front-failure",
                        self._asset("baked_animation_v6/front-failure.png"),
                        max(180, round(1700 * self.speed_factor)),
                        fixed_orientation=True,
                    )
                    if self.front_pipeline
                    else Animation(
                        "failure-bite",
                        self._asset("spritesheets_v3_anchored/failure-bite.png"),
                        max(180, round(1500 * self.speed_factor)),
                    )
                )
                next_stage_index = self.stage_index + 1
                exit_stage_index = next(
                    (
                        index
                        for index in range(next_stage_index, len(self.stages))
                        if self.stages[index].animation.name.startswith("exit-")
                    ),
                    len(self.stages),
                )
                self.stages = (
                    self.stages[:next_stage_index]
                    + [Stage(failure, target, target)]
                    + self.stages[exit_stage_index:]
                )
                self.frames[failure.name] = self._load_frames(failure)

        self.stage_index += 1
        if self.stage_index >= len(self.stages):
            self.timer.stop()
            self.executor.shutdown(wait=False, cancel_futures=False)
            self.file_token.close()
            self.close()
            self.finished.emit()
            return
        self.clock.restart()

    def _tick(self) -> None:
        if self.stage_index >= len(self.stages):
            return
        stage = self.stages[self.stage_index]
        elapsed = self.clock.elapsed()
        progress = min(1.0, elapsed / stage.animation.duration_ms)
        self.stage_progress = progress

        trigger = stage.animation.delete_trigger_progress
        if trigger is not None and progress >= trigger:
            self._trigger_delete()

        self.frame_index = frame_for_progress(stage.animation, progress)

        eased = progress if stage.motion == "linear" else smoothstep(progress)
        self.pet_position = QPointF(
            stage.start.x() + (stage.end.x() - stage.start.x()) * eased,
            stage.start.y() + (stage.end.y() - stage.start.y()) * eased,
        )
        if stage.motion == "bouncy-travel":
            self.pet_position.setY(
                self.pet_position.y() - abs(math.sin(progress * math.tau * 2.5)) * 22.0
            )
        elif stage.motion == "happy-bounce":
            self.pet_position.setY(
                self.pet_position.y() - abs(math.sin(progress * math.tau * 1.5)) * 11.0
            )
        elif stage.motion == "shake":
            envelope = math.sin(math.pi * progress) ** 2
            self.pet_position.setX(
                self.pet_position.x() + math.sin(progress * math.tau * 7.0) * 3.5 * envelope
            )
        elif "run" in stage.animation.name:
            gait_phase = progress * math.tau * 3.0
            self.pet_position.setY(self.pet_position.y() - abs(math.sin(gait_phase)) * 2.2)
        self.move(round(self.pet_position.x()), round(self.pet_position.y()))
        self._update_file_token()
        self.update()

        if progress >= 1.0:
            self._advance_stage()

    def _update_file_token(self) -> None:
        if self.stage_index >= len(self.stages):
            self.file_token.hide()
            return
        if self.stages[self.stage_index].animation.name not in {
            "run-to-pickup",
            "stand-to-pickup",
            "front-pickup",
        }:
            self.file_token.hide()
            return
        lift_start = 0.12
        lift_end = 0.90
        lift_progress = smoothstep(
            max(0.0, min(1.0, (self.stage_progress - lift_start) / (lift_end - lift_start)))
        )
        if self.stages[self.stage_index].animation.name == "front-pickup":
            hand_x = self.pet_position.x() + DISPLAY_WIDTH * 0.50
            hand_y = self.pet_position.y() + DISPLAY_HEIGHT * 0.55
        else:
            hand_x = self.pet_position.x() + (DISPLAY_WIDTH * (0.69 if self.mirror else 0.31))
            hand_y = self.pet_position.y() + DISPLAY_HEIGHT * 0.53
        x = self.target_anchor.x() + (hand_x - self.target_anchor.x()) * lift_progress
        arc_height = math.sin(math.pi * lift_progress) * 18.0
        y = self.target_anchor.y() + (hand_y - self.target_anchor.y()) * lift_progress - arc_height
        size = 19.0 - 2.0 * lift_progress
        self.file_token.set_token(QPointF(x, y), size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self.stage_index >= len(self.stages):
            return
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        stage = self.stages[self.stage_index]
        self._paint_effect(painter, stage, behind=True)
        opacity = self._stage_opacity(stage)
        painter.setOpacity(opacity)
        frames = self.frames[stage.animation.name]
        painter.drawImage(QRectF(self.rect()), frames[self.frame_index])
        painter.setOpacity(1.0)
        self._paint_effect(painter, stage, behind=False)

    def _stage_opacity(self, stage: Stage) -> float:
        if stage.effect in {"materialize", "teleport-in"}:
            return smoothstep(min(1.0, self.stage_progress / 0.62))
        if stage.effect == "fade-out":
            return 1.0 - smoothstep(max(0.0, (self.stage_progress - 0.58) / 0.42))
        if stage.effect == "dissolve":
            return 1.0 - smoothstep(max(0.0, (self.stage_progress - 0.20) / 0.72))
        return 1.0

    def _paint_effect(self, painter: QPainter, stage: Stage, behind: bool) -> None:
        effect = stage.effect
        if effect not in {
            "materialize",
            "teleport-in",
            "dissolve",
            "teleport-out",
            "landing-sparkles",
        }:
            return
        progress = self.stage_progress
        if effect == "landing-sparkles" and progress < 0.42:
            return
        center_x = self.width() * 0.50
        base_y = self.height() * 0.82
        count = 14 if behind else 9
        for index in range(count):
            phase = (progress * (1.35 if effect != "landing-sparkles" else 2.4) + index * 0.137) % 1.0
            angle = index * 2.399963 + progress * math.tau * 0.45
            radius = 18.0 + (index % 5) * 7.0
            x = center_x + math.cos(angle) * radius * (0.45 + phase * 0.55)
            if effect == "landing-sparkles":
                y = base_y - abs(math.sin(angle)) * 16.0 - phase * 15.0
            elif effect in {"materialize", "teleport-in"}:
                y = base_y - phase * self.height() * 0.68
            else:
                y = base_y - (1.0 - phase) * self.height() * 0.62
            alpha = round(210 * math.sin(math.pi * phase))
            if alpha <= 0:
                continue
            size = 1.5 + (index % 3) * 1.2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(116, 225, 255, alpha))
            painter.drawEllipse(QPointF(x, y), size, size)


class PhoebeServer(QObject):
    def __init__(self, initial_request: dict[str, object] | None = None) -> None:
        super().__init__()
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connections)
        self.requests: deque[dict[str, object]] = deque()
        self.buffers: dict[QLocalSocket, bytearray] = {}
        self.current_window: PetWindow | None = None
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(SERVER_IDLE_TIMEOUT_MS)
        self.idle_timer.timeout.connect(self._on_idle_timeout)

        if not self.server.listen(SERVER_NAME):
            probe = QLocalSocket(self)
            probe.connectToServer(SERVER_NAME)
            if probe.waitForConnected(120):
                if initial_request is not None:
                    probe.write((json.dumps(initial_request, ensure_ascii=False) + "\n").encode("utf-8"))
                    probe.waitForBytesWritten(120)
                probe.disconnectFromServer()
                QTimer.singleShot(0, QApplication.quit)
                return
            QLocalServer.removeServer(SERVER_NAME)
            if not self.server.listen(SERVER_NAME):
                raise RuntimeError(f"Unable to listen on local server: {self.server.errorString()}")

        if initial_request is not None:
            self.enqueue(initial_request)
        else:
            self.idle_timer.start()

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self.buffers[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_socket(current))
            socket.disconnected.connect(lambda current=socket: self._socket_disconnected(current))
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self.buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        while b"\n" in buffer:
            raw, _, remaining = buffer.partition(b"\n")
            buffer[:] = remaining
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(request, dict):
                self.enqueue(request)

    def _socket_disconnected(self, socket: QLocalSocket) -> None:
        self._read_socket(socket)
        self.buffers.pop(socket, None)
        socket.deleteLater()

    def enqueue(self, request: dict[str, object]) -> None:
        raw_path = request.get("path")
        if not isinstance(raw_path, str):
            return
        raw_paths = request.get("paths")
        if isinstance(raw_paths, list):
            paths = [Path(value) for value in raw_paths if isinstance(value, str)]
        else:
            paths = [Path(raw_path)]
        if not paths or any(not path.exists() for path in paths):
            return
        request["paths"] = [str(path) for path in paths]
        self.requests.append(request)
        self.idle_timer.stop()
        self._start_next()

    def _start_next(self) -> None:
        if self.current_window is not None or not self.requests:
            return
        request = self.requests.popleft()
        path = Path(str(request["path"]))
        target_paths = [Path(value) for value in request.get("paths", [str(path)])]
        anchor: QPoint | None = None
        if bool(request.get("position_valid", False)):
            try:
                anchor = QPoint(int(request["x"]), int(request["y"]))
            except (KeyError, TypeError, ValueError):
                anchor = None
        try:
            view_hwnd = int(request.get("view_hwnd", 0))
            window = PetWindow(
                path,
                anchor,
                view_hwnd,
                str(request.get("entry_variant", "")),
                str(request.get("satisfaction_variant", "")),
                str(request.get("exit_variant", "")),
                target_paths,
            )
        except RuntimeError:
            QTimer.singleShot(0, self._start_next)
            return
        self.current_window = window
        window.finished.connect(self._window_finished)
        window.start()

    def _window_finished(self) -> None:
        if self.current_window is not None:
            self.current_window.deleteLater()
        self.current_window = None
        if self.requests:
            QTimer.singleShot(0, self._start_next)
        else:
            self.idle_timer.start()

    def _on_idle_timeout(self) -> None:
        if self.current_window is None and not self.requests:
            QApplication.quit()
        else:
            self.idle_timer.start()


def argument_value(name: str, default: str = "") -> str:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


def argument_values(name: str) -> list[str]:
    return [sys.argv[index + 1] for index, value in enumerate(sys.argv[:-1]) if value == name]


def initial_server_request() -> dict[str, object] | None:
    raw_paths = argument_values("--path")
    if not raw_paths:
        return None
    try:
        return {
            "path": raw_paths[0],
            "paths": raw_paths,
            "x": int(argument_value("--x", "0")),
            "y": int(argument_value("--y", "0")),
            "position_valid": argument_value("--position-valid", "0") == "1",
            "explorer_hwnd": int(argument_value("--explorer-hwnd", "0")),
            "view_hwnd": int(argument_value("--view-hwnd", "0")),
            "view_mode": int(argument_value("--view-mode", "0")),
            "entry_variant": argument_value("--entry-variant"),
            "satisfaction_variant": argument_value("--satisfaction-variant"),
            "exit_variant": argument_value("--exit-variant"),
            "source": "shell-launch",
        }
    except ValueError:
        return None


def main() -> int:
    app = QApplication(sys.argv)
    if "--settings" in sys.argv:
        dialog = SettingsDialog()
        dialog.exec()
        return 0
    if "--serve" in sys.argv:
        app.setQuitOnLastWindowClosed(False)
        try:
            server = PhoebeServer(initial_server_request())
        except RuntimeError:
            return 6
        app._phoebe_server = server  # type: ignore[attr-defined]
        return app.exec()

    app.setQuitOnLastWindowClosed(True)
    if len(sys.argv) < 2:
        return 2
    target = Path(sys.argv[1]).resolve()
    if not target.exists():
        return 3
    try:
        window = PetWindow(target)
    except RuntimeError:
        return 4
    window.finished.connect(app.quit)
    window.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
