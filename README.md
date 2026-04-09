Vai su GitHub, apri la repo `askthroughyou`, clicca su `README.md`, poi clicca la matita (Edit).

Cancella tutto quello che c'è e incolla questo:

---

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

Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

### Run

List available countries:

```bash
python3 askthroughyou.py --list
```

Start resolving DNS through a specific country:

```bash
python3 askthroughyou.py --country DE
```

### Configure Your Browser

Point your browser to the local DoH endpoint:

```
http://127.0.0.1:53535/dns-query
```

**Brave / Chrome:** Settings → Privacy and security → Security → Use secure DNS → Custom
**Firefox:** Settings → Network Settings → Enable DNS over HTTPS → Custom

### Test

```bash
curl "http://127.0.0.1:53535/dns-query?name=example.com&type=A"
curl "http://127.0.0.1:53535/status"
```

---

## Running a Bootstrap Server

If you have a machine always on (Synology NAS, Raspberry Pi, VPS, home server), you can run a bootstrap server and contribute to the network infrastructure.

### Requirements

- Python 3.8+
- `pip install flask requests`
- GitHub personal access token with `repo` scope
- GitHub repository (e.g. `youruser/askthroughyou_peers`) with a `peers.json` file containing `[]`

### Configure

Copy `.env.example` to `.env` and fill in the server variables. Never commit `.env` to GitHub.

### Run

```bash
export $(cat .env | xargs)
python3 askthroughyou_server.py
```

Run in background:

```bash
export $(cat .env | xargs) && nohup python3 askthroughyou_server.py > server.log 2>&1 &
```

### Verify

```bash
curl http://your-server-ip:8090/health
```

### Add Your Bootstrap to the Network

Once running, share your peer list URL. Others add it to their `ATY_BOOTSTRAP_URLS`:

```
ATY_BOOTSTRAP_URLS=https://raw.githubusercontent.com/nardaxxx/askthroughyou_peers/main/peers.json,https://raw.githubusercontent.com/youruser/askthroughyou_peers/main/peers.json
```

Multiple URLs are fetched in parallel. If one fails, the others keep the network alive.

---

## Off-Grid Operation

Ask Through You works without central infrastructure.

If bootstrap servers are unreachable, the node uses its local peer cache. If the internet is down, nodes can still communicate over LAN, local WiFi, mesh networks, or any IP connection between them.

The network exists as long as nodes can reach each other. No server required. No account required. No internet required — only IP connectivity between peers.

This makes it relevant for censored networks, disaster scenarios, war zones, and any situation where communication must survive without institutions.

---

## Threat Model

Ask Through You does NOT guarantee anonymity, censorship resistance, or correctness of responses. Nodes are operated by real people who may return incorrect data.

This system is for observation and resilience, not for blind trust. Use Tor or a trusted VPN if you need anonymity.

---

## Roadmap

**Stage 1 — Current:** functional node, bootstrap server, GitHub peer registry, local DoH, peer and DNS cache.

**Stage 2:** single-file executable (.exe), multi-peer verification, offline-first cache.

**Stage 3:** blockchain registry, cryptographic node identity, trust scoring.

**Stage 4:** text messaging between nodes, store-and-forward for disconnected scenarios, mesh and radio network operation.

---

## Related Project

Ask Through You is developed alongside [Human Flag](https://humanflag.org), a Swiss non-profit working on civilian protection protocols for autonomous weapons systems. The resilient communication layer built here is directly relevant to scenarios where civilians need to communicate when infrastructure has been destroyed or captured.

---

## License

**Ask Through You Network License — v1.0**
Copyright (c) 2025 Giovanni Nardacci (nardaxxx)

Free for personal use, academic research (with attribution), and humanitarian operations — with acknowledgment of [Human Flag](https://humanflag.org) and acceptance of its values: civilian protection, visual surrender protocols, and facilitation of safe surrender under international humanitarian law.

Commercial use, embedding in products, and creating competing networks require written permission from the Author.

Attribution is always required. See [LICENSE](LICENSE) for full terms.

The code is free.
The network is one.
The door is on the blockchain.

---

Fatto? Poi passiamo a LICENSE.
