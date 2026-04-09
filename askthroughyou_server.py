#!/usr/bin/env python3
"""
Ask Through You — Bootstrap Server

Functions:
- registers nodes
- updates keepalive
- writes peers.json to GitHub
- keeps the peer list clean

Designed for:
- Synology NAS
- Linux
- any always-on small server
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from typing import Any, Optional

from flask import Flask, jsonify, request
import requests

# ================= LOG =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("askthroughyou-server")

# ================= CONFIG =================

APP_NAME = "askthroughyou-server"
APP_VERSION = "1.0"

HOST = os.getenv("ATY_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("ATY_SERVER_PORT", "8090"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
REPO_OWNER = os.getenv("ATY_REPO_OWNER", "").strip()
REPO_NAME = os.getenv("ATY_REPO_NAME", "askthroughyou_peers").strip()
FILE_PATH = os.getenv("ATY_FILE_PATH", "peers.json").strip()
BRANCH = os.getenv("ATY_BRANCH", "main").strip()

DEFAULT_NODE_PORT = int(os.getenv("ATY_DEFAULT_NODE_PORT", "35353"))
MAX_PEER_AGE = int(os.getenv("ATY_MAX_PEER_AGE", "900"))

REQUIRE_TOKEN = os.getenv("ATY_REQUIRE_API_TOKEN", "0").strip() == "1"
API_TOKEN = os.getenv("ATY_API_TOKEN", "").strip()

REQUEST_TIMEOUT = int(os.getenv("ATY_REQUEST_TIMEOUT", "15"))

# ================= APP =================

app = Flask(__name__)
repo_lock = threading.Lock()


# ================= HELPERS =================

def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_contents_url() -> str:
    return f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"


def sanitize_port(value: Any) -> int:
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except Exception:
        pass
    return DEFAULT_NODE_PORT


def sanitize_country_code(value: Any) -> str:
    cc = str(value or "").strip().upper()
    if len(cc) == 2 and cc.isalpha():
        return cc
    return "??"


def sanitize_node_id(value: Any) -> str:
    node_id = str(value or "").strip()
    return node_id[:64]


def normalize_ip(value: Any) -> str:
    return str(value or "").strip()


def get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return normalize_ip(request.remote_addr)


def require_api_token() -> Optional[tuple[Any, int]]:
    if not REQUIRE_TOKEN:
        return None
    token = request.headers.get("X-API-Token", "").strip()
    if not token or token != API_TOKEN:
        return jsonify({"ok": False, "error": "UNAUTHORIZED"}), 401
    return None


def cleanup_peers(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - MAX_PEER_AGE
    cleaned = []
    for peer in peers:
        try:
            last_seen = int(peer.get("last_seen", 0))
        except Exception:
            last_seen = 0
        if last_seen >= cutoff:
            cleaned.append(peer)
    return cleaned


def load_peers_from_github() -> tuple[list[dict[str, Any]], Optional[str]]:
    url = f"{github_contents_url()}?ref={BRANCH}"
    resp = requests.get(url, headers=github_headers(), timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        return [], None
    resp.raise_for_status()
    data = resp.json()
    raw = base64.b64decode(data.get("content", "")).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        parsed = []
    return parsed, data.get("sha")


def save_peers_to_github(peers: list[dict[str, Any]], sha: Optional[str], message: str) -> None:
    encoded = base64.b64encode(
        json.dumps(peers, indent=2).encode("utf-8")
    ).decode("utf-8")
    payload: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(
        github_contents_url(),
        headers=github_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


def build_peer_entry(ip: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    entry: dict[str, Any] = {
        "ip": ip,
        "port": sanitize_port(payload.get("port")),
        "country_code": sanitize_country_code(payload.get("country_code")),
        "last_seen": now,
    }
    node_id = sanitize_node_id(payload.get("node_id"))
    if node_id:
        entry["node_id"] = node_id
    # optional fields
    for key in ("country", "region", "city", "org", "asn"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            entry[key] = value[:128]
    return entry


def upsert_peer(peers: list[dict[str, Any]], new_entry: dict[str, Any]) -> list[dict[str, Any]]:
    ip = new_entry["ip"]
    node_id = new_entry.get("node_id", "")
    updated = False
    result: list[dict[str, Any]] = []
    for peer in peers:
        same_ip = normalize_ip(peer.get("ip")) == ip
        same_node = bool(node_id) and str(peer.get("node_id", "")).strip() == node_id
        if same_ip or same_node:
            result.append(new_entry)
            updated = True
        else:
            result.append(peer)
    if not updated:
        result.append(new_entry)
    return result


def github_ready() -> bool:
    return bool(GITHUB_TOKEN and REPO_OWNER and REPO_NAME and FILE_PATH and BRANCH)


# ================= ROUTES =================

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "github_ready": github_ready(),
    })


@app.get("/peers")
def peers():
    try:
        auth_error = require_api_token()
        if auth_error:
            return auth_error
        with repo_lock:
            raw_peers, _ = load_peers_from_github()
            cleaned = cleanup_peers(raw_peers)
        return jsonify({
            "ok": True,
            "count": len(cleaned),
            "peers": cleaned,
        })
    except Exception as e:
        log.exception("Error /peers")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/register")
def register():
    try:
        auth_error = require_api_token()
        if auth_error:
            return auth_error
        if not github_ready():
            return jsonify({"ok": False, "error": "SERVER_NOT_CONFIGURED"}), 500
        client_ip = get_client_ip()
        if not client_ip:
            return jsonify({"ok": False, "error": "NO_IP"}), 400
        payload = request.get_json(silent=True) or {}
        entry = build_peer_entry(client_ip, payload)
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"register {entry['ip']}:{entry['port']}")
        log.info(
            "REGISTER %s:%s %s %s",
            entry["ip"],
            entry["port"],
            entry.get("country_code", "??"),
            entry.get("node_id", ""),
        )
        return jsonify({"ok": True, "peer": entry})
    except Exception as e:
        log.exception("Error /register")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/keepalive")
def keepalive():
    try:
        auth_error = require_api_token()
        if auth_error:
            return auth_error
        if not github_ready():
            return jsonify({"ok": False, "error": "SERVER_NOT_CONFIGURED"}), 500
        client_ip = get_client_ip()
        if not client_ip:
            return jsonify({"ok": False, "error": "NO_IP"}), 400
        payload = request.get_json(silent=True) or {}
        entry = build_peer_entry(client_ip, payload)
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"keepalive {entry['ip']}:{entry['port']}")
        log.info(
            "KEEPALIVE %s:%s %s %s",
            entry["ip"],
            entry["port"],
            entry.get("country_code", "??"),
            entry.get("node_id", ""),
        )
        return jsonify({"ok": True})
    except Exception as e:
        log.exception("Error /keepalive")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/cleanup")
def cleanup():
    try:
        auth_error = require_api_token()
        if auth_error:
            return auth_error
        if not github_ready():
            return jsonify({"ok": False, "error": "SERVER_NOT_CONFIGURED"}), 500
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            before = len(peers_list)
            peers_list = cleanup_peers(peers_list)
            after = len(peers_list)
            save_peers_to_github(peers_list, sha, "cleanup peers")
        log.info("CLEANUP %d -> %d", before, after)
        return jsonify({"ok": True, "before": before, "after": after})
    except Exception as e:
        log.exception("Error /cleanup")
        return jsonify({"ok": False, "error": str(e)}), 500


# ================= MAIN =================

if __name__ == "__main__":
    log.info("%s v%s", APP_NAME, APP_VERSION)
    log.info("Listening on %s:%d", HOST, PORT)
    log.info("GitHub repo: %s/%s", REPO_OWNER or "-", REPO_NAME or "-")
    app.run(host=HOST, port=PORT, debug=False)
