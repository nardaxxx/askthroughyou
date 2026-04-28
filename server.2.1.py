#!/usr/bin/env python3
"""
Ask Through You — Peer Registry Server v2.1
--------------------------------------------
Manages peers.json on GitHub. Tracks live presence via persistent TCP.

v2.1 — multi-port + HF SIGNAL 01
- Listens on 35353, 443, 80 (or mapped equivalents)
- HF_SIGNAL message type for emergency surrender/distress
- HF signals logged locally and pushed to GitHub

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
from pathlib import Path

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
APP_VERSION = "2.1"

HOST = os.getenv("ATY_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("ATY_SERVER_PORT", "8090"))

# Porte TCP in ascolto — ordine di priorità
NODE_PORTS = [
    int(os.getenv("ATY_LISTEN_PORT", "35353")),
    int(os.getenv("ATY_LISTEN_PORT_2", "8443")),   # fallback (443 su Termux)
    int(os.getenv("ATY_LISTEN_PORT_3", "8080")),   # fallback estremo (80 su Termux)
]

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
REPO_OWNER = os.getenv("ATY_REPO_OWNER", "").strip()
REPO_NAME = os.getenv("ATY_REPO_NAME", "askthroughyou_peers").strip()
FILE_PATH = os.getenv("ATY_FILE_PATH", "peers.json").strip()
BRANCH = os.getenv("ATY_BRANCH", "main").strip()

HF_FILE_PATH = os.getenv("ATY_HF_FILE_PATH", "hf_signals.json").strip()
HF_LOG_FILE = Path(os.getenv("ATY_HF_LOG", "hf_signals.log"))

DEFAULT_NODE_PORT = NODE_PORTS[0]
MAX_PEER_AGE = int(os.getenv("ATY_MAX_PEER_AGE", "900"))
REQUEST_TIMEOUT = int(os.getenv("ATY_REQUEST_TIMEOUT", "15"))
KEEPALIVE_INTERVAL = int(os.getenv("ATY_KEEPALIVE_INTERVAL", "120"))
MAX_MESSAGE_SIZE = int(os.getenv("ATY_MAX_MESSAGE_SIZE", "65536"))
PING_TIMEOUT = int(os.getenv("ATY_PING_TIMEOUT", "180"))
ATY_DNS_SERVER = os.getenv("ATY_DNS_SERVER", "").strip()

# ================= APP =================

app = Flask(__name__)
repo_lock = threading.Lock()
hf_lock = threading.Lock()

live_clients: dict[str, dict[str, Any]] = {}
live_clients_lock = threading.Lock()


# ================= PUBLIC IP =================

def get_public_ip() -> str:
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip"]:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
            )
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


def github_contents_url(file_path: str = "") -> str:
    fp = file_path or FILE_PATH
    return f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{fp}"


def github_ready() -> bool:
    return bool(GITHUB_TOKEN and REPO_OWNER and REPO_NAME and FILE_PATH and BRANCH)


def load_json_from_github(file_path: str) -> tuple[list, Optional[str]]:
    url = f"{github_contents_url(file_path)}?ref={BRANCH}"
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


def save_json_to_github(
    data: list,
    sha: Optional[str],
    message: str,
    file_path: str = ""
) -> None:
    fp = file_path or FILE_PATH
    encoded = base64.b64encode(
        json.dumps(data, indent=2).encode("utf-8")
    ).decode("utf-8")
    payload: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(
        github_contents_url(fp),
        headers=github_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


# ================= HF SIGNAL =================

def save_hf_signal(entry: dict[str, Any]) -> None:
    """
    Salva segnale HF su file locale e su GitHub (hf_signals.json).
    Il file locale è append-only — non si perde nulla.
    """
    # Log locale immediato
    try:
        with hf_lock:
            with open(HF_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        log.warning(
            "HF_SIGNAL saved locally: %s from %s @ %s",
            entry.get("signal"),
            entry.get("from_ip"),
            entry.get("gps", "no-gps"),
        )
    except Exception as e:
        log.error("HF local log failed: %s", e)

    # Push su GitHub
    if not github_ready():
        return
    try:
        with repo_lock:
            signals, sha = load_json_from_github(HF_FILE_PATH)
            signals.append(entry)
            # Mantieni ultimi 1000 segnali
            if len(signals) > 1000:
                signals = signals[-1000:]
            save_json_to_github(
                signals,
                sha,
                f"HF_SIGNAL {entry.get('signal')} from {entry.get('from_ip')}",
                HF_FILE_PATH,
            )
        log.warning(
            "HF_SIGNAL pushed to GitHub: %s from %s",
            entry.get("signal"),
            entry.get("from_ip"),
        )
    except Exception as e:
        log.error("HF GitHub push failed: %s", e)


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


def upsert_peer(
    peers: list[dict[str, Any]],
    new_entry: dict[str, Any]
) -> list[dict[str, Any]]:
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


def remove_peer_from_list(
    peers: list[dict[str, Any]],
    ip: str
) -> list[dict[str, Any]]:
    return [p for p in peers if normalize_ip(p.get("ip")) != ip]


# ================= GITHUB SYNC =================

def github_add_peer(entry: dict[str, Any]) -> None:
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_json_from_github(FILE_PATH)
            peers_list = cleanup_peers(peers_list)
            peers_list = upsert_peer(peers_list, entry)
            save_json_to_github(
                peers_list, sha,
                f"connect {entry['ip']}:{entry['port']}"
            )
        log.info("GitHub: added %s (%s)", entry["ip"], entry.get("country_code", "??"))
    except Exception as e:
        log.warning("GitHub add failed for %s: %s", entry.get("ip"), e)


def github_remove_peer(ip: str, node_id: str = "") -> None:
    if not github_ready():
        return
    try:
        with repo_lock:
            peers_list, sha = load_json_from_github(FILE_PATH)
            peers_list = cleanup_peers(peers_list)
            our_node_id = os.getenv("ATY_NODE_ID", "node-001").strip()
            new_list = []
            for p in peers_list:
                if (normalize_ip(p.get("ip")) == ip
                        and str(p.get("node_id", "")) != our_node_id):
                    continue
                new_list.append(p)
            if len(new_list) != len(peers_list):
                save_json_to_github(new_list, sha, f"disconnect {ip}")
                log.info("GitHub: removed %s", ip)
    except Exception as e:
        log.warning("GitHub remove failed for %s: %s", ip, e)


# ================= TCP PROTOCOL =================

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


# ================= DNS =================

def handle_dns_query(msg: dict[str, Any]) -> dict[str, Any]:
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


# ================= CLIENT HANDLER =================

def handle_persistent_client(
    conn: socket.socket,
    addr: tuple[str, int],
    listen_port: int,
) -> None:
    conn.settimeout(PING_TIMEOUT)
    client_ip = addr[0]
    registered = False
    entry: Optional[dict[str, Any]] = None

    try:
        while True:
            msg = recv_line(conn)
            if msg is None:
                break

            mtype = msg.get("type", "")
            payload_ip = str(msg.get("ip", "")).strip()
            effective_ip = payload_ip or client_ip

            if mtype == "REGISTER":
                client_ip = effective_ip
                entry = build_peer_entry(client_ip, msg)
                with live_clients_lock:
                    live_clients[client_ip] = {
                        "entry": entry,
                        "connected_at": int(time.time()),
                        "last_ping": int(time.time()),
                        "via_port": listen_port,
                    }
                threading.Thread(
                    target=github_add_peer, args=(entry,), daemon=True
                ).start()
                registered = True
                log.info(
                    "REGISTER %s:%s %s via port %d",
                    entry["ip"], entry["port"],
                    entry.get("country_code", "??"),
                    listen_port,
                )
                send_line(conn, {"type": "REGISTERED", "ok": True})

            elif mtype == "PING":
                with live_clients_lock:
                    if client_ip in live_clients:
                        live_clients[client_ip]["last_ping"] = int(time.time())
                send_line(conn, {"type": "PONG", "timestamp": int(time.time())})

            elif mtype == "DNS_QUERY":
                resp = handle_dns_query(msg)
                send_line(conn, resp)

            elif mtype == "HF_SIGNAL":
                # Segnale emergenza Human Flag
                signal_type = str(msg.get("signal", "unknown")).strip()
                gps = str(msg.get("gps", "")).strip()
                hf_entry = {
                    "from_ip": client_ip,
                    "signal": signal_type,
                    "gps": gps,
                    "node_id": str(msg.get("node_id", "")).strip(),
                    "message": str(msg.get("message", "")).strip()[:256],
                    "timestamp": msg.get("timestamp", int(time.time())),
                    "received_at": int(time.time()),
                    "via_port": listen_port,
                }
                log.warning(
                    "🚨 HF_SIGNAL [%s] from %s @ %s via port %d",
                    signal_type, client_ip, gps or "no-gps", listen_port,
                )
                threading.Thread(
                    target=save_hf_signal, args=(hf_entry,), daemon=True
                ).start()
                send_line(conn, {
                    "type": "HF_ACK",
                    "ok": True,
                    "timestamp": int(time.time()),
                })

            elif mtype == "HELLO":
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


# ================= NODE SERVER (multi-porta) =================

def start_node_server_on_port(port: int) -> None:
    """Avvia un server TCP su una porta specifica."""
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen(32)
        server.settimeout(1.0)
        log.info("Node listening on 0.0.0.0:%d", port)
    except Exception as e:
        log.error("Cannot bind port %d: %s", port, e)
        return

    try:
        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=handle_persistent_client,
                    args=(conn, addr, port),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                log.warning("Node server error on port %d: %s", port, e)
    finally:
        try:
            server.close()
        except Exception:
            pass


def start_all_node_servers() -> None:
    """Avvia un thread per ogni porta configurata."""
    for port in NODE_PORTS:
        threading.Thread(
            target=start_node_server_on_port,
            args=(port,),
            daemon=True,
        ).start()


# ================= STALE CLEANUP =================

def stale_cleanup_loop() -> None:
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
                log.info("STALE %s", ip)
                threading.Thread(
                    target=github_remove_peer, args=(ip,), daemon=True
                ).start()
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
        "listening_ports": NODE_PORTS,
        "dns_server": ATY_DNS_SERVER or "system default",
    })


@app.get("/clients")
def clients():
    with live_clients_lock:
        data = {ip: dict(info) for ip, info in live_clients.items()}
    return jsonify({"ok": True, "count": len(data), "clients": data})


@app.get("/peers")
def peers():
    try:
        with repo_lock:
            raw_peers, _ = load_json_from_github(FILE_PATH)
            cleaned = cleanup_peers(raw_peers)
        return jsonify({"ok": True, "count": len(cleaned), "peers": cleaned})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/hf_signals")
def hf_signals():
    """Mostra tutti i segnali HF ricevuti."""
    try:
        with repo_lock:
            signals, _ = load_json_from_github(HF_FILE_PATH)
        return jsonify({"ok": True, "count": len(signals), "signals": signals})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/cleanup")
def cleanup():
    try:
        if not github_ready():
            return jsonify({"ok": False, "error": "SERVER_NOT_CONFIGURED"}), 500
        with repo_lock:
            peers_list, sha = load_json_from_github(FILE_PATH)
            before = len(peers_list)
            peers_list = cleanup_peers(peers_list)
            after = len(peers_list)
            save_json_to_github(peers_list, sha, "cleanup peers")
        return jsonify({"ok": True, "before": before, "after": after})
    except Exception as e:
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
                port = NODE_PORTS[0]
                entry = build_peer_entry(public_ip, {
                    "port": port,
                    "country_code": country_code,
                    "node_id": node_id,
                })
                with repo_lock:
                    peers_list, sha = load_json_from_github(FILE_PATH)
                    peers_list = cleanup_peers(peers_list)
                    peers_list = upsert_peer(peers_list, entry)
                    save_json_to_github(
                        peers_list, sha,
                        f"keepalive {public_ip}:{port}"
                    )
                log.info("AUTO-KEEPALIVE %s:%s %s", public_ip, port, country_code)
        except Exception as e:
            log.error("AUTO-KEEPALIVE error: %s", e)
        time.sleep(KEEPALIVE_INTERVAL)


# ================= MAIN =================

if __name__ == "__main__":
    log.info("%s v%s", APP_NAME, APP_VERSION)
    log.info("Flask on %s:%d", HOST, PORT)
    log.info("TCP node ports: %s", NODE_PORTS)
    log.info("GitHub repo: %s/%s", REPO_OWNER or "-", REPO_NAME or "-")
    log.info("HF signals log: %s", HF_LOG_FILE)

    threading.Thread(target=auto_keepalive, daemon=True).start()
    start_all_node_servers()
    threading.Thread(target=stale_cleanup_loop, daemon=True).start()

    app.run(host=HOST, port=PORT, debug=False)
