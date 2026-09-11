#!/usr/bin/env bash
# Story phase control. The one supported way to move a story through the
# RED -> GREEN -> GATES cycle. Writes both the machine state the hooks read and
# the human-readable frontmatter in the story file, so the two cannot drift.
#
#   bash scripts/phase.sh show
#   bash scripts/phase.sh set  WORLD-014 RED [--force]
#   bash scripts/phase.sh clear
#   bash scripts/phase.sh board
#
# `set` refuses to move a story past PLANNED while any story in its
# `depends_on` is not DONE, or while the checkout is not on the story's branch.
# Both refusals can be overridden with --force, which prints what was overridden
# so that the override is visible in the transcript.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/.claude/state/current-story.env"
STORIES="$ROOT/docs/backlog/stories"
PHASES="$ROOT/.claude/harness/phases.conf"

export CLAUDE_PROJECT_DIR="$ROOT"
. "$ROOT/.claude/hooks/lib.sh"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

# Exact comparison, never a regex: `GREEN.` matched the GREEN row, was written
# into the state file, and phase_allows - finding no row for it - fell back to
# "unknown phase, do not block". The lock off, by typo.
valid_phase() {
  awk -F'|' -v p="$1" '
    /^[[:space:]]*(#|$)/ { next }
    { t = $1; gsub(/^[ \t]+|[ \t]+$/, "", t); if (t == p) { found = 1; exit } }
    END { exit !found }' "$PHASES"
}

status_for_phase() {
  case "$1" in
    PLANNED)            printf 'todo' ;;
    RED|GREEN|GATES|SCAFFOLD) printf 'in-progress' ;;
    REVIEW)             printf 'in-review' ;;
    DONE)               printf 'done' ;;
    *)                  printf 'todo' ;;
  esac
}

frontmatter() { frontmatter_value "$1" "$2"; }   # lib.sh

# awk to a temp file, not `sed -i`: the in-place flag takes no suffix on GNU
# sed and a mandatory one on BSD sed, so on macOS the old form silently did
# nothing and the frontmatter and the state file - which "cannot drift" -
# drifted. Only the frontmatter is touched: the first block between the two
# `---` lines, never a `phase:` that happens to appear in the body.
set_frontmatter() { # <file> <key> <value>
  local f="$1" tmp="$1.tmp"
  K="$2" V="$3" awk '
    BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"]; fence = 0; done = 0 }
    /^---[[:space:]]*$/ {
      fence++
      if (fence == 2 && !done) { print k ": " v; done = 1 }
      print; next
    }
    fence == 1 && !done && index($0, k ":") == 1 { print k ": " v; done = 1; next }
    { print }' "$f" > "$tmp" && mv "$tmp" "$f"
}

# story_deps <file>   The ids in depends_on, space-separated.
story_deps() { frontmatter_list "$1" depends_on; }   # lib.sh

# guard_transition <id> <file> <target-phase> <branch> <force>
# The checks that make `depends_on` and `branch` mean something. Refuse rather
# than warn: the next agent starts with an empty context and will trust
# whatever state this writes.
guard_transition() {
  local id="$1" file="$2" phase="$3" branch="$4" force="$5"
  case "$phase" in PLANNED|DONE) return 0 ;; esac

  local d dp blocked=""
  for d in $(story_deps "$file"); do
    if [ ! -f "$STORIES/$d.md" ]; then blocked="$blocked $d (no story file)"; continue; fi
    dp="$(frontmatter "$STORIES/$d.md" phase)"
    [ "$dp" = "DONE" ] || blocked="$blocked $d ($dp)"
  done
  if [ -n "$blocked" ]; then
    if [ "$force" = 1 ]; then
      printf 'warning: --force overrides unmet dependencies:%s\n' "$blocked"
    else
      die "$id depends on stories that are not DONE:$blocked
Finish them first. If starting anyway is a deliberate decision, record why in the
story's ## Notes and run:  bash scripts/phase.sh set $id $phase --force"
    fi
  fi

  local cur
  cur="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ -n "$cur" ] && [ "$cur" != "$branch" ]; then
    if [ "$force" = 1 ]; then
      printf 'warning: --force overrides branch check (on %s, story expects %s)\n' "$cur" "$branch"
    else
      die "checkout is on '$cur' but $id belongs on '$branch'.
  git checkout -b $branch        # first time
  git checkout $branch           # if it already exists
If working on '$cur' is deliberate:  bash scripts/phase.sh set $id $phase --force"
    fi
  fi
}

cmd_show() {
  if [ ! -f "$STATE" ]; then
    printf 'No active story. The phase lock is off.\n'
    return 0
  fi
  printf 'Active story\n------------\n'
  sed -e 's/^/  /' "$STATE"
  local id phase
  id=$(grep -E '^STORY_ID=' "$STATE" | cut -d= -f2-)
  phase=$(grep -E '^PHASE=' "$STATE" | cut -d= -f2-)
  printf '\nWrites allowed in %s:\n  %s\n' "$phase" \
    "$(grep -E "^[[:space:]]*$phase[[:space:]]*\|" "$PHASES" | awk -F'|' '{gsub(/^ +| +$/,"",$2); print $2}')"
  [ -f "$STORIES/$id.md" ] && printf '\nStory: docs/backlog/stories/%s.md\n' "$id"
}

cmd_board() {
  printf '%-14s %-12s %-10s %s\n' ID PHASE STATUS TITLE
  printf '%-14s %-12s %-10s %s\n' -------------- ------------ ---------- -----------------------------
  for f in "$STORIES"/*.md; do
    [ -e "$f" ] || continue
    printf '%-14s %-12s %-10s %s\n' \
      "$(frontmatter "$f" id)" "$(frontmatter "$f" phase)" \
      "$(frontmatter "$f" status)" "$(frontmatter "$f" title)"
  done
}

cmd_set() {
  local id="${1:-}" phase="${2:-}" force=0
  [ "${3:-}" = "--force" ] && force=1
  [ -n "$id" ] && [ -n "$phase" ] || die "usage: phase.sh set <story-id> <PHASE> [--force]"
  phase="$(printf '%s' "$phase" | tr 'a-z' 'A-Z')"
  valid_phase "$phase" || die "unknown phase '$phase'. Known: $(awk -F'|' '!/^#|^$/{gsub(/ /,"",$1); printf "%s ", $1}' "$PHASES")"

  local file="$STORIES/$id.md"
  [ -f "$file" ] || die "no story file at docs/backlog/stories/$id.md — create it first (scripts/new-story.sh)"

  local slug type branch
  slug="$(frontmatter "$file" slug)"
  [ -z "$slug" ] && slug="$(frontmatter "$file" title | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed -e 's/^-//' -e 's/-$//' | cut -c1-40)"
  type="$(frontmatter "$file" type)"; [ -z "$type" ] && type="feature"
  branch="$(frontmatter "$file" branch)"; [ -z "$branch" ] && branch="story/$id-$slug"

  guard_transition "$id" "$file" "$phase" "$branch" "$force"

  mkdir -p "$(dirname "$STATE")"
  cat > "$STATE" <<EOF
# Written by scripts/phase.sh — do not edit by hand.
STORY_ID=$id
STORY_SLUG=$slug
STORY_TYPE=$type
PHASE=$phase
BRANCH=$branch
UPDATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

  set_frontmatter "$file" phase "$phase"
  set_frontmatter "$file" status "$(status_for_phase "$phase")"
  set_frontmatter "$file" branch "$branch"

  printf '%s -> %s\n' "$id" "$phase"
  printf 'writes allowed: %s\n' \
    "$(grep -E "^[[:space:]]*$phase[[:space:]]*\|" "$PHASES" | awk -F'|' '{gsub(/^ +| +$/,"",$2); print $2}')"
}

cmd_clear() {
  rm -f "$STATE"
  printf 'Cleared. No active story; the phase lock is off.\n'
}

case "${1:-show}" in
  show)  cmd_show ;;
  board) cmd_board ;;
  set)   shift; cmd_set "$@" ;;
  clear) cmd_clear ;;
  *)     die "usage: phase.sh {show|board|set <id> <PHASE>|clear}" ;;
esac
