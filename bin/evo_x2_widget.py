#!/usr/bin/env python3
"""EVO-X2 desktop widget — a floating frameless panel on the macOS desktop.

No menu bar, no Dock icon: just the live dashboard in a compact draggable
window. Header strip: ⟳ refresh-rate picker · 📌 pin on top · × quit.
Position, size and pin survive restarts (~/.evo-x2-widget.json).

    .venv/bin/python bin/evo_x2_widget.py

Full-size version in any browser: http://127.0.0.1:8765/
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import webview  # noqa: E402

import widget_core as core  # noqa: E402

CONF = os.path.expanduser("~/.evo-x2-widget.json")


def load_conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_conf(**kw):
    c = load_conf() | kw
    with open(CONF, "w") as f:
        json.dump(c, f, indent=1)


class Api:
    """Methods the widget page calls via window.pywebview.api.*"""

    def __init__(self):
        self.win = None

    def set_interval(self, seconds):
        core.CFG["interval"] = int(seconds)
        core.CFG["restart"] = True

    def toggle_pin(self):
        self.win.on_top = not self.win.on_top
        save_conf(pin=self.win.on_top)
        return self.win.on_top

    def quit(self):
        from AppKit import NSApplication  # pyobjc ships with pywebview
        NSApplication.sharedApplication().terminate_(None)


def main():
    conf = load_conf()
    api = Api()
    core.start()
    win = webview.create_window(
        "EVO-X2", f"http://127.0.0.1:{core.PORT}/?widget=1",
        width=conf.get("w", 780), height=conf.get("h", 920),
        x=conf.get("x"), y=conf.get("y"),
        frameless=True, on_top=conf.get("pin", True), resizable=True,
        easy_drag=True,
        background_color="#0d1117", js_api=api)
    api.win = win

    def remember():
        try:
            x, y, w, h = win.get_positions()
            save_conf(x=x, y=y, w=w, h=h)
        except Exception:  # noqa: BLE001 — geometry save is best-effort
            pass

    win.events.closed += remember
    webview.start()


if __name__ == "__main__":
    main()
