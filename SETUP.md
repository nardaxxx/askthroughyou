# Ask Through You — Registry Node Setup

## What this is

`askthroughyou_server.py` is the **registry node** for the Ask Through You network.

A registry is a node with an always-on machine and an open port that:
1. Maintains the live peer list (`peers.json`) on GitHub
2. Acts as the **switchboard** for client nodes — they connect persistently to it via TCP, and the registry tracks their presence in real time
3. In future phases (see roadmap), it will route calls, messages, and SMS onboarding requests

Without at least one registry running, the peer list never gets populated and the network cannot form.

---

## What it does today

1. Listens for **persistent TCP connections** on port 35353 from user nodes
2. When a node sends `REGISTER`, writes it to `peers.json` on GitHub immediately
3. When the connection drops (or no `PING` arrives within 3 minutes), removes the node from `peers.json` immediately
4. Registers itself as a permanent node every 2 minutes (auto-keepalive)
5. Resolves DNS queries on behalf of connected clients
6. Exposes a REST API on port 8090 for monitoring

The registry never stores DNS query content — it only manages the directory and resolves queries.

---

## Requirements

- Python 3.8 or higher
- A GitHub account with a public repository for `peers.json`
- A machine that is always on (NAS, VPS, Raspberry Pi, home server)
- TCP port 35353 reachable from the internet
- (Optional) port 8090 accessible locally for monitoring

---

## Installation

```bash
pip install flask requests python-dotenv dnspython
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou_server.py
```

### Synology NAS

1. Open Package Center → install Python 3.9 or higher
2. Enable SSH: Control Panel → Terminal & SNMP → Enable SSH
3. Connect via SSH:
```bash
ssh Amministratore@192.168.x.x
```
4. Install dependencies:
```bash
sudo pip3 install flask requests python-dotenv dnspython
```

If pip is missing on Synology:
```bash
curl https://bootstrap.pypa.io/pip/3.8/get-pip.py -o get-pip.py
python3 get-pip.py --break-system-packages
sudo pip3 install flask requests python-dotenv dnspython
```

5. Upload `askthroughyou_server.py` via File Station into `~/askthroughyou/`

---

## GitHub setup

The registry writes the peer list to a GitHub repository published via GitHub Pages.

1. Create a public repository named `askthroughyou_peers`
2. Add a file `peers.json` with content `[]`
3. Enable GitHub Pages: Settings → Pages → Source: main branch → Save
4. Create a Personal Access Token:
   - Settings → Developer settings → Personal access tokens → Generate new token
   - Scope: `repo`
   - Copy the token (shown only once)

The peer list is publicly accessible at:
```
https://yourusername.github.io/askthroughyou_peers/peers.json
```

---

## Configuration (`.env`)

Create a `.env` file in the same folder as `askthroughyou_server.py`:

```env
# GitHub — required
GITHUB_TOKEN=ghp_yourtoken
ATY_REPO_OWNER=yourusername
ATY_REPO_NAME=askthroughyou_peers
ATY_BRANCH=main
ATY_FILE_PATH=peers.json

# Server
ATY_SERVER_HOST=0.0.0.0
ATY_SERVER_PORT=8090

# Node identity
ATY_NODE_ID=node-001
ATY_COUNTRY_CODE=CH
ATY_LISTEN_PORT=35353

# Timing
ATY_KEEPALIVE_INTERVAL=120
ATY_MAX_PEER_AGE=900
ATY_PING_TIMEOUT=180

# Optional: use a private DNS resolver (e.g. local Unbound)
# ATY_DNS_SERVER=192.168.2.1
```

**Never commit `.env` to GitHub.** Add it to `.gitignore`.

### `ATY_DNS_SERVER` (optional)

If set, the registry uses this IP to resolve DNS queries on behalf of clients, instead of the system default. Use this to route all queries through a local Unbound or other private resolver — so no DNS query reaches public resolvers like Google.

---

## Port forwarding

For your registry to be reachable from the internet, open **TCP port 35353** on your router.

**Single router:**
Port forward: external 35353 → server's local IP, port 35353

**Double NAT (two routers in cascade):**
- Router 1 (main, e.g. Fritz!Box): 35353 → Router 2's WAN IP
- Router 2 (e.g. OpenWrt): 35353 → server's local IP

**Fritz!Box specific:**
Internet → Port Sharing → select your downstream router → set as Exposed Host

**CGNAT:**
If your ISP uses CGNAT, the registry still registers itself on GitHub via outbound HTTPS. Inbound TCP may or may not work depending on whether the carrier keeps the NAT mapping open. Test:
```bash
curl http://YOUR_PUBLIC_IP:35353
```
"Empty reply from server" means the port is reachable.

**Without port forwarding:**
The registry can still run — it will keep itself on `peers.json` via outbound calls — but other nodes will not be able to connect to it. They will use other registries instead.

---

## Run

```bash
cd ~/askthroughyou
sudo python3 askthroughyou_server.py
```

To run in the background:
```bash
sudo python3 askthroughyou_server.py &
```

### Auto-start on Synology boot

Control Panel → Task Scheduler → Create → Triggered Task → User-defined script
- Event: Boot-up
- User: root
- Run command:
```bash
cd /volume1/homes/YourUser/askthroughyou && sudo python3 askthroughyou_server.py &
```

### Verify it is running

```bash
ps aux | grep askthroughyou_server
curl http://localhost:8090/health
```

Expected response:
```json
{
  "ok": true,
  "service": "askthroughyou-server",
  "version": "2.0",
  "github_ready": true,
  "active_clients": 0,
  "dns_server": "system default"
}
```

---

## What happens automatically

**On startup:**
- Detects own public IP via ipify.org / ifconfig.me
- Registers self in `peers.json` as a permanent node
- Starts the TCP server on port 35353
- Starts the Flask API on port 8090
- Starts auto-keepalive (writes to `peers.json` every 2 minutes)
- Starts stale client cleanup (removes ghosts every minute)

**When a user node connects:**
- Receives `REGISTER` message → writes the node to `peers.json` immediately
- Receives periodic `PING` → updates `last_ping`
- Receives `DNS_QUERY` → resolves locally and replies

**When a user node disconnects:**
- Socket closes → removes node from `peers.json` immediately
- Or: no `PING` for 180 seconds → marks as stale and removes

The permanent registry node (`ATY_NODE_ID`) is never removed — it is protected from accidental deletion.

---

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status, DNS resolver, active client count |
| `/clients` | GET | All currently connected user nodes with timestamps |
| `/peers` | GET | Current `peers.json` from GitHub |
| `/cleanup` | POST | Manually remove stale peers from GitHub |

### Check live clients

```bash
curl http://localhost:8090/clients
```

Returns nodes currently connected via persistent TCP, with `connected_at` and `last_ping` timestamps.

### Check the peer list on GitHub

```bash
curl http://localhost:8090/peers
```

Returns the current `peers.json` as seen on GitHub.

---

## Peer list format

Permanent registry node:
```json
{
  "ip": "89.251.254.185",
  "port": 35353,
  "country_code": "CH",
  "country": "Switzerland",
  "last_seen": 1777181663,
  "node_id": "node-001"
}
```

User node (appears while connected, removed on disconnect):
```json
{
  "ip": "85.12.44.201",
  "port": 35353,
  "country_code": "IT",
  "country": "Italy",
  "last_seen": 1777181699,
  "node_id": "termux-mario"
}
```

---

## Running registry and user node on the same machine

The registry server and the user node are designed to run together:

```bash
# Terminal 1: the registry (manages peers.json, listens on 35353)
sudo python3 askthroughyou_server.py &

# Terminal 2: the user node (DNS relay client, uses port 35353)
python3 askthroughyou.py --country CH &
```

⚠️ **They both want port 35353** — but they don't run on the same machine in production. The registry is on the always-on server. The user node is on each user's device. If you want both on the same machine for testing, run the user node on a different `ATY_LISTEN_PORT`.

---

## Troubleshooting

**"Server not configured"**
Check `.env` contains `GITHUB_TOKEN` and `ATY_REPO_OWNER`. Make sure `python-dotenv` is installed.

**ImportError: cannot import name 'load_dotenv'**
```bash
sudo pip3 install python-dotenv --force-reinstall
```
The server handles this gracefully — if missing, it reads env vars from the system environment.

**Address already in use**
```bash
sudo pkill -f askthroughyou_server.py
```

**pip broken on Synology**
```bash
curl https://bootstrap.pypa.io/pip/3.8/get-pip.py -o get-pip.py
python3 get-pip.py
sudo pip3 install flask requests python-dotenv dnspython
```

**GitHub writes failing (401 Unauthorized)**
- Check the token has `repo` scope
- Check `ATY_REPO_OWNER` matches your GitHub username exactly
- Tokens expire — generate a new one if old

**Clients connect but don't appear on `peers.json`**
- Check `github_ready: true` in `/health`
- Check the GitHub token is valid
- Check the server log for "GitHub: added" messages — if absent, the GitHub write thread is failing

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment and values.

See [LICENSE](LICENSE) for full terms.

---

## Project

Part of the **Ask Through You** initiative.

🌐 https://humanflag.org
