# Proposal: best-effort guard for browser testing in an isolated demo profile (NOT APPLIED)

Status: for the user to apply by hand (revised 2026-10-23, second revision after review). `.claude/settings.json`
and `.claude/hooks/` are Edit-denied to the agent on purpose; nothing here is active until you make the edits below.

**What this is and is not.** It is a best-effort guard meant for a Chrome profile that holds nothing but the
local demo. It is **not** enforced localhost isolation. The hook sees each tool call's name and arguments, never
the page a tab is showing, so it cannot see which page a tab ID points at or where a clicked link leads.
The isolation comes from the profile (no accounts, no other sites open). The hook narrows what the agent can
ask for.

## What blocks browser verification today
- `.claude/settings.json` line 27 in `permissions.deny`: **`"mcp__*"`**. It removes every MCP tool, including
  every `mcp__claude-in-chrome__*` tool. On 2026-10-23 no browser tool was visible to the session, so whether
  the Chrome extension is connected is still **unknown**.
- `.claude/settings.local.json` only adds allow rules; it does not affect MCP.

## Evidence behind this revision (Claude Code 2.1.309, checked 2026-10-23)
- **Tool schemas.** These were read from the installed binary (`~/.local/share/claude/versions/2.1.309`) and
  encoded in `SCHEMAS` / `COMPUTER` in `guard_browser.py`. Points that matter:
  - `file_upload` takes `paths` (absolute), `ref` and `tabId`, and also has a `files` array of inline
    **base64 contents** ("populated by the client… do not set this yourself"). The guard refuses `files`, so
    content cannot be passed around the path check.
  - `computer` has 13 actions plus a `modifiers` field for clicks (cmd/ctrl/shift-click opens links in new
    tabs or windows).
  - `browser_batch` runs other tools inside one call.
  - `navigate` accepts `"back"`/`"forward"` and URLs without a scheme (defaulting to https).
- **Hook failure handling, tested live.** Each case ran as a headless `claude -p` session with a throwaway
  `--settings` file in `/tmp`, a PreToolUse hook on the harmless `Glob` tool, and nothing in `.claude/` changed:

  | Hook failure | `onFailure` omitted / `"continue"` (default) | `"onFailure": "block"` |
  |---|---|---|
  | times out (sleeps 8 s, timeout 2 s) | **call allowed** | blocked: "timed out; blocking because onFailure is \"block\"" |
  | exits 1 | **call allowed** | blocked: "failed; blocking…" |
  | script missing | **call allowed** | blocked: "failed; blocking…" |

  So the earlier claim of failing closed was wrong for timeouts. `|| exit 2` only turns a hook that *runs and
  exits non-zero* into a block. A timed-out hook is stopped by Claude Code before `|| exit 2` can run, so
  `|| exit 2` gives **no** timeout protection on any build. **Fail-closed behaviour therefore requires
  `"onFailure": "block"` and a Claude Code build that honours it, verified only on 2.1.309.** `|| exit 2` stays
  as extra protection for crashes, not as a fallback. Do not install on a different version without first
  re-running the timeout probe and seeing "timed out; blocking because onFailure is \"block\"". The install
  steps below stop if the version differs. The binary's schema text says `onFailure` is ignored for async
  hooks and on Stop/SubagentStop/TaskCompleted/TeammateIdle, which does not apply to a synchronous PreToolUse
  hook.
- **Matcher and command form, tested live.** A regex matcher (`G.*b`) matched `Glob`. The exact proposed
  command, `python3 -I "${CLAUDE_PROJECT_DIR}/…/guard_browser.py" || exit 2`, expanded the variable, ran the guard
  and blocked the call with its message. Not tested: that `mcp__.*` fires for real Chrome tool calls, and the
  exact `tool_input` Claude Code passes for them. The first real calls will show both (see "After installing").

## Installation (run in Terminal, from the project folder)

The settings change is the file `docs/proposals/browser-settings.patch` (31 lines; read it before applying).
It was generated from a copy of the current `.claude/settings.json` (sha1 `567a9e75c866…`) and checked on
scratch copies:
- it applies cleanly and the result is valid JSON;
- the only deny removed is `"mcp__*"`;
- every other deny, the `ask` rules, all other keys and the Bash hook entry are byte-identical;
- reversing it restores the original byte-for-byte.

Run `docs/proposals/install-browser-testing.sh` (read it first). It replaces the earlier command list, whose
STOP lines printed a warning without stopping and whose `| tail` pipes hid test failures. The script:
- aborts on any failed check, with no partial edits before the settings are validated;
- requires Claude Code 2.1.309 and pinned SHA-256 hashes for the patch, the guard and its tests;
- builds and validates the patched settings in a temporary folder before touching `.claude/`;
- keeps an existing backup untouched;
- refuses to overwrite different hook files;
- runs both hook test suites with their exit codes checked;
- verifies the installed result, restoring the original settings if verification fails;
- recognises an existing installation (the settings equal the patch applied to the verified backup) and then
  re-verifies without patching again.

```sh
cd ~/Desktop/"Strava Elo" && /bin/bash docs/proposals/install-browser-testing.sh
```

What the patch does, in full:
- In `permissions.deny`, it replaces `"mcp__*",` with six explicit denies:
  - `mcp__claude-in-chrome__javascript_tool`: page scripting;
  - `mcp__claude-in-chrome__browser_batch`: batched calls the hook cannot inspect one by one;
  - `mcp__claude-in-chrome__upload_image`: screenshot uploads into pages;
  - `mcp__claude-in-chrome__switch_browser` and `mcp__claude-in-chrome__select_browser`: moving to another
    Chrome browser or profile;
  - `mcp__claude-in-chrome__shortcuts_execute`: running extension shortcuts.
- In `hooks.PreToolUse`, after the unchanged Bash entry, it adds:
  ```json
  {"matcher": "mcp__.*", "hooks": [{"type": "command",
    "command": "python3 -I \"${CLAUDE_PROJECT_DIR}/.claude/hooks/guard_browser.py\" || exit 2",
    "timeout": 10, "onFailure": "block"}]}
  ```
  This hook refuses every other MCP tool, from any server.

Unchanged:
- every Git and `gh` deny, `RemoteTrigger` and `Agent(isolation:remote)`;
- the Edit denies, which also cover the new hook files;
- the `ask` rules, Artifact off and bypass mode disabled;
- the Bash hook.

### Connect Chrome
1. Create a **separate Chrome profile with no signed-in accounts, saved passwords, other extensions or other
   open sites**, and install the Claude extension in that profile only.
2. Start the demo in its own Terminal with `./run.sh demo`. It uses the separate synthetic database
   `data/demo/runrank-demo.sqlite`.
3. Restart Claude Code in this folder, run `/chrome` and connect the isolated profile.

## Rollback (any time; restores the exact original)
```sh
cd ~/Desktop/"Strava Elo"
cp -p .claude/settings.json.before-browser .claude/settings.json
shasum .claude/settings.json                                           # must start 567a9e75c866
rm .claude/hooks/guard_browser.py .claude/hooks/test_guard_browser.py  # optional; inert without the entry
```
If the backup is missing, run `patch -p1 -R < docs/proposals/browser-settings.patch` instead; that was checked to
restore the original byte-for-byte. Then restart Claude Code. Removing the extension or the Chrome profile is
separate and optional.

## What it enables
The Chrome tools in `SCHEMAS`, each limited to its schema:
- tabs: list, create, close;
- `navigate` to `http://127.0.0.1:8600` or `http://localhost:8600` only (no `back`/`forward`, no scheme-less
  URLs, no user-info);
- screenshots and zoom;
- clicks, double and triple clicks and hover by coordinate or element ref, **without modifiers**;
- scrolling, waiting, typing text that does not look like a URL or domain;
- keys from a fixed list: Tab, shift+Tab, Return, Escape, arrows, editing keys, single characters, select all;
- reading the page, its text, console and network log;
- `resize_window` (desktop and mobile widths);
- `form_input`;
- GIF recording with a plain filename;
- `file_upload` of existing regular files inside `$CLAUDE_PROJECT_DIR/examples/synthetic/`. Symlinks are
  resolved, the file extension is irrelevant, and a missing or relative `CLAUDE_PROJECT_DIR` refuses the
  upload.

Refused:
- right-click, drag, modified clicks;
- every other key or shortcut (address bar, new tab or window, history, cmd+Return);
- unknown arguments and wrong types;
- every Chrome tool not listed;
- every other MCP server (Gmail, Drive, Docs, Claude Design, anything added later);
- malformed payloads, including a missing or non-object `tool_input`.

## Limits it cannot enforce
- **The page behind a tab ID.** Clicks, typing, screenshots and page reads act on whatever tab ID is passed;
  the hook cannot tell which tab or site that is. Any tab open in the connected profile is reachable. I will
  use only tabs I create.
- **Where a click leads.** A plain click on a link inside a page can navigate the tab anywhere, and the hook
  never sees the result. RunnasUP's frontend source has no external URLs (checked by grep), so its own pages link only within the app. A link in imported
  data or an error page is outside the guard's view.
- **Screenshots and page text go to the model.** Keep to the demo database; do not open the personal database
  while browser tools are enabled.
- **Text checks are heuristic.** URL detection in typed text and the key list are text rules. They refuse some
  harmless text, such as a filename like `x.csv` typed into a search box, and they are not a sandbox.
- **A hook is weaker than a deny rule.** Failure handling was tested only on 2.1.309. Re-check it after a
  Claude Code update with a probe like the one above.

## After installing (first session): enforcement check before any inspection
1. **Hook fires on real Chrome calls.** I call `tabs_context_mcp`, then a call the guard must refuse on
   arguments alone: `tabs_create_mcp` with an unexpected key. Only the hook can refuse that, so the message
   "Blocked by RunnasUP guard_browser" in the result proves that the `mcp__.*` matcher and the guard ran.
2. **Permitted local navigation:** `navigate` to `http://127.0.0.1:8600/` in a tab I created, then a
   screenshot showing the demo.
3. **Refused external navigation:** `navigate` to `https://example.com` must return the guard's refusal, and a
   screenshot must show the tab still on the demo.

If any step does not behave this way (no hook message, an external URL loads, or an allowed call is refused
because of a schema difference), I stop all browser work and report it, without retrying another way.

## If you prefer not to change permissions
Use the manual walkthrough in `docs/ACCEPTANCE.md` (§2 and §3). Browser acceptance stays **incomplete** until
either path is done.
