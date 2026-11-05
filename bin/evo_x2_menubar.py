#!/usr/bin/env python3
"""EVO-X2 menu-bar widget for macOS.

Menu bar title:  CPUtemp · CPU% · RAM%   (live)
Dropdown:        full details, refresh-interval picker, dashboard launcher.
Dashboard:       http://127.0.0.1:8765/ — gauges + history graphs (web/).

Streams bin/collector.py into one persistent ssh session, same as the
terminal monitor; :8080 is never probed. Run inside the repo venv:
    .venv/bin/python bin/evo_x2_menubar.py
"""
import collections
import json
import os
import subprocess
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rumps

HOST = "lukasz@192.168.1.24"
KEY = os.path.expanduser("~/.ssh/evo_x2")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COLLECTOR = os.path.join(HERE, "collector.py")
DASHBOARD = os.path.join(ROOT, "web", "dashboard.html")
PORT = 8765
INTERVALS = [1, 2, 5, 10, 30, 60, 300]

STATE = {"snap": None, "err": None}
HISTORY = collections.deque(maxlen=900)  # ~30 min at 2 s
LOCK = threading.Lock()
CFG = {"interval": 2, "restart": False}


def stream_loop():
    """Keep one ssh stream alive forever; feed STATE/HISTORY."""
    src = open(COLLECTOR).read()
    while True:
        ssh = ["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15",
               "-o", "ConnectTimeout=5", HOST,
               "python3", "-", "--interval", str(CFG["interval"])]
        try:
            p = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)
            assert p.stdin is not None and p.stdout is not None
            p.stdin.write(src)
            p.stdin.close()
            for line in p.stdout:
                if CFG["restart"]:
                    CFG["restart"] = False
                    p.kill()
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    s = json.loads(line)
                except json.JSONDecodeError:
                    continue
                with LOCK:
                    STATE["snap"], STATE["err"] = s, None
                    HISTORY.append(s)
            p.wait()
        except Exception as e:  # noqa: BLE001 — surface in the menu instead of dying
            with LOCK:
                STATE["err"] = str(e)
        if not CFG["restart"]:
            time.sleep(3)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            try:
                body = open(DASHBOARD, "rb").read()
                self._send(200, "text/html; charset=utf-8", body)
            except OSError as e:
                self._send(500, "text/plain", str(e).encode())
        elif self.path == "/history.json":
            with LOCK:
                body = json.dumps({"interval": CFG["interval"],
                                   "history": list(HISTORY)}).encode()
            self._send(200, "application/json", body)
        else:
            self._send(404, "text/plain", b"not found")


class Monitor(rumps.App):
    def __init__(self):
        super().__init__("EVO-X2 …", quit_button=None)
        self._build_menu()
        threading.Thread(target=stream_loop, daemon=True).start()
        threading.Thread(target=self._serve, daemon=True).start()
        self.timer = rumps.Timer(self.tick, 1)
        self.timer.start()

    # ------------------------------------------------------------------ menu
    def _build_menu(self):
        self.about = rumps.MenuItem("Connecting to EVO-X2…", callback=None)
        self.sep1 = rumps.separator
        self.interval_menu = rumps.MenuItem("Refresh every")
        for iv in INTERVALS:
            item = rumps.MenuItem(f"{iv} s" + ("  ●" if iv == CFG["interval"] else ""),
                                  callback=partial(self.set_interval, iv))
            self.interval_menu.add(item)
        self.dash = rumps.MenuItem("Open dashboard (graphs)…",
                                   callback=self.open_dashboard)
        self.sep2 = rumps.separator
        self.quit = rumps.MenuItem("Quit", callback=rumps.quit_application)
        self.menu = [self.about, self.sep1, self.interval_menu, self.dash,
                     self.sep2, self.quit]

    def set_interval(self, _sender, seconds):
        CFG["interval"] = seconds
        CFG["restart"] = True
        for sub in self.interval_menu.menu:
            sub.title = sub.title.replace("  ●", "")
            if sub.title == f"{seconds} s":
                sub.title += "  ●"

    def open_dashboard(self, _sender):
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{PORT}/")

    # ------------------------------------------------------------------ tick
    def tick(self, _timer):
        with LOCK:
            s, err = STATE["snap"], STATE["err"]
        if not s:
            self.title = "EVO-X2 ✕" if err else "EVO-X2 …"
            return
        cpu_t = s["cpu_temp"] / 1000 if s.get("cpu_temp") else 0
        ram = 100.0 * (s["mem_total_kib"] - s["mem_avail_kib"]) / s["mem_total_kib"]
        self.title = f"{cpu_t:.0f}° · {s['cpu_pct'].get('cpu', 0):.0f}% · {ram:.0f}%"
        self.about.title = self.render(s)

    @staticmethod
    def render(s):
        g = lambda k, d=0: s.get(k) or d  # noqa: E731
        ram_u = (g("mem_total_kib") - g("mem_avail_kib")) / 2**20
        ram_t = g("mem_total_kib") / 2**20
        dsk = 100.0 * (g("disk_total") - g("disk_free")) / max(g("disk_total"), 1)
        io = g("io", {}).get("nvme0n1", [0, 0])
        gpu_t = g("gpu_temp", 0) / 1000
        nv_t = g("nvme_temp", 0) / 1000
        net = g("net", [0, 0])
        return (
            f"CPU  {s['cpu_pct'].get('cpu', 0):4.0f}%   Tctl {g('cpu_temp', 0)/1000:5.1f}°C\n"
            f"GPU  {g('gpu_busy'):4.0f}%   edge {gpu_t:5.1f}°C   "
            f"VRAM {g('vram_used')/2**30:.1f}/{g('vram_total')/2**30:.1f}G\n"
            f"RAM  {ram_u:5.1f}/{ram_t:.1f}G   swap {100.0*(1-g('swap_free_kib')/max(g('swap_total_kib'),1)):3.0f}%\n"
            f"SSD  {dsk:3.0f}% used   {io[0]/2**20:6.1f}r {io[1]/2**20:6.1f}w MB/s   {nv_t:4.1f}°C\n"
            f"NET  ↓{net[0]/2**20:7.1f}  ↑{net[1]/2**20:7.1f} MB/s\n"
            f"load {s.get('load1', 0):.2f}   llama-server {s.get('llama', '?')}"
        )

    def _serve(self):
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    Monitor().run()
