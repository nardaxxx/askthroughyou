# Ask Through You

**Ask the internet through someone else.**

A distributed human-node DNS network. Every user is simultaneously a client and a node. DNS queries are routed through real users in chosen countries, exposing geographic and ISP-level DNS inconsistencies.

No central server. No logs. No surveillance.

---

## How it works

- Each node registers itself on a public peer list (GitHub Pages)
- Clients read the peer list and choose a country
- DNS queries are routed through a peer in that country
- The peer resolves the query locally and returns the result
- The network is invisible — traffic looks like normal DNS

---

## Components

| File | Role |
|------|------|
| `askthroughyou.py` | User node — client + DNS relay |
| `askthroughyou_server.py` | Bootstrap server — manages peer registry on GitHub |
| `.env` | Configuration (never commit this file) |

---

## Quick Start — User Node

### Requirements

```
pip install dnspython dnslib
```

### Run

```bash
# Show available countries
python askthroughyou.py --list

# Connect via a specific country
python askthroughyou.py --country CH
```

### DNS endpoint (once running)

```
http://127.0.0.1:53535/dns-query
```

Configure this as your DNS-over-HTTPS provider in your browser or OS.

### Status page

```
http://127.0.0.1:53535/status
```

---

## Quick Start — Bootstrap Server (Synology NAS / Linux)

The bootstrap server runs on your always-on machine. It manages the peer registry and writes it to GitHub automatically.

### Requirements

```
pip install flask requests python-dotenv
```

### Configuration — `.env`

Create a `.env` file in the same folder as `askthroughyou_server.py`:

```
# GitHub — required for peer registry
GITHUB_TOKEN=ghp_yourtoken
ATY_REPO_OWNER=yourusername
ATY_REPO_NAME=askthroughyou_peers
ATY_BRANCH=main
ATY_FILE_PATH=peers.json

# Server
ATY_SERVER_HOST=0.0.0.0
ATY_SERVER_PORT=8090

# Node
ATY_NODE_ID=node-001
ATY_COUNTRY_CODE=CH
ATY_LISTEN_PORT=35353

# Timing
ATY_KEEPALIVE_INTERVAL=120
ATY_MAX_PEER_AGE=900
ATY_REQUEST_TIMEOUT=15
```

**Never commit `.env` to GitHub.** Add it to `.gitignore`.

### Run

```bash
python askthroughyou_server.py &
```

### What the server does automatically

- Reads its own public IP via `ipify.org` and `ifconfig.me` — no manual configuration needed
- Registers itself on the peer list at startup
- Sends keepalive to GitHub every `ATY_KEEPALIVE_INTERVAL` seconds (default: 120s)
- Cleans up stale peers older than `ATY_MAX_PEER_AGE` seconds (default: 900s = 15 min)

### API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status and GitHub connectivity |
| `/peers` | GET | Current peer list |
| `/register` | POST | Register a new node |
| `/keepalive` | POST | Update node timestamp |
| `/cleanup` | POST | Remove stale peers |

### Register manually (optional)

```bash
curl -X POST http://localhost:8090/register \
  -H "Content-Type: application/json" \
  -d '{"port":35353,"country_code":"CH","node_id":"node-001"}'
```

---

## Peer list (public)

The peer list is published as a public JSON file via GitHub Pages:

```
https://yourusername.github.io/askthroughyou_peers/peers.json
```

To enable GitHub Pages on the `askthroughyou_peers` repo:
- Settings → Pages → Source: main branch → Save

---

## Client `.env` (optional)

```
ATY_SERVER_URL=http://your-nas-ip:8090
ATY_BOOTSTRAP_URLS=https://yourusername.github.io/askthroughyou_peers/peers.json
ATY_NODE_ID=node-001
ATY_LISTEN_PORT=35353
ATY_DOH_PORT=53535
ATY_CONNECT_TIMEOUT=5
ATY_HTTP_TIMEOUT=10
ATY_KEEPALIVE_INTERVAL=120
ATY_DISCOVERY_INTERVAL=180
ATY_REFRESH_INTERVAL=300
ATY_MAX_PEER_AGE=900
ATY_MAX_MESSAGE_SIZE=65536
ATY_DNS_TIMEOUT=3.0
ATY_DNS_LIFETIME=5.0
```

---

## Android (Termux)

```bash
pkg install python
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/yourusername/askthroughyou/main/askthroughyou.py
python askthroughyou.py --list
```

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment.

See `LICENSE` file for full terms.

---

## Project

Part of the Ask Through You initiative — restoring DNS universality, not bypassing censorship.
