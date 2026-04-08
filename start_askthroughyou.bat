Windows doppio click
@echo off
cd /d "%~dp0"
python start_askthroughyou.py
pause
..........
Linux Launcher
#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 start_askthroughyou.py
poi
chmod +x start_askthroughyou.sh
......................
Android/Termux
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
python start_askthroughyou.py
