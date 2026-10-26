#!/usr/bin/env python3
"""Simulated payloads for guard_browser.py (no browser, no network). Run: python3 -I <this file>

Uploads are checked against a throwaway fake project in a temporary directory, so the real examples/ and
data/ folders are never read.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GUARD = os.environ.get("GUARD", str(HERE / "guard_browser.py"))
C = "mcp__claude-in-chrome__"

TMP = tempfile.mkdtemp(prefix="guard_browser_test_")
PROJECT = os.path.realpath(TMP)
SYN = os.path.join(PROJECT, "examples", "synthetic")
os.makedirs(os.path.join(SYN, "sub"))
os.makedirs(os.path.join(PROJECT, "data"))
for rel in ("examples/synthetic/a.csv", "examples/synthetic/NOTES", "examples/synthetic/sub/b.zip",
            "data/secret", "data/x.csv"):
    pathlib.Path(PROJECT, rel).write_text("synthetic\n")
os.symlink(os.path.join(PROJECT, "data", "secret"), os.path.join(SYN, "link_out"))
os.symlink(os.path.join(SYN, "a.csv"), os.path.join(SYN, "link_in"))
A, NOTES, B, SECRET = SYN + "/a.csv", SYN + "/NOTES", SYN + "/sub/b.zip", PROJECT + "/data/secret"


def up(paths, **extra):
    return {"tool_name": C + "file_upload", "tool_input": dict({"paths": paths, "ref": "ref_3", "tabId": 7}, **extra)}


def cu(**args):
    return {"tool_name": C + "computer", "tool_input": dict({"tabId": 7}, **args)}


def t(name, **args):
    return {"tool_name": C + name, "tool_input": args}


ENV = {"CLAUDE_PROJECT_DIR": PROJECT}
CASES = [  # (expected exit, payload, env overrides or None)
    # allowed: the calls the demo inspection needs
    (0, t("tabs_context_mcp"), None),
    (0, t("tabs_context_mcp", createIfEmpty=True), None),
    (0, t("tabs_create_mcp"), None),
    (0, t("tabs_close_mcp", tabId=7), None),
    (0, t("navigate", url="http://127.0.0.1:8600/activities", tabId=7), None),
    (0, t("navigate", url="http://localhost:8600/lab?x=1"), None),
    (0, cu(action="screenshot"), None),
    (0, cu(action="screenshot", scale=0.5, save_to_disk=True), None),
    (0, cu(action="zoom", region=[0, 0, 400, 300]), None),
    (0, cu(action="key", text="Tab"), None),
    (0, cu(action="key", text="shift+Tab Return Escape", repeat=3), None),
    (0, cu(action="key", text="cmd+a Backspace"), None),
    (0, cu(action="left_click", coordinate=[10, 20]), None),
    (0, cu(action="left_click", ref="ref_12"), None),
    (0, cu(action="hover", coordinate=[10, 20]), None),
    (0, cu(action="type", text="Morning run 10 km"), None),
    (0, cu(action="scroll", coordinate=[200, 300], scroll_direction="down", scroll_amount=5), None),
    (0, cu(action="scroll_to", ref="ref_4"), None),
    (0, cu(action="wait", duration=1), None),
    (0, t("resize_window", width=390, height=844, tabId=7), None),
    (0, t("read_page", tabId=7, filter="interactive"), None),
    (0, t("find", query="upload button", tabId=7), None),
    (0, t("get_page_text", tabId=7), None),
    (0, t("read_console_messages", tabId=7, pattern="error", onlyErrors=True), None),
    (0, t("read_network_requests", tabId=7, urlPattern="/api/"), None),
    (0, t("form_input", ref="ref_2", value="2026-01-01", tabId=7), None),
    (0, t("form_input", ref="ref_2", value=True, tabId=7), None),
    (0, t("gif_creator", action="export", tabId=7, download=True, filename="mobile_menu.gif",
          options={"quality": 10, "showWatermark": False}), None),
    (0, up([A]), None),
    (0, up([A, NOTES, B]), None),                                   # extensionless file inside: allowed
    (0, up([SYN + "/link_in"]), None),                              # symlink resolving inside
    # navigation and URLs
    (2, t("navigate", url="https://www.strava.com/dashboard", tabId=7), None),
    (2, t("navigate", url="http://127.0.0.1:8601/", tabId=7), None),
    (2, t("navigate", url="http://127.0.0.1:8600@evil.example/", tabId=7), None),
    (2, t("navigate", url="http://user@127.0.0.1:8600/", tabId=7), None),
    (2, t("navigate", url="http://127.0.0.1:8600/\nhttp://evil.example", tabId=7), None),
    (2, t("navigate", url="file:///Users/x/data/runrank.sqlite", tabId=7), None),
    (2, t("navigate", url="127.0.0.1:8600", tabId=7), None),         # tool would default to https
    (2, t("navigate", url="back", tabId=7), None),
    (2, t("navigate", url="forward", tabId=7), None),
    (2, t("navigate", tabId=7), None),
    (2, t("navigate", url="http://127.0.0.1:8600/", tabId="7"), None),
    (2, t("tabs_create_mcp", url="https://mail.google.com"), None),  # unknown key
    (2, t("find", query="https://example.com", tabId=7), None),
    (2, t("form_input", ref="ref_2", value="javascript:alert(1)", tabId=7), None),
    (2, t("gif_creator", action="export", tabId=7, filename="../../x.gif"), None),
    (2, t("gif_creator", action="export", tabId=7, coordinate=[1, 2]), None),
    (2, t("read_page", tabId=7, filter="everything"), None),
    # computer: unknown actions, modifiers, shortcuts, typed URLs, schema mismatches
    (2, cu(action="type", text="https://example.com"), None),
    (2, cu(action="type", text="gmail.com/"), None),
    (2, cu(action="key", text="cmd+l"), None),
    (2, cu(action="key", text="ctrl+t"), None),
    (2, cu(action="key", text="Tab cmd+n"), None),
    (2, cu(action="key", text="cmd+Return"), None),
    (2, cu(action="key", text="alt+Left"), None),
    (2, cu(action="key", text="F6"), None),
    (2, cu(action="key", text=""), None),
    (2, cu(action="left_click", coordinate=[10, 20], modifiers="cmd"), None),
    (2, cu(action="left_click", coordinate=[10, 20], ref="ref_1"), None),
    (2, cu(action="left_click"), None),
    (2, cu(action="left_click", coordinate=[10]), None),
    (2, cu(action="right_click", coordinate=[10, 20]), None),
    (2, cu(action="left_click_drag", start_coordinate=[1, 1], coordinate=[9, 9]), None),
    (2, cu(action="middle_click", coordinate=[10, 20]), None),
    (2, cu(action="javascript_exec", text="1"), None),
    (2, cu(action=None), None),
    (2, cu(text="Tab"), None),
    (2, cu(action="screenshot", url="http://127.0.0.1:8600/"), None),
    (2, {"tool_name": C + "computer", "tool_input": {"action": "screenshot"}}, None),   # no tabId
    (2, cu(action="screenshot", tabId=True), None),
    # tools outside the allowlist
    (2, t("javascript_tool", action="javascript_exec", text="1", tabId=7), None),
    (2, t("browser_batch", actions=[{"name": "navigate", "input": {"url": "https://example.com", "tabId": 7}}]), None),
    (2, t("upload_image", imageId="x", tabId=7), None),
    (2, t("switch_browser"), None),
    (2, t("select_browser", deviceId="x"), None),
    (2, t("shortcuts_execute", tabId=7, command="summarize"), None),
    (2, {"tool_name": "mcp__claude_ai_Gmail__send_email", "tool_input": {}}, None),
    (2, {"tool_name": "mcp__claude-design__anything", "tool_input": {}}, None),
    (2, {"tool_name": "mcp__some_future_server__tool", "tool_input": {}}, None),
    # uploads: mixed, extensionless, malformed, escapes, missing configuration
    (2, up([A, SECRET]), None),                                     # mixed allowed + extensionless outside
    (2, up([SECRET, A]), None),
    (2, up([A, "/etc/passwd"]), None),
    (2, up([A, PROJECT + "/data/x.csv"]), None),
    (2, up(["NOTES"]), None),                                       # relative, extensionless
    (2, up(["examples/synthetic/a.csv"]), None),                    # relative
    (2, up([SYN + "/../../data/secret"]), None),
    (2, up([SYN + "/link_out"]), None),                             # symlink escaping the folder
    (2, up([SYN + "/missing.csv"]), None),
    (2, up([SYN + "/sub"]), None),                                  # a directory
    (2, up([SYN]), None),
    (2, up([]), None),
    (2, up("/" + A), None),                                         # a string, not a list
    (2, up([A, 7]), None),
    (2, up([A, None]), None),
    (2, up([A, ""]), None),
    (2, up([A, A + "\x00x"]), None),
    (2, up([A, [SECRET]]), None),
    (2, up([A], files=[{"data": "c2VjcmV0", "name": "s.csv"}]), None),  # inline contents: refused
    (2, up([A], note=SECRET), None),
    (2, {"tool_name": C + "file_upload", "tool_input": {"paths": [A], "tabId": 7}}, None),     # no ref
    (2, {"tool_name": C + "file_upload", "tool_input": {"tabId": 7, "ref": "ref_3"}}, None),  # no paths
    (2, up([A]), {"CLAUDE_PROJECT_DIR": None}),
    (2, up([A]), {"CLAUDE_PROJECT_DIR": ""}),
    (2, up([A]), {"CLAUDE_PROJECT_DIR": "relative/project"}),
    (2, up([A]), {"CLAUDE_PROJECT_DIR": PROJECT + "/nope"}),
    (2, up([A]), {"CLAUDE_PROJECT_DIR": PROJECT + "/data"}),        # no examples/synthetic there
    # malformed payloads
    (2, "not json", None),
    (2, "", None),
    (2, "[]", None),
    (2, "null", None),
    (2, {"tool_input": {}}, None),
    (2, {"tool_name": C + "tabs_create_mcp"}, None),                # no tool_input
    (2, {"tool_name": C + "tabs_create_mcp", "tool_input": None}, None),
    (2, {"tool_name": C + "tabs_create_mcp", "tool_input": ""}, None),
    (2, {"tool_name": C + "tabs_create_mcp", "tool_input": 0}, None),
    (2, {"tool_name": C + "tabs_create_mcp", "tool_input": []}, None),
    (2, {"tool_name": C + "tabs_create_mcp", "tool_input": "{}"}, None),
    (2, {"tool_name": 7, "tool_input": {}}, None),
]


def run(payload, env_over):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    env = dict(ENV, PATH=os.environ.get("PATH", ""))
    for k, v in (env_over or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    r = subprocess.run([sys.executable, "-I", GUARD], input=data, capture_output=True, text=True, env=env,
                       timeout=10)
    return r.returncode, r.stderr.strip()


fails = 0
for want, payload, env_over in CASES:
    got, err = run(payload, env_over)
    ok = got == want
    fails += not ok
    if isinstance(payload, str):
        label = repr(payload)
    else:
        label = "%s %s" % (str(payload.get("tool_name", "?")).replace(C, "chrome:"),
                           json.dumps(payload.get("tool_input", "<missing>")).replace(PROJECT, "<proj>")[:80])
    if env_over:
        label += "  env=%s" % json.dumps(env_over).replace(PROJECT, "<proj>")
    print("%s want %d got %d  %s%s" % ("ok  " if ok else "FAIL", want, got, label, ("  | " + err) if err and not ok else ""))
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d cases, %d failed" % (len(CASES), fails))
sys.exit(1 if fails else 0)
