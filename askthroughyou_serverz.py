#!/usr/bin/env python3
"""
Ask Through You — Peer Registry Server v2.0
--------------------------------------------
Manages peers.json on GitHub. Tracks live presence via persistent TCP.

v2.0 — persistent presence model
- Clients open a TCP connection and keep it open
- Server writes them to peers.json on connect
- Server removes them from peers.json on disconnect
- Presence on peers.json reflects the live TCP connection state

Functions:
- accepts persistent TCP connections from user nodes
- writes connected nodes to peers.json on GitHub immediately
- removes disconnected nodes from peers.json immediately
- registers itself as a permanent node via auto-keepalive
- exposes a REST API for monitoring

Designed for: Synology NAS, Linux, any always-on server

Dependencies:
  pip install flask requests python-dotenv dnspython
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

import dns.resolver
import requests
from flask import Flask, jsonify, request

# ================= LOG =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("askthroughyou-server")

# ================= CONFIG =================

APP_NAME = "askthroughyou-server"
APP_VERSION = "2.0"

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

REQUEST_TIMEOUT = int(os.getenv("ATY_REQUEST_TIMEOUT", "15"))
KEEPALIVE_INTERVAL = int(os.getenv("ATY_KEEPALIVE_INTERVAL", "120"))

MAX_MESSAGE_SIZE = int(os.getenv("ATY_MAX_MESSAGE_SIZE", "65536"))
PING_TIMEOUT = int(os.getenv("ATY_PING_TIMEOUT", "180"))  # seconds without ping = dead

ATY_DNS_SERVER = os.getenv("ATY_DNS_SERVER", "").strip()

# ================= APP =================

app = Flask(__name__)
repo_lock = threading.Lock()

# Live registry: ip -> {entry, connected_at, last_ping}
live_clients: dict[str, dict[str, Any]] = {}
live_clients_lock = threading.Lock()


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


def cleanup_peers(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - MAX_PEER_AGE
    return [p for p in peers if int(p.get("last_seen", 0)) >= cutoff]


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


def remove_peer_from_list(peers: list[dict[str, Any]], ip: str) -> list[dict[str, Any]]:
    return [p for p in peers if normalize_ip(p.get("ip")) != ip]


# ================= GITHUB SYNC =================

def github_add_peer(entry: dict[str, Any]) -> None:
    """Add or update a peer in peers.json on GitHub."""
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_peers_to_github(peers_list, sha, f"connect {entry['ip']}:{entry['port']}")
        log.info("GitHub: added %s (%s)", entry["ip"], entry.get("country_code", "??"))
    except Exception as e:
        log.warning("GitHub add failed for %s: %s", entry.get("ip"), e)


def github_remove_peer(ip: str, node_id: str = "") -> None:
    """Remove a peer from peers.json on GitHub.
    Skips removal if the peer is a permanent node (we don't remove ourselves)."""
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_peers_from_github()
            peers_list = cleanup_peers(peers_list)
            # Don't remove ourselves (the permanent registry node)
            our_node_id = os.getenv("ATY_NODE_ID", "node-001").strip()
            new_list = []
            for p in peers_list:
                if normalize_ip(p.get("ip")) == ip and str(p.get("node_id", "")) != our_node_id:
                    continue  # remove this one
                new_list.append(p)
            if len(new_list) != len(peers_list):
                save_peers_to_github(new_list, sha, f"disconnect {ip}")
                log.info("GitHub: removed %s", ip)
    except Exception as e:
        log.warning("GitHub remove failed for %s: %s", ip, e)


# ================= TCP NODE SERVER (PERSISTENT) =================

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
        except socket.timeout:
            return None
        except Exception:
            return None
    try:
        line = buf.split(b"\n")[0].decode("utf-8").strip()
        return json.loads(line) if line else None
    except Exception:
        return None


def handle_dns_query(msg: dict[str, Any]) -> dict[str, Any]:
    """Resolve a DNS query and return the response message."""
    domain = str(msg.get("domain", "")).strip()
    qtype = str(msg.get("qtype", "A")).upper()
    if not domain:
        return {"type": "DNS_RESPONSE", "ok": False, "error": "MISSING_DOMAIN"}

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

    return {
        "type": "DNS_RESPONSE",
        "ok": True,
        "domain": domain,
        "qtype": qtype,
        "answers": result,
        "ttl": ttl,
        "resolver_ip": get_public_ip(),
    }


def handle_persistent_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    """
    Handle a persistent client connection.
    Client stays connected — we track presence via the live socket.
    On disconnect, we remove the client from peers.json.
    """
    conn.settimeout(PING_TIMEOUT)
    client_ip = addr[0]
    registered = False
    entry: Optional[dict[str, Any]] = None

    try:
        while True:
            msg = recv_line(conn)
            if msg is None:
                # Connection closed or timeout (no ping received)
                break

            mtype = msg.get("type", "")

            # Use IP from payload if provided (helps with NAT)
            payload_ip = str(msg.get("ip", "")).strip()
            effective_ip = payload_ip or client_ip

            if mtype == "REGISTER":
                # First message — register the client
                client_ip = effective_ip
                entry = build_peer_entry(client_ip, msg)

                with live_clients_lock:
                    live_clients[client_ip] = {
                        "entry": entry,
                        "connected_at": int(time.time()),
                        "last_ping": int(time.time()),
                    }

                # Push to GitHub in a thread (non-blocking)
                threading.Thread(target=github_add_peer, args=(entry,), daemon=True).start()
                registered = True
                log.info("REGISTER %s:%s %s",
                         entry["ip"], entry["port"], entry.get("country_code", "??"))

                # Send acknowledgment
                send_line(conn, {"type": "REGISTERED", "ok": True})

            elif mtype == "PING":
                # Update presence
                with live_clients_lock:
                    if client_ip in live_clients:
                        live_clients[client_ip]["last_ping"] = int(time.time())
                send_line(conn, {"type": "PONG", "timestamp": int(time.time())})

            elif mtype == "DNS_QUERY":
                # Resolve DNS for the client
                resp = handle_dns_query(msg)
                send_line(conn, resp)

            elif mtype == "HELLO":
                # Legacy support: old client just wants peer list
                # Treat as light registration without persistence
                send_line(conn, {"type": "PEER_LIST", "ok": True, "peers": []})

            else:
                send_line(conn, {"type": "ERROR", "error": "UNKNOWN_TYPE"})

    except Exception as e:
        log.warning("Client %s error: %s", client_ip, e)

    finally:
        try:
            conn.close()
        except Exception:
            pass

        # Disconnect: remove from live registry and GitHub
        if registered and entry is not None:
            with live_clients_lock:
                live_clients.pop(client_ip, None)
            node_id = entry.get("node_id", "")
            threading.Thread(
                target=github_remove_peer,
                args=(client_ip, node_id),
                daemon=True,
            ).start()
            log.info("DISCONNECT %s", client_ip)


def start_node_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", NODE_PORT))
    server.listen(32)
    server.settimeout(1.0)
    log.info("Node listening on 0.0.0.0:%d (persistent presence mode)", NODE_PORT)
    try:
        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=handle_persistent_client,
                    args=(conn, addr),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                log.warning("Node server error: %s", e)
    finally:
        try:
            server.close()
        except Exception:
            pass


# ================= STALE CLIENT CLEANUP =================

def stale_cleanup_loop() -> None:
    """
    Detect clients that haven't pinged in PING_TIMEOUT seconds and remove them.
    This is a safety net — normally the socket close already triggers removal.
    """
    while True:
        time.sleep(60)
        try:
            now = int(time.time())
            cutoff = now - PING_TIMEOUT
            stale_ips = []
            with live_clients_lock:
                for ip, info in list(live_clients.items()):
                    if info.get("last_ping", info.get("connected_at", 0)) < cutoff:
                        stale_ips.append(ip)
                        del live_clients[ip]
            for ip in stale_ips:
                log.info("STALE %s — no ping in %ds", ip, PING_TIMEOUT)
                threading.Thread(target=github_remove_peer, args=(ip,), daemon=True).start()
        except Exception as e:
            log.warning("Stale cleanup error: %s", e)


# ================= FLASK ROUTES =================

@app.get("/health")
def health():
    with live_clients_lock:
        active_clients = len(live_clients)
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
    """Show all live clients currently connected."""
    with live_clients_lock:
        data = {ip: dict(info) for ip, info in live_clients.items()}
    return jsonify({"ok": True, "count": len(data), "clients": data})


@app.get("/peers")
def peers():
    try:
        with repo_lock:
            raw_peers, _ = load_peers_from_github()
            cleaned = cleanup_peers(raw_peers)
        return jsonify({"ok": True, "count": len(cleaned), "peers": cleaned})
    except Exception as e:
        log.exception("Error /peers")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/cleanup")
def cleanup():
    try:
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


# ================= AUTO KEEPALIVE (registers ourselves) =================

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
    log.info("TCP node on 0.0.0.0:%d", NODE_PORT)
    log.info("GitHub repo: %s/%s", REPO_OWNER or "-", REPO_NAME or "-")
    log.info("DNS server: %s", ATY_DNS_SERVER or "system default")

    threading.Thread(target=auto_keepalive, daemon=True).start()
    log.info("Auto-keepalive started (every %ds)", KEEPALIVE_INTERVAL)

    threading.Thread(target=start_node_server, daemon=True).start()

    threading.Thread(target=stale_cleanup_loop, daemon=True).start()
    log.info("Stale client cleanup started (timeout %ds)", PING_TIMEOUT)

    app.run(host=HOST, port=PORT, debug=False)
