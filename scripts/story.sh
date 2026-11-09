#!/usr/bin/env bash
# Read a story by section, so the orchestrator re-sends the part a phase needs
# rather than the whole file (HARNESS-086).
#
#   bash scripts/story.sh section <id> "<name>"   the body of `## <name>`, heading excluded
#   bash scripts/story.sh sections <id>           `<name>\t<lines>` per `## ` heading, file order
#   bash scripts/story.sh frontmatter <id>        the lines between line 1 `---` and the next `---`
#
# A section is check-boundaries.sh's reading - from the heading to the line
# before the next column-0 `## ` (a later heading of the same name continues
# it rather than ending it), fences not special - through lib.sh's
# story_section, with the name matched against the WHOLE heading (trailing
# spaces trimmed). Output is the file's lines unchanged, comments included:
# strip_comments is the caller's choice.
#
# Exit: 0 printed (an empty section prints nothing and is still 0); 1 no story
# file, no such section, or no frontmatter; 2 usage or an id that is not one
# path component.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/.claude/hooks/lib.sh"

usage() {
  printf 'usage: story.sh section <id> "<name>" | sections <id> | frontmatter <id>\n' >&2
  exit 2
}

sub="${1:-}"
case "$sub" in
  section)               [ "$#" -eq 3 ] || usage ;;
  sections|frontmatter)  [ "$#" -eq 2 ] || usage ;;
  *)                     usage ;;
esac
id="$2"

valid_story_id "$id" || { printf "error: story id '%s' is not one path component: an id is letters, digits, '.', '_' or '-', and starts with a letter or digit\n" "$id" >&2; exit 2; }
rel="docs/backlog/stories/$id.md"
file="$ROOT/$rel"
[ -f "$file" ] || { printf 'no story file at %s\n' "$rel" >&2; exit 1; }

# headings [names]   `<trimmed name>\t<body line count>` per `## ` line, file
# order; with `names`, `  <trimmed name>` instead, for the absent-name message.
headings() {
  awk -v names="${1:-}" '
    function out() { if (names != "") print "  " name; else print name "\t" count }
    /^## / {
      if (n) out()
      name = substr($0, 4); sub(/[ \t]+$/, "", name); count = 0; n = 1; next
    }
    n { count++ }
    END { if (n) out() }' "$file"
}

case "$sub" in
  section)
    story_section "$file" "$3" && exit 0
    {
      printf 'no section "%s" in %s\n' "$3" "$rel"
      headings names
    } >&2
    exit 1 ;;
  sections)
    headings ;;
  frontmatter)
    awk '
      NR == 1 { if ($0 != "---") exit 1; next }
      $0 == "---" { closed = 1; exit }
      { body = body $0 "\n" }
      END { if (!closed) exit 1; printf "%s", body }' "$file" \
      || { printf 'no frontmatter in %s\n' "$rel" >&2; exit 1; } ;;
esac
