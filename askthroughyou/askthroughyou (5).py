#!/usr/bin/env python3
"""
Ask Through You v1.2
--------------------
Distributed human-node DNS network.

Dependencies:
  pip install dnspython dnslib
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Any
from urllib.parse import urlparse, parse_qs

try:
    import dns.resolver
    import dns.exception
except ImportError:
    print("Error: pip install dnspython")
    sys.exit(1)

try:
    import dnslib
    from dnslib import DNSRecord, RR, QTYPE
except ImportError:
    print("Error: pip install dnslib")
    sys.exit(1)


def load_dotenv_file(filename: str = ".env") -> None:
    env_path = Path(filename)
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"')) or
                (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except Exception as e:
        print(f"Warning: cannot read {filename}: {e}")


load_dotenv_file()

# ---------------------------------------------------------------------------
# Config file (~/.askthroughyou/config.json) — caricato DOPO .env
# Usato dal client per non dipendere dal .env del server
# ---------------------------------------------------------------------------

def _app_data_dir_early() -> Path:
    if os.name == "nt":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / "AskThroughYou"
    return Path.home() / ".askthroughyou"


def load_config() -> None:
    """Carica config.json e imposta le variabili d'ambiente mancanti."""
    config_file = _app_data_dir_early() / "config.json"
    if not config_file.exists():
        return
    try:
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
        for key, value in cfg.items():
            if value:
                os.environ.setdefault(key, str(value))
    except Exception as e:
        print(f"Warning: cannot read config.json: {e}")


def save_config(data: dict) -> None:
    """Salva/aggiorna config.json."""
    config_dir = _app_data_dir_early()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    existing = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(data)
    config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")


load_config()

# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("askthroughyou")

APP_NAME = "askthroughyou"
APP_VERSION = "1.2"

NODE_HOST = "0.0.0.0"
NODE_PORT = int(os.getenv("ATY_LISTEN_PORT", "35353"))

DOH_HOST = "127.0.0.1"
DOH_PORT = int(os.getenv("ATY_DOH_PORT", "53535"))

CONNECT_TIMEOUT = int(os.getenv("ATY_CONNECT_TIMEOUT", "5"))
HTTP_TIMEOUT = int(os.getenv("ATY_HTTP_TIMEOUT", "10"))

FALLBACK_PORTS = [35353, 8443, 8080]

KEEPALIVE_INTERVAL = int(os.getenv("ATY_KEEPALIVE_INTERVAL", "120"))
DISCOVERY_INTERVAL = int(os.getenv("ATY_DISCOVERY_INTERVAL", "180"))
REFRESH_INTERVAL = int(os.getenv("ATY_REFRESH_INTERVAL", "300"))

MAX_PEER_AGE = int(os.getenv("ATY_MAX_PEER_AGE", "900"))
MAX_MESSAGE_SIZE = int(os.getenv("ATY_MAX_MESSAGE_SIZE", "65536"))

DNS_TIMEOUT = float(os.getenv("ATY_DNS_TIMEOUT", "3.0"))
DNS_LIFETIME = float(os.getenv("ATY_DNS_LIFETIME", "5.0"))

PUBLIC_IP_SERVICES = [
    "https://api.ipify.org",
    "https://ip.seeip.org",
    "https://ifconfig.me/ip",
]

GEO_API = "https://ipwho.is/{ip}"

BOOTSTRAP_URLS = [
    u.strip()
    for u in os.getenv(
        "ATY_BOOTSTRAP_URLS",
        "https://nardaxxx.github.io/askthroughyou_peers/peers.json"
    ).split(",")
    if u.strip()
]

CENTRAL_SERVER = os.getenv("ATY_SERVER_URL", "").strip()
API_TOKEN = os.getenv("ATY_API_TOKEN", "").strip()
NODE_ID = os.getenv("ATY_NODE_ID", "").strip()
PHONEBOOK_URL = os.getenv("ATY_PHONEBOOK_URL", "").strip()


def app_data_dir() -> Path:
    return _app_data_dir_early()


DATA_DIR = app_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PEER_CACHE_FILE = DATA_DIR / "peers_cache.json"
DNS_CACHE_FILE  = DATA_DIR / "dns_cache.json"
IDENTITY_FILE   = DATA_DIR / "identity.json"

running = True
state_lock = threading.Lock()

_my_ip = ""
_my_country = ""
_central_server = ""

known_peers: list["Peer"] = []
connected_peers: dict[str, int] = {}
dns_cache: dict[str, dict[str, Any]] = {}


@dataclass
class Peer:
    ip: str
    port: int
    last_seen: int
    country: str = ""
    country_code: str = ""
    region: str = ""
    city: str = ""
    org: str = ""
    asn: str = ""
    node_id: str = ""
    source: str = "bootstrap"

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Optional["Peer"]:
        try:
            ip = str(data["ip"]).strip()
            port = int(data["port"])
            last_seen = int(data["last_seen"])
            if not ip or not (1 <= port <= 65535):
                return None
            return Peer(
                ip=ip, port=port, last_seen=last_seen,
                country=str(data.get("country", "")),
                country_code=str(data.get("country_code", "")),
                region=str(data.get("region", "")),
                city=str(data.get("city", "")),
                org=str(data.get("org", "")),
                asn=str(data.get("asn", "")),
                node_id=str(data.get("node_id", "")),
                source=str(data.get("source", "bootstrap")),
            )
        except Exception:
            return None

    def server_url(self) -> str:
        return f"http://{self.ip}:8090"


def save_peer_cache(peers: list[Peer]) -> None:
    try:
        PEER_CACHE_FILE.write_text(
            json.dumps([asdict(p) for p in peers], indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning("Cannot save peer cache: %s", e)


def load_peer_cache() -> list[Peer]:
    if not PEER_CACHE_FILE.exists():
        return []
    try:
        raw = json.loads(PEER_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [p for item in raw if (p := Peer.from_dict(item))]
    except Exception as e:
        log.warning("Cannot read peer cache: %s", e)
        return []


def save_dns_cache() -> None:
    try:
        with state_lock:
            DNS_CACHE_FILE.write_text(
                json.dumps(dns_cache, indent=2), encoding="utf-8"
            )
    except Exception as e:
        log.warning("Cannot save DNS cache: %s", e)


def load_dns_cache() -> None:
    global dns_cache
    if not DNS_CACHE_FILE.exists():
        return
    try:
        raw = json.loads(DNS_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            dns_cache = raw
    except Exception as e:
        log.warning("Cannot read DNS cache: %s", e)


def cleanup_dns_cache() -> None:
    now = time.time()
    with state_lock:
        expired = [k for k, v in dns_cache.items() if v.get("expires_at", 0) <= now]
        for k in expired:
            del dns_cache[k]


def get_public_ip() -> Optional[str]:
    for url in PUBLIC_IP_SERVICES:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None


def get_geo(ip: str) -> dict[str, str]:
    try:
        req = urllib.request.Request(
            GEO_API.format(ip=ip),
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success", True):
                raise RuntimeError(data.get("message", "geo lookup failed"))
            conn = data.get("connection", {}) or {}
            return {
                "country": data.get("country", ""),
                "country_code": data.get("country_code", ""),
                "region": data.get("region", ""),
                "city": data.get("city", ""),
                "org": conn.get("org", ""),
                "asn": str(conn.get("asn", "")),
            }
    except Exception as e:
        log.warning("Geo lookup failed: %s", e)
        return {}


def cleanup_peers(peers: list[Peer]) -> list[Peer]:
    cutoff = int(time.time()) - MAX_PEER_AGE
    return [p for p in peers if p.last_seen >= cutoff]


def cleanup_connected_peers() -> None:
    cutoff = int(time.time()) - MAX_PEER_AGE
    with state_lock:
        stale = [ip for ip, ts in connected_peers.items() if ts < cutoff]
        for ip in stale:
            connected_peers.pop(ip, None)


def merge_peers(new_peers: list[Peer]) -> None:
    global known_peers
    with state_lock:
        existing = {(p.ip, p.port): p for p in known_peers}
        for peer in new_peers:
            key = (peer.ip, peer.port)
            old = existing.get(key)
            if old is None or peer.last_seen > old.last_seen:
                existing[key] = peer
        known_peers = cleanup_peers(list(existing.values()))
    save_peer_cache(known_peers)


def discover_server(country: str, peers: list[Peer]) -> str:
    if CENTRAL_SERVER:
        return CENTRAL_SERVER
    country_peers = [p for p in peers if p.country_code.upper() == country.upper()]
    for peer in country_peers:
        url = peer.server_url()
        if _check_server(url):
            log.info("Auto-discovered server in %s: %s", country, url)
            return url
    for peer in peers:
        url = peer.server_url()
        if _check_server(url):
            log.info("Auto-discovered server (fallback): %s", url)
            return url
    log.warning("No server found — running without registration")
    return ""


def _check_server(url: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{url}/health",
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def http_json(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: int = HTTP_TIMEOUT,
) -> tuple[int, Any]:
    data = None
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    if API_TOKEN:
        headers["X-API-Token"] = API_TOKEN
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return resp.status, parsed


def fetch_from_url(url: str) -> list[Peer]:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []
            peers = [p for item in parsed if (p := Peer.from_dict(item))]
            log.info("Bootstrap %s -> %d peers", url[:60], len(peers))
            return peers
    except Exception as e:
        log.warning("Bootstrap %s failed: %s", url[:60], e)
        return []


def fetch_all_peers() -> list[Peer]:
    if not BOOTSTRAP_URLS:
        return []
    seen: dict[tuple[str, int], Peer] = {}
    results: list[list[Peer]] = []
    results_lock = threading.Lock()

    def worker(url: str) -> None:
        peers = fetch_from_url(url)
        with results_lock:
            results.append(peers)

    threads = [threading.Thread(target=worker, args=(u,), daemon=True) for u in BOOTSTRAP_URLS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=HTTP_TIMEOUT + 2)

    for result in results:
        for peer in result:
            key = (peer.ip, peer.port)
            if key not in seen:
                seen[key] = peer

    peers = list(seen.values())
    log.info("Total bootstrap peers: %d", len(peers))
    return peers


def register_to_server(server: str, geo: dict[str, str]) -> bool:
    if not server:
        return False
    payload = {
        "port": NODE_PORT,
        "country_code": geo.get("country_code", ""),
        "country": geo.get("country", ""),
        "region": geo.get("region", ""),
        "city": geo.get("city", ""),
        "org": geo.get("org", ""),
        "asn": geo.get("asn", ""),
        "node_id": NODE_ID,
    }
    try:
        status, data = http_json("POST", f"{server.rstrip('/')}/register", payload)
        if status == 200:
            log.info("Registered on server: %s", server)
            return True
        log.warning("Registration failed: %s", data)
        return False
    except Exception as e:
        log.warning("Registration error: %s", e)
        return False


def keepalive_to_server(server: str, geo: dict[str, str]) -> bool:
    if not server:
        return False
    payload = {
        "port": NODE_PORT,
        "country_code": geo.get("country_code", ""),
        "country": geo.get("country", ""),
        "region": geo.get("region", ""),
        "city": geo.get("city", ""),
        "org": geo.get("org", ""),
        "asn": geo.get("asn", ""),
        "node_id": NODE_ID,
    }
    try:
        status, _ = http_json("POST", f"{server.rstrip('/')}/keepalive", payload)
        return status == 200
    except Exception as e:
        log.warning("Keepalive error: %s", e)
        return False


def resolve_dns(domain: str, qtype: str) -> tuple[list[str], int]:
    cache_key = f"{domain}|{qtype}"
    now = time.time()
    with state_lock:
        cached = dns_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > now:
            return cached["answers"], cached["ttl"]
    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT
    resolver.lifetime = DNS_LIFETIME
    try:
        answers = resolver.resolve(domain, qtype)
        ttl = answers.rrset.ttl if answers.rrset else 60
        result = [str(r) for r in answers]
        with state_lock:
            dns_cache[cache_key] = {"answers": result, "ttl": ttl, "expires_at": now + ttl}
        return result, ttl
    except dns.resolver.NXDOMAIN:
        return [], 0
    except dns.resolver.NoAnswer:
        return [], 60
    except Exception as e:
        log.warning("DNS error %s [%s]: %s", domain, qtype, e)
        return [], 0


def try_connect_peer(peer: Peer) -> Optional[socket.socket]:
    for port in FALLBACK_PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((peer.ip, port))
            return sock
        except Exception:
            continue
    return None


def resolve_via_peer(peer: Peer, qname: str, qtype: str) -> Optional[tuple[list[str], int]]:
    sock = try_connect_peer(peer)
    if not sock:
        return None
    try:
        msg = json.dumps({
            "type": "DNS_QUERY",
            "domain": qname,
            "qtype": qtype,
            "timestamp": int(time.time()),
            "node_id": NODE_ID,
        }) + "\n"
        sock.sendall(msg.encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            if len(buf) > MAX_MESSAGE_SIZE:
                return None
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n")[0].decode("utf-8").strip()
        if not line:
            return None
        resp = json.loads(line)
        if not resp.get("ok"):
            return None
        return resp.get("answers", []), int(resp.get("ttl", 60))
    except Exception as e:
        log.warning("Peer %s error: %s", peer.ip, e)
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def resolve_query(qname: str, qtype: str) -> tuple[list[str], int]:
    with state_lock:
        country = _my_country
        peers = [p for p in known_peers if p.country_code == country and p.ip != _my_ip]
    if not peers:
        with state_lock:
            peers = [p for p in known_peers if p.ip != _my_ip]
    if not peers:
        log.error("No peers available for DNS resolution")
        return [], 0
    for peer in peers:
        result = resolve_via_peer(peer, qname, qtype)
        if result is not None:
            log.info("Resolved %s [%s] via %s (%s)", qname, qtype, peer.ip, peer.country_code)
            return result
    log.error("All peers failed for %s", qname)
    return [], 0


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
        if mtype == "HELLO":
            incoming = [p for item in msg.get("peers", []) if (p := Peer.from_dict(item))]
            merge_peers(incoming)
            with state_lock:
                wire = [asdict(p) for p in known_peers]
                connected_peers[addr[0]] = int(time.time())
            send_line(conn, {"type": "PEER_LIST", "ok": True, "peers": wire})
            log.info("HELLO from %s — %d peers", addr[0], len(incoming))
        elif mtype == "DNS_QUERY":
            domain = str(msg.get("domain", "")).strip()
            qtype = str(msg.get("qtype", "A")).upper()
            if not domain:
                send_line(conn, {"type": "DNS_RESPONSE", "ok": False, "error": "MISSING_DOMAIN"})
                return
            answers, ttl = resolve_dns(domain, qtype)
            send_line(conn, {
                "type": "DNS_RESPONSE",
                "ok": True,
                "domain": domain,
                "qtype": qtype,
                "answers": answers,
                "ttl": ttl,
                "resolver_ip": _my_ip,
                "node_id": NODE_ID,
            })
        else:
            send_line(conn, {"type": "ERROR", "error": "UNKNOWN_TYPE"})
    except Exception as e:
        log.warning("Peer error %s: %s", addr[0], e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_node_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((NODE_HOST, NODE_PORT))
    server.listen(32)
    server.settimeout(1.0)
    log.info("Node listening on %s:%d", NODE_HOST, NODE_PORT)
    try:
        while running:
            try:
                conn, addr = server.accept()
                threading.Thread(target=handle_peer, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if running:
                    log.warning("Node server error: %s", e)
    finally:
        try:
            server.close()
        except Exception:
            pass


class DoHHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/status":
            self._send(200, self._status().encode("utf-8"), "text/plain; charset=utf-8")
            return
        if not self.path.startswith("/dns-query"):
            self._send(404, b"Not found", "text/plain")
            return
        params = parse_qs(urlparse(self.path).query)
        name = params.get("name", [""])[0].strip().rstrip(".")
        qtype = params.get("type", ["A"])[0].strip().upper()
        if not name:
            self._send(400, b"Missing name", "text/plain")
            return
        answers, ttl = resolve_query(name, qtype)
        self._send(200, self._json_resp(name, qtype, answers, ttl).encode("utf-8"), "application/dns-json")

    def do_POST(self) -> None:
        if not self.path.startswith("/dns-query"):
            self._send(404, b"Not found", "text/plain")
            return
        if "dns-message" not in self.headers.get("Content-Type", ""):
            self._send(415, b"Unsupported Media Type", "text/plain")
            return
        raw_req = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            request = DNSRecord.parse(raw_req)
            qname = str(request.q.qname).rstrip(".")
            qtype = QTYPE[request.q.qtype]
        except Exception:
            self._send(400, b"Bad DNS request", "text/plain")
            return
        answers, ttl = resolve_query(qname, qtype)
        reply = request.reply()
        if answers:
            for a in answers:
                try:
                    for rr in RR.fromZone(f"{qname}. {ttl} IN {qtype} {a}"):
                        reply.add_answer(rr)
                except Exception:
                    pass
        else:
            reply.header.rcode = dnslib.RCODE.SERVFAIL
        self._send(200, reply.pack(), "application/dns-message")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json_resp(self, name: str, qtype: str, answers: list[str], ttl: int) -> str:
        qt = {"A": 1, "AAAA": 28, "MX": 15, "TXT": 16, "CNAME": 5, "NS": 2}.get(qtype, 1)
        return json.dumps({
            "Status": 0 if answers else 2,
            "TC": False, "RD": True, "RA": True, "AD": False, "CD": False,
            "Question": [{"name": name, "type": qt}],
            "Answer": [{"name": name, "type": qt, "TTL": ttl, "data": a} for a in answers],
        })

    def _status(self) -> str:
        cleanup_connected_peers()
        cleanup_dns_cache()
        with state_lock:
            peers = len(known_peers)
            connected = len(connected_peers)
            cache = len(dns_cache)
        identity = load_identity()
        identity_str = f"{identity['name']} {identity['surname']}" if identity else "non registrato"
        return (
            f"Ask Through You v{APP_VERSION}\n"
            f"IP:        {_my_ip}:{NODE_PORT}\n"
            f"Country:   {_my_country}\n"
            f"Node ID:   {NODE_ID or '-'}\n"
            f"Identity:  {identity_str}\n"
            f"Server:    {_central_server or '-'}\n"
            f"Peers:     {peers} known, {connected} connected\n"
            f"DNS cache: {cache} entries\n"
            f"HF ports:  {FALLBACK_PORTS}\n"
            f"DoH:       http://{DOH_HOST}:{DOH_PORT}/dns-query\n"
        )


class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request: Any, client_address: Any) -> None:
        threading.Thread(target=self._handle, args=(request, client_address), daemon=True).start()

    def _handle(self, request: Any, client_address: Any) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            pass
        finally:
            self.shutdown_request(request)


def keepalive_loop(geo: dict[str, str]) -> None:
    while running:
        time.sleep(KEEPALIVE_INTERVAL)
        if not running:
            break
        cleanup_connected_peers()
        cleanup_dns_cache()
        keepalive_to_server(_central_server, geo)
        save_dns_cache()


def discovery_loop() -> None:
    while running:
        time.sleep(DISCOVERY_INTERVAL)
        if not running:
            break
        cleanup_connected_peers()
        with state_lock:
            targets = [p for p in known_peers if p.ip not in connected_peers and p.ip != _my_ip]
        for peer in targets[:5]:
            sock = try_connect_peer(peer)
            if not sock:
                continue
            try:
                with state_lock:
                    wire = [asdict(p) for p in known_peers]
                send_line(sock, {"type": "HELLO", "peers": wire, "timestamp": int(time.time()), "node_id": NODE_ID})
                resp = recv_line(sock)
                if resp and resp.get("type") == "PEER_LIST":
                    incoming = [p for item in resp.get("peers", []) if (p := Peer.from_dict(item))]
                    merge_peers(incoming)
                    with state_lock:
                        connected_peers[peer.ip] = int(time.time())
                    log.info("Discovery: connected to %s", peer.ip)
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass


def refresh_loop() -> None:
    while running:
        time.sleep(REFRESH_INTERVAL)
        if not running:
            break
        peers = fetch_all_peers()
        if peers:
            merge_peers(peers)


def signal_handler(sig: int, frame: Any) -> None:
    global running
    log.info("Stopping Ask Through You...")
    running = False
    save_dns_cache()


def load_identity() -> Optional[dict[str, Any]]:
    if not IDENTITY_FILE.exists():
        return None
    try:
        return json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


PHONEBOOK_DISCOVERY_URL = "https://nardaxxx.github.io/askthroughyou_peers/phonebook.json"


def _fetch_phonebook_url_from_github() -> str:
    """Scarica l'URL del phonebook da GitHub Pages."""
    try:
        req = urllib.request.Request(
            PHONEBOOK_DISCOVERY_URL,
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            url = str(data.get("phonebook_url", "")).strip()
            if url:
                return url
    except Exception as e:
        log.warning("Impossibile scaricare phonebook.json da GitHub: %s", e)
    return ""


def _ask_phonebook_url() -> str:
    """
    Risolve l'URL del phonebook con priorità:
    1. config.json locale
    2. GitHub Pages (phonebook.json)
    3. Input interattivo
    """
    # 1. config.json locale
    config_file = _app_data_dir_early() / "config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
            url = cfg.get("ATY_PHONEBOOK_URL", "").strip()
            if url:
                return url
        except Exception:
            pass

    # 2. GitHub
    print("Cerco phonebook URL da GitHub...")
    url = _fetch_phonebook_url_from_github()
    if url:
        save_config({"ATY_PHONEBOOK_URL": url})
        os.environ["ATY_PHONEBOOK_URL"] = url
        print(f"URL trovato: {url}")
        return url

    # 3. Input interattivo
    print("\nImpossibile trovare il phonebook automaticamente.")
    url = input("Inserisci URL phonebook ATY: ").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "http://" + url
    save_config({"ATY_PHONEBOOK_URL": url})
    os.environ["ATY_PHONEBOOK_URL"] = url
    print(f"URL salvato in {_app_data_dir_early() / 'config.json'}")
    return url


def cmd_register(name: str, surname: str, country: str) -> int:
    """Registra l'utente al phonebook e salva le credenziali localmente."""
    global PHONEBOOK_URL
    phonebook = PHONEBOOK_URL
    if not phonebook:
        phonebook = _ask_phonebook_url()
    if not phonebook:
        print("Errore: URL phonebook non fornito.")
        return 1

    node_id = NODE_ID

    payload = {
        "name": name.strip().lower(),
        "surname": surname.strip().lower(),
        "country_code": country.strip().upper(),
        "node_id": node_id,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{phonebook.rstrip('/')}/register",
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1

        identity = {
            "contact_id": result["contact_id"],
            "secret": result["secret"],
            "name": name.strip().lower(),
            "surname": surname.strip().lower(),
            "country": country.strip().upper(),
            "phonebook_url": phonebook,
        }
        IDENTITY_FILE.write_text(json.dumps(identity, indent=2), encoding="utf-8")

        print(f"Registrato come {name} {surname} ({country.upper()})")
        print(f"Credenziali salvate in {IDENTITY_FILE}")
        return 0

    except Exception as e:
        print(f"Errore connessione al phonebook: {e}")
        return 1


def _phonebook_request(
    method: str,
    path: str,
    payload: Optional[dict[str, Any]] = None,
) -> tuple[int, Any]:
    """Chiamata HTTP al phonebook con credenziali da identity.json."""
    identity = load_identity()
    if not identity:
        raise RuntimeError("Non sei registrato. Usa prima --register.")
    pb_url = identity.get("phonebook_url") or PHONEBOOK_URL
    if not pb_url:
        raise RuntimeError("Phonebook URL non trovato in identity.json né in config.")
    headers = {
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "X-Contact-ID": identity["contact_id"],
        "X-Contact-Secret": identity["secret"],
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = f"{pb_url.rstrip('/')}/{path.lstrip('/')}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except Exception:
            return resp.status, body


def cmd_search(name: str, surname: str, city: str = "") -> int:
    """Cerca una persona nel phonebook."""
    try:
        payload: dict[str, Any] = {"name": name, "surname": surname}
        if city:
            payload["city"] = city
        status, result = _phonebook_request("POST", "/search", payload)
        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1
        rid = result["request_id"]
        expires = result.get("expires_at", 0)
        expires_str = time.strftime("%H:%M:%S", time.localtime(expires)) if expires else "?"
        print(f"Richiesta inviata.")
        print(f"  request_id : {rid}")
        print(f"  stato      : in attesa di autorizzazione")
        print(f"  scade alle : {expires_str}")
        print(f"\nUsa --status {rid} per controllare la risposta.")
        return 0
    except Exception as e:
        print(f"Errore: {e}")
        return 1


def cmd_pending() -> int:
    """Mostra le richieste di contatto in arrivo in attesa di autorizzazione."""
    try:
        status, result = _phonebook_request("GET", "/pending")
        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1
        pending = result.get("pending", [])
        if not pending:
            print("Nessuna richiesta in arrivo.")
            return 0
        print(f"\n{len(pending)} richiesta/e in arrivo:\n")
        for r in pending:
            created = time.strftime("%d/%m %H:%M", time.localtime(r["created_at"]))
            expires = time.strftime("%H:%M:%S", time.localtime(r["expires_at"]))
            print(f"  [{r['request_id']}]")
            print(f"    Da       : {r['from_id']}")
            print(f"    Cerca    : {r['search_query']}")
            print(f"    Ricevuta : {created}  |  Scade: {expires}")
            print()
        print("Usa --authorize <request_id> <accept|accept_always|reject|block>")
        return 0
    except Exception as e:
        print(f"Errore: {e}")
        return 1


def cmd_authorize(request_id: str, action: str) -> int:
    """Accetta o rifiuta una richiesta di contatto."""
    action_map = {
        "accept": "accept_once",
        "accept_always": "accept_always",
        "reject": "reject",
        "block": "block",
    }
    mapped = action_map.get(action.lower())
    if not mapped:
        print(f"Azione non valida: {action}")
        print("Valori accettati: accept, accept_always, reject, block")
        return 1
    try:
        status, result = _phonebook_request("POST", "/authorize", {
            "request_id": request_id,
            "action": mapped,
        })
        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1
        labels = {
            "accept_once": "Accettata (una volta)",
            "accept_always": "Accettata (sempre — contatto fidato)",
            "reject": "Rifiutata",
            "block": "Rifiutata e utente bloccato",
        }
        print(f"OK — {labels.get(mapped, mapped)}")
        return 0
    except Exception as e:
        print(f"Errore: {e}")
        return 1


def cmd_status(request_id: str) -> int:
    """Controlla lo stato di una richiesta di ricerca inviata."""
    try:
        status, result = _phonebook_request("GET", f"/request/{request_id}")
        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1
        s = result.get("status", "?")
        print(f"Richiesta : {request_id}")
        print(f"Stato     : {s}")
        if s == "accepted":
            token = result.get("connect_token")
            if token:
                # Riscatta il token automaticamente
                try:
                    _, conn_result = _phonebook_request("GET", f"/connect/{token}")
                    if conn_result.get("ok") and conn_result.get("online"):
                        print(f"IP        : {conn_result['ip']}")
                        print(f"Porta     : {conn_result['port']}")
                        print(f"Paese     : {conn_result.get('country_code', '?')}")
                    else:
                        print("Contatto offline o nodo non registrato.")
                except Exception as e:
                    print(f"Errore recupero IP: {e}")
            else:
                print("Accettato ma nessun token disponibile.")
        elif s == "no_response":
            print("L'utente non ha risposto o ha rifiutato.")
        return 0
    except Exception as e:
        print(f"Errore: {e}")
        return 1


def cmd_connect(token: str) -> int:
    """Riscatta un connect token e ottieni IP+porta del contatto."""
    try:
        status, result = _phonebook_request("GET", f"/connect/{token}")
        if not result.get("ok"):
            print(f"Errore: {result.get('error', 'sconosciuto')}")
            return 1
        if result.get("online"):
            print(f"Contatto online:")
            print(f"  IP   : {result['ip']}")
            print(f"  Porta: {result['port']}")
            print(f"  Paese: {result.get('country_code', '?')}")
        else:
            print("Contatto offline o nodo non registrato.")
        return 0
    except Exception as e:
        print(f"Errore: {e}")
        return 1


def cmd_list() -> int:
    log.info("Fetching bootstrap peers...")
    peers = fetch_all_peers()
    if not peers:
        peers = load_peer_cache()
    if not peers:
        print("No peers found.")
        return 0
    countries: dict[str, int] = {}
    for p in peers:
        c = p.country_code or "??"
        countries[c] = countries.get(c, 0) + 1
    print("\nAvailable countries:\n")
    for c in sorted(countries):
        print(f"  {c}  ({countries[c]} nodes)")
    print(f"\n  Total: {len(peers)} nodes\n")
    return 0


def cmd_run(country: str) -> int:
    global running, _my_ip, _my_country, _central_server

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    load_dns_cache()

    log.info("Detecting public IP...")
    my_ip = get_public_ip()
    if not my_ip:
        log.error("Cannot detect public IP")
        return 1

    _my_ip = my_ip
    _my_country = country.upper()

    log.info("IP: %s", my_ip)
    log.info("Target country: %s", _my_country)

    geo = get_geo(my_ip)
    if geo:
        log.info("Local geo: %s, %s — %s", geo.get("city"), geo.get("country"), geo.get("org"))
    else:
        log.warning("Geo lookup failed")

    if not geo.get("country_code"):
        geo["country_code"] = country.upper()

    peers = fetch_all_peers()
    if peers:
        merge_peers(peers)
    else:
        cached = load_peer_cache()
        if cached:
            merge_peers(cached)
            log.info("Using local peer cache")
        else:
            log.warning("No bootstrap peers and no cache")

    with state_lock:
        all_peers = list(known_peers)
    _central_server = discover_server(country, all_peers)

    register_to_server(_central_server, geo)

    identity = load_identity()
    pb_url = PHONEBOOK_URL or (identity.get("phonebook_url") if identity else None)
    if identity and pb_url and my_ip:
        try:
            payload = json.dumps({"node_id": NODE_ID}).encode("utf-8")
            req = urllib.request.Request(
                f"{pb_url.rstrip('/')}/update",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Contact-ID": identity["contact_id"],
                    "X-Contact-Secret": identity["secret"],
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                },
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
            log.info("Phonebook node_id aggiornato")
        except Exception as e:
            log.warning("Phonebook update failed: %s", e)

    def initial_hello():
        time.sleep(2)
        with state_lock:
            targets = list(known_peers)
        for peer in targets[:5]:
            if peer.ip == _my_ip:
                continue
            sock = try_connect_peer(peer)
            if not sock:
                log.warning("Initial HELLO to %s failed on all ports", peer.ip)
                continue
            try:
                with state_lock:
                    wire = [asdict(p) for p in known_peers]
                send_line(sock, {
                    "type": "HELLO",
                    "peers": wire,
                    "timestamp": int(time.time()),
                    "node_id": NODE_ID,
                    "ip": _my_ip,
                })
                resp = recv_line(sock)
                if resp and resp.get("type") == "PEER_LIST":
                    incoming = [p for item in resp.get("peers", []) if (p := Peer.from_dict(item))]
                    merge_peers(incoming)
                    with state_lock:
                        connected_peers[peer.ip] = int(time.time())
                    log.info("Initial HELLO to %s OK", peer.ip)
            except Exception as e:
                log.warning("Initial HELLO to %s failed: %s", peer.ip, e)
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

    threading.Thread(target=initial_hello, daemon=True).start()

    threads = [
        threading.Thread(target=start_node_server, daemon=True),
        threading.Thread(target=refresh_loop, daemon=True),
        threading.Thread(target=discovery_loop, daemon=True),
        threading.Thread(target=keepalive_loop, args=(geo,), daemon=True),
    ]
    for t in threads:
        t.start()

    doh_server = ThreadedHTTPServer((DOH_HOST, DOH_PORT), DoHHandler)
    threading.Thread(target=doh_server.serve_forever, daemon=True).start()

    log.info("=" * 58)
    log.info("Ask Through You v%s active", APP_VERSION)
    log.info("Node: %s:%d", NODE_HOST, NODE_PORT)
    log.info("Country: %s", _my_country)
    log.info("Server: %s", _central_server or "none")
    log.info("HF ports: %s", FALLBACK_PORTS)
    log.info("DoH: http://127.0.0.1:%d/dns-query", DOH_PORT)
    log.info("Status: http://127.0.0.1:%d/status", DOH_PORT)
    log.info("=" * 58)

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
    finally:
        try:
            doh_server.shutdown()
        except Exception:
            pass
        save_dns_cache()

    log.info("Ask Through You stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ask Through You — distributed human-node DNS"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--country", "-c", metavar="XX", help="Target country (e.g.: CH, IT, DE)")
    group.add_argument("--list", "-l", action="store_true", help="Show available countries")
    group.add_argument("--register", nargs=3, metavar=("NOME", "COGNOME", "PAESE"),
                       help="Registrati al phonebook: --register nome cognome CH")
    group.add_argument("--search", nargs="+", metavar="NOME",
                       help="Cerca persona: --search nome cognome [città]")
    group.add_argument("--pending", action="store_true",
                       help="Mostra richieste in arrivo da autorizzare")
    group.add_argument("--authorize", nargs=2, metavar=("REQUEST_ID", "AZIONE"),
                       help="Autorizza richiesta: --authorize <id> accept|accept_always|reject|block")
    group.add_argument("--status", metavar="REQUEST_ID",
                       help="Controlla stato di una richiesta inviata")
    group.add_argument("--connect", metavar="TOKEN",
                       help="Riscatta token e ottieni IP contatto")
    args = parser.parse_args()

    if args.list:
        return cmd_list()
    if args.register:
        return cmd_register(args.register[0], args.register[1], args.register[2])
    if args.search:
        parts = args.search
        name = parts[0] if len(parts) > 0 else ""
        surname = parts[1] if len(parts) > 1 else ""
        city = parts[2] if len(parts) > 2 else ""
        if not name or not surname:
            print("Uso: --search nome cognome [città]")
            return 1
        return cmd_search(name, surname, city)
    if args.pending:
        return cmd_pending()
    if args.authorize:
        return cmd_authorize(args.authorize[0], args.authorize[1])
    if args.status:
        return cmd_status(args.status)
    if args.connect:
        return cmd_connect(args.connect)
    return cmd_run(args.country)


if __name__ == "__main__":
    sys.exit(main())
