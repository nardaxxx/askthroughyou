#!/usr/bin/env python3
"""
ATY Centralino Server
Analogo al centralino telefonico anni '20:
- Sa chi sei (ID + nome + IP)
- Mette in contatto i peer
- Non rivela identità a nessuno
- Dati cifrati con Fernet (AES-128)
"""

from flask import Flask, request, jsonify
from cryptography.fernet import Fernet
import json
import os

app = Flask(__name__)

# --- CONFIGURAZIONE ---
DB_FILE = "rubrica.enc"       # File cifrato sul NAS
KEY_FILE = "centralino.key"   # Chiave segreta - NON condividere mai

# --- GESTIONE CHIAVE ---
def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        print(f"[CENTRALINO] Nuova chiave generata: {KEY_FILE}")
        return key

KEY = load_or_create_key()
fernet = Fernet(KEY)

# --- STORAGE CIFRATO ---
def load_rubrica():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "rb") as f:
        decrypted = fernet.decrypt(f.read())
        return json.loads(decrypted)

def save_rubrica(rubrica):
    encrypted = fernet.encrypt(json.dumps(rubrica).encode())
    with open(DB_FILE, "wb") as f:
        f.write(encrypted)

# --- ENDPOINT: REGISTRAZIONE PEER ---
@app.route("/register", methods=["POST"])
def register():
    """
    Il peer si registra con:
    {
        "app_id": "ID univoco app",
        "nome": "Mario",
        "cognome": "Rossi",
        "ip": "1.2.3.4",
        "porta": 5000
    }
    """
    data = request.json
    required = ["app_id", "nome", "cognome", "ip", "porta"]
    if not all(k in data for k in required):
        return jsonify({"error": "Dati incompleti"}), 400

    rubrica = load_rubrica()
    rubrica[data["app_id"]] = {
        "nome": data["nome"],
        "cognome": data["cognome"],
        "ip": data["ip"],
        "porta": data["porta"]
    }
    save_rubrica(rubrica)

    print(f"[CENTRALINO] Registrato: {data['app_id']} ({data['nome']} {data['cognome']})")
    return jsonify({"status": "ok", "app_id": data["app_id"]}), 200

# --- ENDPOINT: LOOKUP (pronto a passare la chiamata) ---
@app.route("/lookup", methods=["POST"])
def lookup():
    """
    Un peer chiede di contattare un altro peer:
    {
        "app_id": "ID del peer cercato"
    }
    Risponde SOLO con IP e porta - mai nome/cognome
    """
    data = request.json
    if "app_id" not in data:
        return jsonify({"error": "app_id mancante"}), 400

    rubrica = load_rubrica()
    peer = rubrica.get(data["app_id"])

    if not peer:
        return jsonify({"error": "Peer non trovato"}), 404

    # Restituisce SOLO i dati di connessione, mai identità
    return jsonify({
        "ip": peer["ip"],
        "porta": peer["porta"]
    }), 200

# --- ENDPOINT: LISTA ANONIMA (solo ID attivi) ---
@app.route("/peers", methods=["GET"])
def list_peers():
    """
    Restituisce lista di ID attivi - nessun dato personale
    """
    rubrica = load_rubrica()
    return jsonify({"peers": list(rubrica.keys())}), 200

# --- ENDPOINT: CANCELLAZIONE ---
@app.route("/unregister", methods=["POST"])
def unregister():
    data = request.json
    if "app_id" not in data:
        return jsonify({"error": "app_id mancante"}), 400

    rubrica = load_rubrica()
    if data["app_id"] in rubrica:
        del rubrica[data["app_id"]]
        save_rubrica(rubrica)
        return jsonify({"status": "rimosso"}), 200
    return jsonify({"error": "Peer non trovato"}), 404

# --- AVVIO ---
if __name__ == "__main__":
    print("[CENTRALINO] Avvio server ATY Centralino...")
    print("[CENTRALINO] Buonasera, mi può passare Luigi Grande?")
    app.run(host="0.0.0.0", port=6000, debug=False)
