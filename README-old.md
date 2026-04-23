# Ask Through You

**Ask the internet through someone else.**

A distributed human-node DNS network based on **DNS Sharing** — a concept created by Giovanni Nardacci.

Every user is simultaneously a client and a node. When you request content, a node in your chosen country resolves the DNS **and relays the content** on your behalf — the destination server sees only the node's IP, never yours. Nodes share their DNS and connection with each other, reciprocally.

This is not a VPN. This is not a traditional DNS proxy.
**DNS Sharing** is a new concept: peer-to-peer DNS resolution with content relay, distributed across human nodes worldwide.

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

## Installation

### Windows

1. Download and install Python from https://www.python.org/downloads/
   - During installation, check **"Add Python to PATH"**
2. Open Command Prompt (Win + R → type `cmd` → Enter)
3. Install dependencies:
   ```
   pip install dnspython dnslib
   ```
4. Download the client:
   ```
   curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
   ```

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip curl
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### Linux (Fedora / RHEL)

```bash
sudo dnf install python3 python3-pip curl
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### macOS

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### Android (Termux)

1. Install Termux from F-Droid: https://f-droid.org/packages/com.termux/
   - Do NOT use the Play Store version (outdated)
2. Open Termux and run:
   ```bash
   pkg install python curl
   pip install dnspython dnslib
   curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
   ```

---

## Quick Start — User (Client)

### Show available countries

```bash
python askthroughyou.py --list
```

### Connect via a specific country

```bash
python askthroughyou.py --country CH
```

Replace `CH` with any country code from the list (IT, DE, FR, US, etc.)

### Status page

While running, open in your browser:
```
http://127.0.0.1:53535/status
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

## Synology NAS Setup

### Requirements

- Synology NAS with DSM 7.x
- Python 3.9 package installed from Package Center

### Install Python on Synology

1. Open **Package Center** in DSM
2. Search for **Python 3.9**
3. Click Install

### Connect via SSH

Enable SSH: DSM → Control Panel → Terminal & SNMP → Enable SSH

Then connect from your PC:
```bash
ssh Amministratore@192.168.x.x
```

### Install dependencies

```bash
pip install flask requests python-dotenv dnspython --break-system-packages
```

If pip is not found:
```bash
python3 -m ensurepip
python3 -m pip install flask requests python-dotenv dnspython
```

### Upload server file

Use **File Station** in DSM:
1. Open File Station
2. Navigate to `home` → create folder `askthroughyou`
3. Upload `askthroughyou_server.py` into that folder
4. Create `.env` file in the same folder (see Configuration section above)

### Run the server

```bash
cd /volume1/homes/YourUsername/askthroughyou
python3 askthroughyou_server.py &
```

### Auto-start on boot

The server includes an auto-keepalive thread — it restarts itself if GitHub connectivity is lost.

For auto-start after NAS reboot, use **Task Scheduler** in DSM:
1. Control Panel → Task Scheduler → Create → Triggered Task → User-defined script
2. Event: Boot-up
3. Task Settings → Run command:
```bash
cd /volume1/homes/YourUsername/askthroughyou && python3 askthroughyou_server.py &
```

### Verify it is running

```bash
ps aux | grep python
curl http://localhost:8090/health
```

---

## Quick Start — Node Operator

A node is any always-on machine that runs the bootstrap server and accepts incoming connections. It registers itself on GitHub and logs clients.

### Requirements

```bash
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

### GitHub setup

1. Create a GitHub account at https://github.com
2. Create a new repository named `askthroughyou_peers` (public)
3. Add a file `peers.json` with content `[]`
4. Enable GitHub Pages: Settings → Pages → Source: main branch → Save
5. Create a Personal Access Token: Settings → Developer settings → Personal access tokens → Generate new token
   - Select scope: `repo`
   - Copy the token (shown only once)

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

**Never commit `.env` to GitHub.** Add `.env` to your `.gitignore` file.

### Run the server

```bash
python askthroughyou_server.py &
```

### What the server does automatically

- Detects its own public IP via `ipify.org` and `ifconfig.me`
- Registers itself on the peer list at startup
- Sends keepalive to GitHub every `ATY_KEEPALIVE_INTERVAL` seconds
- Accepts incoming connections from clients on port `35353`
- Logs each client connection with their real public IP
- Writes client entries to GitHub — building the network directory
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
    "10.10.10.1": {
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

Permanent nodes appear with `node_id`. Temporary clients appear with `"temporary": true` while connected.

---

## Client `.env` (optional)

The client works without any configuration. Optionally create a `.env` in the same folder as `askthroughyou.py`:

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

## Troubleshooting

**No peers found**
- Check your internet connection
- Verify the bootstrap URL is reachable in your browser

**Initial HELLO failed: No route to host**
- Port 35353 is not open on your router
- Add a port forward rule as described above

**Server not configured**
- Check your `.env` file contains `GITHUB_TOKEN` and `ATY_REPO_OWNER`
- Make sure `python-dotenv` is installed: `pip install python-dotenv`

**ImportError: cannot import name 'load_dotenv'**
- Run: `pip install python-dotenv --force-reinstall`

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment and values.

See `LICENSE` file for full terms.

---

## Project

Part of the Ask Through You initiative — restoring DNS universality, not bypassing censorship.

Human Flag: https://humanflag.org
