#!/usr/bin/env python3
"""
Ask Through You — Phonebook Operator v1.1
------------------------------------------
The 1920s telephone switchboard for ATY.

Users register with a real name. Callers search by name+surname (+city).
The operator mediates: it notifies the callee someone is looking for
them, waits for authorization, and only then reveals the IP taken
from the ATY peers.json (the live network directory).

SIMPLIFIED MODEL (v1.1)
-----------------------
Every search always generates a pending request — the callee always
decides. No privacy modes, no default invisibility. If you don't want
to be reached, simply don't answer (the request expires in 24h), or
block the caller after the first attempt.

IPs are NOT stored here. The phonebook fetches them live from
peers.json (the ATY network tabellone) using the user's node_id.

Anti-fingerprint: all negative outcomes (no match / blocked / rejected
/ timeout) collapse to 'no_response' from the caller's point of view.
The caller cannot map the directory by probing names.

Runs on the NAS alongside askthroughyou_server.py. SQLite local —
NOTHING is published to GitHub.

Dependencies:
  pip install flask requests python-dotenv
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

import requests
from flask import Flask, g, jsonify, request


# ================= LOG =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("askthroughyou-phonebook")


# ================= CONFIG =================

APP_NAME = "askthroughyou-phonebook"
APP_VERSION = "1.1"

HOST = os.getenv("ATY_PHONEBOOK_HOST", "0.0.0.0")
PORT = int(os.getenv("ATY_PHONEBOOK_PORT", "8091"))

DB_PATH = os.getenv(
    "ATY_PHONEBOOK_DB",
    str(Path.home() / ".askthroughyou" / "phonebook.db"),
)

# Where to fetch the live peers.json (the IP tabellone).
# Default: the local bootstrap server on the same NAS.
# Alternative: the public GitHub Pages URL.
PEERS_SOURCE = os.getenv(
    "ATY_PHONEBOOK_PEERS_SOURCE",
    "http://localhost:8090/peers",
).strip()

REQUEST_TIMEOUT = int(os.getenv("ATY_PHONEBOOK_REQUEST_TIMEOUT", str(24 * 3600)))  # 24h
CONNECT_TOKEN_TTL = int(os.getenv("ATY_PHONEBOOK_CONNECT_TTL", "300"))  # 5 min
PEERS_FETCH_TIMEOUT = int(os.getenv("ATY_PHONEBOOK_PEERS_TIMEOUT", "5"))

MAX_SEARCHES_PER_HOUR = int(os.getenv("ATY_PHONEBOOK_MAX_SEARCHES_PER_HOUR", "30"))


# ================= DB =================

db_lock = threading.Lock()


def ensure_db_dir() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    with db_lock:
        conn = db_connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    ensure_db_dir()
    with db_cursor() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            contact_id     TEXT PRIMARY KEY,
            secret_hash    TEXT NOT NULL,
            name           TEXT NOT NULL,
            surname        TEXT NOT NULL,
            city           TEXT NOT NULL DEFAULT '',
            country_code   TEXT NOT NULL DEFAULT '',
            node_id        TEXT NOT NULL DEFAULT '',
            public_key     TEXT NOT NULL DEFAULT '',
            created_at     INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_name
            ON users (LOWER(name), LOWER(surname), LOWER(city));

        CREATE INDEX IF NOT EXISTS idx_users_node_id
            ON users (node_id);

        CREATE TABLE IF NOT EXISTS blocked_contacts (
            blocker_id     TEXT NOT NULL,
            blocked_id     TEXT NOT NULL,
            created_at     INTEGER NOT NULL,
            PRIMARY KEY (blocker_id, blocked_id),
            FOREIGN KEY (blocker_id) REFERENCES users (contact_id) ON DELETE CASCADE,
            FOREIGN KEY (blocked_id) REFERENCES users (contact_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS trusted_contacts (
            truster_id     TEXT NOT NULL,
            trusted_id     TEXT NOT NULL,
            granted_at     INTEGER NOT NULL,
            PRIMARY KEY (truster_id, trusted_id),
            FOREIGN KEY (truster_id) REFERENCES users (contact_id) ON DELETE CASCADE,
            FOREIGN KEY (trusted_id) REFERENCES users (contact_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS contact_requests (
            request_id     TEXT PRIMARY KEY,
            from_id        TEXT NOT NULL,
            to_id          TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            search_query   TEXT NOT NULL DEFAULT '',
            created_at     INTEGER NOT NULL,
            resolved_at    INTEGER,
            expires_at     INTEGER NOT NULL,
            FOREIGN KEY (from_id) REFERENCES users (contact_id) ON DELETE CASCADE,
            FOREIGN KEY (to_id)   REFERENCES users (contact_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_requests_to_pending
            ON contact_requests (to_id, status);

        CREATE TABLE IF NOT EXISTS connect_tokens (
            token          TEXT PRIMARY KEY,
            request_id     TEXT NOT NULL,
            issued_at      INTEGER NOT NULL,
            expires_at     INTEGER NOT NULL,
            FOREIGN KEY (request_id) REFERENCES contact_requests (request_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_rate_limit (
            contact_id     TEXT NOT NULL,
            window_start   INTEGER NOT NULL,
            count          INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (contact_id, window_start)
        );
        """)
    log.info("DB ready at %s", DB_PATH)


# ================= PEERS FETCH (LIVE IP LOOKUP) =================

_peers_cache: dict[str, Any] = {"data": [], "fetched_at": 0}
_peers_cache_lock = threading.Lock()
PEERS_CACHE_TTL = 30  # seconds


def fetch_peers() -> list[dict[str, Any]]:
    """Fetch the live peers list. Cached for PEERS_CACHE_TTL seconds."""
    now = int(time.time())
    with _peers_cache_lock:
        if now - _peers_cache["fetched_at"] < PEERS_CACHE_TTL:
            return _peers_cache["data"]

    try:
        resp = requests.get(
            PEERS_SOURCE,
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            timeout=PEERS_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # Accept both raw list and {"peers": [...]}
        if isinstance(data, dict) and "peers" in data:
            data = data["peers"]
        if not isinstance(data, list):
            data = []
    except Exception as e:
        log.warning("Failed to fetch peers from %s: %s", PEERS_SOURCE, e)
        data = []

    with _peers_cache_lock:
        _peers_cache["data"] = data
        _peers_cache["fetched_at"] = now
    return data


def find_peer_by_node_id(node_id: str) -> Optional[dict[str, Any]]:
    if not node_id:
        return None
    for peer in fetch_peers():
        if str(peer.get("node_id", "")).strip() == node_id:
            return peer
    return None


# ================= AUTH =================

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def authenticate() -> Optional[sqlite3.Row]:
    cid = request.headers.get("X-Contact-ID", "").strip()
    secret = request.headers.get("X-Contact-Secret", "").strip()
    if not cid or not secret:
        return None
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE contact_id = ? AND secret_hash = ?",
            (cid, hash_secret(secret)),
        ).fetchone()
    return row


def require_auth() -> Optional[tuple[Any, int]]:
    user = authenticate()
    if not user:
        return jsonify({"ok": False, "error": "UNAUTHORIZED"}), 401
    g.user = user
    return None


# ================= RATE LIMIT =================

def check_search_rate(contact_id: str) -> bool:
    now = int(time.time())
    window = now - (now % 3600)
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT count FROM search_rate_limit WHERE contact_id = ? AND window_start = ?",
            (contact_id, window),
        ).fetchone()
        if row and row["count"] >= MAX_SEARCHES_PER_HOUR:
            return False
        if row:
            conn.execute(
                "UPDATE search_rate_limit SET count = count + 1 "
                "WHERE contact_id = ? AND window_start = ?",
                (contact_id, window),
            )
        else:
            conn.execute(
                "INSERT INTO search_rate_limit (contact_id, window_start, count) VALUES (?, ?, 1)",
                (contact_id, window),
            )
        conn.execute(
            "DELETE FROM search_rate_limit WHERE window_start < ?",
            (window - 24 * 3600,),
        )
    return True


# ================= HELPERS =================

def normalize(s: str) -> str:
    return s.strip().lower()


def generate_id() -> str:
    return secrets.token_urlsafe(16)


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


# ================= APP =================

app = Flask(__name__)


@app.get("/health")
def health():
    peers = fetch_peers()
    return jsonify({
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "peers_source": PEERS_SOURCE,
        "peers_reachable": len(peers) > 0 or _peers_cache["fetched_at"] > 0,
        "peers_count": len(peers),
    })


@app.post("/register")
def register():
    """
    Create a new account.
    Body: name, surname, city, country_code, node_id (optional), public_key (optional)
    Returns: contact_id + secret (shown only once).
    """
    payload = request.get_json(silent=True) or {}
    name = normalize(str(payload.get("name", "")))
    surname = normalize(str(payload.get("surname", "")))
    city = normalize(str(payload.get("city", "")))
    country = str(payload.get("country_code", "")).strip().upper()[:2]
    node_id = str(payload.get("node_id", "")).strip()[:64]
    public_key = str(payload.get("public_key", "")).strip()[:1024]

    if not name or not surname:
        return jsonify({"ok": False, "error": "NAME_REQUIRED"}), 400

    cid = generate_id()
    secret = generate_secret()
    now = int(time.time())

    with db_cursor() as conn:
        conn.execute("""
            INSERT INTO users (
                contact_id, secret_hash, name, surname, city, country_code,
                node_id, public_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cid, hash_secret(secret), name, surname, city, country, node_id, public_key, now))

    log.info("REGISTER %s (%s %s, %s) node_id=%s",
             cid, name, surname, country or "??", node_id or "-")
    return jsonify({
        "ok": True,
        "contact_id": cid,
        "secret": secret,
        "warning": "Save the secret now — it will not be shown again.",
    })


@app.post("/update")
def update():
    """Update your own profile (city, country, node_id)."""
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    city = normalize(str(payload.get("city", "")))
    country = str(payload.get("country_code", "")).strip().upper()[:2]
    node_id = str(payload.get("node_id", "")).strip()[:64]

    fields: list[str] = []
    values: list[Any] = []
    if "city" in payload:
        fields.append("city = ?")
        values.append(city)
    if "country_code" in payload:
        fields.append("country_code = ?")
        values.append(country)
    if "node_id" in payload:
        fields.append("node_id = ?")
        values.append(node_id)
    if not fields:
        return jsonify({"ok": False, "error": "NOTHING_TO_UPDATE"}), 400

    values.append(g.user["contact_id"])
    with db_cursor() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE contact_id = ?", tuple(values))
    return jsonify({"ok": True})


@app.post("/search")
def search():
    """
    Search by name+surname (+optional city).

    UNIFORM RESPONSE: always returns pending request_id with 24h timeout,
    regardless of match / miss / block / rejection. Caller polls
    /request/<id> and can only ever see: pending | accepted | no_response.
    """
    err = require_auth()
    if err:
        return err

    caller_id = g.user["contact_id"]

    if not check_search_rate(caller_id):
        return jsonify({"ok": False, "error": "RATE_LIMIT"}), 429

    payload = request.get_json(silent=True) or {}
    name = normalize(str(payload.get("name", "")))
    surname = normalize(str(payload.get("surname", "")))
    city = normalize(str(payload.get("city", "")))

    if not name or not surname:
        return jsonify({"ok": False, "error": "NAME_REQUIRED"}), 400

    now = int(time.time())
    request_id = generate_id()
    expires_at = now + REQUEST_TIMEOUT
    search_query = f"{name} {surname}" + (f" ({city})" if city else "")

    with db_cursor() as conn:
        if city:
            rows = conn.execute(
                "SELECT * FROM users "
                "WHERE LOWER(name) = ? AND LOWER(surname) = ? AND LOWER(city) = ?",
                (name, surname, city),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users WHERE LOWER(name) = ? AND LOWER(surname) = ?",
                (name, surname),
            ).fetchall()

        # Pick first candidate that is not self and not blocking the caller
        target = None
        for row in rows:
            if row["contact_id"] == caller_id:
                continue
            blocked = conn.execute(
                "SELECT 1 FROM blocked_contacts WHERE blocker_id = ? AND blocked_id = ?",
                (row["contact_id"], caller_id),
            ).fetchone()
            if blocked:
                continue
            target = row
            break

        if target is None:
            # Sink request — from_id == to_id → never delivered, expires silently
            conn.execute("""
                INSERT INTO contact_requests
                (request_id, from_id, to_id, status, search_query, created_at, expires_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """, (request_id, caller_id, caller_id, search_query, now, expires_at))
        else:
            # Auto-accept if caller is already in target's trusted_contacts
            auto_trusted = conn.execute(
                "SELECT 1 FROM trusted_contacts WHERE truster_id = ? AND trusted_id = ?",
                (target["contact_id"], caller_id),
            ).fetchone()
            status = "accepted" if auto_trusted else "pending"
            conn.execute("""
                INSERT INTO contact_requests
                (request_id, from_id, to_id, status, search_query, created_at, expires_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id, caller_id, target["contact_id"], status,
                search_query, now, expires_at,
                now if status == "accepted" else None,
            ))

    log.info("SEARCH %s -> %s [%s]", caller_id, search_query, "match" if target else "sink")
    return jsonify({
        "ok": True,
        "request_id": request_id,
        "status": "pending",
        "expires_at": expires_at,
        "timeout_seconds": REQUEST_TIMEOUT,
    })


@app.get("/pending")
def list_pending():
    """Callee polls this to see who is looking for them."""
    err = require_auth()
    if err:
        return err
    now = int(time.time())
    cid = g.user["contact_id"]
    with db_cursor() as conn:
        rows = conn.execute("""
            SELECT request_id, from_id, search_query, created_at, expires_at
            FROM contact_requests
            WHERE to_id = ? AND status = 'pending' AND expires_at > ?
              AND to_id != from_id
            ORDER BY created_at DESC
        """, (cid, now)).fetchall()
    return jsonify({"ok": True, "count": len(rows), "pending": [dict(r) for r in rows]})


@app.post("/authorize")
def authorize():
    """Callee decides: action = accept_once | accept_always | reject | block."""
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    request_id = str(payload.get("request_id", "")).strip()
    action = str(payload.get("action", "")).strip()
    if action not in ("accept_once", "accept_always", "reject", "block"):
        return jsonify({"ok": False, "error": "INVALID_ACTION"}), 400
    if not request_id:
        return jsonify({"ok": False, "error": "MISSING_REQUEST_ID"}), 400

    cid = g.user["contact_id"]
    now = int(time.time())

    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM contact_requests "
            "WHERE request_id = ? AND to_id = ? AND status = 'pending'",
            (request_id, cid),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "REQUEST_NOT_FOUND"}), 404

        caller_id = row["from_id"]

        if action in ("accept_once", "accept_always"):
            conn.execute(
                "UPDATE contact_requests SET status = 'accepted', resolved_at = ? "
                "WHERE request_id = ?",
                (now, request_id),
            )
            if action == "accept_always":
                conn.execute(
                    "INSERT OR IGNORE INTO trusted_contacts "
                    "(truster_id, trusted_id, granted_at) VALUES (?, ?, ?)",
                    (cid, caller_id, now),
                )
        else:
            conn.execute(
                "UPDATE contact_requests SET status = 'rejected', resolved_at = ? "
                "WHERE request_id = ?",
                (now, request_id),
            )
            if action == "block":
                conn.execute(
                    "INSERT OR IGNORE INTO blocked_contacts "
                    "(blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
                    (cid, caller_id, now),
                )

    log.info("AUTHORIZE %s -> %s: %s", cid, request_id, action)
    return jsonify({"ok": True, "action": action})


@app.get("/request/<request_id>")
def request_status(request_id: str):
    """
    Caller polls this for outcome.
    Public status: pending | accepted | no_response (collapses rejected/timeout/sink).
    When accepted → returns a short-lived connect_token.
    """
    err = require_auth()
    if err:
        return err
    cid = g.user["contact_id"]
    now = int(time.time())
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM contact_requests WHERE request_id = ? AND from_id = ?",
            (request_id, cid),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "REQUEST_NOT_FOUND"}), 404

        status = row["status"]
        if status == "pending" and row["expires_at"] <= now:
            status = "timeout"
            conn.execute(
                "UPDATE contact_requests SET status = 'timeout' WHERE request_id = ?",
                (request_id,),
            )

        public_status = {
            "pending": "pending",
            "accepted": "accepted",
            "rejected": "no_response",
            "timeout": "no_response",
        }.get(status, "no_response")

        resp: dict[str, Any] = {
            "ok": True,
            "request_id": request_id,
            "status": public_status,
        }

        if status == "accepted" and row["to_id"] != row["from_id"]:
            token = generate_id()
            token_expires = now + CONNECT_TOKEN_TTL
            conn.execute(
                "INSERT INTO connect_tokens "
                "(token, request_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, request_id, now, token_expires),
            )
            resp["connect_token"] = token
            resp["expires_at"] = token_expires

    return jsonify(resp)


@app.get("/connect/<token>")
def connect(token: str):
    """
    Redeem a connect token. Returns the callee's current IP+port looked up
    live from peers.json (the ATY tabellone) via their node_id.
    Single-use, TTL ~5 min.
    """
    err = require_auth()
    if err:
        return err
    now = int(time.time())
    with db_cursor() as conn:
        row = conn.execute("""
            SELECT ct.request_id, cr.to_id, cr.from_id
            FROM connect_tokens ct
            JOIN contact_requests cr ON cr.request_id = ct.request_id
            WHERE ct.token = ? AND ct.expires_at > ?
        """, (token, now)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "INVALID_OR_EXPIRED_TOKEN"}), 404
        if row["from_id"] != g.user["contact_id"]:
            return jsonify({"ok": False, "error": "NOT_YOUR_TOKEN"}), 403
        callee = conn.execute(
            "SELECT contact_id, node_id FROM users WHERE contact_id = ?",
            (row["to_id"],),
        ).fetchone()
        if not callee:
            return jsonify({"ok": False, "error": "CALLEE_NOT_FOUND"}), 404
        conn.execute("DELETE FROM connect_tokens WHERE token = ?", (token,))

    # Live IP lookup from peers.json
    node_id = callee["node_id"]
    peer = find_peer_by_node_id(node_id) if node_id else None

    if peer:
        return jsonify({
            "ok": True,
            "contact_id": callee["contact_id"],
            "ip": str(peer.get("ip", "")),
            "port": int(peer.get("port", 0)) or 35353,
            "online": True,
            "last_seen": int(peer.get("last_seen", now)),
            "country_code": str(peer.get("country_code", "")),
        })

    # Callee offline or has no node_id set
    return jsonify({
        "ok": True,
        "contact_id": callee["contact_id"],
        "ip": "",
        "port": 0,
        "online": False,
        "note": "Callee is offline or has no node registered",
    })


@app.post("/block")
def block_contact():
    """Block a contact_id — they silently fail all searches toward you."""
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("contact_id", "")).strip()
    if not target:
        return jsonify({"ok": False, "error": "MISSING_TARGET"}), 400
    now = int(time.time())
    with db_cursor() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO blocked_contacts "
            "(blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (g.user["contact_id"], target, now),
        )
    return jsonify({"ok": True, "blocked": target})


@app.post("/unblock")
def unblock_contact():
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("contact_id", "")).strip()
    with db_cursor() as conn:
        conn.execute(
            "DELETE FROM blocked_contacts WHERE blocker_id = ? AND blocked_id = ?",
            (g.user["contact_id"], target),
        )
    return jsonify({"ok": True, "unblocked": target})


@app.post("/trust")
def trust_contact():
    """Add to trusted list — their future searches toward you auto-accept."""
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("contact_id", "")).strip()
    if not target:
        return jsonify({"ok": False, "error": "MISSING_TARGET"}), 400
    now = int(time.time())
    with db_cursor() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO trusted_contacts "
            "(truster_id, trusted_id, granted_at) VALUES (?, ?, ?)",
            (g.user["contact_id"], target, now),
        )
    return jsonify({"ok": True, "trusted": target})


@app.post("/untrust")
def untrust_contact():
    err = require_auth()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("contact_id", "")).strip()
    with db_cursor() as conn:
        conn.execute(
            "DELETE FROM trusted_contacts WHERE truster_id = ? AND trusted_id = ?",
            (g.user["contact_id"], target),
        )
    return jsonify({"ok": True, "untrusted": target})


@app.get("/me")
def me():
    err = require_auth()
    if err:
        return err
    u = g.user
    # Optionally enrich with live peer info
    peer = find_peer_by_node_id(u["node_id"]) if u["node_id"] else None
    return jsonify({
        "ok": True,
        "contact_id": u["contact_id"],
        "name": u["name"],
        "surname": u["surname"],
        "city": u["city"],
        "country_code": u["country_code"],
        "node_id": u["node_id"],
        "online": peer is not None,
        "current_ip": str(peer.get("ip", "")) if peer else "",
        "current_port": int(peer.get("port", 0)) if peer else 0,
    })


# ================= CLEANUP =================

def cleanup_loop() -> None:
    while True:
        time.sleep(600)
        try:
            now = int(time.time())
            with db_cursor() as conn:
                conn.execute(
                    "UPDATE contact_requests SET status = 'timeout' "
                    "WHERE status = 'pending' AND expires_at <= ?",
                    (now,),
                )
                conn.execute(
                    "DELETE FROM connect_tokens WHERE expires_at <= ?",
                    (now,),
                )
        except Exception as e:
            log.warning("Cleanup error: %s", e)


# ================= MAIN =================

if __name__ == "__main__":
    log.info("%s v%s", APP_NAME, APP_VERSION)
    log.info("DB:           %s", DB_PATH)
    log.info("Peers source: %s", PEERS_SOURCE)
    log.info("Host:         %s:%d", HOST, PORT)

    init_db()

    threading.Thread(target=cleanup_loop, daemon=True).start()
    log.info("Cleanup thread started")

    app.run(host=HOST, port=PORT, debug=False, threaded=True)
