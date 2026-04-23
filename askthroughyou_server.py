#!/usr/bin/env python3
"""
Ask Through You — Bootstrap Server v1.2
----------------------------------------
Logs all client connections and writes them to GitHub.

Functions:
- registers permanent nodes
- logs temporary client connections
- updates keepalive
- writes peers.json to GitHub
- keeps the peer list clean
- auto-detects public IP

Designed for:
- Synology NAS
- Linux
- any always-on server

Dependencies:
  pip install flask requests python-dotenv
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import base64
import json
import logging
import os
import socket
import threading
import time
import urllib.request
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
APP_VERSION = "1.2"

HOST = os.getenv("ATY_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("ATY_SERVER_PORT", "8090"))
NODE_PORT = int(os.getenv("ATY_LISTEN_PORT", "35353"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
REPO_OWNER = os.getenv("ATY_REPO_OWNER", "").strip()
REPO_NAME = os.getenv("ATY_REPO_NAME", "askthroughyou_peers").strip()
FILE_PATH = os.getenv("ATY_FILE_PATH", "peers.json").strip()
BRANCH = os.getenv("ATY_BRANCH", "main").strip()

DEFAULT_NODE_PORT = int(os.getenv("ATY_DEFAULT_NODE_PORT", "35353"))
MAX_PEER_AGE = int(os.getenv("ATY_MAX_PEER_AGE", "900"))
CLIENT_MAX_AGE = int(os.getenv("ATY_CLIENT_MAX_AGE", "300"))  # 5 min for temporary clients

REQUIRE_TOKEN = os.getenv("ATY_REQUIRE_API_TOKEN", "0").strip() == "1"
API_TOKEN = os.getenv("ATY_API_TOKEN", "").strip()

REQUEST_TIMEOUT = int(os.getenv("ATY_REQUEST_TIMEOUT", "15"))
KEEPALIVE_INTERVAL = int(os.getenv("ATY_KEEPALIVE_INTERVAL", "120"))

MAX_MESSAGE_SIZE = int(os.getenv("ATY_MAX_MESSAGE_SIZE", "65536"))
CONNECT_TIMEOUT = int(os.getenv("ATY_CONNECT_TIMEOUT", "5"))

# Optional: set ATY_DNS_SERVER in .env to use your own DNS (e.g. 192.168.2.1)
ATY_DNS_SERVER = os.getenv("ATY_DNS_SERVER", "").strip()

# ================= APP =================

app = Flask(__name__)
repo_lock = threading.Lock()

# In-memory client connections log
# { ip: { "first_seen": ts, "last_seen": ts, "connections": count } }
client_log: dict[str, dict[str, Any]] = {}
client_log_lock = threading.Lock()


# ================= PUBLIC IP =================

def get_public_ip() -> str:
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                ip = r.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return ""


# ================= GITHUB =================

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


def github_ready() -> bool:
    return bool(GITHUB_TOKEN and REPO_OWNER and REPO_NAME and FILE_PATH and BRANCH)


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
    encoded = base64.b64encode(json.dumps(peers, indent=2).encode("utf-8")).decode("utf-8")
    payload: dict[str, Any] = {"message": message, "content": encoded, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    resp = requests.put(
        github_contents_url(),
        headers=github_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


# ================= PEER HELPERS =================

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
    return str(value or "").strip()[:64]


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
    return [p for p in peers if int(p.get("last_seen", 0)) >= cutoff]


def cleanup_clients(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove temporary clients that have expired."""
    cutoff = int(time.time()) - CLIENT_MAX_AGE
    return [p for p in peers if not p.get("temporary") or int(p.get("last_seen", 0)) >= cutoff]


def build_peer_entry(ip: str, payload: dict[str, Any], temporary: bool = False) -> dict[str, Any]:
    now = int(time.time())
    entry: dict[str, Any] = {
        "ip": ip,
        "port": sanitize_port(payload.get("port")),
        "country_code": sanitize_country_code(payload.get("country_code")),
        "last_seen": now,
    }
    if temporary:
        entry["temporary"] = True
        entry["connected_at"] = now
    node_id = sanitize_node_id(payload.get("node_id"))
    if node_id:
        entry["node_id"] = node_id
    for key in ("country", "region", "city", "org", "asn"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            entry[key] = value[:128]
    return entry


def upsert_peer(peers: list[dict[str, Any]], new_entry: dict[str, Any]) -> list[dict[str, Any]]:
    ip = new_entry["ip"]
    node_id = new_entry.get("node_id", "")
    updated = False
    result = []
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


def remove_peer(peers: list[dict[str, Any]], ip: str) -> list[dict[str, Any]]:
    return [p for p in peers if normalize_ip(p.get("ip")) != ip]


# ================= CLIENT CONNECTION LOG =================

def log_client_connection(client_ip: str) -> None:
    now = int(time.time())
    with client_log_lock:
        if client_ip not in client_log:
            client_log[client_ip] = {
                "first_seen": now,
                "last_seen": now,
                "connections": 1,
            }
            log.info("NEW CLIENT connected: %s", client_ip)
        else:
            client_log[client_ip]["last_seen"] = now
            client_log[client_ip]["connections"] += 1
            log.info("CLIENT reconnected: %s (total: %d)", client_ip, client_log[client_ip]["connections"])


def write_client_to_github(client_ip: str) -> None:
    """Write a temporary client connection to GitHub peers list."""
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = cleanup_clients(peers_list)
            entry = build_peer_entry(client_ip, {"port": 0, "country_code": "??"}, temporary=True)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"client connected {client_ip}")
        log.info("CLIENT written to GitHub: %s", client_ip)
    except Exception as e:
        log.warning("Failed to write client to GitHub: %s", e)


def remove_client_from_github(client_ip: str) -> None:
    """Remove a temporary client from GitHub when it disconnects."""
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = [p for p in peers_list if not (
                normalize_ip(p.get("ip")) == client_ip and p.get("temporary")
            )]
            save_peers_to_github(peers_list, sha, f"client disconnected {client_ip}")
        log.info("CLIENT removed from GitHub: %s", client_ip)
    except Exception as e:
        log.warning("Failed to remove client from GitHub: %s", e)


# ================= TCP NODE SERVER =================

def send_line(sock: socket.socket, data: dict[str, Any]) -> None:
    sock.sendall((json.dumps(data) + "\n").encode("utf-8"))


def recv_line(sock: socket.socket) -> Optional[dict[str, Any]]:
    buf = b""
    while b"\n" not in buf:
        if len(buf) > MAX_MESSAGE_SIZE:
            return None
        try:
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
        except Exception:
            return None
    try:
        line = buf.split(b"\n")[0].decode("utf-8").strip()
        return json.loads(line) if line else None
    except Exception:
        return None


def handle_peer(conn: socket.socket, addr: tuple[str, int]) -> None:
    conn.settimeout(CONNECT_TIMEOUT)

    try:
        msg = recv_line(conn)
        if not msg:
            return
        mtype = msg.get("type", "")

        # Use IP from HELLO payload if available (bypasses NAT issues)
        # Otherwise fall back to TCP source address
        client_ip = str(msg.get("ip", "")).strip() or addr[0]

        # Log the connection
        log_client_connection(client_ip)

        # Write to GitHub in background
        threading.Thread(target=write_client_to_github, args=(client_ip,), daemon=True).start()

        if mtype == "HELLO":
            log.info("HELLO from %s (TCP: %s)", client_ip, addr[0])
            send_line(conn, {"type": "PEER_LIST", "ok": True, "peers": []})

        elif mtype == "DNS_QUERY":
            domain = str(msg.get("domain", "")).strip()
            qtype = str(msg.get("qtype", "A")).upper()
            if not domain:
                send_line(conn, {"type": "DNS_RESPONSE", "ok": False, "error": "MISSING_DOMAIN"})
                return
            # Resolve locally
            import dns.resolver
            resolver = dns.resolver.Resolver()
            if ATY_DNS_SERVER:
                resolver.nameservers = [ATY_DNS_SERVER]
            resolver.timeout = 3.0
            resolver.lifetime = 5.0
            try:
                answers = resolver.resolve(domain, qtype)
                result = [str(r) for r in answers]
                ttl = answers.rrset.ttl if answers.rrset else 60
            except Exception:
                result = []
                ttl = 0
            send_line(conn, {
                "type": "DNS_RESPONSE",
                "ok": True,
                "domain": domain,
                "qtype": qtype,
                "answers": result,
                "ttl": ttl,
                "resolver_ip": get_public_ip(),
            })
            log.info("DNS %s [%s] -> %s for %s", domain, qtype, result, client_ip)

        else:
            send_line(conn, {"type": "ERROR", "error": "UNKNOWN_TYPE"})

    except Exception as e:
        client_ip = addr[0]
        log.warning("Peer error %s: %s", client_ip, e)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        # Remove from GitHub after disconnect
        threading.Thread(target=remove_client_from_github, args=(client_ip,), daemon=True).start()


def start_node_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", NODE_PORT))
    server.listen(32)
    server.settimeout(1.0)
    log.info("Node listening on 0.0.0.0:%d (client connection logging active)", NODE_PORT)
    running = True
    try:
        while running:
            try:
                conn, addr = server.accept()
                threading.Thread(target=handle_peer, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                log.warning("Node server error: %s", e)
    finally:
        try:
            server.close()
        except Exception:
            pass


# ================= FLASK ROUTES =================

@app.get("/health")
def health():
    with client_log_lock:
        active_clients = len(client_log)
    return jsonify({
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "github_ready": github_ready(),
        "active_clients": active_clients,
        "dns_server": ATY_DNS_SERVER or "system default",
    })


@app.get("/clients")
def clients():
    """Show all clients that have connected."""
    with client_log_lock:
        data = dict(client_log)
    return jsonify({"ok": True, "count": len(data), "clients": data})


@app.get("/peers")
def peers():
    try:
        auth_error = require_api_token()
        if auth_error:
            return auth_error
        with repo_lock:
            raw_peers, _ = load_peers_from_github()
            cleaned = cleanup_peers(raw_peers)
        return jsonify({"ok": True, "count": len(cleaned), "peers": cleaned})
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

        client_ip = get_public_ip()
        if not client_ip:
            return jsonify({"ok": False, "error": "CANNOT_DETERMINE_PUBLIC_IP"}), 500

        payload = request.get_json(silent=True) or {}
        entry = build_peer_entry(client_ip, payload)
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = cleanup_clients(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"register {entry['ip']}:{entry['port']}")
        log.info("REGISTER %s:%s %s", entry["ip"], entry["port"], entry.get("country_code", "??"))
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

        client_ip = get_public_ip()
        if not client_ip:
            return jsonify({"ok": False, "error": "CANNOT_DETERMINE_PUBLIC_IP"}), 500

        payload = request.get_json(silent=True) or {}
        entry = build_peer_entry(client_ip, payload)
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = cleanup_clients(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"keepalive {entry['ip']}:{entry['port']}")
        log.info("KEEPALIVE %s:%s", entry["ip"], entry["port"])
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
            peers_list = cleanup_clients(peers_list)
            after = len(peers_list)
            save_peers_to_github(peers_list, sha, "cleanup peers")
        log.info("CLEANUP %d -> %d", before, after)
        return jsonify({"ok": True, "before": before, "after": after})
    except Exception as e:
        log.exception("Error /cleanup")
        return jsonify({"ok": False, "error": str(e)}), 500


# ================= AUTO KEEPALIVE =================

def auto_keepalive() -> None:
    time.sleep(5)
    while True:
        try:
            public_ip = get_public_ip()
            if public_ip and github_ready():
                node_id = os.getenv("ATY_NODE_ID", "node-001").strip()
                country_code = os.getenv("ATY_COUNTRY_CODE", "CH").strip()
                port = int(os.getenv("ATY_LISTEN_PORT", "35353"))
                entry = build_peer_entry(public_ip, {
                    "port": port,
                    "country_code": country_code,
                    "node_id": node_id,
                })
                with repo_lock:
                    peers_list, sha = load_peers_from_github()
                    peers_list = cleanup_peers(peers_list)
                    peers_list = cleanup_clients(peers_list)
                    peers_list = upsert_peer(peers_list, entry)
                    save_peers_to_github(peers_list, sha, f"keepalive {public_ip}:{port}")
                log.info("AUTO-KEEPALIVE %s:%s %s", public_ip, port, country_code)
        except Exception as e:
            log.error("AUTO-KEEPALIVE error: %s", e)
        time.sleep(KEEPALIVE_INTERVAL)


# ================= MAIN =================

if __name__ == "__main__":
    log.info("%s v%s", APP_NAME, APP_VERSION)
    log.info("Flask on %s:%d", HOST, PORT)
    log.info("Node on 0.0.0.0:%d", NODE_PORT)
    log.info("GitHub repo: %s/%s", REPO_OWNER or "-", REPO_NAME or "-")
    log.info("DNS server: %s", ATY_DNS_SERVER or "system default")

    # Start auto-keepalive
    threading.Thread(target=auto_keepalive, daemon=True).start()
    log.info("Auto-keepalive started (every %ds)", KEEPALIVE_INTERVAL)

    # Start TCP node server for client connections
    threading.Thread(target=start_node_server, daemon=True).start()

    app.run(host=HOST, port=PORT, debug=False)
