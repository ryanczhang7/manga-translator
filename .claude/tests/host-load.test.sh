#!/usr/bin/env bash
# Tests for the host-load warning (HARNESS-074): scripts/selftest.sh looks at
# the host's process listing before its first suite and says, on stderr, how
# many OTHER harness test runs share the host. It never refuses, never waits
# and never changes a byte of stdout or the exit status.
#
# THE LISTING IS INJECTED, ALWAYS. Every case below points HARNESS_PS_LISTING
# at a listing this suite wrote under its own temp directory ($W), so nothing
# here depends on what else the machine is running. _lib.sh exports it as
# /dev/null (AC-6), which is what keeps every OTHER suite's fixture runs silent;
# this suite overrides it per call, never globally.
#
# THE TWO HEADER SHAPES ARE READ OUT, NOT DERIVED (story, PO decision 3):
#   MSYS  : `UID PID PPID TTY STIME COMMAND`         (Git Bash on this host)
#   Linux : `UID PID PPID C STIME TTY TIME CMD`      (Linux and macOS)
# The MSYS rows carry the trailing space the real `ps -ef` prints.
#
# NEEDLES. Output is compared WHOLE - the full stdout of host_load_others, the
# full stderr of a fixture run - never by substring: `selftest:` is a prefix
# every line of the warning shares, and `pid 1` is a prefix of `pid 12`.
#
# THE RED SHAPE. scripts/host-load.sh does not exist in RED. The suite checks
# for it (one named assertion), sources it only if present, and lets every
# direct call fail as `command not found` (rc 127, empty output). Every case
# runs whether or not the file exists, so the executed count is the same in
# RED and GREEN.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

# --- AC-6, first half: what _lib.sh did, read BEFORE this suite touches it ----
LIB_SAW="${HARNESS_PS_LISTING-<unset>}"
LIB_CHILD_SAW="$(bash -c 'printf %s "${HARNESS_PS_LISTING-<unset>}"')"
LIB_OVERRIDES="$(HARNESS_PS_LISTING=/somewhere/else bash -c '
  . "$1"
  bash -c "printf %s \"\${HARNESS_PS_LISTING-<unset>}\""' _ "$REPO_ROOT/.claude/tests/_lib.sh")"

W="$(mktemp -d 2>/dev/null || mktemp -d -t hostload.XXXXXX)"
FIX=""
cleanup() { rm -rf "$W"; [ -n "$FIX" ] && rm -rf "$FIX"; }
trap cleanup EXIT

HL="$REPO_ROOT/scripts/host-load.sh"
TAB="$(printf '\t')"

# --- listings ----------------------------------------------------------------

# listing <msys|linux> <file>   Rows on stdin as `pid|ppid|command[|stime]`;
# writes a `ps -ef` listing of that shape, header first, rows in the given
# order. STIME defaults to 12:07:33 (MSYS) / 12:07 (Linux) when the fourth
# field is absent, so a three-field row renders exactly as it did in 074.
# HARNESS-076: a two-word MSYS STIME (`Oct 25`, `Oct  5`) is right-aligned in
# ten columns as ps.cc's ffmt `%10s` does; the one-word default keeps `%8s`
# (the width is not load-bearing - host_load_others splits on whitespace - and
# `%10s` would add two spaces to every existing row). Linux keeps `%5s`.
listing() {
  local shape="$1" out="$2" pid ppid cmd stime
  {
    if [ "$shape" = msys ]; then
      printf '     UID     PID    PPID  TTY        STIME COMMAND\n'
    else
      printf 'UID          PID    PPID  C STIME TTY          TIME CMD\n'
    fi
    while IFS='|' read -r pid ppid cmd stime; do
      [ -z "$pid" ] && continue
      if [ "$shape" = msys ]; then
        case "$stime" in
          '')    stime=12:07:33 ;;
          *' '*) stime="$(printf '%10s' "$stime")" ;;
        esac
        printf '%8s %7s %7s %-8s %8s %s \n' ryanc "$pid" "$ppid" '?' "$stime" "$cmd"
      else
        printf '%-8s %7s %7s %2s %5s %-12s %8s %s\n' ryanc "$pid" "$ppid" 0 "${stime:-12:07}" pts/0 00:00:00 "$cmd"
      fi
    done
  } > "$out"
}

# stime_on <pid> <stime>   A filter over `pid|ppid|command` rows: gives the
# row whose pid is <pid> that STIME as its fourth field. Every other row passes
# through unchanged.
stime_on() { sed -e "s/^$1|.*/&|$2/"; }

# stime_all <stime>   A filter giving every row that STIME.
stime_all() { sed -e "s/\$/|$1/"; }

# The world of AC-1/AC-2. This run is S (4003), launched by P (4002), launched
# by G (4001), launched by GG (4000). Another tree's `bash scripts/selftest.sh`
# is X (5001), its suite Y (5002). Noise rows are not test runs at all.
S=4003; P=4002; G=4001; GG=4000; X=5001; Y=5002
D1=4101; D2=4102; E1=4201; E2=4202; R=$P

base_rows() {
  cat <<EOF
3999|1|/usr/bin/bash -c source /c/Users/ryanc/.claude/shell-snapshots/snapshot.sh
$X|3999|bash scripts/selftest.sh
770|703|tee /d/manga-translator/.claude/state/gate-logs/unit.log
$Y|$X|/usr/bin/bash /d/other/.claude/tests/plan.test.sh
$S|$P|bash scripts/selftest.sh
$P|$G|bash scripts/ci-local.sh
$G|1|bash /tmp/run-selftest091.sh
3402|$S|ps -ef
EOF
}

# AC-2: D1 a suite of this run, D2 a fixture's selftest.sh under it; GG an
# ancestor whose command DOES match (P and G do not - see the handoff), so
# the ancestor exclusion is exercised by a row that would otherwise print.
ac2_rows() {
  base_rows | sed -e "s/^$G|1|/$G|$GG|/"
  cat <<EOF
$GG|1|bash /d/me/scripts/gates.sh
$D1|$S|bash .claude/tests/x.test.sh
$D2|$D1|bash scripts/selftest.sh
EOF
}

# AC-2, second half: R (= P) holds the run lock; E1 and E2 are R's descendants
# on ANOTHER branch than S - ours by the root rule, not by S's ancestry.
ac2r_rows() {
  ac2_rows
  cat <<EOF
$E1|$R|bash .claude/tests/y.test.sh
$E2|$E1|bash /tmp/fixture/scripts/gates.sh
EOF
}

base_rows | listing msys  "$W/ac1-msys"
base_rows | listing linux "$W/ac1-linux"
ac2_rows  | listing msys  "$W/ac2"
ac2r_rows | listing msys  "$W/ac2r"
# Control: D2 rewired to an unrelated parent (7777, not in the listing).
ac2_rows | sed -e "s/^$D2|$D1|/$D2|7777|/" | listing msys "$W/ac2-rewired"
# Control: S's own parent link broken, so GG is no longer an ancestor of S.
ac2_rows | sed -e "s/^$S|$P|/$S|7777|/" | listing msys "$W/ac2-orphaned"

LX="$X${TAB}bash scripts/selftest.sh"
LY="$Y${TAB}/usr/bin/bash /d/other/.claude/tests/plan.test.sh"

# --- instruments -------------------------------------------------------------

# others <self> <root> <listing>   Calls host_load_others; sets OUT and RC.
OUT=""; RC=""
others() {
  OUT="$(host_load_others "$@" 2> "$W/others.err")"; RC=$?
}

# --- the module --------------------------------------------------------------
describe "HARNESS-074  scripts/host-load.sh is a sourced file with three functions"

if [ -f "$HL" ]; then
  _ok "scripts/host-load.sh exists"
  # shellcheck disable=SC1090
  . "$HL"
else
  _bad "scripts/host-load.sh exists" "not found at $HL - every direct call below fails as 'command not found'"
fi

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-1  another tree's run and its suite are printed, pid TAB command, in listing order"

others "$S" "$S" "$W/ac1-msys"
assert_eq "MSYS shape: exactly X and Y are printed, in listing order" \
  "$LX
$LY" "$OUT"
assert_eq "MSYS shape: host_load_others returns 0" "0" "$RC"

others "$S" "$S" "$W/ac1-linux"
assert_eq "control - Linux shape (C, TTY, TIME columns filled): the identical two lines" \
  "$LX
$LY" "$OUT"
assert_eq "Linux shape: host_load_others returns 0" "0" "$RC"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-2  this run's own tree is not printed: descendants of root, ancestors of self"

others "$S" "$S" "$W/ac2"
assert_eq "D1 (suite of this run), D2 (fixture under D1), P, G and GG (ancestors) are not printed; X and Y still are" \
  "$LX
$LY" "$OUT"

others "$S" "$S" "$W/ac2-rewired"
assert_eq "control - D2 with its PPID rewired to an unrelated pid IS printed: exclusion is by ancestry, not command text" \
  "$LX
$LY
$D2${TAB}bash scripts/selftest.sh" "$OUT"

others "$S" "$S" "$W/ac2-orphaned"
assert_eq "control - with S's parent link broken, GG (bash /d/me/scripts/gates.sh) is no longer an ancestor and IS printed" \
  "$LX
$LY
$GG${TAB}bash /d/me/scripts/gates.sh" "$OUT"

others "$S" "$R" "$W/ac2r"
assert_eq "root R (an ancestor of S holding the run lock): R's other descendants E1, E2 are not printed either" \
  "$LX
$LY" "$OUT"

others "$S" "$S" "$W/ac2r"
assert_eq "control - the same listing rooted at S prints E1 and E2: it is the root that makes them ours" \
  "$LX
$LY
$E1${TAB}bash .claude/tests/y.test.sh
$E2${TAB}bash /tmp/fixture/scripts/gates.sh" "$OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-3  a test run is bash/sh running *selftest.sh, *.test.sh or *gates.sh"

cat <<'EOF' | listing msys "$W/ac3-not"
6001|1|grep -i selftest.sh
6002|1|vim scripts/selftest.sh
6003|1|bash scripts/plan.sh conflicts
6004|1|bash C:\x\run-selftest091.sh
6005|1|node vitest.test.sh
EOF
others 60000 60000 "$W/ac3-not"
assert_eq "grep, vim, plan.sh, run-selftest091.sh and node vitest.test.sh: none is printed" "" "$OUT"
assert_eq "and host_load_others still returns 0 on a listing with no test runs" "0" "$RC"

cat <<'EOF' | listing msys "$W/ac3-yes"
6101|1|bash scripts/gates.sh --gate unit
6102|1|sh scripts/selftest.sh
6103|1|/usr/bin/bash /x/.claude/tests/a.test.sh
6104|1|C:\Program Files\Git\usr\bin\bash.exe scripts/selftest.sh
EOF
others 60000 60000 "$W/ac3-yes"
assert_eq "gates.sh --gate unit, sh selftest.sh, /usr/bin/bash a.test.sh, bash.exe under C:\\Program Files: each is printed" \
  "6101${TAB}bash scripts/gates.sh --gate unit
6102${TAB}sh scripts/selftest.sh
6103${TAB}/usr/bin/bash /x/.claude/tests/a.test.sh
6104${TAB}C:\\Program Files\\Git\\usr\\bin\\bash.exe scripts/selftest.sh" "$OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-5 (unit)  a header without PID, PPID or COMMAND/CMD is refused, not guessed"

printf '     UID    PPID  TTY        STIME COMMAND\n   ryanc       1 ?        12:07:33 bash scripts/selftest.sh \n' > "$W/no-pid"
printf '     UID     PID  TTY        STIME COMMAND\n   ryanc    6201 ?        12:07:33 bash scripts/selftest.sh \n' > "$W/no-ppid"
printf '     UID     PID    PPID  TTY        STIME\n   ryanc    6201       1 ?        12:07:33\n' > "$W/no-cmd"
for h in no-pid no-ppid no-cmd; do
  others 60000 60000 "$W/$h"
  assert_eq "header $h: host_load_others returns 1" "1" "$RC"
  assert_eq "header $h: and prints nothing" "" "$OUT"
done

LRC="$(HARNESS_PS_LISTING="$W/does-not-exist" bash -c '. "$1" 2>/dev/null; host_load_listing >/dev/null 2>&1; printf %s $?' _ "$HL")"
assert_eq "host_load_listing returns 1 when HARNESS_PS_LISTING names a file that does not exist" "1" "$LRC"
LOUT="$(HARNESS_PS_LISTING="$W/ac1-msys" bash -c '. "$1" 2>/dev/null; host_load_listing 2>/dev/null' _ "$HL")"
assert_eq "host_load_listing writes the injected file's contents to stdout, unchanged" \
  "$(cat "$W/ac1-msys")" "$LOUT"

# --- the fixture -------------------------------------------------------------
# A project fixture whose .claude/tests holds two passing suites and a
# floors.conf naming both, as run-lock.test.sh's fixture_setup does. Two, so
# "exactly three lines" also says the warning is printed ONCE, not per suite.
FIX="$(make_project_fixture)"
mkdir -p "$FIX/.claude/tests" "$FIX/.claude/state"
cp "$REPO_ROOT/.claude/tests/_lib.sh" "$FIX/.claude/tests/_lib.sh"
for n in tiny tiny2; do
  cat > "$FIX/.claude/tests/$n.test.sh" <<SUITE
#!/usr/bin/env bash
. "\$(dirname "\${BASH_SOURCE[0]}")/_lib.sh"
assert_eq "$n" x x
summary "$n"
SUITE
done
printf 'floor | tiny | 1\nfloor | tiny2 | 1\n' > "$FIX/.claude/tests/floors.conf"

# selftest <listing-path>   Runs the fixture's full self-test with
# HARNESS_PS_LISTING set to that path. Sets SOUT, SERR, SRC and SECS.
SOUT=""; SERR=""; SRC=""; SECS=""
selftest() {
  local t0=$SECONDS
  ( cd "$FIX" && HARNESS_PS_LISTING="$1" bash scripts/selftest.sh ) \
    > "$W/st.out" 2> "$W/st.err" < /dev/null
  SRC=$?
  SECS=$((SECONDS - t0))
  SOUT="$(cat "$W/st.out"; printf x)"; SERR="$(cat "$W/st.err"; printf x)"
}

# Foreign runs for AC-4. Pids above Linux's pid_max (4194304) so none can be
# this fixture run's own $$ or an ancestor of it.
foreign() { # <count>
  local i=1
  printf '9100000|1|/usr/bin/bash -c something else\n'
  while [ "$i" -le "$1" ]; do
    printf '%s|9100000|bash /d/other%s/scripts/selftest.sh\n' "$((9100000 + i))" "$i"
    i=$((i+1))
  done
}
: > "$W/empty"
foreign 2 | listing msys "$W/foreign2"
foreign 7 | listing msys "$W/foreign7"

selftest "$W/empty"
E_OUT="$SOUT"; E_ERR="$SERR"; E_RC="$SRC"; E_SECS="$SECS"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-6  an empty listing prints nothing; _lib.sh exports /dev/null"

assert_eq "HARNESS_PS_LISTING is /dev/null after sourcing _lib.sh" "/dev/null" "$LIB_SAW"
assert_eq "and it is exported: a child process sees /dev/null" "/dev/null" "$LIB_CHILD_SAW"
assert_eq "and _lib.sh sets it even when the environment already named another listing" "/dev/null" "$LIB_OVERRIDES"
assert_eq "the fixture's selftest.sh with an EMPTY listing: stderr is empty" "x" "$E_ERR"
assert_eq "the empty-listing run itself passes (exit 0), so it is a fair baseline" "0" "$E_RC"
selftest /dev/null
assert_eq "the fixture's selftest.sh with the inherited /dev/null: stderr is empty" "x" "$SERR"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-4  N other runs: one header line, up to five pid lines, then 'and N more'"

selftest "$W/foreign2"
F_SECS="$SECS"
assert_eq "two foreign runs: stderr is exactly the header line and two pid lines" \
  "selftest: 2 other test run(s) are on this host; expect this run to be slower, not wrong:
selftest:   pid 9100001: bash /d/other1/scripts/selftest.sh
selftest:   pid 9100002: bash /d/other2/scripts/selftest.sh
x" "$SERR"
assert_eq "two foreign runs: exit status identical to the empty-listing run" "$E_RC" "$SRC"
assert_eq "two foreign runs: stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"

selftest "$W/foreign7"
assert_eq "seven foreign runs: the header, the first five pid lines, and 'and 2 more'" \
  "selftest: 7 other test run(s) are on this host; expect this run to be slower, not wrong:
selftest:   pid 9100001: bash /d/other1/scripts/selftest.sh
selftest:   pid 9100002: bash /d/other2/scripts/selftest.sh
selftest:   pid 9100003: bash /d/other3/scripts/selftest.sh
selftest:   pid 9100004: bash /d/other4/scripts/selftest.sh
selftest:   pid 9100005: bash /d/other5/scripts/selftest.sh
selftest:   and 2 more
x" "$SERR"
assert_eq "seven foreign runs: exit status identical to the empty-listing run" "$E_RC" "$SRC"
assert_eq "seven foreign runs: stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"

# Before the first suite: in one merged stream, the warning precedes `=== tiny ===`.
( cd "$FIX" && HARNESS_PS_LISTING="$W/foreign2" bash scripts/selftest.sh ) > "$W/merged" 2>&1 < /dev/null
FIRST="$(awk 'NF { print; exit }' "$W/merged")"
assert_eq "the warning is printed before the first suite's header" \
  "selftest: 2 other test run(s) are on this host; expect this run to be slower, not wrong:" "$FIRST"

# ===========================================================================
# HARNESS-076  a two-word STIME. ps.cc's start_time() prints `HH:MM:SS` for a
# process under 24 h old and `Mon DD` at or over it - `Oct 25`, and `Oct  5`
# (two spaces, ctime's padding) for a single-digit day: two words where the
# header has one, so every field after STIME moves right by one. Linux procps
# prints one token (`Oct20`) and nothing moves. The shapes are read out of the
# source (story ## Context), never derived. These blocks sit here, before
# 074's AC-7 deletes the fixture's host-load.sh, because AC-4 needs it.
# ===========================================================================

base_rows | stime_on "$X" 'Oct 25' | stime_on "$Y" 'Oct  5' | listing msys "$W/076-ac1"
ac2_rows | stime_on "$GG" 'Oct 25' | stime_on "$D1" 'Oct 25' | stime_on "$D2" 'Oct 25' \
  | listing msys "$W/076-ac2"
ac2_rows | stime_all 'Oct 25' | listing msys "$W/076-ac2-all"
ac2_rows | sed -e "s/^$D2|$D1|/$D2|7777|/" \
  | stime_on "$GG" 'Oct 25' | stime_on "$D1" 'Oct 25' | stime_on "$D2" 'Oct 25' \
  | listing msys "$W/076-ac2-rewired"
cat <<'EOF' | stime_all 'Oct 25' | listing msys "$W/076-ac3-not"
6001|1|grep -i selftest.sh
6002|1|vim scripts/selftest.sh
6003|1|bash scripts/plan.sh conflicts
6004|1|bash C:\x\run-selftest091.sh
6005|1|node vitest.test.sh
EOF
cat <<'EOF' | stime_all 'Oct 25' | listing msys "$W/076-ac3-yes"
6101|1|bash scripts/gates.sh --gate unit
6102|1|sh scripts/selftest.sh
6103|1|/usr/bin/bash /x/.claude/tests/a.test.sh
6104|1|C:\Program Files\Git\usr\bin\bash.exe scripts/selftest.sh
EOF
base_rows | stime_on "$X" Oct20 | stime_on "$Y" Oct20 | listing linux "$W/076-ac3-linux"
foreign 2 | stime_on 9100001 'Oct 25' | stime_on 9100002 'Oct 25' | listing msys "$W/076-foreign2"

# ---------------------------------------------------------------------------
describe "HARNESS-076  the fixture rows carry the STIME ps.cc prints, and 074's rows are unchanged"

# The helper is the instrument every case below reads through: pin what it
# wrote, so a fixture that silently stopped carrying two words cannot make a
# red case green or a green case vacuous.
assert_eq "X's row in the AC-1 listing: STIME 'Oct 25' right-aligned in ten columns, command after it" \
  "   ryanc    5001    3999 ?            Oct 25 bash scripts/selftest.sh " \
  "$(awk -v p="$X" '$2 == p' "$W/076-ac1")"
assert_eq "Y's row in the AC-1 listing: STIME 'Oct  5' (two spaces, ctime's single-digit day)" \
  "   ryanc    5002    5001 ?            Oct  5 /usr/bin/bash /d/other/.claude/tests/plan.test.sh " \
  "$(awk -v p="$Y" '$2 == p' "$W/076-ac1")"
assert_eq "S's row in the AC-1 listing keeps the one-word default 12:07:33, byte for byte as in 074" \
  "$(awk -v p="$S" '$2 == p' "$W/ac1-msys")" "$(awk -v p="$S" '$2 == p' "$W/076-ac1")"
assert_eq "Linux control: X's row carries the one-token procps STIME Oct20" \
  "ryanc       5001    3999  0 Oct20 pts/0        00:00:00 bash scripts/selftest.sh" \
  "$(awk -v p="$X" '$2 == p' "$W/076-ac3-linux")"

# ---------------------------------------------------------------------------
describe "HARNESS-076 AC-1  a run over a day old (STIME 'Oct 25' / 'Oct  5') is still printed, command from the interpreter on"

others "$S" "$S" "$W/076-ac1"
assert_eq "MSYS, X at 'Oct 25' and Y at 'Oct  5': exactly X and Y are printed, in listing order, no day number in the command" \
  "$LX
$LY" "$OUT"
assert_eq "MSYS, two-word STIME rows: host_load_others returns 0" "0" "$RC"

others "$S" "$S" "$W/ac1-msys"
assert_eq "control - the same listing with HH:MM:SS on every row: the identical two lines" \
  "$LX
$LY" "$OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-076 AC-2  a shifted row keeps its PID and PPID: this run's own tree is still not printed"

others "$S" "$S" "$W/076-ac2"
assert_eq "GG, D1 and D2 at 'Oct 25': none of them is printed; X and Y still are" \
  "$LX
$LY" "$OUT"

others "$S" "$S" "$W/076-ac2-all"
assert_eq "every row of the AC-2 world at 'Oct 25': still exactly X and Y - ancestry is unaffected by the shift" \
  "$LX
$LY" "$OUT"

others "$S" "$S" "$W/076-ac2-rewired"
assert_eq "control - D2 at 'Oct 25' with its PPID rewired to an unrelated pid IS printed, as 'bash scripts/selftest.sh' with no day number" \
  "$LX
$LY
$D2${TAB}bash scripts/selftest.sh" "$OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-076 AC-3  the shift moves where the command starts, not what counts as a test run"

others 60000 60000 "$W/076-ac3-not"
assert_eq "every row at 'Oct 25': grep, vim, plan.sh, run-selftest091.sh and node vitest.test.sh - none is printed" "" "$OUT"
assert_eq "every row at 'Oct 25', no test runs: host_load_others returns 0" "0" "$RC"

others 60000 60000 "$W/076-ac3-yes"
assert_eq "every row at 'Oct 25': gates.sh --gate unit, sh selftest.sh, /usr/bin/bash a.test.sh, bash.exe under C:\\Program Files - each printed with its full command" \
  "6101${TAB}bash scripts/gates.sh --gate unit
6102${TAB}sh scripts/selftest.sh
6103${TAB}/usr/bin/bash /x/.claude/tests/a.test.sh
6104${TAB}C:\\Program Files\\Git\\usr\\bin\\bash.exe scripts/selftest.sh" "$OUT"

others "$S" "$S" "$W/076-ac3-linux"
assert_eq "control - Linux listing with the one-token STIME Oct20 on X and Y: the two AC-1 lines, no shift applied" \
  "$LX
$LY" "$OUT"

# Contract: STIME is optional in the header. A header without it is parsed as
# 074 parses it - not refused, and the command still read from COMMAND.
printf '     UID     PID    PPID  TTY COMMAND\n   ryanc    5001    3999 ?   bash scripts/selftest.sh \n' > "$W/076-no-stime"
others "$S" "$S" "$W/076-no-stime"
assert_eq "a header with no STIME column is not refused: X is printed and host_load_others returns 0" \
  "$LX rc=0" "$OUT rc=$RC"

# ---------------------------------------------------------------------------
describe "HARNESS-076 AC-4  selftest.sh warns about two foreign runs over a day old, exactly as about fresh ones"

selftest "$W/076-foreign2"
assert_eq "two foreign runs at 'Oct 25': stderr is exactly the header line and two pid lines, each command from the interpreter on" \
  "selftest: 2 other test run(s) are on this host; expect this run to be slower, not wrong:
selftest:   pid 9100001: bash /d/other1/scripts/selftest.sh
selftest:   pid 9100002: bash /d/other2/scripts/selftest.sh
x" "$SERR"
assert_eq "two foreign runs at 'Oct 25': exit status identical to the empty-listing run" "$E_RC" "$SRC"
assert_eq "two foreign runs at 'Oct 25': stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-5  a listing that cannot be read or parsed says so, in one line"

CANNOT="selftest: cannot list this host's processes; other test runs, if any, were not noticed.
x"
selftest "$W/does-not-exist"
assert_eq "HARNESS_PS_LISTING names a missing file: stderr is exactly the 'cannot list' line" "$CANNOT" "$SERR"
assert_eq "missing file: exit status unchanged" "$E_RC" "$SRC"
assert_eq "missing file: stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"
for h in no-pid no-ppid no-cmd; do
  selftest "$W/$h"
  assert_eq "header $h: stderr is exactly the 'cannot list' line" "$CANNOT" "$SERR"
  assert_eq "header $h: stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"
done

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-7  the warning path never waits; a missing host-load.sh is said, not fatal"

assert_eq "a run with two foreign runs finishes within the empty-listing run's time plus 5 s (empty ${E_SECS}s, two foreign ${F_SECS}s)" \
  "yes" "$([ "$F_SECS" -le $((E_SECS + 5)) ] && printf yes || printf no)"

# The static half: no sleep, read or wait at a command position in host-load.sh,
# comments stripped. Absent file is reported as such, never as a pass.
if [ -f "$HL" ]; then
  WAITS="$(awk '{ sub(/(^|[[:space:]])#.*$/, "") }
    /(^|[;&|({]|then|do|else)[[:space:]]*(sleep|read|wait)([[:space:]]|;|$)/ { print FILENAME ":" FNR ": " $0 }' "$HL")"
else
  WAITS="scripts/host-load.sh is absent"
fi
assert_eq "scripts/host-load.sh contains no sleep, read or wait" "" "$WAITS"

rm -f "$FIX/scripts/host-load.sh"
selftest "$W/foreign2"
assert_eq "host-load.sh deleted: stderr is exactly the 'is missing' line, even with foreign runs listed" \
  "selftest: scripts/host-load.sh is missing; other test runs on this host were not checked.
x" "$SERR"
assert_eq "host-load.sh deleted: the run proceeds, exit status unchanged" "$E_RC" "$SRC"
assert_eq "host-load.sh deleted: stdout byte-identical to the empty-listing run" "$E_OUT" "$SOUT"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-8  continuation rows of a multi-line command (PID or PPID not all digits) are never reported"

# Git Bash's `ps -ef` prints each later line of a multi-line command as a raw
# row of its own, so field 2 and field 3 - PID and PPID by the header - are
# whatever words that line happens to hold. The two shapes AC-8 names, plus
# one row with only PPID junk and one with only PID junk: the guard is on
# EITHER field. Appended raw, after X, exactly as `ps -ef` prints them.
printf '%s|3999|bash scripts/selftest.sh\n%s|%s|bash scripts/selftest.sh\n' "$X" "$S" "$P" \
  | listing msys "$W/ac8"
cat >> "$W/ac8" <<'EOF'
# a b c d bash scripts/selftest.sh
cd /d/a && git -C /d/b/c status && bash scripts/selftest.sh
# 7005 b c d bash scripts/selftest.sh
# a 7006 c d bash scripts/selftest.sh
EOF
others "$S" "$S" "$W/ac8"
assert_eq "MSYS listing with X and four continuation rows: exactly X's one line is printed" "$LX" "$OUT"
assert_eq "continuation rows: host_load_others still returns 0" "0" "$RC"

# Control: the SAME raw rows with only fields 2 and 3 made numeric. Every other
# word is where it was, so what prints is decided by the PID/PPID shape alone.
printf '%s|3999|bash scripts/selftest.sh\n%s|%s|bash scripts/selftest.sh\n' "$X" "$S" "$P" \
  | listing msys "$W/ac8-numeric"
cat >> "$W/ac8-numeric" <<'EOF'
# 7001 7002 c d bash scripts/selftest.sh
cd 7003 7004 git -C /d/b/c status && bash scripts/selftest.sh
EOF
others "$S" "$S" "$W/ac8-numeric"
assert_eq "control - the same command texts on rows with numeric PID and PPID ARE printed" \
  "$LX
7001${TAB}bash scripts/selftest.sh
7003${TAB}/d/b/c status && bash scripts/selftest.sh" "$OUT"

# ---------------------------------------------------------------------------
describe "HARNESS-074 AC-9  with HARNESS_PS_LISTING empty, the listing comes from 'ps -ef' on PATH, and no ps says 'cannot list'"

# A stub `ps` that answers `-ef` with a one-foreign-run listing and refuses
# any other arguments, so a branch that stops calling `ps -ef` is noticed.
foreign 1 | listing msys "$W/foreign1"
mkdir -p "$W/stub-ps"
cat > "$W/stub-ps/ps" <<STUB
#!/bin/sh
[ "\$*" = "-ef" ] || { echo "stub ps: expected -ef, got: \$*" >&2; exit 2; }
cat "$W/foreign1"
STUB
chmod +x "$W/stub-ps/ps"

WARN_OUT="$(HARNESS_PS_LISTING= PATH="$W/stub-ps:$PATH" \
  bash -c '. "$1"; host_load_warn "$2" "$2"; printf "rc=%s" $?' _ "$HL" "$S" 2>/dev/null)"
assert_eq "stub ps first on PATH, one foreign run: the AC-4 header line and that run's pid line, rc 0" \
  "selftest: 1 other test run(s) are on this host; expect this run to be slower, not wrong:
selftest:   pid 9100001: bash /d/other1/scripts/selftest.sh
rc=0" "$WARN_OUT"

# No ps reachable. On Git Bash awk and ps share /usr/bin, so PATH cannot just
# drop a directory: it is set to ONE directory holding an `awk` wrapper that
# execs the real awk by absolute path, and nothing else. awk is the only
# external tool host_load_warn needs when HARNESS_PS_LISTING is empty
# (`command`, `printf`, `local`, `set` are builtins) - and it must be there,
# or host_load_others would fail on its own and say "cannot list" for the
# wrong reason. The wrapper is #!/bin/sh with an absolute exec, so it runs
# with PATH holding no system directory at all.
AWK_BIN="$(command -v awk)"
mkdir -p "$W/no-ps"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$AWK_BIN" > "$W/no-ps/awk"
chmod +x "$W/no-ps/awk"

NOPS="$(HARNESS_PS_LISTING= bash -c '. "$1"; PATH="$2"
  if command -v ps >/dev/null 2>&1; then printf "ps=%s " "$(command -v ps)"; else printf "ps=none "; fi
  if printf "a\n" | awk "{print \"awk=ok\"}" 2>/dev/null; then :; else printf "awk=broken"; fi' _ "$HL" "$W/no-ps")"
assert_eq "precondition - under the no-ps PATH, ps is not found and awk still runs" "ps=none awk=ok" "$NOPS"

WARN_OUT="$(HARNESS_PS_LISTING= bash -c '. "$1"; PATH="$3"; host_load_warn "$2" "$2"; printf "rc=%s" $?' \
  _ "$HL" "$S" "$W/no-ps" 2>/dev/null)"
assert_eq "no ps on PATH: exactly the AC-5 'cannot list' line, rc 0" \
  "selftest: cannot list this host's processes; other test runs, if any, were not noticed.
rc=0" "$WARN_OUT"

summary "host-load"
