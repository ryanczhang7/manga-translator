"""The About text: credits and licence notices the shipped app owes (MT-020 AC-8).

`typeset-font.md` §5 duty 2: the lettering font's copyright, licence and designer
credit are reproduced in the app. This is the text; no About screen exists yet
(MT-020 PO-5), and MT-024 carries the installer's notices.
"""

from __future__ import annotations

from mangatl.typeset.font import FONT_FAMILY, FONT_VERSION, OFL_FILENAME

ABOUT_TEXT: str = (
    "Lettering font\n"
    f"{FONT_FAMILY} {FONT_VERSION}, by Stephen Nixon / Arrow Type, with concept and "
    "creative direction by Shantell Martin.\n"
    "Copyright 2022 The Shantell Sans Project Authors "
    "(https://github.com/arrowtype/shantell-sans).\n"
    "Licensed under the SIL Open Font License 1.1; the full licence ships beside "
    f"the font files as {OFL_FILENAME}.\n"
)
