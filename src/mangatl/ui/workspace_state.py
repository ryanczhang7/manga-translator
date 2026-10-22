"""The workspace's remembered layout, kept on disk between sessions (MT-088).

`layout.md` §Window: the window's size, position, maximised state and the
**dragged** column width are remembered in one JSON file beside
`settings.json` (`mangatl.app_paths.workspace_state_path`). This module is the
file and the arithmetic, and imports only the standard library, so it is
tested without a `QApplication`; `Workspace.remember_layout` applies it.

Nothing read from disk is applied as is: `clamp_state` fits it to the current
work area first, so a file written on a larger screen never opens a window
off-screen or below the minimum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "FIRST_RUN_SIZE",
    "STATE_VERSION",
    "Rect",
    "WorkspaceState",
    "clamp_state",
    "first_run_size",
    "read_state",
    "write_state",
]

#: The file's `version`; a file of any other version reads as no state.
STATE_VERSION: int = 1
#: `layout.md` "Default on first run".
FIRST_RUN_SIZE: tuple[int, int] = (1600, 1000)

#: x, y, width, height.
Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class WorkspaceState:
    """One remembered layout. `x`/`y` are the frame's top-left, what `move()` takes."""

    width: int
    height: int
    x: int
    y: int
    maximized: bool
    #: `None`: the user never dragged the column, so the breakpoint sets it.
    column_width: int | None


def _is_int(value: object) -> bool:
    # `bool` subclasses `int`; a `true` in the file is not a width.
    return isinstance(value, int) and not isinstance(value, bool)


def read_state(path: Path) -> WorkspaceState | None:
    """The state in `path`, or `None` if there is none usable. Never raises."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if not _is_int(version) or version != STATE_VERSION:
        return None
    ints = ("width", "height", "x", "y")
    if not all(_is_int(data.get(name)) for name in ints):
        return None
    maximized = data.get("maximized")
    if not isinstance(maximized, bool):
        return None
    if "column_width" not in data:
        return None
    column = data["column_width"]
    if column is not None and not _is_int(column):
        return None
    return WorkspaceState(
        width=data["width"],
        height=data["height"],
        x=data["x"],
        y=data["y"],
        maximized=maximized,
        column_width=column,
    )


def write_state(path: Path, state: WorkspaceState) -> bool:
    """Write `state` to `path`, creating its folders. `False` on failure; never raises."""
    data = {
        "version": STATE_VERSION,
        "width": state.width,
        "height": state.height,
        "x": state.x,
        "y": state.y,
        "maximized": state.maximized,
        "column_width": state.column_width,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _clamp_size(
    size: tuple[int, int], work_area: Rect, minimum: tuple[int, int]
) -> tuple[int, int]:
    """Per axis `max(minimum, min(size, area))` - but the minimum on BOTH axes
    when the area cannot hold the minimum on EITHER (A-1)."""
    _, _, area_w, area_h = work_area
    min_w, min_h = minimum
    if area_w < min_w or area_h < min_h:
        return minimum
    return (max(min_w, min(size[0], area_w)), max(min_h, min(size[1], area_h)))


def first_run_size(work_area: Rect, minimum: tuple[int, int]) -> tuple[int, int]:
    """The size a window with no usable state opens at on `work_area`."""
    return _clamp_size(FIRST_RUN_SIZE, work_area, minimum)


def _clamp_edge(value: int, start: int, length: int, size: int) -> int:
    """`value` moved so `[value, value + size]` lies inside `[start, start + length]`;
    `start` when it cannot."""
    if length < size:
        return start
    return min(max(value, start), start + length - size)


def clamp_state(
    state: WorkspaceState,
    work_area: Rect,
    minimum: tuple[int, int],
    column_range: tuple[int, int],
) -> WorkspaceState:
    """`state` fitted to `work_area`: the size within the minimum and the area,
    the WHOLE window inside the area (AM-1), the column within `column_range`."""
    area_x, area_y, area_w, area_h = work_area
    width, height = _clamp_size((state.width, state.height), work_area, minimum)
    column = state.column_width
    if column is not None:
        column = min(max(column, column_range[0]), column_range[1])
    return WorkspaceState(
        width=width,
        height=height,
        x=_clamp_edge(state.x, area_x, area_w, width),
        y=_clamp_edge(state.y, area_y, area_h, height),
        maximized=state.maximized,
        column_width=column,
    )
