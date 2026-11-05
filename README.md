# EVO-X2-Monitor

Health monitor for the GMKtec EVO-X2 (Ryzen AI Max+ 395 / Radeon 8060S, 128 GB,
Ubuntu 24.04) fired from the Mac over SSH.

## Status

v1 working — live dashboard in [`bin/`](bin/), design in [docs/PROPOSAL.md](docs/PROPOSAL.md).

```bash
./bin/evo_x2_monitor.py            # 2 s live refresh; --once for a single snapshot
```

## Connect

```bash
ssh -i ~/.ssh/evo_x2 lukasz@192.168.1.24
```

## Sensors verified on the host (2026-11-05)

| Metric | Source |
|---|---|
| CPU temp | `k10temp` hwmon — `Tctl` |
| GPU busy | `/sys/class/drm/card1/device/gpu_busy_percent` |
| GPU temp | `amdgpu` hwmon (edge) |
| VRAM | `/sys/class/drm/card1/device/mem_info_vram_{used,total}` + GTT via TTM |
| SSD temp | `nvme` hwmon — Composite |
| Per-core load | `/proc/stat` delta |
| RAM / swap | `free -b` / `/proc/meminfo` |
| Disk usage | `df -B1 /` |
| Network | `/proc/net/dev` delta |
| llama-server | `systemctl is-active llama-server` (never probe `:8080`) |
