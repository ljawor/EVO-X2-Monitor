# EVO-X2 Monitor — Design

Terminal health dashboard for the GMKtec EVO-X2 (Ryzen AI Max+ 395 /
Radeon 8060S, 128 GB, Ubuntu 24.04), fired from the Mac over SSH.

## Architecture

```
Mac                                    EVO-X2 (192.168.1.24)
bin/evo_x2_monitor.py  ──ssh──▶  python3 -  (bin/collector.py streamed via stdin)
  redraws ANSI dashboard          emits one JSON snapshot per line
  every --interval seconds        reads only /proc + /sys + systemctl
```

- One persistent SSH session; drops auto-reconnect.
- **Nothing installed on the box** — the collector is streamed over stdin and is
  stdlib-only Python on both sides.
- **Never probes `:8080`** — llama-server state comes from
  `systemctl is-active` (probing the port would queue behind live chats and
  evict the prompt cache).

## Metrics

| Row | Metric | Source |
|---|---|---|
| Header | uptime, load avg, runnable, llama-server state | `/proc/uptime`, `/proc/loadavg`, `systemctl is-active` |
| CPU | aggregate % + 32-core grid (`. - + * #`), Tctl | `/proc/stat` delta, `k10temp` hwmon |
| GPU | busy %, edge °C, VRAM | `gpu_busy_percent`, `amdgpu` hwmon, `mem_info_vram_*` |
| RAM | used/total/free, swap | `/proc/meminfo` |
| SSD | root used %, read/write MB/s, NVMe °C | `statvfs`, `/proc/diskstats` delta, `nvme` hwmon |
| NET | LAN down/up MB/s | `/proc/net/dev` delta |

Colours: green < 70 %, yellow < 90 %, red above; temps green < 80 °C,
yellow < 90 °C, red above.

## Known limits

- **GTT usage shows `n/a`**: this kernel (7.0.0-xx) exposes no
  amdgpu/TTM sysfs or debugfs file for GTT occupancy. RAM "used" is the
  working proxy — the 95 GB model is shared RAM by design.
- Verified live 2026-11-05: idle 0 %, synthetic 8×`yes` load showed exactly
  8 cores at 100 % and 25 % aggregate; Tctl 62–68 °C; llama-server `active`.

## Run

```bash
./bin/evo_x2_monitor.py            # live dashboard, 2 s refresh
./bin/evo_x2_monitor.py --once     # single snapshot
./bin/evo_x2_monitor.py --interval 5 --host lukasz@192.168.1.24
```
