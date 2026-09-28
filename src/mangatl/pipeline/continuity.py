"""What a page's request carries from the pages before it (MT-014 C-8).

**In `pipeline` and not `translate`, and that is forced**: the caller is
`TranslateStage`, which may not import `mangatl.translate` at all under the
*"Only translate imports anthropic"* contract (MT-011 C-1). `pipeline` may
import `store` and `domain`, which is all this needs.

Page 1 - ordinal 0 - gets `EMPTY_CONTEXT` without reading the store, whatever
the glossary holds (AC-5): a chapter re-run from the top has a glossary already,
and page 1 still sends MT-011's request. Every later page gets the whole
glossary rendered under `MAX_GLOSSARY_TOKENS` and the previous page's
**proposed** English - not the user's `final_en`, which reaches the next page
through the glossary (AC-2) - under `MAX_ROLLING_TOKENS`.
"""

from __future__ import annotations

from mangatl.domain.glossary import (
    EMPTY_CONTEXT,
    MAX_GLOSSARY_TOKENS,
    MAX_ROLLING_TOKENS,
    PromptContext,
    render_block,
    render_rolling,
)
from mangatl.store.glossary import read_entries
from mangatl.store.project import Project

__all__ = ["build_prompt_context"]


def build_prompt_context(project: Project, ordinal: int) -> PromptContext:
    """The glossary and rolling blocks for page `ordinal`'s request.

    Untranslated regions of the previous page (`None`) are left out; a region
    proposed as `""` is kept as an empty line, so the model reads the page's
    lines in their real count (PO-7).
    """
    if ordinal == 0:
        return EMPTY_CONTEXT
    return PromptContext(
        render_block(read_entries(project), MAX_GLOSSARY_TOKENS),
        render_rolling(
            [line for line in project.read_proposed(ordinal - 1) if line is not None],
            MAX_ROLLING_TOKENS,
        ),
    )
