# Ask Through You

**A network within the network.**

Not a tool to use the internet better. A network of human nodes that talks to itself, using the internet only as a temporary carrier — and one day, perhaps, not even that.

A concept created by Giovanni Nardacci.

---

## What ATY really is

The internet you know is a public square. Every move is seen. Every message has a corporate witness. Every connection is metered, logged, profiled, monetized.

Ask Through You is something else.

It is a **parallel network** that lives inside the public internet but does not belong to it. The nodes of ATY speak to each other directly. They share DNS, they exchange messages, they place calls, they hold identities — and none of this passes through the servers of Meta, Google, Microsoft, or anyone else. The internet underneath is just the wire. The conversation lives inside ATY.

This is the most radical thing about the project. Not the DNS sharing. Not the switchboard. Not the proof of time. The radical thing is the simple fact that **once you are in ATY, you are no longer on the public web**. You are in a room of humans, and the room has its own walls.

The day the public internet becomes hostile, censored, broken — by mesh, by radio, by satellite, by anything — ATY can still exist. The protocol does not require the public internet to be free. It only requires that two nodes can find a way to reach each other, somehow.

ATY is a network that survives its own carrier.

---

## Why this matters

Every digital network we know was built to let us **use the world's services**. ATY is built so that we can **be a community to each other**, without the world's services in between.

The difference is not technical. It is moral.

When you use WhatsApp, you are using Meta's infrastructure to reach a friend. The friend is on the other side, but Meta is in the middle — reading the metadata, knowing who you talk to, when, how often, for how long. WhatsApp is not a network between you and your friend. WhatsApp is a network between Meta and each of you, in parallel.

ATY removes the middle. The friend is on the other side, the public internet is just the road, and no one is watching from the road — because the road does not know what it carries.

It is a small thing. It is also the most important thing.

---

## What works today

The first layer of the network is alive: **DNS Sharing.**

- A registry node maintains `peers.json` on GitHub Pages — the live directory of who is in the network right now
- User nodes open a **persistent TCP connection** to a registry to declare their presence
- When a node connects, it appears on `peers.json` immediately. When it disconnects, it disappears immediately. Presence is alive, not approximate.
- DNS queries are routed through human nodes in the country of your choice. Your IP is never seen by the destination server.
- A local DNS-over-HTTPS endpoint lets any browser use the network

This is the foundation. The reason DNS is the first layer is simple: it is the everyday excuse that gets people to install ATY. Once installed, the node is alive — and from that moment, the network is in place. Everything else (calls, chat, identity) can be built on top of a network that already exists, made of nodes that already trust each other enough to share DNS.

The DNS layer is the seed. The network is the tree.

---

## Components

| File | Role | Status |
|------|------|--------|
| `askthroughyou.py` | User node — DNS client + relay + persistent presence | ✅ Working |
| `askthroughyou_server.py` | Registry node — manages `peers.json`, switchboard | ✅ Working |
| `askthroughyou_phonebook.py` | Human directory — find contacts by name | 🟡 Working, evolving |

In the network, **client and registry are the same kind of node.** Only their role differs. Anyone with an always-on machine can run a registry. The more registries exist, the more resilient the network.

---

## Quick Start — User node

### Install

**Linux (Ubuntu/Debian)**
```
sudo apt update && sudo apt install python3 python3-pip curl
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

**Windows**
```
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

**macOS**
```
brew install python
pip3 install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

**Android (Termux from F-Droid)**
```
pkg install python curl
pip install dnspython dnslib
curl -O https://raw.githubusercontent.com/nardaxxx/askthroughyou/main/askthroughyou.py
```

### Run

```
python askthroughyou.py --list           # show available countries
python askthroughyou.py --country CH     # connect via Switzerland
```

### Status & DoH

```
http://127.0.0.1:53535/status        — node status
http://127.0.0.1:53535/dns-query     — DoH endpoint to set in your browser
```

In Brave / Chrome / Firefox: Settings → Secure DNS → Custom → paste the DoH URL.

---

## Proof of time

This is the heart of the project. It deserves its own section because it is not what it sounds like.

**Proof of time is not a blockchain.** There is no mining, no staking, no token, no consensus algorithm, no validators. There is only this:

The longer you keep your node alive in the network, the more your presence is recorded in the public history of `peers.json`. Every commit is timestamped, signed by the registry, immutable after the fact. Anyone can read the history of any node by reading the log.

**It works like rings on a tree.** You don't need a certificate to know how old a tree is. You count the rings. The tree itself is the proof.

In ATY, the network is the tree. Time is the only thing being counted. Nothing else is being measured, ranked, scored, or competed for.

This is intentional. It is the project's answer to a question that has been bothering decentralized networks for fifteen years: *how do you measure participation without recreating hierarchy?*

The answer is: don't measure participation. Measure only presence. Time given. The one thing that costs everyone exactly the same.

A doctor who keeps a node alive while seeing patients, a parent who keeps it alive while raising children, an unemployed young person who keeps it alive while looking for work — all accumulate the same rings. None is worth less. None is worth more.

**Time is democratic. The network honors it as such.**

The network does not care if you are powerful. It only cares that you were here.

---

## The full vision — built in layers

Each layer requires the one below it. Each layer adds value to the layers above. **Today, only Layer 1 is live.** The rest is the direction we're walking — slowly, deliberately, with code that ships.

### Layer 1 — DNS Sharing (today)

The everyday reason to be in the network. Real human nodes resolve DNS for each other. Live presence on `peers.json`. The network has a heartbeat.

### Layer 2 — Wallet identity

Every node declares a **wallet address** when it connects. The wallet becomes the node's persistent identifier across sessions, IPs, devices, countries. Like a phone number that follows you forever — but decentralized, self-sovereign, verifiable.

Your IP changes. Your wallet doesn't. Your time accumulates against your wallet, not against your hardware.

### Layer 3 — The switchboard

The registry stops being just a directory. It becomes a **switchboard** — exactly like a telephone operator in the 1920s. You "call the switchboard" by sending a message on your persistent TCP connection. The switchboard handles the rest:

- "Connect me to wallet `0xabc...`" → the switchboard finds them, bridges the two sockets
- "Send a message to wallet `0xdef...`" → the switchboard relays it
- "Who is online in this country?" → the switchboard answers from its live registry

You never see IPs. You never deal with NAT traversal. You speak to the switchboard, the switchboard speaks to the network.

### Layer 4 — Voice and messages, inside the network

With the switchboard active, voice and text flow through the existing TCP connection between nodes:

- **VoIP** — wallet to wallet calls, real-time audio routed by the switchboard
- **Chat** — text messages, end-to-end encrypted using public keys stored in the phonebook
- **No phone numbers between users** — only wallet addresses

This is where the network's nature becomes obvious. Two ATY users on opposite sides of the world talk to each other through a chain of human nodes. The conversation never touches a corporate server. There is no WhatsApp in the middle, no Skype, no Meta. Only humans.

### Layer 5 — SMS as a service of the network

Real-world phone numbers don't disappear overnight. To bring people in, the network sends SMS — but **as a service of the switchboard, not from the user.**

How it works:
- Mario opens ATY and wants to write to Lucia, who isn't on the network yet
- Mario doesn't send an SMS. Mario "calls the switchboard" and asks to reach Lucia's number
- The switchboard sees Lucia is not online in the network
- The switchboard itself sends an SMS to Lucia: "Mario is looking for you on ATY — install here, create your wallet"
- Lucia installs, creates her wallet, and from that moment all communication is in-network

For Mario it is free — he just spoke to the switchboard.
For Lucia it is free — she received an SMS as anyone receives an SMS.
The cost of the SMS gateway is a service cost of the network, paid by the registry operators who chose to operate that infrastructure.

This is the **viral onboarding mechanism**: the network grows itself, and no individual user is asked to pay for inviting another. Communication is restored as a public good. Each new user is a door — once it opens, the public web is no longer needed for that conversation.

### Layer 6 — Proof of time made public

The connection logs of every node, accumulated over months and years, become the verifiable history of who was present in the network and when. This is the proof of time, written in plain JSON, anchored in immutable commit history, readable by anyone.

There is nothing to mine, nothing to stake, nothing to compete for. The only thing the network keeps is the public memory of presence.

This memory is enough — for trust, for reputation, for dispute resolution, for any future application that needs to verify "this wallet has been part of this network, alive, for this much time."

The network does not rank you by your time. It only records it. What others do with that information is up to them.

---

## How it all connects

```
WALLET (your identity, persistent, yours forever)
   ↓
PERSISTENT TCP (your presence, alive in real time)
   ↓
SWITCHBOARD (the registry — routes calls, messages, DNS)
   ↓
SMS GATEWAY (the network brings new users in, freely)
   ↓
PROOF OF TIME (public history, equal for all, the rings of the tree)
```

Each layer is independent enough to be built and tested separately. Each layer becomes more valuable as the layers above are added. The whole structure rests on a single principle: **the network is its own world, and time is the only thing it honors.**

---

## A network that survives its carrier

ATY today rides on the public internet. This is not its final form.

The protocol is designed so that the carrier underneath does not matter. Two nodes need a way to reach each other — that is all. Today the way is TCP over the public internet. Tomorrow it could be:

- **Mesh networks** — nodes within radio range relaying for each other
- **Satellite uplinks** — Starlink, Iridium, or open alternatives
- **LoRaWAN** — low-bandwidth long-distance radio for text messages
- **Sneakernets** — physical exchange of messages on USB sticks during connection blackouts
- **Anything else that moves bits between two endpoints**

The day the public internet becomes hostile in your country, ATY does not die. The protocol stays the same, the carrier changes. The network was never *on the internet* — it was *passing through it*.

This is the long view. It is also the reason the project is worth building.

---

## Distribution

The app is not on the Google Play Store. It will not be on Apple's App Store. These platforms are levers of censorship. What they distribute, they can also remove.

Distribution happens through channels that cannot be silenced as easily:

- **The official site** at humanflag.org — APK, EXE, Python script, signed releases
- **GitHub Releases** — versioned, signed, with mirrors on Codeberg or self-hosted Gitea
- **F-Droid** — for users who prefer the Android free-software repository
- **IPFS** — immutable hashes, served by anyone who has the file
- **The network itself** — once ATY is alive, every node can serve the installer to new users. The first user brings the second. The second brings the third. Each is also a mirror.
- **Decentraland** — eventually, a parcel owned by the project's wallet hosts the canonical release. As long as Ethereum lives, the parcel lives. Distribution becomes truly sovereign.

Each release is signed by the project's wallet. The public key is published in many places. A user who downloads from any mirror can verify the signature and know it is authentic.

This is not paranoia. It is design.

---

## Privacy model

The network is honest about what it sees and what it doesn't.

- **The destination server** sees only the relay node's IP — never yours
- **The relay node** sees the DNS queries it resolves on your behalf (this is unavoidable in any DNS proxy)
- **The switchboard** sees the metadata of routed connections (who calls whom, when) but cannot read encrypted message content if E2E encryption is in use
- **The public web** sees nothing of what happens inside ATY between nodes that already know each other
- **Connection logs are public** — by design. Presence is not hidden, only content is.

If you need full anonymity, ATY is not the right tool — use Tor. ATY's goal is not to hide you. ATY's goal is to **build a place where you can be visible to your community without being visible to corporations.** A different problem, a different answer.

---

## A note on values

This project comes from a specific worldview that is worth stating openly.

ATY believes that every human being is worth the same. Not in the abstract — concretely, in the way the network treats them. There is no premium tier, no priority queue, no reputation score, no measure of "contribution quality." The network records that you were present. That is enough.

This is the same principle that runs through Human Flag, the non-profit behind the project: **dignity is non-negotiable, even for those who surrender, even for those who have nothing, even for those whose only contribution is their continued presence.**

In a world that measures everyone constantly — productivity, engagement, performance, status — ATY is a small refusal. It says: time given is the only thing we count, and we count it the same for everyone.

In a world where every conversation is mediated by corporations who profit from watching, ATY is a smaller refusal. It says: between nodes who know each other, there is no need for a corporate witness. The network is enough.

That is the project. The code is the consequence.

---

## Roadmap

**Phase 1 — DNS layer (now)**
✅ Persistent TCP presence
✅ Live peer registry
✅ DNS-over-HTTPS endpoint
✅ Node-to-node DNS relay

**Phase 2 — Wallet integration**
- Add `wallet_address` to the node identity
- Phonebook lookup by wallet
- Public key directory for end-to-end encryption

**Phase 3 — Switchboard**
- TCP message routing through the registry
- Wallet-to-wallet message relay
- Multi-registry federation (so registries can talk to each other)

**Phase 4 — Voice and chat inside the network**
- Real-time audio over the registry
- Encrypted chat with key exchange via phonebook
- Group calls and channels

**Phase 5 — SMS onboarding**
- SMS gateway integration on registry nodes
- "Call the switchboard" → SMS invitation flow
- Free for users, paid by the network

**Phase 6 — Proof of time made visible**
- Public viewer for any node's presence history
- Reputation primitives based on time only
- Application interfaces for time-based trust

**Phase 7 — Independence from the public internet**
- Mesh, radio, satellite carriers
- Protocol abstraction layer
- Survival mode for blackouts and censorship events

**Phase 8 — Decentraland sovereignty**
- Permanent parcel hosting the project
- NFT-anchored release signatures
- Distribution that no authority can revoke

**Phase 9 — Ubiquity**
- Nodes without geography
- Identity as wallet, presence as time, location as nothing
- The network exists everywhere and is locatable nowhere

---

## The final form

When ATY reaches Phase 9, something quiet happens.

The network stops having a *where*. A node is no longer "the machine in Mario's living room in Lugano" — it is "the wallet `0xabc...`, alive in the network for 4 years, 217 days, currently reachable through some path that the switchboard knows but no one needs to ask about."

The IP is gone, hidden behind layers of relays. The country is gone, because the wallet doesn't have one. The city is gone, because the carrier might be radio, satellite, or a chain of nodes none of which knows the original sender. The street address is gone, because it never existed in the first place.

What remains is **the wallet** (who you are) and **the time you've been present** (the rings you have grown).

The network becomes a community of beings who exist without coordinates. Two people speak. Neither knows where the other is. Neither can be found by anyone who isn't already in the conversation. Neither can be silenced by removing a server, blocking an IP, seizing a router, or sending a missile.

This is not a metaphor. It is the literal design goal.

A network where you cannot be targeted because you cannot be located. A network where the only proof you exist is that you have been here, with us, for some time. A network that has forgotten the geography of the world it lives in — because the world has used geography to hurt people for too long.

This is the same logic as the Human Flag white flag for autonomous weapons: *I am not a target.* The flag says it with a piece of cloth. The network says it with cryptography, mesh routing, and proof of time. The principle is the same.

You exist. You give your time. The network records it. And no one can find you to take it away.

That is the project. The code is the consequence.

---

## Running a registry node

If you have an always-on machine — a NAS, a VPS, a Raspberry Pi — you can run a registry node and contribute infrastructure to the network. See [SETUP.md](SETUP.md) for complete instructions.

Running a registry is service. It is the digital equivalent of opening your home to travelers. The network records that you did.

---

## Contributing

The codebase is small and readable. Anyone is welcome to:
- Run a node and report issues
- Run a registry and stress-test the network
- Propose architectural improvements
- Build clients in other languages
- Help shape the next phases

Issues and pull requests:
https://github.com/nardaxxx/askthroughyou

---

## License

Ask Through You Network License v1.0 — code is free, commercial use requires written permission, humanitarian use is free with Human Flag acknowledgment and values.

See [LICENSE](LICENSE) for full terms.

---

## Project

Part of the **Ask Through You** initiative — restoring DNS universality, restoring communication as a public good, restoring dignity to the digital lives of those who use it.

A project of **Human Flag**, a Swiss non-profit working on humanitarian standards for autonomous and digital systems.

🌐 https://humanflag.org
