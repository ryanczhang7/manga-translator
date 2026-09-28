# Generated from docs/wiki/design/tokens.toml by mangatl.ui.tokens.
# Do not edit: regenerate with `uv run python -m mangatl.ui.tokens`.

COLOR_SURFACE_BASE = "#1C1C1C"
COLOR_SURFACE_RAISED = "#262626"
COLOR_SURFACE_SUNKEN = "#141414"
COLOR_SURFACE_OVERLAY = "#2E2E2E"
COLOR_SURFACE_HOVER = "#303030"
COLOR_SURFACE_PRESSED = "#3A3A3A"
COLOR_SURFACE_DISABLED = "#212121"
COLOR_SURFACE_SELECTED = "#17425C"
COLOR_CANVAS_SURROUND = "#5F5F5F"
COLOR_CANVAS_PAGE_EDGE = "#0B0B0B"
COLOR_CANVAS_FRAME = "#7A7A7A"
COLOR_BORDER_SUBTLE = "#333333"
COLOR_BORDER_DEFAULT = "#4A4A4A"
COLOR_BORDER_INTERACTIVE = "#7A7A7A"
COLOR_BORDER_FOCUS = "#FFFFFF"
COLOR_TEXT_PRIMARY = "#EDEDED"
COLOR_TEXT_SECONDARY = "#B4B4B4"
COLOR_TEXT_MUTED = "#949494"
COLOR_TEXT_DISABLED = "#737373"
COLOR_TEXT_ON_ACCENT = "#06202B"
COLOR_TEXT_ON_DANGER = "#2B0A0A"
COLOR_TEXT_ON_WARNING = "#2B1F05"
COLOR_TEXT_ON_SUCCESS = "#062012"
COLOR_ACCENT_BASE = "#4CC2FF"
COLOR_ACCENT_HOVER = "#7AD3FF"
COLOR_ACCENT_PRESSED = "#2FA8E8"
COLOR_ACCENT_SUBTLE = "#17425C"
COLOR_STATUS_DANGER = "#FF7A7A"
COLOR_STATUS_WARNING = "#FFC14D"
COLOR_STATUS_SUCCESS = "#6FD08C"
COLOR_FOCUS_RING = "#FFFFFF"
COLOR_FOCUS_HALO = "#0B0B0B"
OVERLAY_HALO = "#0B0B0B"
OVERLAY_BUBBLE_IDLE = "#D6DCE2"
OVERLAY_BUBBLE_HOVER = "#A8E4FF"
OVERLAY_BUBBLE_SELECTED = "#4CC2FF"
OVERLAY_BUBBLE_ERROR = "#FF7A7A"
OVERLAY_FILL_HOVER = "#4CC2FF1A"
OVERLAY_FILL_SELECTED = "#4CC2FF2E"
OVERLAY_FILL_ERROR = "#FF7A7A2E"
OVERLAY_STROKE_CORE_IDLE = 2
OVERLAY_STROKE_CORE_HOVER = 2
OVERLAY_STROKE_CORE_SELECTED = 3
OVERLAY_STROKE_CORE_ERROR = 3
OVERLAY_STROKE_HALO = 2
OVERLAY_DIM_OPACITY = 0.55
OVERLAY_BADGE_SIZE = 18
OVERLAY_BADGE_GAP = 4
OVERLAY_BADGE_LEADER_WIDTH = 2
TYPE_FAMILY_UI = "Segoe UI Variable Text, Segoe UI, sans-serif"
TYPE_FAMILY_MONO = "Consolas, Courier New, monospace"
TYPE_DISPLAY_SIZE = 20
TYPE_DISPLAY_LINE = 26
TYPE_DISPLAY_WEIGHT = 600
TYPE_DISPLAY_FAMILY = "ui"
TYPE_TITLE_SIZE = 16
TYPE_TITLE_LINE = 22
TYPE_TITLE_WEIGHT = 600
TYPE_TITLE_FAMILY = "ui"
TYPE_BODY_SIZE = 13
TYPE_BODY_LINE = 19
TYPE_BODY_WEIGHT = 400
TYPE_BODY_FAMILY = "ui"
TYPE_BODY_STRONG_SIZE = 13
TYPE_BODY_STRONG_LINE = 19
TYPE_BODY_STRONG_WEIGHT = 600
TYPE_BODY_STRONG_FAMILY = "ui"
TYPE_EDITOR_SIZE = 15
TYPE_EDITOR_LINE = 22
TYPE_EDITOR_WEIGHT = 400
TYPE_EDITOR_FAMILY = "ui"
TYPE_CAPTION_SIZE = 11
TYPE_CAPTION_LINE = 16
TYPE_CAPTION_WEIGHT = 400
TYPE_CAPTION_FAMILY = "ui"
TYPE_NUMERIC_SIZE = 13
TYPE_NUMERIC_LINE = 19
TYPE_NUMERIC_WEIGHT = 400
TYPE_NUMERIC_FAMILY = "mono"
TYPE_NUMERIC_LEAD_SIZE = 18
TYPE_NUMERIC_LEAD_LINE = 24
TYPE_NUMERIC_LEAD_WEIGHT = 600
TYPE_NUMERIC_LEAD_FAMILY = "mono"
SPACE_S0 = 0
SPACE_S1 = 4
SPACE_S2 = 8
SPACE_S3 = 12
SPACE_S4 = 16
SPACE_S6 = 24
SPACE_S8 = 32
SPACE_S12 = 48
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_PILL = 999
BORDER_WIDTH_HAIRLINE = 1
BORDER_WIDTH_EMPHASIS = 2
ELEVATION_E0_SURFACE = "color.surface.base"
ELEVATION_E0_BORDER = "none"
ELEVATION_E1_SURFACE = "color.surface.raised"
ELEVATION_E1_BORDER = "color.border.subtle"
ELEVATION_E2_SURFACE = "color.surface.overlay"
ELEVATION_E2_BORDER = "color.border.default"
FOCUS_WIDTH = 2
FOCUS_OFFSET = 2
FOCUS_HALO = 1
MOTION_DURATION_FAST = 120
MOTION_DURATION_BASE = 180
MOTION_DURATION_SLOW = 280
MOTION_EASING_STANDARD = "OutCubic"
MOTION_EASING_EMPHASIZED = "OutQuint"
MOTION_EASING_LINEAR = "Linear"
TYPESET_FONT_FAMILY = "Shantell Sans"
TYPESET_FONT_LICENCE = "OFL-1.1"
TYPESET_FONT_VERSION = "1.011"
TYPESET_FONT_REGULAR = "ShantellSans-Regular"
TYPESET_FONT_ITALIC = "ShantellSans-Italic"
TYPESET_FONT_BOLD = "ShantellSans-Bold"
TYPESET_FONT_BOLD_ITALIC = "ShantellSans-BoldItalic"
TYPESET_ALIGN = "center"
TYPESET_LINE_HEIGHT = 1.08
TYPESET_SIZE_MIN = 14
TYPESET_SIZE_MAX = 42
TYPESET_SIZE_STEP = 1
TYPESET_PADDING_RATIO = 0.12
TYPESET_HYPHENATE = False
TYPESET_MAX_LINES = 0

TOKENS: dict[str, str] = {
    "color.surface.base": "#1C1C1C",
    "color.surface.raised": "#262626",
    "color.surface.sunken": "#141414",
    "color.surface.overlay": "#2E2E2E",
    "color.surface.hover": "#303030",
    "color.surface.pressed": "#3A3A3A",
    "color.surface.disabled": "#212121",
    "color.surface.selected": "#17425C",
    "color.canvas.surround": "#5F5F5F",
    "color.canvas.page-edge": "#0B0B0B",
    "color.canvas.frame": "#7A7A7A",
    "color.border.subtle": "#333333",
    "color.border.default": "#4A4A4A",
    "color.border.interactive": "#7A7A7A",
    "color.border.focus": "#FFFFFF",
    "color.text.primary": "#EDEDED",
    "color.text.secondary": "#B4B4B4",
    "color.text.muted": "#949494",
    "color.text.disabled": "#737373",
    "color.text.on-accent": "#06202B",
    "color.text.on-danger": "#2B0A0A",
    "color.text.on-warning": "#2B1F05",
    "color.text.on-success": "#062012",
    "color.accent.base": "#4CC2FF",
    "color.accent.hover": "#7AD3FF",
    "color.accent.pressed": "#2FA8E8",
    "color.accent.subtle": "#17425C",
    "color.status.danger": "#FF7A7A",
    "color.status.warning": "#FFC14D",
    "color.status.success": "#6FD08C",
    "color.focus.ring": "#FFFFFF",
    "color.focus.halo": "#0B0B0B",
    "overlay.halo": "#0B0B0B",
    "overlay.bubble.idle": "#D6DCE2",
    "overlay.bubble.hover": "#A8E4FF",
    "overlay.bubble.selected": "#4CC2FF",
    "overlay.bubble.error": "#FF7A7A",
    "overlay.fill.hover": "#4CC2FF1A",
    "overlay.fill.selected": "#4CC2FF2E",
    "overlay.fill.error": "#FF7A7A2E",
    "overlay.stroke.core-idle": "2",
    "overlay.stroke.core-hover": "2",
    "overlay.stroke.core-selected": "3",
    "overlay.stroke.core-error": "3",
    "overlay.stroke.halo": "2",
    "overlay.dim.opacity": "0.55",
    "overlay.badge.size": "18",
    "overlay.badge.gap": "4",
    "overlay.badge.leader-width": "2",
    "type.family.ui": "Segoe UI Variable Text, Segoe UI, sans-serif",
    "type.family.mono": "Consolas, Courier New, monospace",
    "type.display.size": "20",
    "type.display.line": "26",
    "type.display.weight": "600",
    "type.display.family": "ui",
    "type.title.size": "16",
    "type.title.line": "22",
    "type.title.weight": "600",
    "type.title.family": "ui",
    "type.body.size": "13",
    "type.body.line": "19",
    "type.body.weight": "400",
    "type.body.family": "ui",
    "type.body-strong.size": "13",
    "type.body-strong.line": "19",
    "type.body-strong.weight": "600",
    "type.body-strong.family": "ui",
    "type.editor.size": "15",
    "type.editor.line": "22",
    "type.editor.weight": "400",
    "type.editor.family": "ui",
    "type.caption.size": "11",
    "type.caption.line": "16",
    "type.caption.weight": "400",
    "type.caption.family": "ui",
    "type.numeric.size": "13",
    "type.numeric.line": "19",
    "type.numeric.weight": "400",
    "type.numeric.family": "mono",
    "type.numeric-lead.size": "18",
    "type.numeric-lead.line": "24",
    "type.numeric-lead.weight": "600",
    "type.numeric-lead.family": "mono",
    "space.s0": "0",
    "space.s1": "4",
    "space.s2": "8",
    "space.s3": "12",
    "space.s4": "16",
    "space.s6": "24",
    "space.s8": "32",
    "space.s12": "48",
    "radius.sm": "4",
    "radius.md": "6",
    "radius.pill": "999",
    "border-width.hairline": "1",
    "border-width.emphasis": "2",
    "elevation.e0.surface": "color.surface.base",
    "elevation.e0.border": "none",
    "elevation.e1.surface": "color.surface.raised",
    "elevation.e1.border": "color.border.subtle",
    "elevation.e2.surface": "color.surface.overlay",
    "elevation.e2.border": "color.border.default",
    "focus.width": "2",
    "focus.offset": "2",
    "focus.halo": "1",
    "motion.duration.fast": "120",
    "motion.duration.base": "180",
    "motion.duration.slow": "280",
    "motion.easing.standard": "OutCubic",
    "motion.easing.emphasized": "OutQuint",
    "motion.easing.linear": "Linear",
    "typeset.font.family": "Shantell Sans",
    "typeset.font.licence": "OFL-1.1",
    "typeset.font.version": "1.011",
    "typeset.font.regular": "ShantellSans-Regular",
    "typeset.font.italic": "ShantellSans-Italic",
    "typeset.font.bold": "ShantellSans-Bold",
    "typeset.font.bold-italic": "ShantellSans-BoldItalic",
    "typeset.align": "center",
    "typeset.line-height": "1.08",
    "typeset.size-min": "14",
    "typeset.size-max": "42",
    "typeset.size-step": "1",
    "typeset.padding-ratio": "0.12",
    "typeset.hyphenate": "false",
    "typeset.max-lines": "0",
}

HC_PALETTE_ROLE: dict[str, str] = {
    "color.surface.base": "Window",
    "color.surface.raised": "Window",
    "color.surface.sunken": "Window",
    "color.surface.overlay": "Window",
    "color.surface.hover": "Window",
    "color.surface.pressed": "Window",
    "color.surface.disabled": "Window",
    "color.surface.selected": "Highlight",
    "color.canvas.surround": "@static",
    "color.canvas.page-edge": "@static",
    "color.canvas.frame": "WindowText",
    "color.border.subtle": "WindowText",
    "color.border.default": "WindowText",
    "color.border.interactive": "WindowText",
    "color.border.focus": "WindowText",
    "color.text.primary": "WindowText",
    "color.text.secondary": "WindowText",
    "color.text.muted": "WindowText",
    "color.text.disabled": "DisabledText",
    "color.text.on-accent": "HighlightedText",
    "color.text.on-danger": "Window",
    "color.text.on-warning": "Window",
    "color.text.on-success": "Window",
    "color.accent.base": "Highlight",
    "color.accent.hover": "Highlight",
    "color.accent.pressed": "Highlight",
    "color.accent.subtle": "Highlight",
    "color.status.danger": "WindowText",
    "color.status.warning": "WindowText",
    "color.status.success": "WindowText",
    "color.focus.ring": "WindowText",
    "color.focus.halo": "Window",
    "overlay.halo": "@static",
    "overlay.bubble.idle": "@static",
    "overlay.bubble.hover": "@static",
    "overlay.bubble.selected": "@static",
    "overlay.bubble.error": "@static",
    "overlay.fill.hover": "@static",
    "overlay.fill.selected": "@static",
    "overlay.fill.error": "@static",
}

HC_OVERRIDE: dict[str, str | float] = {
    "overlay.dim.opacity": 1.0,
}
