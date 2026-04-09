#!/usr/bin/env python3
"""
Ask Through You — Launcher
--------------------------
Double-click to start. No command line needed.

Automatically reads the bootstrap peer list,
shows available countries, and starts the node.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


# ================= .env =================

def load_dotenv_file(filename: str = ".env") -> None:
    env_path = Path(filename)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"')) or
            (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


# ================= DEPENDENCIES =================

def ensure_dependencies() -> None:
    missing = []
    try:
        import dns.resolver  # noqa: F401
    except ImportError:
        missing.append("dnspython")
    try:
        import dnslib  # noqa: F401
    except ImportError:
        missing.append("dnslib")

    if missing:
        print(f"Installing missing dependencies: {', '.join(missing)}")
        subprocess.call(
            [sys.executable, "-m", "pip", "install", "-q"] + missing
        )
        print("Done.\n")


# ================= BOOTSTRAP =================

def get_bootstrap_urls() -> list[str]:
    env = os.getenv("ATY_BOOTSTRAP_URLS", "").strip()
    if not env:
        return []
    return [u.strip() for u in env.split(",") if u.strip()]


def fetch_peers(url: str) -> list[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AskThroughYou-Launcher/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []


def collect_countries() -> list[tuple[str, int]]:
    urls = get_bootstrap_urls()
    if not urls:
        return []

    counts: dict[str, int] = {}
    for url in urls:
        try:
            peers = fetch_peers(url)
        except Exception as e:
            print(f"Bootstrap failed: {url} -> {e}")
            continue
        for peer in peers:
            cc = str(peer.get("country_code", "")).strip().upper()
            if not cc or cc == "??":
                continue
            counts[cc] = counts.get(cc, 0) + 1

    return sorted(counts.items(), key=lambda x: x[0])


# ================= UI =================

def choose_country(countries: list[tuple[str, int]]) -> str:
    if not countries:
        print("No countries available.")
        print("The network may be empty or bootstrap is unreachable.")
        print("Check your internet connection and try again.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print("Available countries:\n")
    for i, (cc, count) in enumerate(countries, start=1):
        print(f"  {i:2d}.  {cc}  ({count} node{'s' if count != 1 else ''})")

    print()
    while True:
        choice = input("Choose a number: ").strip()
        try:
            index = int(choice)
            if 1 <= index <= len(countries):
                return countries[index - 1][0]
        except ValueError:
            pass
        print("Invalid choice. Try again.")


# ================= MAIN =================

def main() -> int:
    os.system("cls" if os.name == "nt" else "clear")

    print("=" * 50)
    print("  Ask Through You")
    print("  Ask the internet through someone else.")
    print("=" * 50)
    print()

    load_dotenv_file()
    ensure_dependencies()

    print("Loading available countries...\n")
    countries = collect_countries()
    country = choose_country(countries)

    print(f"\nStarting node — routing through {country}...\n")
    print("Browser DNS endpoint:")
    print("  http://127.0.0.1:53535/dns-query")
    print()
    print("Node status:")
    print("  http://127.0.0.1:53535/status")
    print()
    print("Press Ctrl+C to stop.\n")

    try:
        return subprocess.call(
            [sys.executable, "askthroughyou.py", "--country", country]
        )
    except KeyboardInterrupt:
        pass

    print("\nAsk Through You stopped.")
    input("Press Enter to exit...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
