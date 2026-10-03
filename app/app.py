import fcntl
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

# --- Configuração por variáveis de ambiente (cada container recebe a sua) ---
INSTANCE = os.environ.get("INSTANCE_NAME", "app")
PEERS = [p.strip() for p in os.environ.get("PEERS", "").split(",") if p.strip()]
PEER_PORT = os.environ.get("PEER_PORT", "5000")   # porta INTERNA, não a publicada
DATA_DIR = os.environ.get("DATA_DIR", "/data")
PORT = int(os.environ.get("PORT", "5000"))
TIMEOUT = float(os.environ.get("PEER_TIMEOUT", "2"))

os.makedirs(DATA_DIR, exist_ok=True)
MESSAGES_FILE = os.path.join(DATA_DIR, f"messages_{INSTANCE}.jsonl")
LOG_FILE = os.path.join(DATA_DIR, f"{INSTANCE}.log")

# --- Log: um arquivo por instância no volume + saída padrão (docker compose logs) ---
log = logging.getLogger(INSTANCE)
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
for _h in (logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

app = Flask(__name__)


# --- Armazenamento (JSON Lines: uma mensagem por linha) ---
def save_message(msg):
    with open(MESSAGES_FILE, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)          # protege contra escritas simultâneas
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def read_messages():
    if not os.path.exists(MESSAGES_FILE):
        return []
    with open(MESSAGES_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def message_exists(msg_id):
    return any(m.get("id") == msg_id for m in read_messages())


# --- Replicação para os outros containers ---
def replicate(msg):
    results = {}
    for peer in PEERS:
        url = f"http://{peer}:{PEER_PORT}/send"
        try:
            r = requests.post(url, json=msg, headers={"X-Replicated": "true"},
                              timeout=TIMEOUT)
            r.raise_for_status()
            results[peer] = "ok"
            log.info("replicada id=%s para %s", msg["id"], peer)
        except requests.RequestException as exc:
            results[peer] = f"erro: {type(exc).__name__}"
            log.warning("falha ao replicar id=%s para %s: %s", msg["id"], peer, exc)
    return results


# --- Endpoints ---
@app.post("/send")
def send():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or not isinstance(body.get("message"), str)
            or not body["message"].strip()):
        return jsonify(error='envie um JSON no formato {"message": "texto"}'), 400

    # Cabeçalho que diferencia "cópia vinda de outro container" de "cliente".
    # Sem isso, as cópias seriam replicadas de volta, em loop infinito.
    replicated = request.headers.get("X-Replicated") == "true"

    if replicated:
        if not body.get("id"):
            return jsonify(error="cópia sem id"), 400
        if message_exists(body["id"]):          # idempotência
            log.info("cópia duplicada ignorada id=%s", body["id"])
            return jsonify(status="duplicada", id=body["id"]), 200
        msg = {"id": body["id"], "message": body["message"],
               "origin": body.get("origin"), "timestamp": body.get("timestamp")}
        save_message(msg)
        log.info("cópia recebida de %s id=%s", msg["origin"], msg["id"])
        return jsonify(status="replicada", id=msg["id"]), 201

    msg = {"id": str(uuid.uuid4()), "message": body["message"], "origin": INSTANCE,
           "timestamp": datetime.now(timezone.utc).isoformat()}
    save_message(msg)
    log.info("mensagem do cliente id=%s", msg["id"])
    results = replicate(msg)
    return jsonify(id=msg["id"], armazenada_em=INSTANCE, replicacao=results), 201


@app.get("/messages")
def messages():
    msgs = read_messages()
    return jsonify(instance=INSTANCE, count=len(msgs), messages=msgs)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
