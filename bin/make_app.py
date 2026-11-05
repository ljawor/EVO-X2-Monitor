#!/usr/bin/env python3
"""Build EVO X2 Monitor.app — double-clickable menu-bar app from this repo.

Writes build/EVO X2 Monitor.app whose launcher calls this repo's venv,
so `git pull` updates the app in place. Then:
    open build/EVO\\ X2\\ Monitor.app     (or drag to /Applications)
"""
import os
import stat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "build", "EVO X2 Monitor.app")
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>CFBundleName</key><string>EVO X2 Monitor</string>
 <key>CFBundleIdentifier</key><string>local.ljawor.evox2monitor</string>
 <key>CFBundleVersion</key><string>1.0</string>
 <key>CFBundlePackageType</key><string>APPL</string>
 <key>LSUIElement</key><true/>
 <key>NSHighResolutionCapable</key><true/>
</dict></plist>
"""


def touch(path, content=None, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if content is not None:
        with open(path, "w") as f:
            f.write(content)
    if mode is not None:
        os.chmod(path, mode)


for d in ("Contents/MacOS",):
    os.makedirs(os.path.join(APP, d), exist_ok=True)
touch(os.path.join(APP, "Contents/Info.plist"), PLIST)
launcher = (
    "#!/bin/sh\n"
    f'exec "{os.path.join(ROOT, ".venv", "bin", "python")}" '
    f'"{os.path.join(ROOT, "bin", "evo_x2_menubar.py")}"\n'
)
touch(os.path.join(APP, "Contents/MacOS/EVO X2 Monitor"),
      launcher, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
print("built:", APP)
