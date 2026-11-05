#!/usr/bin/env python3
"""EVO-X2 desktop widget — a macOS-style widget on the desktop.

Rounded translucent card that lives just BELOW normal app windows (above the
desktop, below everything you open), follows you across Spaces, no Dock icon,
no Cmd-Tab entry. Drag it anywhere; position/size/pin/refresh-rate survive
restarts (~/.evo-x2-widget.json). Header strip:
⟳ refresh-rate picker · 📌 float above everything · × quit.

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
        seconds = int(seconds)
        core.CFG["interval"] = seconds
        core.CFG["restart"] = True
        save_conf(interval=seconds)

    def _apply_level(self):
        import AppKit
        import Quartz
        if self.nswindow is None:
            return
        if self.pinned:
            level = AppKit.NSStatusWindowLevel
            behavior = self.nswindow.collectionBehavior() & ~AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        else:
            # One level BELOW normal windows: above the desktop/Finder layer
            # (so it still receives mouse events — the desktop-icon layer is
            # covered by Finder's own window and swallows clicks), below every
            # app window, like a real macOS desktop widget.
            level = Quartz.CGWindowLevelForKey(Quartz.kCGNormalWindowLevelKey) - 1
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
    import socket
    with socket.socket() as s:  # single instance: the shortcut is safe to spam
        if s.connect_ex(("127.0.0.1", core.PORT)) == 0:
            print("EVO-X2 widget is already running")
            return
    conf = load_conf()
    from AppKit import NSScreen
    screen = NSScreen.mainScreen().frame()
    sw, sh = int(screen.size.width), int(screen.size.height)
    core.CFG["interval"] = int(conf.get("interval", core.CFG.get("interval", 2)))
    api = Api()
    core.start()
    win = webview.create_window(
        "EVO-X2", f"http://127.0.0.1:{core.PORT}/?widget=1",
        width=conf.get("w", 400), height=conf.get("h", min(sh - 140, 860)),
        x=conf.get("x", sw - 400 - 50), y=conf.get("y", 60),
        frameless=True, on_top=False, resizable=True,
        easy_drag=True, transparent=True, js_api=api)
    api.win = win
    api.pinned = bool(conf.get("pin", False))

    def promote_to_desktop_widget():
        # no Dock icon, no Cmd-Tab; unpinned it sits just below all app
        # windows, like a real macOS desktop widget
        import AppKit
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        nsw = get_ns_window(win)
        if nsw is not None:
            api.nswindow = nsw
            api._apply_level()
            nsw.setOpaque_(False)
            nsw.setBackgroundColor_(AppKit.NSColor.clearColor())

    win.events.loaded += promote_to_desktop_widget

    def remember():
        # pywebview has no get_positions() in this version; read the NSWindow.
        # Cocoa origin is bottom-left; conf stores top-left like create_window.
        try:
            nsw = api.nswindow or get_ns_window(win)
            if nsw is None:
                return
            f = nsw.frame()
            sh = NSScreen.mainScreen().frame().size.height
            save_conf(x=int(f.origin.x), y=int(sh - f.origin.y - f.size.height),
                      w=int(f.size.width), h=int(f.size.height))
        except Exception:  # noqa: BLE001 — geometry save is best-effort
            pass

    win.events.closed += remember

    # The × button hard-terminates the app (no closed handler runs), so keep
    # geometry fresh in conf from a daemon thread instead.
    import threading
    import time as _t

    def autosave():
        last = None
        while True:
            _t.sleep(5)
            try:
                if api.nswindow is None:
                    continue
                f = api.nswindow.frame()
                sh = NSScreen.mainScreen().frame().size.height
                geo = dict(x=int(f.origin.x), y=int(sh - f.origin.y - f.size.height),
                           w=int(f.size.width), h=int(f.size.height))
                if geo != last:
                    save_conf(**geo)
                    last = geo
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=autosave, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
