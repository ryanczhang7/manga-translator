"""`ChapterSummary`: what a run would read from a folder of pages (MT-057).

`components.md` §2's populated state, which replaces the drop target once a
folder with no project has been read: the folder's name, its page count, its
first and last page, and - when the filenames sort differently as numbers and
as text - a notice listing both orders and saying which one the run uses.

The widget is a view of a `Chapter` and reads nothing from disk: the order it
shows is `chapter.pages`, which `read_chapter` built in `order_filenames`
order, so the summary cannot disagree with the run about which page is first.
There is no second listing and no second natural sort here. The *text* order
the notice contrasts it with is plain code-point `sorted()`, which is what
"sort as text" means to the user looking at a file list.

A part the design says is absent for this chapter (the first/last lines of a
one-page chapter, the notice when the orders agree) is never created, so
nothing can show it by accident and an accessibility tree never finds a hidden
line.

Every label is plain text (a folder named `a<b>c` is not markup), selectable
with the mouse so a filename can be copied, and never a focus stop: the scroll
area is the one stop for reading, and the button below it - outside the scroll
area, so it never scrolls away - is the one way out. A `QPushButton` outside a
dialog does not activate on Return or Enter, only on Space, so the button
handles those two itself, as `FolderDropTarget` does.

Spacing and type come from the design tokens (`tokens_gen`). Text colour and
ground are left to the application palette: `theme.qss` is not applied by the
app yet, and a token text colour painted over an unthemed ground could be
unreadable. The notice's warning border is the one colour set here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mangatl.domain.page import Chapter
from mangatl.ui import tokens_gen
from mangatl.ui.intake import display_name

__all__ = ["ChapterSummary"]

SUMMARY_OBJECT_NAME = "chapter-summary"
SCROLL_ACCESSIBLE_NAME = "Chapter summary"
CHOOSE_OTHER = "Choose a different folder"  # components.md §2, "Leaving the summary"
ORDER_LEAD = "These filenames sort differently as numbers and as text. The run uses natural order."
NATURAL_PREFIX = "Natural order (used): "
LEXICAL_PREFIX = "Text order (not used): "

_ACTIVATION_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class ChapterSummary(QWidget):
    """The chapter a folder of pages would become, before anything is run."""

    #: The user asked to choose a different folder; the owner asks the chooser.
    choose_other = Signal()

    def __init__(self, chapter: Chapter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(SUMMARY_OBJECT_NAME)
        self.setAcceptDrops(False)  # PO-9: the button is the way out, not a drop

        natural = [page.filename for page in chapter.pages]
        lexical = sorted(natural)
        uncut_name = chapter.source_dir.name or str(chapter.source_dir)

        # Created first, so it is the first focus stop: Tab order is scroll
        # area, then button (Design notes, "Accessibility").
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("summary-scroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scroll_area.setAccessibleName(SCROLL_ACCESSIBLE_NAME)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        heading = _label("summary-name", display_name(chapter.source_dir), _TITLE)
        heading.setAccessibleName(uncut_name)
        column.addWidget(heading)
        column.addSpacing(tokens_gen.SPACE_S2)
        lines = [uncut_name]

        count = len(natural)
        parts = [("summary-count", "1 page" if count == 1 else f"{count} pages")]
        if count == 1:
            parts.append(("summary-only", f"Only page: {natural[0]}"))
        else:
            parts.append(("summary-first", f"First page: {natural[0]}"))
            parts.append(("summary-last", f"Last page: {natural[-1]}"))
        for index, (name, text) in enumerate(parts):
            if index:
                column.addSpacing(tokens_gen.SPACE_S1)
            column.addWidget(_label(name, text, _BODY))
            lines.append(text)

        if lexical != natural:
            notice_lines = (
                ORDER_LEAD,
                NATURAL_PREFIX + ", ".join(natural),
                LEXICAL_PREFIX + ", ".join(lexical),
            )
            column.addSpacing(tokens_gen.SPACE_S4)
            column.addWidget(_order_notice(notice_lines))
            lines.extend(notice_lines)
        column.addStretch(1)

        self.scroll_area.setWidget(content)
        self.scroll_area.setAccessibleDescription("\n".join(lines))

        self.choose = _ActivatedByEnter(CHOOSE_OTHER, self)
        self.choose.setObjectName("summary-choose")
        self.choose.clicked.connect(self.choose_other.emit)

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.addWidget(self.scroll_area, 1)
        layout.addSpacing(tokens_gen.SPACE_S4)
        layout.addWidget(self.choose, 0, Qt.AlignmentFlag.AlignLeft)


class _ActivatedByEnter(QPushButton):
    """A push button that Return and Enter activate as Space does: outside a
    dialog, a `QPushButton` ignores both (measured in MT-057 RED)."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _ACTIVATION_KEYS and not event.isAutoRepeat():
            self.click()
            return
        super().keyPressEvent(event)


def _font(size: int, weight: int) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    return font


_TITLE = (tokens_gen.TYPE_TITLE_SIZE, tokens_gen.TYPE_TITLE_WEIGHT)
_BODY = (tokens_gen.TYPE_BODY_SIZE, tokens_gen.TYPE_BODY_WEIGHT)
_BODY_STRONG = (tokens_gen.TYPE_BODY_STRONG_SIZE, tokens_gen.TYPE_BODY_STRONG_WEIGHT)


def _label(name: str, text: str, type_: tuple[int, int]) -> QLabel:
    """A plain, word-wrapped label: selectable with the mouse, never focused."""
    label = QLabel()
    label.setObjectName(name)
    # Before the text, so it is never interpreted as rich text.
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    label.setFont(_font(*type_))
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    # After the flags: mouse selection alone makes a QLabel a click-focus stop.
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label


def _order_notice(lines: tuple[str, str, str]) -> QFrame:
    """AC-4's notice: both orders in full and which one the run uses. No
    control - the run always uses natural order (PO-5)."""
    notice = QFrame()
    notice.setObjectName("summary-order-notice")
    notice.setAccessibleName("\n".join(lines))
    notice.setStyleSheet(
        f"QFrame#summary-order-notice {{"
        f" border: {tokens_gen.BORDER_WIDTH_HAIRLINE}px solid {tokens_gen.COLOR_STATUS_WARNING};"
        f" border-radius: {tokens_gen.RADIUS_SM}px; }}"
    )
    column = QVBoxLayout(notice)
    pad = tokens_gen.SPACE_S3
    column.setContentsMargins(pad, pad, pad, pad)
    column.setSpacing(tokens_gen.SPACE_S1)
    lead, natural, lexical = lines
    column.addWidget(_label("order-lead", lead, _BODY_STRONG))
    column.addWidget(_label("order-natural", natural, _BODY))
    column.addWidget(_label("order-lexical", lexical, _BODY))
    return notice
