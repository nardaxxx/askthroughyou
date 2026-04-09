# Ask Through You

**Ask the internet through someone else.**

Ask Through You is a distributed human-node network where real users resolve DNS queries for each other. When you use it, you see the internet as another person — on another network, in another country — sees it.

You are not using a VPN.  
You are not using a public resolver.  
You are asking through someone else.

---

## Why This Exists

The internet is not the same everywhere.

DNS responses change depending on country, ISP, network policies, filtering systems, and CDN geolocation. Governments and ISPs block content. Censorship is invisible — you just get an error, or nothing.

Ask Through You makes those differences visible, using real users as resolution points.

It also works when infrastructure fails. In war zones, natural disasters, or network blackouts, central services go down. WhatsApp dies when Meta's servers are unreachable, or when no one can pay a phone bill. Ask Through You only needs two nodes that can see each other — on a LAN, a local WiFi, a mesh network, or any IP connection.

This is not theoretical. It is the gap this project was built to fill.

---

## What It Does

- Resolve DNS from another country
- Compare DNS results across networks
- Detect filtering, censorship, or manipulation
- Observe CDN geolocation behavior
- Debug region-specific issues
- Communicate when central infrastructure is unavailable

---

## How It Works

Every user who runs the program becomes a node. Every node is both a client and a server.

```
your browser
     ↓  DNS-over-HTTPS (DoH)
local node (askthroughyou.py)
     ↓  TCP JSON
remote human node (another user, another country)
     ↓  system DNS
internet
     ↑  DNS response
remote node
     ↑
your node
     ↑
browser
```

When you run `askthroughyou.py --country DE`, your DNS queries are sent to a real user in Germany, resolved using their network's DNS, and returned to you. You see what Germany sees.

At the same time, other users can resolve queries through your node. You contribute your network perspective to the network.

---

## Quick Start

### Requirements

- Python 3.8 or higher
- pip

### Install

```bash
git clone https://github.com/nardaxxx/askthroughyou.git
cd askthroughyou
pip install dnslib dnspython
```

### Configure

Create a `.env` file in the project folder:

```
ATY_SERVER_URL=http://your-bootstrap-server:8090
ATY_BOOTSTRAP_URLS=https://raw.githubusercontent.com/nardaxxx/askthroughyou_peers/main/peers.json
ATY_NODE_ID=my-node
ATY_LISTEN_PORT=35353
ATY_DOH_PORT=53535
```

The bootstrap URL above is the official public peer list. Your node will download it automatically on startup.

### Run

List available countries:

```bash
python3 askthroughyou.py --list
```

Start resolving DNS through a specific country:

```bash
python3 askthroughyou.py --country DE
```

Replace `DE` with any country code shown in the list.

### Configure Your Browser

Point your browser to the local DoH endpoint:

```
http://127.0.0.1:53535/dns-query
```

**Brave / Chrome:** Settings → Privacy and security → Security → Use secure DNS → Custom  
**Firefox:** Settings → Network Settings → Enable DNS over HTTPS → Custom → enter the URL above

### Test

```bash
curl "http://127.0.0.1:53535/dns-query?name=example.com&type=A"
```

Check node status:

```bash
curl "http://127.0.0.1:53535/status"
```

---

## Running a Bootstrap Server

A bootstrap server helps new nodes find peers. It is optional — the network can use GitHub-hosted peer lists without any server.

If you have a machine that is always on (Synology NAS, Raspberry Pi, VPS, home server), you can run a bootstrap server.

### Requirements

- Python 3.8+
- flask, requests (`pip install flask requests`)
- A GitHub personal access token with `repo` scope
- A GitHub repository for the peer list (e.g. `youruser/askthroughyou_peers`) containing a `peers.json` file with `[]`

### Configure

Create a `.env` file next to `askthroughyou_server.py`:

```
GITHUB_TOKEN=your_github_token
ATY_REPO_OWNER=your_github_username
ATY_REPO_NAME=askthroughyou_peers
ATY_SERVER_PORT=8090
ATY_MAX_PEER_AGE=900
ATY_REQUEST_TIMEOUT=15
```

**Never commit this file to GitHub.** Add `.env` to your `.gitignore`.

### Run

```bash
export $(cat .env | xargs)
python3 askthroughyou_server.py
```

To run in background (Linux/Synology):

```bash
export $(cat .env | xargs) && nohup python3 askthroughyou_server.py > server.log 2>&1 &
```

### Verify

```bash
curl http://your-server-ip:8090/health
```

Should return:

```json
{"ok": true, "github_ready": true, "service": "askthroughyou-server", "version": "1.0"}
```

### Add Your Bootstrap to the Network

Once your server is running, share your peer list URL so others can add it to their `ATY_BOOTSTRAP_URLS`:

```
https://raw.githubusercontent.com/YOURUSER/askthroughyou_peers/main/peers.json
```

Multiple bootstrap URLs can be combined with a comma:

```
ATY_BOOTSTRAP_URLS=https://raw.githubusercontent.com/nardaxxx/askthroughyou_peers/main/peers.json,https://raw.githubusercontent.com/youruser/askthroughyou_peers/main/peers.json
```

The node fetches all of them in parallel and merges the results. If one goes down, the others keep the network alive.

---

## Environment Variables

### Node (askthroughyou.py)

| Variable | Default | Description |
|---|---|---|
| `ATY_SERVER_URL` | (empty) | Bootstrap server URL |
| `ATY_BOOTSTRAP_URLS` | (empty) | Comma-separated peer list URLs |
| `ATY_NODE_ID` | (empty) | Human-readable node name |
| `ATY_LISTEN_PORT` | 35353 | TCP port for peer-to-peer communication |
| `ATY_DOH_PORT` | 53535 | Local DoH endpoint port |
| `ATY_CONNECT_TIMEOUT` | 5 | TCP connection timeout (seconds) |
| `ATY_HTTP_TIMEOUT` | 10 | HTTP request timeout (seconds) |
| `ATY_KEEPALIVE_INTERVAL` | 120 | Keepalive interval (seconds) |
| `ATY_DISCOVERY_INTERVAL` | 180 | Peer discovery interval (seconds) |
| `ATY_REFRESH_INTERVAL` | 300 | Bootstrap refresh interval (seconds) |
| `ATY_MAX_PEER_AGE` | 900 | Max seconds before a peer is considered stale |
| `ATY_MAX_MESSAGE_SIZE` | 65536 | Max TCP message size (bytes) |
| `ATY_DNS_TIMEOUT` | 3.0 | DNS resolver timeout (seconds) |
| `ATY_DNS_LIFETIME` | 5.0 | DNS resolver lifetime (seconds) |

### Server (askthroughyou_server.py)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | (required) | GitHub personal access token |
| `ATY_REPO_OWNER` | (required) | GitHub username |
| `ATY_REPO_NAME` | askthroughyou_peers | GitHub repository name |
| `ATY_SERVER_PORT` | 8090 | Server port |
| `ATY_MAX_PEER_AGE` | 900 | Max peer age before cleanup |
| `ATY_REQUEST_TIMEOUT` | 15 | GitHub API timeout |
| `ATY_REQUIRE_API_TOKEN` | 0 | Set to 1 to require API token from nodes |
| `ATY_API_TOKEN` | (empty) | API token (if REQUIRE_TOKEN is 1) |

---

## Architecture

### Peer Protocol

Nodes communicate over TCP using newline-delimited JSON messages.

**HELLO** — peer discovery and exchange:
```json
{"type": "HELLO", "peers": [...], "timestamp": 1234567890, "node_id": "my-node"}
```

**PEER_LIST** — response to HELLO:
```json
{"type": "PEER_LIST", "ok": true, "peers": [...]}
```

**DNS_QUERY** — resolve a domain:
```json
{"type": "DNS_QUERY", "domain": "example.com", "qtype": "A", "timestamp": 1234567890}
```

**DNS_RESPONSE** — answer to DNS_QUERY:
```json
{"type": "DNS_RESPONSE", "ok": true, "domain": "example.com", "qtype": "A", "answers": ["93.184.216.34"], "ttl": 3600, "resolver_ip": "1.2.3.4"}
```

### Peer List Format

The `peers.json` file on GitHub is a simple JSON array:

```json
[
  {
    "ip": "1.2.3.4",
    "port": 35353,
    "country_code": "DE",
    "country": "Germany",
    "node_id": "node-berlin",
    "last_seen": 1234567890
  }
]
```

### Local Cache

The node maintains two local caches to survive offline or bootstrap failures:

- `~/.askthroughyou/peers_cache.json` — last known peer list
- `~/.askthroughyou/dns_cache.json` — cached DNS responses with TTL

On Windows: `%APPDATA%\AskThroughYou\`

---

## Off-Grid Operation

Ask Through You is designed to work without central infrastructure.

If bootstrap servers are unreachable, the node falls back to the local peer cache. If the internet is down, nodes can still communicate over:

- Local area network (LAN)
- Local WiFi
- Mesh networks
- Any IP connectivity between nodes

The network exists as long as nodes can reach each other. No server required. No account required. No internet required — only IP connectivity between peers.

This makes it relevant for:

- Censored networks where DNS is manipulated
- Disaster scenarios where central infrastructure has failed
- War zones where commercial services are unavailable
- Any situation where communication must survive without institutions

---

## Threat Model

Ask Through You does NOT guarantee:

- Anonymity — your IP is visible to the peers you connect to
- Censorship resistance — peers may themselves be filtered
- Correctness — a peer could return manipulated responses
- Trustless operation — you are trusting real humans

Nodes are operated by real people. They may filter results, return incorrect data, or misrepresent their location.

This system is for **observation and resilience**, not for blind trust or guaranteed anonymity. Use Tor or a trusted VPN if you need anonymity.

---

## Roadmap

### Stage 1 — Current
- Functional node and bootstrap server
- GitHub-based peer registry
- DoH local resolver
- Peer discovery and keepalive
- Local peer and DNS cache

### Stage 2
- Windows/Linux single-file executable (.exe)
- Multi-peer response verification
- Offline-first peer cache

### Stage 3
- Decentralized registry (blockchain / smart contract)
- Cryptographic node identity
- Trust scoring

### Stage 4
- Text messaging between nodes
- Store-and-forward for disconnected scenarios
- Operation over mesh and radio networks

---

## Contributing

Running a node is already a contribution.

Every new network perspective adds value — a new country, a new ISP, a new network environment.

If you want to contribute more:

- Run a bootstrap server and share your peer list URL
- Report bugs or unexpected DNS behavior
- Improve the code
- Help with documentation and translations

Areas of interest: networking, DNS, distributed systems, resilience, cryptography, low-bandwidth communication, humanitarian technology.

---

## Related Project

Ask Through You is developed alongside [Human Flag](https://humanflag.org), a Swiss non-profit working on civilian protection protocols for autonomous weapons systems. The resilient communication layer being built here is directly relevant to scenarios where civilian populations need to communicate when infrastructure has been destroyed or captured.

---

## License

**Ask Through You Network License — v1.0**

The code is free.  
The network is one.  
The door is on the blockchain.

You are free to:

- Use, copy, share, and distribute this software
- Run it on any machine
- Modify and improve the code
- Contribute to the official repository

With one condition:

To participate in the official Ask Through You network, you must be registered in the official registry. Registration requires payment of the network fee via the official smart contract on Ethereum.

The code is free. The network has one door. You pay once to enter.

Any registry claiming to be the official Ask Through You network, other than the official Ethereum contract, is not the official network.

---

## Status

Active development.

The system works.  
The network is forming.  

The first node is online in Switzerland.

Join it.
