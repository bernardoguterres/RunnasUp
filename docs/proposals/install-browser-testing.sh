#!/bin/bash
# Install the best-effort browser guard for the isolated demo Chrome profile (docs/proposals/
# browser-testing-permissions.md). For the user to run by hand; the agent cannot edit .claude/.
#
# What it does, in order. Any failed check aborts; nothing in .claude/ changes before step 5.
#   1. Preconditions: Claude Code 2.1.309 (the only build where "onFailure": "block" was verified) and
#      pinned SHA-256 hashes for the patch, the guard and its tests.
#   2. State: the settings are either the original (install), or exactly the patch applied to a
#      verified backup of the original (already installed: re-verify only, nothing is patched again).
#      Anything else aborts.
#   3. Builds the patched settings in a temporary folder and validates them against the original: the
#      only change is "mcp__*" replaced by six Chrome denies, plus one added hook entry. Every other deny,
#      the ask rules, the other keys and the Bash hook entry must be identical.
#   4. Backup: keeps an existing .claude/settings.json.before-browser untouched. If it is not the original,
#      it writes a new timestamped backup instead of overwriting it.
#   5. Installs the guard and its tests (never overwrites different files), runs both hook test suites,
#      then writes the validated settings.
#   6. Verifies the installed result. On any failure after step 5 starts, it restores the original
#      settings from the backup and removes the hook files this run created.
# It never touches Git, remotes, accounts, the network or private data.
set -euo pipefail
umask 077

EXPECTED_VERSION="2.1.309"
ORIG_SHA="0924c5b54de969792842f352f28bf2aac5856bd7ea5ec8d00ff1cca8984b0d8c"   # current .claude/settings.json
PATCH_SHA="c04d98c07b2ea324254dbe9304f9cc8262c37d8588ff41d940160ffebd344d29"  # browser-settings.patch
GUARD_SHA="67c38c63cafad9136a39801bde1e60d65f6aafa0de3a9ab25acd959fce450728"  # guard_browser.py
TEST_SHA="4cbf7cac8e52224568a37713a8f6fe4dcc81890ddd25fa0ca6e00a673fbf20fa"   # test_guard_browser.py

PROJECT="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$PROJECT"
SETTINGS=".claude/settings.json"
BACKUP=".claude/settings.json.before-browser"
HOOKS=".claude/hooks"
PATCH_FILE="docs/proposals/browser-settings.patch"
SRC_GUARD="docs/proposals/guard_browser.py"
SRC_TEST="docs/proposals/test_guard_browser.py"
DST_GUARD="$HOOKS/guard_browser.py"
DST_TEST="$HOOKS/test_guard_browser.py"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/runnasup-browser-install.XXXXXX")"
RESTORE_FROM=""        # backup holding the original settings
SETTINGS_WRITTEN=0     # 1 once step 5 has written the settings file
CREATED=""             # hook files this run created (removed again on failure)
DONE=0

say() { printf '%s\n' "$*"; }
die() { printf 'ABORT: %s\n' "$*" >&2; exit 1; }
sha() { shasum -a 256 "$1" | awk '{print $1}'; }

on_exit() {
  status=$?
  if [ "$DONE" -ne 1 ] && [ "$status" -ne 0 ]; then
    if [ "$SETTINGS_WRITTEN" -eq 1 ] && [ -n "$RESTORE_FROM" ]; then
      cp -p "$RESTORE_FROM" "$SETTINGS" && [ "$(sha "$SETTINGS")" = "$ORIG_SHA" ] \
        && printf 'RESTORED: %s is back to the original (sha256 %s...)\n' "$SETTINGS" "${ORIG_SHA:0:12}" >&2 \
        || printf 'RESTORE FAILED: copy %s over %s by hand and check its sha256 is %s\n' \
             "$RESTORE_FROM" "$SETTINGS" "$ORIG_SHA" >&2
    fi
    for f in $CREATED; do rm -f "$f" && printf 'removed %s (created by this run)\n' "$f" >&2; done
    printf 'Installation did not complete. Restart Claude Code only after reading the messages above.\n' >&2
  fi
  rm -rf "$TMP"
}
trap on_exit EXIT

# Validator: compares an original and a patched settings file. Exit 0 only if the patch is exactly the
# intended change.
cat > "$TMP/validate.py" <<'PY'
import json, sys
SIX = ["mcp__claude-in-chrome__" + t for t in
       ("javascript_tool", "browser_batch", "upload_image", "switch_browser", "select_browser", "shortcuts_execute")]
HOOK = {"matcher": "mcp__.*", "hooks": [{"type": "command",
        "command": "python3 -I \"${CLAUDE_PROJECT_DIR}/.claude/hooks/guard_browser.py\" || exit 2",
        "timeout": 10, "onFailure": "block"}]}
def fail(msg):
    print("validation failed: " + msg); sys.exit(1)
try:
    o, n = (json.load(open(p)) for p in sys.argv[1:3])
except Exception as exc:
    fail("not valid JSON (%s)" % exc)
op, np_ = o.get("permissions", {}), n.get("permissions", {})
od, nd = op.get("deny", []), np_.get("deny", [])
if od.count("mcp__*") != 1:
    fail("original deny list does not contain \"mcp__*\" exactly once")
i = od.index("mcp__*")
if nd != od[:i] + SIX + od[i + 1:]:
    fail("deny list is not the original with \"mcp__*\" replaced by the six Chrome denies")
for k in set(op) | set(np_):
    if k != "deny" and op.get(k) != np_.get(k):
        fail("permissions.%s changed" % k)
for k in set(o) | set(n):
    if k not in ("permissions", "hooks") and o.get(k) != n.get(k):
        fail("top-level key %s changed" % k)
oh, nh = o.get("hooks", {}), n.get("hooks", {})
for k in set(oh) | set(nh):
    if k != "PreToolUse" and oh.get(k) != nh.get(k):
        fail("hooks.%s changed" % k)
opre = oh.get("PreToolUse", [])
if any(isinstance(e, dict) and e.get("matcher") == "mcp__.*" for e in opre):
    fail("original already has an mcp__.* hook")
if nh.get("PreToolUse") != opre + [HOOK]:
    fail("PreToolUse is not the original entries plus exactly the guard entry")
print("validation ok: only \"mcp__*\" replaced by %d Chrome denies and one hook added; %d other denies, "
      "ask rules, other keys and the Bash hook unchanged" % (len(SIX), len(od) - 1))
PY

# ---- 1. Preconditions ---------------------------------------------------------------------------
for c in claude python3 patch shasum cmp awk; do
  command -v "$c" >/dev/null 2>&1 || die "required command not found: $c"
done
VERSION="$(claude --version)" || die "could not run claude --version"
case "$VERSION" in
  "$EXPECTED_VERSION "*) say "ok: Claude Code $EXPECTED_VERSION" ;;
  *) die "Claude Code is '$VERSION', not $EXPECTED_VERSION. onFailure: block was verified only on $EXPECTED_VERSION; re-run the timeout probe on this build first (see the proposal)." ;;
esac
for pair in "$PATCH_FILE:$PATCH_SHA" "$SRC_GUARD:$GUARD_SHA" "$SRC_TEST:$TEST_SHA"; do
  f="${pair%%:*}"; want="${pair##*:}"
  [ -f "$f" ] || die "missing $f"
  [ "$(sha "$f")" = "$want" ] || die "$f does not match the reviewed version (sha256 differs)"
done
[ -f "$SETTINGS" ] || die "missing $SETTINGS"
[ -d "$HOOKS" ] || die "missing $HOOKS"
say "ok: patch, guard and tests match the reviewed hashes"

# ---- 2. State: original, already installed, or unknown ------------------------------------------
CUR_SHA="$(sha "$SETTINGS")"
STATE=""
if [ "$CUR_SHA" = "$ORIG_SHA" ]; then
  STATE="install"
  cp -p "$SETTINGS" "$TMP/orig.json"
elif [ -f "$BACKUP" ] && [ "$(sha "$BACKUP")" = "$ORIG_SHA" ]; then
  cp -p "$BACKUP" "$TMP/orig.json"
  patch -s -o "$TMP/derived.json" -r "$TMP/derived.rej" "$TMP/orig.json" < "$PATCH_FILE" \
    || die "the patch does not apply to the backup $BACKUP"
  cmp -s "$SETTINGS" "$TMP/derived.json" \
    || die "$SETTINGS is neither the original nor the patched version; nothing was changed. Inspect it by hand."
  STATE="installed"
  RESTORE_FROM="$BACKUP"
else
  die "$SETTINGS is not the original (sha256 ${CUR_SHA:0:12}...) and no matching backup proves it is the patched version; nothing was changed"
fi
say "state: $STATE"

# Hook files: allowed only if absent or byte-identical to the reviewed copies (never overwritten).
for pair in "$SRC_GUARD:$DST_GUARD" "$SRC_TEST:$DST_TEST"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ -e "$dst" ] && ! cmp -s "$src" "$dst"; then
    die "$dst exists and differs from $src; not overwriting it"
  fi
done

# ---- 3. Build and validate the patched settings outside .claude/ --------------------------------
if [ "$STATE" = "install" ]; then
  patch -s -o "$TMP/new.json" -r "$TMP/new.rej" "$TMP/orig.json" < "$PATCH_FILE" \
    || die "the patch does not apply cleanly to $SETTINGS"
else
  cp -p "$SETTINGS" "$TMP/new.json"
fi
python3 -I "$TMP/validate.py" "$TMP/orig.json" "$TMP/new.json" || die "patched settings failed validation"

# ---- 4. Backup (existing backups are never overwritten) -----------------------------------------
if [ "$STATE" = "install" ]; then
  if [ -e "$BACKUP" ]; then
    if [ "$(sha "$BACKUP")" = "$ORIG_SHA" ]; then
      RESTORE_FROM="$BACKUP"
      say "backup: kept existing $BACKUP (it is the original)"
    else
      RESTORE_FROM="$BACKUP.$(date +%Y%m%d-%H%M%S)"
      [ -e "$RESTORE_FROM" ] && die "$RESTORE_FROM already exists"
      cp -p "$SETTINGS" "$RESTORE_FROM"
      say "backup: $BACKUP exists with other content and was left untouched; original saved as $RESTORE_FROM"
    fi
  else
    RESTORE_FROM="$BACKUP"
    cp -p "$SETTINGS" "$RESTORE_FROM"
    say "backup: $RESTORE_FROM"
  fi
  [ "$(sha "$RESTORE_FROM")" = "$ORIG_SHA" ] || die "backup $RESTORE_FROM does not match the original"
fi

# ---- 5. Install hook files, run tests, write settings -------------------------------------------
for pair in "$SRC_GUARD:$DST_GUARD" "$SRC_TEST:$DST_TEST"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ ! -e "$dst" ]; then
    cp "$src" "$dst"
    CREATED="$CREATED $dst"
    say "installed $dst"
  else
    say "kept $dst (already identical)"
  fi
done
[ "$(sha "$DST_GUARD")" = "$GUARD_SHA" ] || die "$DST_GUARD does not match after copying"
[ "$(sha "$DST_TEST")" = "$TEST_SHA" ] || die "$DST_TEST does not match after copying"

run_tests() {  # name, file, expected summary line; output goes to a log so the exit code is not masked
  log="$TMP/$1.log"
  if ! env -u GUARD python3 -I "$2" > "$log" 2>&1; then
    tail -n 20 "$log" >&2
    die "$1 tests failed"
  fi
  grep -qx "$3" "$log" || { tail -n 5 "$log" >&2; die "$1 tests did not report '$3'"; }
  say "ok: $1 tests: $3"
}
run_tests guard_browser "$DST_TEST" "118 cases, 0 failed"
if ! python3 -I "$HOOKS/test_guard_bash.py" > "$TMP/guard_bash.log" 2>&1; then
  tail -n 20 "$TMP/guard_bash.log" >&2
  die "existing guard_bash tests failed"
fi
say "ok: guard_bash tests: $(tail -n 1 "$TMP/guard_bash.log")"

if [ "$STATE" = "install" ]; then
  SETTINGS_WRITTEN=1
  cp "$TMP/new.json" "$SETTINGS"
  say "wrote $SETTINGS"
fi

# ---- 6. Verify the installed result (failure restores the original) -----------------------------
cmp -s "$SETTINGS" "$TMP/new.json" || die "installed settings differ from the validated file"
python3 -I "$TMP/validate.py" "$RESTORE_FROM" "$SETTINGS" || die "installed settings failed validation"
python3 -I -m json.tool "$SETTINGS" > /dev/null || die "installed settings are not valid JSON"

probe() {  # expected exit, payload: runs the installed guard exactly as the hook will
  if printf '%s' "$2" | CLAUDE_PROJECT_DIR="$PROJECT" python3 -I "$PROJECT/$DST_GUARD" > /dev/null 2>&1; then rc=0; else rc=$?; fi
  [ "$rc" -eq "$1" ] || die "installed guard returned $rc, expected $1, for $2"
}
probe 0 '{"tool_name":"mcp__claude-in-chrome__tabs_context_mcp","tool_input":{}}'
probe 0 '{"tool_name":"mcp__claude-in-chrome__navigate","tool_input":{"url":"http://127.0.0.1:8600/","tabId":1}}'
probe 2 '{"tool_name":"mcp__claude-in-chrome__navigate","tool_input":{"url":"https://example.com","tabId":1}}'
probe 2 '{"tool_name":"mcp__claude-in-chrome__javascript_tool","tool_input":{"text":"1","tabId":1}}'
probe 2 '{"tool_name":"mcp__claude_ai_Gmail__send_email","tool_input":{}}'
say "ok: installed guard allows local navigation and refuses external navigation and other MCP tools"

DONE=1
say ""
if [ "$STATE" = "install" ]; then say "INSTALLED."; else say "ALREADY INSTALLED: verified, nothing patched again."; fi
say "Original settings backup: $RESTORE_FROM"
say "Rollback: cp -p '$RESTORE_FROM' '$SETTINGS'  (then restart Claude Code)"
say "Next: start ./run.sh demo, restart Claude Code in this folder, run /chrome and connect the isolated profile."
