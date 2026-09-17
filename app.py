import os
import logging

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ig-bot")

app = Flask(__name__)

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]

GRAPH_URL = "https://graph.instagram.com/v21.0"

DM_MESSAGE = (
    "Olá! Separei um teste rápido pra descobrir qual receita natural mais "
    "pode te ajudar hoje.\n\n"
    "Leva menos de 1 minuto, e no final você já recebe uma receita de graça.\n\n"
    "https://bit.ly/4gWVOPl"
)

PUBLIC_REPLY = "Te mandei no direct! 📩"


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    log.info("Evento recebido: %s", data)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {})
            comment_id = value.get("id")
            from_user = value.get("from", {})
            username = from_user.get("username")

            if not comment_id or from_user.get("id") == IG_USER_ID:
                continue

            log.info("Comentário de %s (%s)", username, comment_id)

            reply_to_comment(comment_id, PUBLIC_REPLY)
            send_private_reply(comment_id, DM_MESSAGE)

    return jsonify(status="ok"), 200


def reply_to_comment(comment_id: str, message: str):
    url = f"{GRAPH_URL}/{comment_id}/replies"
    resp = requests.post(
        url,
        params={"access_token": PAGE_ACCESS_TOKEN},
        data={"message": message},
    )
    if not resp.ok:
        log.error("Erro ao responder comentário %s: %s", comment_id, resp.text)


def send_private_reply(comment_id: str, message: str):
    url = f"{GRAPH_URL}/me/messages"
    resp = requests.post(
        url,
        params={"access_token": PAGE_ACCESS_TOKEN},
        json={
            "recipient": {"comment_id": comment_id},
            "message": {"text": message},
        },
    )
    if not resp.ok:
        log.error("Erro ao enviar DM pro comentário %s: %s", comment_id, resp.text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
