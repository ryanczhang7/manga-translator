"""MT-020 AC-8: the About text credits the font as OFL 1.1 requires.

`typeset-font.md` §5 duty 2: the copyright and licence notice, with the designer
credit. PO-5: "the About text" is the constant `mangatl.about.ABOUT_TEXT`; no
About screen exists, and showing it is out of scope.
"""

from __future__ import annotations

import pytest

from mangatl.about import ABOUT_TEXT


@pytest.mark.parametrize(
    "needle",
    [
        "Shantell Sans",
        "1.011",
        "Stephen Nixon",
        "Arrow Type",
        "Shantell Martin",
        "SIL Open Font License 1.1",
    ],
)
def test_the_about_text_names_the_font_its_designers_and_its_licence(needle: str) -> None:
    assert needle in ABOUT_TEXT
