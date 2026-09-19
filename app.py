import os
import logging
import random
import threading
import time

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ig-bot")

app = Flask(__name__)

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]

GRAPH_URL = "https://graph.instagram.com/v21.0"

DM_TEXT = (
    "Olá! Separei um teste rápido pra descobrir qual receita natural mais "
    "pode te ajudar hoje.\n\n"
    "Leva menos de 1 minuto, e no final você já recebe uma receita de graça."
)
DM_LINK = "https://cilene-sales-page.vercel.app"
DM_BUTTON_TITLE = "Clique aqui para receber"

PUBLIC_REPLIES = [
    "Te mandei no direct! 📩",
    "Acabei de te enviar uma mensagem no direct, dá uma olhadinha! 💚",
    "Olha lá no seu direct, mandei tudo por lá! ✨",
]

_processed_comments = {}
_processed_lock = threading.Lock()
_DEDUPE_TTL_SECONDS = 3600


def already_processed(comment_id: str) -> bool:
    now = time.time()
    with _processed_lock:
        # limpa entradas velhas
        for cid in list(_processed_comments):
            if now - _processed_comments[cid] > _DEDUPE_TTL_SECONDS:
                del _processed_comments[cid]
        if comment_id in _processed_comments:
            return True
        _processed_comments[comment_id] = now
        return False


@app.route("/privacy", methods=["GET"])
def privacy():
    return """
    <html>
    <head><title>Política de Privacidade</title></head>
    <body style="font-family: sans-serif; max-width: 700px; margin: 40px auto; line-height: 1.6;">
        <h1>Política de Privacidade</h1>
        <p>Este aplicativo automatiza respostas a comentários e mensagens
        diretas na conta do Instagram @dicas_da_cilene.</p>
        <p>Os dados acessados (comentários públicos, nome de usuário do
        Instagram e mensagens diretas) são usados exclusivamente para
        responder automaticamente aos usuários que interagem com os posts
        da conta, enviando informações e links relacionados ao conteúdo
        publicado.</p>
        <p>Nenhum dado é vendido, compartilhado com terceiros ou usado para
        fins diferentes deste. Os dados não ficam armazenados de forma
        permanente pelo aplicativo.</p>
        <p>Para dúvidas ou solicitações de remoção de dados, entre em
        contato pela própria conta do Instagram @dicas_da_cilene.</p>
    </body>
    </html>
    """, 200


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

    # responde rápido pro Meta e processa em background, pra evitar que
    # ele reenvie o mesmo evento por causa de timeout
    threading.Thread(target=process_event, args=(data,), daemon=True).start()

    return jsonify(status="ok"), 200


def process_event(data: dict):
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

            if already_processed(comment_id):
                log.info("Comentário %s já processado, ignorando", comment_id)
                continue

            log.info("Comentário de %s (%s)", username, comment_id)

            reply_to_comment(comment_id, random.choice(PUBLIC_REPLIES))
            send_private_reply_with_button(comment_id, DM_TEXT, DM_BUTTON_TITLE, DM_LINK)


def reply_to_comment(comment_id: str, message: str):
    url = f"{GRAPH_URL}/{comment_id}/replies"
    resp = requests.post(
        url,
        params={"access_token": PAGE_ACCESS_TOKEN},
        data={"message": message},
    )
    if not resp.ok:
        log.error("Erro ao responder comentário %s: %s", comment_id, resp.text)


def send_private_reply_with_button(comment_id: str, text: str, button_title: str, url_link: str):
    url = f"{GRAPH_URL}/me/messages"
    resp = requests.post(
        url,
        params={"access_token": PAGE_ACCESS_TOKEN},
        json={
            "recipient": {"comment_id": comment_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text,
                        "buttons": [
                            {
                                "type": "web_url",
                                "url": url_link,
                                "title": button_title,
                            }
                        ],
                    },
                }
            },
        },
    )
    if not resp.ok:
        log.error("Erro ao enviar DM pro comentário %s: %s", comment_id, resp.text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
