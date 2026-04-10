#!/usr/bin/env python3
"""
Ask Through You
---------------
Nodo utente distribuito.

Funzioni:
- si registra al centralino
- scarica la peer list bootstrap
- mantiene cache locale peer e DNS
- espone DoH locale
- inoltra query DNS ad altri peer
- serve query agli altri peer

Compatibile con:
- Linux
- Windows
- Android (Termux / Pydroid, con i limiti della piattaforma)

Dipendenze:
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
import urllib.error
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
    print("Errore: pip install dnspython")
    sys.exit(1)

try:
    import dnslib
    from dnslib import DNSRecord, RR, QTYPE
except ImportError:
    print("Errore: pip install dnslib")
    sys.exit(1)


# ================= .env =================

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
        print(f"Attenzione: impossibile leggere {filename}: {e}")


load_dotenv_file()


# ================= LOG =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("askthroughyou")


# ================= CONFIG =================

APP_NAME = "askthroughyou"
APP_VERSION = "1.0"

NODE_HOST = "0.0.0.0"
NODE_PORT = int(os.getenv("ATY_LISTEN_PORT", "35353"))

DOH_HOST = "127.0.0.1"
DOH_PORT = int(os.getenv("ATY_DOH_PORT", "53535"))

CONNECT_TIMEOUT = int(os.getenv("ATY_CONNECT_TIMEOUT", "5"))
HTTP_TIMEOUT = int(os.getenv("ATY_HTTP_TIMEOUT", "10"))

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

CENTRAL_SERVER = os.getenv("ATY_SERVER_URL", "").strip()
API_TOKEN = os.getenv("ATY_API_TOKEN", "").strip()
NODE_ID = os.getenv("ATY_NODE_ID", "").strip()

BOOTSTRAP_URLS = [
    u.strip()
    for u in os.getenv("ATY_BOOTSTRAP_URLS", "https://nardaxxx.github.io/askthroughyou_peers/peers.json").split(",")
    if u.strip()
]


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / "AskThroughYou"
    return Path.home() / ".askthroughyou"


DATA_DIR = app_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PEER_CACHE_FILE = DATA_DIR / "peers_cache.json"
DNS_CACHE_FILE = DATA_DIR / "dns_cache.json"


# ================= STATE =================

running = True
state_lock = threading.Lock()

_my_ip = ""
_my_country = ""

known_peers: list["Peer"] = []
connected_peers: dict[str, int] = {}
dns_cache: dict[str, dict[str, Any]] = {}


# ================= PEER =================

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
                ip=ip,
                port=port,
                last_seen=last_seen,
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


# ================= FILE CACHE =================

def save_peer_cache(peers: list[Peer]) -> None:
    try:
        raw = [asdict(p) for p in peers]
        PEER_CACHE_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Impossibile salvare peer cache: %s", e)


def load_peer_cache() -> list[Peer]:
    if not PEER_CACHE_FILE.exists():
        return []
    try:
        raw = json.loads(PEER_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [p for item in raw if (p := Peer.from_dict(item))]
    except Exception as e:
        log.warning("Impossibile leggere peer cache: %s", e)
        return []


def save_dns_cache() -> None:
    try:
        with state_lock:
            DNS_CACHE_FILE.write_text(json.dumps(dns_cache, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Impossibile salvare DNS cache: %s", e)


def load_dns_cache() -> None:
    global dns_cache
    if not DNS_CACHE_FILE.exists():
        return
    try:
        raw = json.loads(DNS_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            dns_cache = raw
    except Exception as e:
        log.warning("Impossibile leggere DNS cache: %s", e)


def cleanup_dns_cache() -> None:
    now = time.time()
    with state_lock:
        expired = [k for k, v in dns_cache.items() if v.get("expires_at", 0) <= now]
        for k in expired:
            del dns_cache[k]


# ================= GEO + IP =================

def get_public_ip() -> Optional[str]:
    for url in PUBLIC_IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None


def get_geo(ip: str) -> dict[str, str]:
    try:
        url = GEO_API.format(ip=ip)
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("success", True):
                raise RuntimeError(data.get("message", "geo lookup failed"))
            connection = data.get("connection", {}) or {}
            return {
                "country": data.get("country", ""),
                "country_code": data.get("country_code", ""),
                "region": data.get("region", ""),
                "city": data.get("city", ""),
                "org": connection.get("org", ""),
                "asn": str(connection.get("asn", "")),
            }
    except Exception as e:
        log.warning("Geo lookup fallito: %s", e)
        return {}


# ================= PEER HELPERS =================

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


# ================= HTTP HELPERS =================

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


# ================= BOOTSTRAP =================

def fetch_from_url(url: str) -> list[Peer]:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []
            peers = [p for item in parsed if (p := Peer.from_dict(item))]
            log.info("Bootstrap %s -> %d peer", url[:60], len(peers))
            return peers
    except Exception as e:
        log.warning("Bootstrap %s fallito: %s", url[:60], e)
        return []


def fetch_all_peers() -> list[Peer]:
    if not BOOTSTRAP_URLS:
        return []
    seen: dict[tuple[str, int], Peer] = {}
    threads: list[threading.Thread] = []
    results: list[list[Peer]] = []
    results_lock = threading.Lock()

    def worker(url: str) -> None:
        peers = fetch_from_url(url)
        with results_lock:
            results.append(peers)

    for url in BOOTSTRAP_URLS:
        t = threading.Thread(target=worker, args=(url,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=HTTP_TIMEOUT + 2)
    for result in results:
        for peer in result:
            key = (peer.ip, peer.port)
            if key not in seen:
                seen[key] = peer
    peers = list(seen.values())
    log.info("Totale peer bootstrap: %d", len(peers))
    return peers


# ================= CENTRAL SERVER =================

def register_to_server(geo: dict[str, str]) -> bool:
    if not CENTRAL_SERVER:
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
        status, data = http_json("POST", f"{CENTRAL_SERVER.rstrip('/')}/register", payload)
        if status == 200:
            log.info("Registrazione centralino OK")
            return True
        log.warning("Registrazione centralino fallita: %s", data)
        return False
    except Exception as e:
        log.warning("Errore register centralino: %s", e)
        return False


def keepalive_to_server(geo: dict[str, str]) -> bool:
    if not CENTRAL_SERVER:
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
        status, data = http_json("POST", f"{CENTRAL_SERVER.rstrip('/')}/keepalive", payload)
        if status == 200:
            return True
        log.warning("Keepalive centralino fallito: %s", data)
        return False
    except Exception as e:
        log.warning("Errore keepalive centralino: %s", e)
        return False


# ================= DNS =================

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


def resolve_via_peer(peer: Peer, qname: str, qtype: str) -> Optional[tuple[list[str], int]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((peer.ip, peer.port))
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
        log.error("Nessun peer per paese: %s", country)
        return [], 0
    for peer in peers:
        result = resolve_via_peer(peer, qname, qtype)
        if result is not None:
            log.info("Risolto %s [%s] via %s (%s)", qname, qtype, peer.ip, peer.country_code)
            return result
    log.error("Tutti i peer di %s hanno fallito per %s", country, qname)
    return [], 0


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
        except Exception:
            return None
    try:
        line = buf.split(b"\n")[0].decode("utf-8").strip()
        return json.loads(line) if line else None
    except Exception:
        return None


# ================= NODE SERVER =================

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
            log.info("HELLO da %s — %d peer", addr[0], len(incoming))
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
        log.warning("Errore peer %s: %s", addr[0], e)
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
    log.info("Nodo in ascolto su %s:%d", NODE_HOST, NODE_PORT)
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


# ================= DOH SERVER =================

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
        return (
            f"AskThroughYou v{APP_VERSION}\n"
            f"IP:        {_my_ip}:{NODE_PORT}\n"
            f"Country:   {_my_country}\n"
            f"Node ID:   {NODE_ID or '-'}\n"
            f"Peers:     {peers} known, {connected} connected\n"
            f"DNS cache: {cache} entries\n"
            f"DoH:       http://{DOH_HOST}:{DOH_PORT}/dns-query\n"
            f"Server:    {CENTRAL_SERVER or '-'}\n"
            f"API token: {('enabled' if API_TOKEN else '-')}\n"
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


# ================= BACKGROUND LOOPS =================

def keepalive_loop(geo: dict[str, str]) -> None:
    while running:
        time.sleep(KEEPALIVE_INTERVAL)
        if not running:
            break
        cleanup_connected_peers()
        cleanup_dns_cache()
        keepalive_to_server(geo)
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
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(CONNECT_TIMEOUT)
                sock.connect((peer.ip, peer.port))
                with state_lock:
                    wire = [asdict(p) for p in known_peers]
                send_line(sock, {"type": "HELLO", "peers": wire, "timestamp": int(time.time()), "node_id": NODE_ID})
                resp = recv_line(sock)
                sock.close()
                if resp and resp.get("type") == "PEER_LIST":
                    incoming = [p for item in resp.get("peers", []) if (p := Peer.from_dict(item))]
                    merge_peers(incoming)
                    with state_lock:
                        connected_peers[peer.ip] = int(time.time())
                    log.info("Discovery: connesso a %s", peer.ip)
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


# ================= SIGNAL =================

def signal_handler(sig: int, frame: Any) -> None:
    global running
    log.info("Arresto Ask Through You...")
    running = False
    save_dns_cache()


# ================= COMMANDS =================

def cmd_list() -> int:
    log.info("Scarico peer bootstrap...")
    peers = fetch_all_peers()
    if not peers:
        peers = load_peer_cache()
    if not peers:
        print("Nessun peer trovato.")
        return 0
    countries: dict[str, int] = {}
    for p in peers:
        c = p.country_code or "??"
        countries[c] = countries.get(c, 0) + 1
    print("\nPaesi disponibili:\n")
    for c in sorted(countries):
        n = countries[c]
        print(f"  {c}  ({n} nodes)")
    print(f"\n  Totale: {len(peers)} nodes\n")
    return 0


def cmd_run(country: str) -> int:
    global running, _my_ip, _my_country

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    load_dns_cache()

    log.info("Rilevo IP pubblico...")
    my_ip = get_public_ip()
    if not my_ip:
        log.error("Impossibile rilevare IP pubblico")
        return 1

    _my_ip = my_ip
    _my_country = country.upper()

    log.info("IP: %s", my_ip)
    log.info("Country target: %s", _my_country)

    geo = get_geo(my_ip)
    if geo:
        log.info("Geo locale: %s, %s — %s", geo.get("city"), geo.get("country"), geo.get("org"))
    else:
        log.warning("Geo locale non disponibile")

    if not geo.get("country_code"):
        geo["country_code"] = country.upper()

    peers = fetch_all_peers()
    if peers:
        merge_peers(peers)
    else:
        cached = load_peer_cache()
        if cached:
            merge_peers(cached)
            log.info("Uso peer cache locale")
        else:
            log.warning("Nessun bootstrap e nessuna cache peer")

    register_to_server(geo)

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
    log.info("Ask Through You attivo")
    log.info("Nodo attivo su %s:%d", NODE_HOST, NODE_PORT)
    log.info("Paese scelto: %s", _my_country)
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
        try:
            doh_server.server_close()
        except Exception:
            pass
        save_dns_cache()

    log.info("Ask Through You fermato.")
    return 0


# ================= MAIN =================

def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Through You — distributed human-node DNS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--country", "-c", metavar="XX", help="Paese target (es: DE, FR, CH, US)")
    group.add_argument("--list", "-l", action="store_true", help="Mostra i paesi disponibili")
    args = parser.parse_args()
    if args.list:
        return cmd_list()
    return cmd_run(args.country)


if __name__ == "__main__":
    sys.exit(main())
