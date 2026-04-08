from flask import Flask, request, jsonify
import requests, json, time, os

app = Flask(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "tuo_user/dpnn-peers"
FILE = "peers.json"

def get_peers():
    url = f"https://api.github.com/repos/{REPO}/contents/{FILE}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    data = r.json()
    content = json.loads(
        __import__("base64").b64decode(data["content"])
    )
    return content, data["sha"]

def save_peers(peers, sha):
    url = f"https://api.github.com/repos/{REPO}/contents/{FILE}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content = __import__("base64").b64encode(
        json.dumps(peers, indent=2).encode()
    ).decode()

    payload = {
        "message": "update peers",
        "content": content,
        "sha": sha
    }

    requests.put(url, headers=headers, json=payload)

@app.route("/register", methods=["POST"])
def register():
    data = request.json

    ip = request.remote_addr
    port = data.get("port", 35353)
    country = data.get("country_code", "??")

    peers, sha = get_peers()

    peers = [p for p in peers if p["ip"] != ip]

    peers.append({
        "ip": ip,
        "port": port,
        "country_code": country,
        "last_seen": int(time.time())
    })

    save_peers(peers, sha)

    return jsonify({"ok": True})

app.run(host="0.0.0.0", port=8080)
