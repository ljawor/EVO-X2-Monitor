#!/usr/bin/env python3
"""EVO-X2 health monitor — fires from the Mac, reads the Ubuntu box over SSH.

Usage:
    ./bin/evo_x2_monitor.py                 # live dashboard, 2 s refresh
    ./bin/evo_x2_monitor.py --interval 5
    ./bin/evo_x2_monitor.py --once          # single snapshot, no redraw

How it works: streams bin/collector.py (stdlib only) into a single persistent
`ssh ... python3 -` session; the box emits one JSON snapshot per line and this
script redraws a terminal dashboard locally. Nothing is installed on the box;
nothing probes llama-server's :8080 port (service state comes from systemctl).

Ctrl-C to quit. SSH drops are auto-reconnected.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HOST = "lukasz@192.168.1.24"
KEY = os.path.expanduser("~/.ssh/evo_x2")
HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "collector.py")

ap = argparse.ArgumentParser()
ap.add_argument("--interval", type=float, default=2.0)
ap.add_argument("--host", default=HOST)
ap.add_argument("--key", default=KEY)
ap.add_argument("--once", action="store_true")
A = ap.parse_args()

# ---- ANSI ------------------------------------------------------------------
ESC = "\x1b"
CLEAR = ESC + "[2J" + ESC + "[H"
HIDE = ESC + "[?25l"
SHOW = ESC + "[?25h"
HOME = ESC + "[H"
RST = ESC + "[0m"
DIM = ESC + "[2m"
BOLD = ESC + "[1m"
RED, GRN, YEL, CYN, MAG = (ESC + f"[{31+i*2}m" for i in range(5))


def tcol(v_c):  # temperature colour: <80 dim-green, <90 yellow, else red
    if v_c is None:
        return DIM
    return GRN if v_c < 80 else (YEL if v_c < 90 else RED)


def bar(pct, width=24):
    pct = max(0.0, min(100.0, pct))
    n = round(pct * width / 100)
    col = GRN if pct < 70 else (YEL if pct < 90 else RED)
    return f"{col}{'█' * n}{DIM}{'░' * (width - n)}{RST} {pct:4.0f}%"


def gbps(bps):
    for unit, div in (("GB/s", 1e9), ("MB/s", 1e6), ("kB/s", 1e3), ("B/s", 1)):
        if bps >= div or unit == "B/s":
            return f"{bps / div:6.1f} {unit}"
    return "     0 B/s"


def gib(n):
    return f"{n / 2**30:5.1f}"


def fmt_up(s):
    d, r = divmod(int(s), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d}d " if d else "") + f"{h}h {m:02d}m"


def mini2(pct):
    ch = "." if pct < 5 else ("-" if pct < 20 else ("+" if pct < 40 else ("*" if pct < 75 else "#")))
    col = DIM if pct < 5 else (GRN if pct < 75 else (YEL if pct < 92 else RED))
    return f"{col}{ch}{RST}"


def render(s, W):
    L = []
    llama = s["llama"]
    lcol = GRN if llama == "active" else RED
    L.append(f"{BOLD}{CYN}EVO-X2{RST}  up {fmt_up(s['uptime_s'])}   "
             f"load {s['load1']:.2f} {s['load5']:.2f}   run {DIM}{s['run']}{RST}   "
             f"llama-server {lcol}●{llama}{RST}")

    agg = s["cpu_pct"].get("cpu", 0.0)
    ct = s["cpu_temp"]
    L.append(f"CPU  {bar(agg)}   Tctl {tcol(ct)}{ct/1000:5.1f}°C{RST}")
    cores = [v for k, v in sorted(s["cpu_pct"].items()) if k != "cpu"]
    per_row = max(8, W // 4)
    for i in range(0, len(cores), per_row):
        row = " ".join(mini2(c) for c in cores[i:i + per_row])
        L.append(f"     {row}")

    gt = s["gpu_temp"]
    vram_u, vram_t = s["vram_used"], s["vram_total"]
    gtt = s.get("gtt_kib")
    gtt_s = f"  GTT {gib(gtt * 1024)}G" if gtt else f"  GTT {DIM}n/a{RST}"
    L.append(f"GPU  {bar(s['gpu_busy'])}   edge {tcol(gt)}{gt/1000:5.1f}°C{RST}"
             f"   VRAM {gib(vram_u)}/{gib(vram_t)}G{gtt_s}")

    mt, ma = s["mem_total_kib"] * 1024, s["mem_avail_kib"] * 1024
    used = mt - ma
    L.append(f"RAM  {bar(100.0 * used / mt)}   used {gib(used)} / {gib(mt)}G   free {gib(ma)}G")
    st_, sf = s["swap_total_kib"], s["swap_free_kib"]
    if st_:
        L.append(f"SWAP {bar(100.0 * (st_ - sf) / st_)}")

    d = s["io"].get("nvme0n1", (0.0, 0.0))
    dt_, df_ = s["disk_total"], s["disk_free"]
    dpct = 100.0 * (dt_ - df_) / dt_
    nt = s["nvme_temp"]
    L.append(f"SSD  {bar(dpct)} used   io {gbps(d[0])}r {gbps(d[1])}w   "
             f"{tcol(nt)}{nt/1000:5.1f}°C{RST}" if nt else
             f"SSD  {bar(dpct)} used   io {gbps(d[0])}r {gbps(d[1])}w")

    n = s["net"]
    L.append(f"NET  down {gbps(n[0])}   up {gbps(n[1])}")
    L.append(f"{DIM}{'─' * min(W, 78)}{RST}")
    return "\n".join(L)


def main():
    if not os.path.exists(COLLECTOR):
        sys.exit(f"collector.py not found next to this script: {COLLECTOR}")
    src = open(COLLECTOR).read()
    ssh = ["ssh", "-i", A.key, "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15",
           "-o", "ConnectTimeout=5", A.host, "python3", "-", "--interval", str(A.interval)]
    if A.once:
        r = subprocess.run(ssh + ["--once"], input=src, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr.strip() or "collector failed")
        print(render(json.loads(r.stdout.strip()), 80))
        return

    print(CLEAR + HIDE, end="", flush=True)
    try:
        while True:
            p = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)
            assert p.stdin is not None and p.stdout is not None
            p.stdin.write(src)
            p.stdin.close()
            try:
                for line in p.stdout:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        s = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    W = shutil.get_terminal_size((100, 30)).columns
                    sys.stdout.write(HOME + render(s, W) + "\n")
                    sys.stdout.flush()
            except BrokenPipeError:
                pass
            p.wait()
            sys.stdout.write(HOME + f"\n{YEL}SSH dropped — reconnecting…{RST}\n")
            sys.stdout.flush()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW, end="")


main()
