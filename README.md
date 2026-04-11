# Ask Through You

**Ask the internet through someone else.**

A distributed human-node DNS network. Every user is simultaneously a client and a node. DNS queries are routed through real users in chosen countries, exposing geographic and ISP-level DNS inconsistencies.

No central server. No query logging. No content surveillance.

Node operators keep connection logs (IP, timestamp, duration, country). Query content is never recorded. Connection logs are public — they form the network directory. Every node that connects becomes part of a global address book, visible on GitHub. The network is designed to see the world as it is, not to hide.

**Vision:** connection logs are the foundation of a future distributed communication layer — a global directory where every node is a contact, enabling P2P messaging without central servers.

---

## How it works

1. Each node registers itself on a public peer list (GitHub Pages)
2. Clients read the peer list and choose a country
3. The client connects to a node in that country
4. DNS queries are routed through that node and resolved locally
5. The network is invisible — traffic looks like normal DNS

---

## Components

| File | Role |
|------|------|
| `askthroughyou.py` | User node — client + DNS relay |
| `askthroughyou_server.py` | Bootstrap server — manages peer registry on GitHub |
| `.env` | Configuration (never commit this file) |

---

## Quick Start — User (Client)

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

### Status page

```
http://127.0.0.1:53535/status
```

### Android (Termux)

```bash
pkg install python
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
python askthroughyou.py --list
python askthroughyou.py --country CH
```

---

## Configure your browser

Once `askthroughyou.py --country XX` is running, set this DoH endpoint in your browser:

```
http://127.0.0.1:53535/dns-query
```

### Brave
Settings → Privacy and Security → Security → Use secure DNS → With Custom → paste the URL above.

### Chrome
Settings → Privacy and Security → Security → Use secure DNS → With Custom → paste the URL above.

### Firefox
Settings → Privacy & Security → scroll to DNS over HTTPS → Enable → Custom → paste the URL above.

### Edge
Settings → Privacy, search, and services → Security → Use secure DNS → Choose a service provider → Custom → paste the URL above.

### Android — Brave
Same as desktop: Settings → Privacy and Security → Security → Use secure DNS → Custom.

### Android — system-wide (Android 9+)
Settings → Network → Private DNS → Private DNS provider hostname.

Note: Android system DNS only supports DoT (port 853), not DoH. For DoH use the browser setting above.

### iOS
iOS requires a DNS configuration profile. Create one at: https://dnscrypt.info/stamps

Or use Brave on iOS which supports DoH natively.

---

## Quick Start — Node Operator

A node is any always-on machine that runs the bootstrap server and accepts incoming connections. It registers itself on GitHub and logs clients.

### Requirements

```
pip install flask requests python-dotenv dnspython
```

### Port forwarding — required for public nodes

For your node to be reachable from the internet, open **TCP port 35353** on your router.

**Single router:**
Add a port forward: external port `35353` → your server's local IP → port `35353`.

**Double NAT (two routers in cascade):**
- Router 1 (main, e.g. Fritz!Box): port forward `35353` → Router 2's WAN IP
- Router 2 (e.g. OpenWrt): port forward `35353` → server's local IP

**Fritz!Box specific:**
Internet → Port Sharing → select your downstream router → set as **Exposed Host**.
This passes all traffic to the next router, which handles its own firewall.

**Without port forwarding:**
The node works as client only — it can use the network but cannot be reached by others.

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
ATY_CLIENT_MAX_AGE=300
ATY_REQUEST_TIMEOUT=15
```

**Never commit `.env` to GitHub.** Add it to `.gitignore`.

### Run

```bash
python askthroughyou_server.py &
```

### What the server does automatically

- Detects its own public IP via `ipify.org` and `ifconfig.me`
- Registers itself on the peer list at startup
- Sends keepalive to GitHub every `ATY_KEEPALIVE_INTERVAL` seconds
- Accepts incoming connections from clients on port `35353`
- Logs each client connection with their real public IP
- Writes temporary client entries to GitHub while connected
- Keeps connection history — every node that connects is recorded in the public directory
- Cleans up stale peers older than `ATY_MAX_PEER_AGE` seconds

### API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status |
| `/peers` | GET | Current peer list from GitHub |
| `/clients` | GET | Active client connections with timestamps |
| `/register` | POST | Register a permanent node |
| `/keepalive` | POST | Update node timestamp |
| `/cleanup` | POST | Remove stale peers |

### Check connected clients

```bash
curl http://localhost:8090/clients
```

Returns:
```json
{
  "clients": {
    "93.36.227.198": {
      "connections": 1,
      "first_seen": 1775912918,
      "last_seen": 1775912918
    }
  },
  "count": 1,
  "ok": true
}
```

---

## Peer list (public)

The peer list is published as a public JSON file via GitHub Pages:

```
https://yourusername.github.io/askthroughyou_peers/peers.json
```

To enable GitHub Pages on the `askthroughyou_peers` repo:
Settings → Pages → Source: main branch → Save.

Permanent nodes appear with `node_id`. Temporary clients appear with `"temporary": true` while connected and are removed on disconnect.

---

## Client `.env` (optional)

The client works without any configuration. Optionally create a `.env`:

```
ATY_BOOTSTRAP_URLS=https://yourusername.github.io/askthroughyou_peers/peers.json
ATY_NODE_ID=my-node
ATY_LISTEN_PORT=35353
ATY_DOH_PORT=53535
ATY_CONNECT_TIMEOUT=5
ATY_HTTP_TIMEOUT=10
ATY_KEEPALIVE_INTERVAL=120
ATY_DISCOVERY_INTERVAL=180
ATY_REFRESH_INTERVAL=300
ATY_MAX_PEER_AGE=900
ATY_DNS_TIMEOUT=3.0
ATY_DNS_LIFETIME=5.0
```

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment and values.

See `LICENSE` file for full terms.

---

## Project

Part of the Ask Through You initiative — restoring DNS universality, not bypassing censorship.

Human Flag: https://humanflag.org
