"""Generate `packaging/notices/THIRD_PARTY_NOTICES.txt` from the manifest and notices.json.

MT-076 Contract blocks 1 and 2, discharging `architecture.md` D13's
obligations O-1 to O-5. Run from the repository root after changing
`packaging/models.json`, `packaging/notices/notices.json` or the About text:

    uv run python packaging/build_notices.py           # rewrite the file
    uv run python packaging/build_notices.py --check   # 1 when it is stale

The file is committed (MT-076 PO-4) and this script is its only writer; a
`tests/core` equality test holds the two together. Every manifest entry must
have exactly one notices.json entry and the other way round (O-5): when they
drift, nothing is rendered and nothing is written, and each problem is named on
stderr.

The manifest parser is `mangatl.models.manifest`'s and the font notice is
`mangatl.about.ABOUT_TEXT`; nothing else here comes from `mangatl`. An
engineer's reading of the licences, not legal advice (D13).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mangatl.about import ABOUT_TEXT
from mangatl.models.manifest import ModelEntry, load_manifest

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "models.json"
NOTICES = HERE / "notices" / "notices.json"
OUTPUT = HERE / "notices" / "THIRD_PARTY_NOTICES.txt"

_LABEL_WIDTH = len("Corresponding source: ")
_STALE = "THIRD_PARTY_NOTICES.txt is stale; run: uv run python packaging/build_notices.py"
_HEADER = (
    "THIRD-PARTY NOTICES for mangatl\n"
    "\n"
    "This application bundles the model weights and the font listed below. Each is\n"
    "conveyed under its own licence; the full licence texts named here ship beside\n"
    "this file. This file was generated from packaging/models.json and\n"
    "packaging/notices/notices.json by packaging/build_notices.py, and it is an\n"
    "engineer's reading of the licences, not legal advice (architecture.md D13).\n"
)


@dataclass(frozen=True)
class Notice:
    """What a model's notice adds to its manifest entry (Contract block 1)."""

    name: str
    upstream: str
    corresponding_source: str
    training_data: str
    licence_text: str


class NoticeDrift(Exception):
    """The manifest and notices.json disagree; the message is the drift lines, one per line."""


def load_notices(path: Path) -> tuple[Notice, ...]:
    """The entries of `path`'s `notices` array, in file order."""
    raw = json.loads(path.read_text(encoding="utf-8"))["notices"]
    return tuple(Notice(**entry) for entry in raw)


def drift(manifest_names: Sequence[str], notice_names: Sequence[str]) -> list[str]:
    """One line per disagreement: manifest names with no notice (manifest
    order), then notice names with no manifest entry and notice names listed
    twice (notices order). `[]` when the two agree."""
    in_manifest = set(manifest_names)
    counts = Counter(notice_names)
    lines = [
        f"manifest entry {name!r} has no entry in notices.json"
        for name in manifest_names
        if name not in counts
    ]
    seen: set[str] = set()
    for name in notice_names:
        if name in seen:
            continue
        seen.add(name)
        if name not in in_manifest:
            lines.append(f"notices.json entry {name!r} is not in the manifest")
        elif counts[name] > 1:
            lines.append(f"notices.json names {name!r} twice")
    return lines


def _line(label: str, value: str) -> str:
    return f"{label:<{_LABEL_WIDTH}}{value}"


def render(entries: Sequence[ModelEntry], notices: Sequence[Notice], about_text: str) -> str:
    """Block 2's text: the header, one block per manifest entry in manifest
    order, then the font's About text verbatim. Raises `NoticeDrift` rather
    than render a file that omits a model."""
    problems = drift([entry.name for entry in entries], [notice.name for notice in notices])
    if problems:
        raise NoticeDrift("\n".join(problems))
    by_name = {notice.name: notice for notice in notices}
    parts = [_HEADER]
    for entry in entries:
        notice = by_name[entry.name]
        lines = [
            f"== {entry.name} ({entry.role}) ==",
            _line("File:", f"models/{entry.path}"),
            _line("Source:", f"https://huggingface.co/{entry.repo} at revision {entry.revision}"),
            _line("SHA-256:", entry.sha256),
            _line("Licence:", entry.licence),
            _line("Licence text:", notice.licence_text),
            _line("Upstream:", notice.upstream),
        ]
        if notice.corresponding_source:
            lines.append(_line("Corresponding source:", notice.corresponding_source))
        if notice.training_data:
            lines.append(_line("Training data:", notice.training_data))
        parts.append("\n".join(lines) + "\n")
    parts.append("== Lettering font ==\n" + about_text)
    return "\n".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the rendering to `OUTPUT`, or with `--check` compare against it.
    0 on success; 1 when the file is stale or the inputs drift, with the reason
    on stderr. `MANIFEST`, `NOTICES` and `OUTPUT` are read here, at call time
    (Contract block 1, A-1)."""
    parser = argparse.ArgumentParser(description="Generate THIRD_PARTY_NOTICES.txt.")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    arguments = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        text = render(load_manifest(MANIFEST), load_notices(NOTICES), ABOUT_TEXT)
    except NoticeDrift as error:
        for line in str(error).splitlines():
            print(f"build_notices: {line}", file=sys.stderr)
        return 1
    data = text.encode("utf-8")
    if arguments.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != data:
            print(_STALE, file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_bytes(data)
    print(f"build_notices: wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
