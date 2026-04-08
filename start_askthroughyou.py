#!/usr/bin/env python3
"""
Ask Through You Launcher
------------------------
Mostra automaticamente tutti i paesi disponibili
leggendo la peer list bootstrap, poi avvia il nodo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


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
            print(f"Bootstrap fallito: {url} -> {e}")
            continue

        for peer in peers:
            cc = str(peer.get("country_code", "")).strip().upper()
            if not cc:
                continue
            counts[cc] = counts.get(cc, 0) + 1

    return sorted(counts.items(), key=lambda x: x[0])


def choose_country(countries: list[tuple[str, int]]) -> str:
    if not countries:
        print("Nessun paese disponibile trovato.")
        sys.exit(1)

    print("\nPaesi disponibili:\n")
    for i, (cc, count) in enumerate(countries, start=1):
        print(f"{i:2d}. {cc}  ({count} nodes)")

    while True:
        choice = input("\nScegli il numero del paese: ").strip()
        try:
            index = int(choice)
            if 1 <= index <= len(countries):
                return countries[index - 1][0]
        except ValueError:
            pass
        print("Scelta non valida.")


def main() -> int:
    load_dotenv_file()

    countries = collect_countries()
    country = choose_country(countries)

    print(f"\nAvvio Ask Through You con paese: {country}\n")

    cmd = [sys.executable, "askthroughyou.py", "--country", country]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
