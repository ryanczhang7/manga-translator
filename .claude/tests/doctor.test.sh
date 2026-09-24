#!/usr/bin/env bash
# Tests for scripts/doctor.sh - specifically the discovery checks, which are
# the answer to a gate whose scope collapsed to nothing without anyone noticing.

. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

FIX="$(make_project_fixture)"
trap 'rm -rf "$FIX"' EXIT

doctor() { ( cd "$FIX" && bash scripts/doctor.sh 2>&1 ); }

describe "discovery: the runner is asked what it can see"

write_conf "$FIX" <<'EOF'
gate      | unit     | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit     | Tests +[1-9][0-9]* passed
discovery | platform | . | printf 'src/platform/gl.test.ts\n' | grep -q "src/platform/"
EOF
out="$(doctor)"
assert_contains "a directory the runner can see" "ok       platform     discovered" "$out"

write_conf "$FIX" <<'EOF'
gate      | unit     | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit     | Tests +[1-9][0-9]* passed
discovery | platform | . | printf 'src/ui/app.test.ts\n' | grep -q "src/platform/"
EOF
out="$(doctor)"
assert_contains "a directory it cannot" "MISSING  platform" "$out"
assert_contains "says what that costs"  "committed and never run" "$out"

describe "discovery: nothing declared is reported, not skipped silently"

write_conf "$FIX" <<'EOF'
gate     | unit | required | . | printf 'Tests  1 passed (1)\n'
evidence | unit | Tests +[1-9][0-9]* passed
EOF
out="$(doctor)"
assert_contains "the section still appears" "none declared" "$out"


describe "the harness says which version it is"

# A vendored copy cannot be dated from the outside: it has the consuming
# project's git history, not this one's. Two field reports in a row arrived
# reporting defects that had been fixed upstream for weeks, and neither could
# say which harness it had measured - so every finding had to be re-verified by
# hand before it could be called already-fixed. The stamp is what makes
# "already fixed in 2026-09-11" a comparison instead of an afternoon.
out="$(doctor)"
assert_contains "doctor prints the harness version" "harness ver" "$out"
assert_contains "and it is the one in the file" \
  "$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$REPO_ROOT/.claude/harness/VERSION" | head -1)" "$out"

# Absent, it says so rather than printing an empty field. A blank where a
# version should be reads as "no version", which is the one thing it must not
# be confused with - an unstamped copy is an OLD copy, from before stamping.
mv "$FIX/.claude/harness/VERSION" "$FIX/.claude/harness/VERSION.hidden" 2>/dev/null
out="$(doctor)"
assert_contains "an unstamped copy is named as one" "unstamped" "$out"
mv "$FIX/.claude/harness/VERSION.hidden" "$FIX/.claude/harness/VERSION" 2>/dev/null

# ============================================================================
# MT-040: doctor.sh and task.sh parse the manifest without a process per field
# ============================================================================
#
# gates.test.sh holds AC-1, AC-2 and gates.sh's half of AC-3/AC-4. This half is
# the other two scripts: doctor.sh splits `discovery` lines at -f4- (the
# manifest's worst case, project.conf:596, three pipes inside the value) and
# task.sh splits `task` lines at -f5-. Neither script had a test of that, and
# task.sh had no test at all.

_mt040="$(mktemp -d 2>/dev/null || mktemp -d -t mt040)"
trap 'rm -rf "$FIX" "$_mt040"' EXIT

# A stand-in for `uv` that runs nothing and says what it was asked to run, so
# the REAL manifest's task and discovery lines can be driven end to end on a
# machine with no stack: the output is the command line the script built.
mkdir -p "$FIX/.mt040bin"
cat > "$FIX/.mt040bin/uv" <<'STUB'
#!/usr/bin/env bash
printf 'uv'; for a in "$@"; do printf ' %s' "$a"; done; printf '\n'
STUB
chmod +x "$FIX/.mt040bin/uv"
task() { ( cd "$FIX" && PATH="$FIX/.mt040bin:$PATH" bash scripts/task.sh "$@" 2>&1 ); }
doctor_stubbed() { ( cd "$FIX" && PATH="$FIX/.mt040bin:$PATH" bash scripts/doctor.sh 2>&1 ); }

describe "MT-040 AC-3: doctor.sh keeps a discovery command whole (-f4-)"

# Two lines shaped like project.conf:596, three pipes inside the value each.
# `providers` succeeds only if the WHOLE command reaches eval: cut at any of its
# pipes it is an unterminated quote. `absent` fails whole, and its MISSING line
# quotes the command - cut at its first pipe it would be a bare `printf`, which
# succeeds and is reported as discovered.
write_conf "$FIX" <<'CONF'
gate      | unit      | required | . | printf 'Tests  1 passed (1)\n'
evidence  | unit      | Tests +[1-9][0-9]* passed
discovery | providers | . | [ -n "$(printf 'CPU\n' | grep -E "CUDA|Dml|CPU")" ]
discovery | absent    | . | printf 'x\n' | grep -qE "CUDA|Dml|CPU"
CONF
out="$(doctor)"
assert_contains "a discovery command with three embedded pipes runs whole" \
  "ok       providers    discovered" "$out"
assert_contains "and a failing one is quoted whole, pipes intact" \
  "MISSING  absent       nothing discovered by: printf 'x\n' | grep -qE \"CUDA|Dml|CPU\"" "$out"
assert_not_contains "and is not reported as discovered" "ok       absent" "$out"

describe "MT-040 AC-3 / AC-6: doctor.sh over the 629-line manifest"

# The real manifest, `uv` stubbed: every discovery command reaches eval, the
# stub prints its arguments, and each grep then decides. The section from
# `Test discovery` to the end is compared byte-for-byte with what the unchanged
# doctor.sh printed for the same manifest and stub (76ed934; see the story's
# handoff). Only that section: the lines above it carry `command -v` paths,
# which are this machine's, not the parser's.
cp "$MANIFEST_SNAPSHOT" "$FIX/.claude/harness/project.conf"
doctor_stubbed | awk '/^Test discovery$/ { on = 1 } on' > "$_mt040/doctor.out"
if cmp -s "$MANIFEST_FIXTURES/doctor-discovery.golden" "$_mt040/doctor.out"; then
  _ok "AC-6: doctor.sh's discovery report over the manifest is byte-identical to the pre-MT-040 one"
else
  _bad "AC-6: doctor.sh's discovery report over the manifest is byte-identical to the pre-MT-040 one" \
    "$(diff "$MANIFEST_FIXTURES/doctor-discovery.golden" "$_mt040/doctor.out" | head -20)"
fi
assert_contains "AC-3: the providers discovery keeps all three inner pipes (project.conf:596, -f4-)" \
  'nothing discovered by: uv run python -c "import onnxruntime as o; print(o.get_available_providers())" | grep -qE "CUDA|Dml|CPU"' \
  "$(cat "$_mt040/doctor.out")"

describe "MT-040 C-3 / AC-6: task.sh dev, test and install run the same commands"

# No arguments lists the tasks; this path is awk, not the parse loop, and is
# pinned so the rewrite leaves it alone.
out="$(task)"; rc=$?
assert_eq "task.sh with no arguments lists the manifest's tasks, unchanged" \
  "Available tasks:
  install    uv sync --all-extras
  dev        uv run python -m mangatl.app
  test       uv run pytest -q tests/core tests/ui" "$out"
assert_eq "and exits 0" "0" "$rc"

out="$(task dev)"; rc=$?
assert_eq "task.sh dev runs the manifest's dev command" "uv run python -m mangatl.app" "$out"
assert_eq "and exits with its status" "0" "$rc"
assert_eq "task.sh test runs the manifest's test command" \
  "uv run pytest -q tests/core tests/ui" "$(task test)"
assert_eq "task.sh install runs the manifest's install command" \
  "uv sync --all-extras" "$(task install)"
assert_eq "extra arguments are appended to the command" \
  "uv run pytest -q tests/core tests/ui -k smoke" "$(task test -k smoke)"

describe "MT-040 AC-3: task.sh keeps a task command whole (-f5-)"

TABC="$(printf '\t')"
write_conf "$FIX" <<CONF
${TABC}# task | pipes | - | . | printf 'a commented-out line was run\n'
task | pipes | - | .   | printf 'CUDA|Dml|CPU\n' | grep -E "Dml|CPU"
task | where | - | sub | printf '%s\n' "\${PWD##*/}"
task | args  | - | .   | printf '%s,'
task | empty | - | .   |
CONF
mkdir -p "$FIX/sub"
out="$(task pipes)"; rc=$?
assert_eq "a task command with embedded pipes runs whole" "CUDA|Dml|CPU" "$out"
assert_eq "and exits 0" "0" "$rc"
assert_eq "a task runs in its own cwd (field 4)" "sub" "$(task where)"
assert_eq "arguments are passed through to the command" "a,b," "$(task args a b)"
out="$(task empty)"; rc=$?
assert_eq "an unconfigured task says so" "task 'empty' is not configured in project.conf" "$out"
assert_eq "and exits 1" "1" "$rc"
out="$(task nope)"; rc=$?
assert_eq "an unknown task says so" "no such task: nope" "$out"
assert_eq "and exits 1 too" "1" "$rc"

# task.sh never strips `\r` itself; trim()'s [:space:] is what keeps a CRLF
# manifest's carriage return out of the command. A trim that knew only spaces
# and tabs would hand printf `done\r` - which bash on Linux prints and MSYS bash
# on Windows silently parses as whitespace, so that case only discriminates on
# Linux. The empty-command case discriminates everywhere: the command field of
# `task | crlfempty | - | . |<CR>` is the carriage return alone, which a correct
# trim reduces to "not configured" and a space-only trim hands to eval.
printf 'task | crlf | - | . | printf "[%%s]\\n" done\r\ntask | crlfempty | - | . |\r\n' > "$FIX/.claude/harness/project.conf"
assert_eq "a task line with a CRLF ending runs without the carriage return" "[done]" "$(task crlf)"
out="$(task crlfempty)"; rc=$?
assert_eq "a CRLF task line with no command is unconfigured, not a carriage return to run" \
  "task 'crlfempty' is not configured in project.conf" "$out"
assert_eq "and exits 1" "1" "$rc"

describe "MT-040 AC-4: doctor.sh's and task.sh's trim() agree with the shipped sed form"

# Same input set and oracle as gates.test.sh's AC-4 block (_lib.sh), applied to
# the trim() each of these two scripts defines.
trim_inputs "$_mt040/trim.in"
trim_oracle "$_mt040/trim.in" "$_mt040/trim.oracle"
for _s in doctor task; do
  assert_contains "$_s.sh defines trim()" "trim()" "$(extract_fn "$REPO_ROOT/scripts/$_s.sh" trim)"
  apply_trim "$REPO_ROOT/scripts/$_s.sh" "$_mt040/trim.in" "$_mt040/trim.$_s"
  assert_eq "$_s.sh trim() agrees with the sed form on all 635 inputs" \
    "0" "$(disagreements "$_mt040/trim.oracle" "$_mt040/trim.$_s")"
done

summary "doctor"
