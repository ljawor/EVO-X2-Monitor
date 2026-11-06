"""Shared core for the EVO-X2 desktop widget: SSH stream + loopback HTTP.

Streams bin/collector.py over one persistent ssh session, keeps a ring
buffer of snapshots, and serves them (plus the dashboard) on
127.0.0.1:8765. :8080 (llama-server) is never probed.
"""
import collections
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "lukasz@192.168.1.24"
KEY = os.path.expanduser("~/.ssh/evo_x2")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COLLECTOR = os.path.join(HERE, "collector.py")
DASHBOARD = os.path.join(ROOT, "web", "dashboard.html")
PORT = 8765
INTERVALS = [1, 2, 5, 10, 30, 60, 300]

STATE = {"snap": None, "err": None}
HISTORY = collections.deque(maxlen=900)
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
        except Exception as e:  # noqa: BLE001 — surface, don't die
            with LOCK:
                STATE["err"] = str(e)
        if not CFG["restart"]:
            time.sleep(3)


def latest():
    with LOCK:
        return {"interval": CFG["interval"], "err": STATE["err"],
                "history": list(HISTORY)}


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
        if self.path.split("?")[0] in ("/", "/index.html"):
            try:
                self._send(200, "text/html; charset=utf-8", open(DASHBOARD, "rb").read())
            except OSError as e:
                self._send(500, "text/plain", str(e).encode())
        elif self.path == "/history.json":
            self._send(200, "application/json", json.dumps(latest()).encode())
        else:
            self._send(404, "text/plain", b"not found")


def serve_forever():
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


def start():
    threading.Thread(target=stream_loop, daemon=True).start()
    threading.Thread(target=serve_forever, daemon=True).start()
