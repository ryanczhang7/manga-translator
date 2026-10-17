"""MT-020 AC-8: the About text credits the font as OFL 1.1 requires.

`typeset-font.md` §5 duty 2: the copyright and licence notice, with the designer
credit. PO-5: "the About text" is the constant `mangatl.about.ABOUT_TEXT`; no
About screen exists, and showing it is out of scope.

MT-076 AC-7 adds a seventh needle: the line that names where the installer's
third-party notices and licence texts ship. MT-020's six are untouched.
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
        # MT-076 AC-7: the one licence surface the app has points at the rest.
        "Third-party notices and licence texts ship with the application under notices/"
        " (THIRD_PARTY_NOTICES.txt, GPL-3.0.txt, Apache-2.0.txt).",
    ],
)
def test_the_about_text_names_the_font_its_designers_and_its_licence(needle: str) -> None:
    assert needle in ABOUT_TEXT


def test_the_notices_line_is_a_whole_line_and_the_last_one() -> None:
    """MT-076 AC-7 and Contract block 3: the line, not a fragment of one, and
    appended last so MT-020's text above it is untouched."""
    line = (
        "Third-party notices and licence texts ship with the application under notices/"
        " (THIRD_PARTY_NOTICES.txt, GPL-3.0.txt, Apache-2.0.txt)."
    )

    assert ABOUT_TEXT.endswith("\n" + line + "\n")
