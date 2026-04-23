# Ask Through You

Ask the internet through someone else.

A distributed human-node DNS network based on **DNS Sharing** — a concept created by Giovanni Nardacci.

Every user is simultaneously a client and a node. When you request content, a node in your chosen country resolves the DNS and relays the content on your behalf — the destination server sees only the node's IP, never yours. Nodes share their DNS and connection with each other, reciprocally.

**This is not a VPN. This is not a traditional DNS proxy.** DNS Sharing is a new concept: peer-to-peer DNS resolution with content relay, distributed across human nodes worldwide.

**No central server. No query logging. No content surveillance.**

Node operators keep connection logs (IP, timestamp, duration, country). Query content is never recorded. Connection logs are public — they form the network directory. Every node that connects becomes part of a global address book, visible on GitHub. The network is designed to see the world as it is, not to hide.

> Vision: connection logs are the foundation of a future distributed communication layer — a global directory where every node is a contact, enabling P2P messaging without central servers.

---

## How it works

1. Each node registers itself on a public peer list (GitHub Pages)
2. Clients read the peer list and choose a country
3. The client connects to a node in that country
4. DNS queries are routed through that node and resolved locally
5. The network is invisible — traffic looks like normal DNS

## Components

| File | Role |
|------|------|
| `askthroughyou.py` | User node — client + DNS relay |
| `askthroughyou_server.py` | Bootstrap server — manages peer registry on GitHub |
| `.env` | Configuration (never commit this file) |

---

## Installation

### Windows

```cmd
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### Linux (Ubuntu / Debian)

```bash
sudo apt update && sudo apt install python3 python3-pip curl
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
brew install python
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### Android (Termux)

Install Termux from F-Droid: https://f-droid.org/packages/com.termux/

> Do NOT use the Play Store version (outdated)

```bash
pkg install python curl
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

**Run in background with wake lock (no root required):**

```bash
termux-wake-lock
python askthroughyou.py --country CH &
```

---

## Quick Start — User (Client)

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

### Configure your browser (DoH)

```
http://127.0.0.1:53535/dns-query
```

**Brave / Chrome / Edge:** Settings → Privacy and Security → Security → Use secure DNS → With Custom → paste the URL above.

**Firefox:** Settings → Privacy & Security → DNS over HTTPS → Enable → Custom → paste the URL above.

**Android — Brave:** Same as desktop.

> Note: Android system DNS only supports DoT (port 853), not DoH. For system-wide DNS use the browser setting above, or use ATY in background for app-level DNS.

---

## Quick Start — Node Operator

See [SETUP.md](SETUP.md) for complete node setup instructions including Synology NAS, port forwarding, GitHub configuration, and private DNS resolver setup.

---

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status + DNS resolver info |
| `/peers` | GET | Current peer list from GitHub |
| `/clients` | GET | Active client connections |
| `/register` | POST | Register a permanent node |
| `/keepalive` | POST | Update node timestamp |
| `/cleanup` | POST | Remove stale peers |

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment and values.

See LICENSE file for full terms.

---

## Project

Part of the Ask Through You initiative — restoring DNS universality, not bypassing censorship.

Human Flag: https://humanflag.org
