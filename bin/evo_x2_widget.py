#!/usr/bin/env python3
"""EVO-X2 desktop widget — a floating frameless panel on the macOS desktop.

No menu bar, no Dock icon: just the live dashboard in a compact draggable
window that sits BEHIND your apps like a real desktop widget. Header strip:
⟳ refresh-rate picker · 📌 float above everything · × quit.
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
        self.pinned = False
        self.nswindow = None

    def set_interval(self, seconds):
        core.CFG["interval"] = int(seconds)
        core.CFG["restart"] = True

    def _apply_level(self):
        import AppKit
        import Quartz
        if self.nswindow is None:
            return
        if self.pinned:
            level = AppKit.NSStatusWindowLevel
            behavior = self.nswindow.collectionBehavior() & ~AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        else:  # desktop-widget layer: below all app windows, like native widgets
            level = Quartz.CGWindowLevelForKey(Quartz.kCGDesktopIconWindowLevelKey)
            behavior = (AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                        | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        self.nswindow.setLevel_(level)
        self.nswindow.setCollectionBehavior_(behavior)

    def toggle_pin(self):
        self.pinned = not self.pinned
        self._apply_level()
        save_conf(pin=self.pinned)
        return self.pinned

    def get_pin(self):
        return self.pinned

    def quit(self):
        from AppKit import NSApplication  # pyobjc ships with pywebview
        NSApplication.sharedApplication().terminate_(None)


def get_ns_window(win):
    """Reach the real NSWindow through pywebview's cocoa internals."""
    try:
        from webview.platforms import cocoa
        view = cocoa.BrowserView.instances.get(win.uid)
        return getattr(view, "window", None)
    except Exception:  # noqa: BLE001
        return None


def main():
    conf = load_conf()
    from AppKit import NSScreen  # default height: as tall as the screen allows
    sh = int(NSScreen.mainScreen().frame().size.height)
    api = Api()
    core.start()
    win = webview.create_window(
        "EVO-X2", f"http://127.0.0.1:{core.PORT}/?widget=1",
        width=conf.get("w", 820), height=conf.get("h", min(sh - 70, 1160)),
        x=conf.get("x"), y=conf.get("y"),
        frameless=True, on_top=False, resizable=True,
        easy_drag=True,
        background_color="#0d1117", js_api=api)
    api.win = win
    api.pinned = bool(conf.get("pin", False))

    def promote_to_desktop_widget():
        # no Dock icon, no Cmd-Tab; unpinned it sits on the desktop layer
        # below all app windows, like a real macOS widget
        import AppKit
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        nsw = get_ns_window(win)
        if nsw is not None:
            api.nswindow = nsw
            api._apply_level()

    win.events.loaded += promote_to_desktop_widget

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
