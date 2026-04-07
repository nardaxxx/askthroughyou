# Ask Through You

**Ask the internet through someone else.**

Ask Through You is a distributed human-node network.

You do not query the internet directly.
Another real user — on another network, in another country — performs the request for you.

The answer you receive is the answer their network sees.

---

## The Idea

The internet is not the same everywhere.

DNS responses change depending on:

* country
* ISP
* network policies
* filtering systems
* CDN geolocation

Ask Through You lets you **observe those differences directly**, using real users as resolution points.

You are not using a public resolver.
You are not using a VPN.

You are asking through someone else.

---

## What It Does

* Resolve DNS from another country
* Compare results across networks
* Detect filtering or censorship
* Observe CDN behavior
* Debug region-specific issues

Each user is also a node.

Every node:

* resolves queries using its own system DNS
* shares its network perspective
* can answer other users

---

## Architecture

```
your browser
     ↓  DNS query (DoH)
local node (askthroughyou.py)
     ↓  TCP JSON
remote human node
     ↓  system DNS
internet
     ↑
remote node
     ↑
your node
     ↑
browser
```

---

## Components

### askthroughyou.py

The main node.

* Runs locally
* Exposes a DNS-over-HTTPS endpoint
* Connects to other nodes
* Resolves queries through selected country
* Serves queries for other users

### askthroughyou_server.py

The central registry (bootstrap).

* Accepts node registration
* Maintains peer list
* Writes to GitHub registry
* Enables initial network discovery

---

## Quick Start

### Install

```bash
git clone https://github.com/YOUR_USER/askthroughyou.git
cd askthroughyou
pip install -r requirements.txt
```

### Configure

```bash
export ATY_SERVER_URL=http://YOUR_SERVER:8090
export ATY_BOOTSTRAP_URLS=https://raw.githubusercontent.com/YOUR_USER/askthroughyou-peers/main/peers.json
export ATY_NODE_ID=my-node
```

### Run

```bash
python askthroughyou.py --list
python askthroughyou.py --country DE
```

---

## Browser Setup

Use the local DoH endpoint:

```
http://127.0.0.1:53535/dns-query
```

### Chrome / Brave

Settings → Privacy → Security → Secure DNS → Custom

### Firefox

Settings → Network → DNS over HTTPS → Custom

---

## Test

```bash
curl "http://127.0.0.1:53535/dns-query?name=example.com&type=A"
```

---

## Running a Node

Every user is automatically a node.

When you run the program:

* your IP and port are registered
* your network becomes part of the system
* you start answering queries for others

---

## Network Model

* No central DNS authority
* No datacenter resolvers
* No single point of truth

The network is made of real users.

Each node is:

* independent
* imperfect
* real

---

## Bootstrap (Current Phase)

Currently, the network uses:

* a central server (Synology / Flask)
* a GitHub repository (`peers.json`)

This is temporary.

Future versions will remove all central components.

---

## Roadmap

### Stage 1 — Now

* Functional node and server
* GitHub-based peer registry
* DoH local resolver
* Peer discovery

### Stage 2

* Local peer cache (offline capable)
* Multi-peer verification
* Connection type classification

### Stage 3

* Decentralized registry (blockchain)
* Signed node identities
* Trust models

### Stage 4

* Micropayments per query
* Fully decentralized network
* No central server

---

## Future Direction

Ask Through You can evolve beyond DNS.

Possible extensions:

* Low-bandwidth messaging
* Store-and-forward communication
* Resilient chat networks
* Operation in degraded or partially unavailable internet environments

Including:

* censored networks
* unstable connections
* disaster or war scenarios

---

## Threat Model

Ask Through You does NOT guarantee:

* anonymity
* censorship resistance
* correctness of responses
* trustless operation

Nodes are operated by real users.

They may:

* filter results
* return incorrect data
* misrepresent their location

This system is for **observation, not blind trust**.

---

## Philosophy

You do not ask directly.
You ask through someone else.

They ask from where they are.
You receive what their network sees.

---

## License

Ask Through You Network License — v1.0

The code is free.
The network has one door.

That door will be on the blockchain.

---

## Contributing

Running a node is already a contribution.

Every new network perspective adds value.

Areas of interest:

* networking
* DNS
* distributed systems
* resilience
* security
* low-bandwidth communication

---

## Status

Active development.

The system works.
The network is forming.

Join it.

