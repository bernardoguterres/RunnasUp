#!/usr/bin/env python3
"""PreToolUse guard for every MCP tool (proposed; copy to .claude/hooks/ by hand).

A best-effort guard for an isolated demo browser profile, not enforced localhost isolation. It sees only the
tool name and the arguments of each call, never the page a tab shows, so tab IDs it cannot check and links
clicked inside a page stay outside its view. Rules:
  - every MCP tool is refused unless it is a Claude in Chrome tool listed in SCHEMAS;
  - each call's arguments are checked against that tool's input schema as shipped in Claude Code 2.1.309:
    the payload and tool_input must be JSON objects, unknown keys and wrong types are refused, computer
    actions are limited to the listed ones, with click modifiers refused and keys limited to KEYS_OK;
  - navigate needs an http://127.0.0.1:8600 or http://localhost:8600 URL; free-text fields that look like
    a URL or domain are refused;
  - file_upload takes only `paths`: absolute paths of existing regular files inside
    $CLAUDE_PROJECT_DIR/examples/synthetic/ (symlinks resolved). The client-filled `files` field is refused.
A refusal exits 2 (Claude Code blocks the call and shows the reason). The hook entry must set
"onFailure": "block": without it a timed-out guard lets the call through, and `|| exit 2` cannot help because a
timed-out command never reaches it. Verified on 2.1.309 only; see docs/proposals/browser-testing-permissions.md.
"""
import json
import os
import re
import sys
from urllib.parse import urlparse

PREFIX = "mcp__claude-in-chrome__"
HOSTS = {("127.0.0.1", 8600), ("localhost", 8600)}
URLISH = re.compile(r"\b[a-z][a-z0-9+.-]*://|\b(?:javascript|data|file|about|chrome|blob|view-source|mailto):|"
                    r"^www\.|\b[a-z0-9-]+\.[a-z]{2,}(/|:|$)", re.I)
# keys the computer tool may press: plain navigation and editing keys, single characters, shift+Tab or
# shift+arrow, select all. Everything else (address bar, new tab, history, cmd+Return on a link) is refused.
PLAIN = {"tab", "return", "enter", "escape", "esc", "space", "backspace", "delete", "home", "end", "pageup",
         "pagedown", "up", "down", "left", "right", "arrowup", "arrowdown", "arrowleft", "arrowright"}
KEYS_OK = re.compile(r"^(?:[a-z0-9]|%s|shift\+(?:tab|up|down|left|right|arrow(?:up|down|left|right))|"
                     r"(?:cmd|ctrl)\+a)$" % "|".join(sorted(PLAIN)), re.I)


def deny(msg):
    sys.stderr.write("Blocked by RunnasUP guard_browser: %s\n" % msg)
    sys.exit(2)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool) or isinstance(v, float) and v.is_integer()


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def nums(n):
    return lambda v: isinstance(v, list) and len(v) == n and all(is_num(x) for x in v)


def one_of(*vals):
    return lambda v: v in vals


def text(v):
    """A free-text string that does not look like a URL or domain."""
    return isinstance(v, str) and not URLISH.search(v)


def local_url(s):
    if not isinstance(s, str) or re.search(r"[\s\\\x00-\x1f]", s):
        return False
    u = urlparse(s)
    try:
        port = u.port
    except ValueError:
        return False
    return u.scheme == "http" and u.username is None and u.password is None and (u.hostname, port) in HOSTS


def keys(v):
    return isinstance(v, str) and v.strip() != "" and all(KEYS_OK.match(k) for k in v.split())


def name(v):
    return isinstance(v, str) and re.fullmatch(r"[\w .-]{1,80}", v) is not None and ".." not in v


def gif_options(v):
    ok = {"showClickIndicators", "showDragPaths", "showActionLabels", "showProgressBar", "showWatermark"}
    return isinstance(v, dict) and all(k in ok and isinstance(x, bool) or k == "quality" and is_num(x)
                                       for k, x in v.items())


B, I, N, S = (lambda v: isinstance(v, bool)), is_int, is_num, (lambda v: isinstance(v, str))
REF = lambda v: isinstance(v, str) and re.fullmatch(r"ref_\d+", v) is not None  # noqa: E731

# tool -> (allowed keys with validators, required keys). Absent tools (javascript_tool, browser_batch,
# upload_image, shortcuts_*, switch_browser, select_browser, list_connected_browsers) are refused.
SCHEMAS = {
    "tabs_context_mcp": ({"createIfEmpty": B}, set()),
    "tabs_create_mcp": ({}, set()),
    "tabs_close_mcp": ({"tabId": I}, {"tabId"}),
    "navigate": ({"url": local_url, "tabId": I}, {"url"}),
    "read_page": ({"tabId": I, "filter": one_of("interactive", "all"), "depth": I, "ref_id": REF, "max_chars": I},
                  {"tabId"}),
    "find": ({"query": text, "tabId": I}, {"query", "tabId"}),
    "get_page_text": ({"tabId": I}, {"tabId"}),
    "read_console_messages": ({"tabId": I, "onlyErrors": B, "clear": B, "pattern": S, "limit": I}, {"tabId"}),
    "read_network_requests": ({"tabId": I, "urlPattern": S, "clear": B, "limit": I}, {"tabId"}),
    "resize_window": ({"width": I, "height": I, "tabId": I}, {"width", "height", "tabId"}),
    "gif_creator": ({"action": one_of("start_recording", "stop_recording", "export", "clear"), "tabId": I,
                     "download": B, "filename": name, "options": gif_options}, {"action", "tabId"}),
    "form_input": ({"ref": REF, "value": lambda v: text(v) or isinstance(v, bool) or is_num(v), "tabId": I},
                   {"ref", "value", "tabId"}),
    "computer": None,      # per action, below
    "file_upload": None,   # paths, below
}
TARGET = {"coordinate": nums(2), "ref": REF}
# computer action -> extra keys (beyond action and tabId); right_click, left_click_drag and modifiers are
# left out on purpose (context menus, drags and modified clicks can open links in new tabs or windows).
COMPUTER = {
    "left_click": TARGET, "double_click": TARGET, "triple_click": TARGET, "hover": TARGET,
    "type": {"text": text}, "key": {"text": keys, "repeat": I},
    "screenshot": {"scale": N, "save_to_disk": B}, "zoom": {"region": nums(4), "scale": N, "save_to_disk": B},
    "wait": {"duration": N}, "scroll": {"coordinate": nums(2), "scroll_direction": one_of("up", "down", "left", "right"),
                                        "scroll_amount": I},
    "scroll_to": {"ref": REF},
}
TARGET_ACTIONS = {"left_click", "double_click", "triple_click", "hover"}
COMPUTER_REQUIRED = {"type": {"text"}, "key": {"text"}, "zoom": {"region"}, "wait": {"duration"},
                     "scroll": {"coordinate", "scroll_direction"}, "scroll_to": {"ref"}}


def check(tool, args, spec, required):
    for k in sorted(required - set(args)):
        deny("%s needs %r" % (tool, k))
    for k, v in args.items():
        if k not in spec:
            deny("%s does not accept %r here" % (tool, k))
        if not spec[k](v):
            deny("%s: value of %r is not allowed: %r" % (tool, k, json.dumps(v)[:120]))


def upload_root():
    proj = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not proj or not os.path.isabs(proj) or not os.path.isdir(proj):
        deny("file_upload needs CLAUDE_PROJECT_DIR set to the project's absolute path")
    root = os.path.realpath(os.path.join(proj, "examples", "synthetic"))
    if not os.path.isdir(root):
        deny("file_upload needs %s to exist" % root)
    return root


def check_upload(args):
    check("file_upload", args, {"paths": lambda v: isinstance(v, list), "ref": REF, "tabId": I},
          {"paths", "ref", "tabId"})
    paths = args["paths"]
    if not paths:
        deny("file_upload needs at least one path")
    root = upload_root()
    for f in paths:
        if not isinstance(f, str) or not f or "\x00" in f or not os.path.isabs(f):
            deny("file_upload paths must be absolute path strings, not %r" % json.dumps(f)[:120])
        real = os.path.realpath(f)
        if not real.startswith(root + os.sep) or not os.path.isfile(real):
            deny("uploads are limited to existing files in examples/synthetic/, not %r" % f[:160])


def main():
    try:
        p = json.load(sys.stdin)
        if not isinstance(p, dict):
            raise TypeError("payload is not an object")
        tool, args = p["tool_name"], p["tool_input"]
        if not isinstance(tool, str) or not isinstance(args, dict):
            raise TypeError("tool_name must be a string and tool_input an object")
    except Exception as exc:
        deny("malformed payload (%s: %s)" % (type(exc).__name__, exc))
    if not tool.startswith(PREFIX):
        deny("MCP tool %s is not permitted in this project (only local Claude in Chrome testing)" % tool)
    short = tool[len(PREFIX):]
    if short not in SCHEMAS:
        deny("Chrome tool %s is not on the local-testing allowlist" % short)
    if short == "file_upload":
        check_upload(args)
    elif short == "computer":
        action = args.get("action")
        if action not in COMPUTER:
            deny("computer action %r is not allowed" % json.dumps(action)[:60])
        check("computer " + action, args, dict(COMPUTER[action], action=S, tabId=I),
              {"action", "tabId"} | COMPUTER_REQUIRED.get(action, set()))
        if action in TARGET_ACTIONS and not ("coordinate" in args) ^ ("ref" in args):
            deny("computer %s needs exactly one of coordinate or ref" % action)
    else:
        check(short, args, *SCHEMAS[short])
    sys.exit(0)


if __name__ == "__main__":
    main()
