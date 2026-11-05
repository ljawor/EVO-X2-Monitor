#!/usr/bin/env python3
"""Collector for the EVO-X2 health monitor. Runs ON the EVO-X2 (Ubuntu).

Emits one compact JSON snapshot per line to stdout, every --interval seconds.
Read-only: /proc, /sys, one `systemctl is-active`. Never touches :8080.
Local renderer: bin/evo_x2_monitor.py (this file is embedded in it).
"""
import argparse
import glob
import json
import os
import subprocess
import time

ap = argparse.ArgumentParser()
ap.add_argument("--interval", type=float, default=2.0)
ap.add_argument("--once", action="store_true")
A = ap.parse_args()


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def read_words(path):
    return read(path).split()


# ---------------------------------------------------------------- hwmon scan
def hwmon_temps():
    """Return {chip_name: max_milli_degC} from /sys/class/hwmon."""
    out = {}
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        name = read(d + "/name").strip()
        best = None
        for t in glob.glob(d + "/temp*_input"):
            try:
                v = int(read(t).strip())
            except ValueError:
                continue
            if best is None or v > best:
                best = v
        if best is not None and name not in out:
            out[name] = best
    return out


# ------------------------------------------------------------------ /proc I/O
def cpu_sample():
    """Per-cpu + aggregate busy/total ticks."""
    rows = {}
    for line in read("/proc/stat").splitlines():
        w = line.split()
        if not w or not (w[0] == "cpu" or w[0].startswith("cpu")):
            continue
        f = list(map(int, w[1:]))
        idle = f[3] + (f[4] if len(f) > 4 else 0)
        rows[w[0]] = (sum(f), idle)
    return rows


def delta_pct(prev, cur):
    out = {}
    for k, (ct, ci) in cur.items():
        pt, pi = prev.get(k, (ct, ci))
        dt, di = ct - pt, ci - pi
        out[k] = 100.0 * (1.0 - di / dt) if dt > 0 else 0.0
    return out


DISK_SKIP = ("loop", "ram", "dm-", "zram", "fd", "sr")


def io_sample():
    sectors = {}
    for line in read("/proc/diskstats").splitlines():
        w = line.split()
        if len(w) < 14:
            continue
        name = w[2]
        if name.startswith(DISK_SKIP):
            continue
        sectors[name] = (int(w[5]), int(w[9]))  # sectors read, written
    return sectors


def io_rates(prev, cur, dt):
    out = {}
    for name, (r, w) in cur.items():
        pr, pw = prev.get(name, (r, w))
        out[name] = ((r - pr) * 512.0 / dt, (w - pw) * 512.0 / dt)
    return out


def net_sample():
    tot = [0, 0]
    for line in read("/proc/net/dev").splitlines()[2:]:
        p = line.split(":")
        if len(p) != 2:
            continue
        if p[0].strip() == "lo":
            continue
        w = p[1].split()
        tot[0] += int(w[0])
        tot[1] += int(w[8])
    return tot


# --------------------------------------------------------------------- amdgpu
def drm_node():
    for c in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        if os.path.exists(c + "/device/gpu_busy_percent"):
            return c
    return None


def gtt_used_bytes():
    """GTT/TTM in use: amdgpu debugfs memory_info, else /proc/meminfo Shmem heuristics.

    debugfs needs root; when unreadable we report None and the renderer shows GTT n/a.
    """
    for p in ("/sys/kernel/debug/dri/1/memory_info", "/sys/kernel/debug/dri/0/memory_info"):
        txt = read(p)
        for line in txt.splitlines():
            w = line.split()
            if len(w) == 2 and w[0].lower().startswith("gtt") and w[1].isdigit():
                return int(w[1])  # kB
    return None


# --------------------------------------------------------------------- sample
DRM = drm_node()
LAST_SYSCTL = [0.0, "unknown"]


def snapshot(prev_cpu, prev_io, prev_net, prev_t):
    now = time.time()
    dt = max(now - prev_t, 1e-6)
    cpu = cpu_sample()
    io = io_sample()
    net = net_sample()
    temps = hwmon_temps()

    mem = {}
    for line in read("/proc/meminfo").splitlines():
        w = line.split()
        if len(w) >= 2:
            mem[w[0].rstrip(":")] = int(w[1])  # kB

    df = read("/proc/mounts")  # cheap; use statvfs instead
    st = os.statvfs("/")

    if now - LAST_SYSCTL[0] > 5:
        try:
            r = subprocess.run(["systemctl", "is-active", "llama-server"],
                               capture_output=True, text=True, timeout=2)
            LAST_SYSCTL[1] = r.stdout.strip() or "inactive"
        except Exception:
            LAST_SYSCTL[1] = "unknown"
        LAST_SYSCTL[0] = now

    la = read("/proc/loadavg").split()
    up = read("/proc/uptime").split()

    snap = {
        "t": round(now, 1),
        "cpu_pct": delta_pct(prev_cpu, cpu),
        "cpu_temp": temps.get("k10temp"),
        "acpitz": temps.get("acpitz"),
        "gpu_busy": int(read(DRM + "/device/gpu_busy_percent").strip() or 0) if DRM else 0,
        "gpu_temp": temps.get("amdgpu"),
        "vram_used": int(read(DRM + "/device/mem_info_vram_used").strip() or 0) if DRM else 0,
        "vram_total": int(read(DRM + "/device/mem_info_vram_total").strip() or 0) if DRM else 0,
        "gtt_kib": gtt_used_bytes(),
        "nvme_temp": temps.get("nvme"),
        "io": io_rates(prev_io, io, dt),
        "net": [(net[0] - prev_net[0]) / dt, (net[1] - prev_net[1]) / dt],
        "mem_total_kib": mem.get("MemTotal", 0),
        "mem_avail_kib": mem.get("MemAvailable", 0),
        "swap_total_kib": mem.get("SwapTotal", 0),
        "swap_free_kib": mem.get("SwapFree", 0),
        "disk_total": st.f_blocks * st.f_frsize,
        "disk_free": st.f_bfree * st.f_frsize,
        "load1": float(la[0]) if la else 0.0,
        "load5": float(la[1]) if len(la) > 1 else 0.0,
        "load15": float(la[2]) if len(la) > 2 else 0.0,
        "run": la[3] if len(la) > 3 else "",
        "uptime_s": int(float(up[0])) if up else 0,
        "llama": LAST_SYSCTL[1],
    }
    return cpu, io, net, snap


def main():
    prev_cpu, prev_io, prev_net, prev_t = {}, {}, [0, 0], time.time()
    prev_cpu, prev_io, prev_net, s = snapshot(prev_cpu, prev_io, prev_net, prev_t)
    if A.once:
        # first snapshot's rates are against zero — sample once more
        time.sleep(max(A.interval, 1.0))
        prev_cpu, prev_io, prev_net, s = snapshot(prev_cpu, prev_io, prev_net, prev_t)
        print(json.dumps(s, separators=(",", ":")))
        return
    prev_t = time.time()
    while True:
        time.sleep(A.interval)
        prev_cpu, prev_io, prev_net, s = snapshot(prev_cpu, prev_io, prev_net, prev_t)
        prev_t = time.time()
        print(json.dumps(s, separators=(",", ":")), flush=True)


main()
