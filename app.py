import os
import html
import json
import logging
import uuid
import random
import threading
import time

import requests
from flask import Flask, request, jsonify, redirect, Response

try:
    import psycopg
except ImportError:
    psycopg = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ig-bot")

app = Flask(__name__)

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]

FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

GRAPH_URL = "https://graph.instagram.com/v21.0"
FB_GRAPH_URL = "https://graph.facebook.com/v21.0"

DM_TEXTS = [
    "Oi! Que bom que você comentou 💚\n\n"
    "Preparei um teste rápido pra descobrir qual receita natural mais "
    "pode te ajudar hoje. Leva menos de 1 minuto e é totalmente gratuito.\n\n"
    "É só clicar no botão abaixo:",
    "Olá! Obrigada pelo comentário 🌿\n\n"
    "Montei um teste gratuito de menos de 1 minuto que mostra qual receita "
    "natural combina mais com você agora.\n\n"
    "Toca no botão pra começar:",
    "Oi, tudo bem? Vi seu comentário e queria te ajudar 💚\n\n"
    "Fiz um teste bem rápido (1 minutinho, de graça) pra indicar a receita "
    "natural ideal pro seu momento.\n\n"
    "É só clicar aqui embaixo:",
    "Que bom ter você por aqui! ✨\n\n"
    "Separei um teste gratuito e rápido pra descobrir qual receita natural "
    "pode te ajudar hoje.\n\n"
    "Clica no botão pra fazer:",
]
DM_LINK = "https://cilene-sales-page.vercel.app"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://ig-bot-dicas-cilene.onrender.com").rstrip("/")
LINK_A = PUBLIC_URL + "/go/a"
LINK_B = DM_LINK
DATABASE_URL = os.environ.get("DATABASE_URL")
STATS_KEY = os.environ.get("STATS_KEY", "")

DM_TEXTS_B = [
    "Oi! Que bom que você comentou 💚\n\n"
    "Preparei um teste rápido pra descobrir qual receita natural mais "
    "pode te ajudar hoje. Leva menos de 1 minuto e é totalmente gratuito.\n\n"
    "É só clicar no link:\n{link}",
    "Olá! Obrigada pelo comentário 🌿\n\n"
    "Montei um teste gratuito de menos de 1 minuto que mostra qual receita "
    "natural combina mais com você agora.\n\n"
    "Toca no link pra começar:\n{link}",
    "Oi, tudo bem? Vi seu comentário e queria te ajudar 💚\n\n"
    "Fiz um teste bem rápido (1 minutinho, de graça) pra indicar a receita "
    "natural ideal pro seu momento.\n\n"
    "É só clicar aqui:\n{link}",
    "Que bom ter você por aqui! ✨\n\n"
    "Separei um teste gratuito e rápido pra descobrir qual receita natural "
    "pode te ajudar hoje.\n\n"
    "Clica no link pra fazer:\n{link}",
]
COPIES = {
    "m1": (
        "Oi! Que bom que você comentou 💚\n\n"
        "Deixa eu te passar uma que eu faço sempre: 1 xícara de água quente, 3 folhas de hortelã "
        "e 1 rodela de limão. Abafa por 5 minutinhos e toma de manhã, pra começar o dia mais leve 🌿\n\n"
        "Essa e mais 99 receitinhas da minha família estão todas organizadas aqui:\n{link}"
    ),
    "m2": (
        "Oi, tudo bem? 🌿\n\n"
        "Sabe aquela receita que você salva e, na hora de precisar, não acha mais? "
        "Juntei as 100 receitas naturais que aprendi com a minha mãe e a minha avó, "
        "organizadas por necessidade, com medida, horário e cuidados.\n\n"
        "Dá uma olhada aqui:\n{link}"
    ),
    "m3": (
        "Oi! Obrigada pelo comentário 💛\n\n"
        "Minha avó tinha um chá pra cada coisa: um pra dormir melhor, um pra digestão, "
        "um banho de pés pro fim do dia… Passei anos anotando tudo, e agora estão as "
        "100 receitas juntas num lugar só.\n\n"
        "Te mostro aqui:\n{link}"
    ),
    "m4": (
        "Oi! Que bom ter você aqui ✨\n\n"
        "Aqui estão as minhas 100 receitas naturais de casa, com ingredientes simples "
        "de mercado e feira:\n{link}"
    ),
}
COPY_NAMES = {"m1": "1 — Valor primeiro", "m2": "2 — Dor", "m3": "3 — História", "m4": "4 — Direta"}
TRACK_EVENTS = {"landed", "cta"}


def copy_text(variant: str) -> str:
    return COPIES[variant].format(link=f"{DM_LINK}/?m={variant[1:]}")


DM_BUTTON_TITLE = "Clique aqui para receber"  # usado só no fluxo do Facebook

CLICK_BUTTON_TITLE = "QUERO ✅"
CLICK_PAYLOAD = "QUERO_LINK"

FINAL_DM_TEXTS = [
    "Perfeito! Aqui está o seu teste 👇\n{link}",
    "Que bom! Foi só clicar aqui pra fazer o teste 👇\n{link}",
    "Prontinho! Seu teste gratuito está aqui 👇\n{link}",
]

PUBLIC_REPLIES = [
    "Te mandei no direct! 📩",
    "Acabei de te enviar uma mensagem no direct, dá uma olhadinha! 💚",
    "Olha lá no seu direct, mandei tudo por lá! ✨",
]

_processed_comments = {}
_processed_lock = threading.Lock()
_DEDUPE_TTL_SECONDS = 3600


BOT_UA_MARKERS = ("facebookexternalhit", "facebot", "meta-externalagent", "bot", "crawler", "spider", "preview")


def _db():
    return psycopg.connect(DATABASE_URL, connect_timeout=5, autocommit=True)


def init_db():
    if not (DATABASE_URL and psycopg):
        log.warning("DATABASE_URL não configurado, métricas A/B desligadas")
        return
    try:
        with _db() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ab_events_cilene (
                    id BIGSERIAL PRIMARY KEY,
                    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                    variant TEXT NOT NULL,
                    evt TEXT NOT NULL,
                    sid TEXT NOT NULL,
                    platform TEXT
                )"""
            )
    except Exception:
        log.exception("init_db falhou")


def record(variant: str, evt: str, sid: str, platform: str = None):
    if not (DATABASE_URL and psycopg):
        return
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO ab_events_cilene (variant, evt, sid, platform) VALUES (%s, %s, %s, %s)",
                (variant, evt, sid[:64], platform),
            )
    except Exception:
        log.exception("record falhou (%s %s)", variant, evt)


def pick_variant() -> str:
    return random.choice(list(COPIES))


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


@app.route("/go/<variant>", methods=["GET"])
def go(variant):
    resp = redirect(DM_LINK, code=302)
    resp.headers["Cache-Control"] = "no-store"
    if variant not in ("a", "b"):
        return resp
    ua = (request.headers.get("User-Agent") or "").lower()
    if any(m in ua for m in BOT_UA_MARKERS):
        return resp
    sid = request.cookies.get("cs_sid")
    if not sid or len(sid) > 64:
        sid = uuid.uuid4().hex
        resp.set_cookie("cs_sid", sid, max_age=60 * 60 * 24 * 365, samesite="Lax", secure=True)
    record(variant, "landed", sid)
    return resp


@app.route("/t", methods=["POST", "OPTIONS"])
def track():
    resp = Response(status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    if request.method == "OPTIONS":
        resp.headers["Access-Control-Allow-Methods"] = "POST"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    try:
        body = json.loads(request.get_data(as_text=True) or "{}")
    except ValueError:
        return resp
    if not isinstance(body, dict):
        return resp
    v, e, sid = body.get("v"), body.get("e"), str(body.get("s") or "")
    if v in COPIES and e in TRACK_EVENTS and 0 < len(sid) <= 64:
        record(v, e, sid)
    return resp


STATS_SQL = """
SELECT variant,
  COUNT(*) FILTER (WHERE evt = 'dm_sent') AS dms,
  COUNT(DISTINCT sid) FILTER (WHERE evt = 'landed') AS people,
  COUNT(DISTINCT sid) FILTER (WHERE evt = 'cta') AS cta
FROM ab_events_cilene GROUP BY variant
"""


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "–"


STATS_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60"><title>Teste de copys — Cilene</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f5f2;color:#1d1d1f;margin:0;padding:24px 16px}
main{max-width:760px;margin:0 auto}
.wrap{overflow-x:auto;background:#fff;border:1px solid #e3e1dc;border-radius:12px}
table{border-collapse:collapse;width:100%;min-width:620px}
th,td{padding:12px 14px;border-bottom:1px solid #eee;text-align:right;font-variant-numeric:tabular-nums}
thead th{text-align:left;font-size:12px;color:#666;font-weight:600}
tbody th{text-align:left;font-weight:600}
p.note{color:#666;font-size:13px;line-height:1.5}
</style></head><body><main>
<h1>Teste de copys da DM — bot Cilene</h1>__ERR__
<div class="wrap"><table><thead><tr><th>Mensagem</th><th>DMs enviadas</th><th>Pessoas que entraram</th>
<th>% que entrou</th><th>Clicaram em comprar</th><th>% compra / entrada</th></tr></thead>
<tbody>__ROWS__</tbody></table></div>
<p class="note">Cada comentário sorteia uma das 4 mensagens (25% cada). "Entraram" e "clicaram" contam pessoas
diferentes (o mesmo navegador conta uma vez) e dependem do script instalado na página da Vercel.
"Clicaram em comprar" é o clique em um botão "Quero"; a venda em si aparece na Zuptos.
Espere umas 100 DMs em cada mensagem antes de decidir. A página atualiza sozinha a cada minuto.</p>
</main></body></html>"""


@app.route("/stats", methods=["GET"])
def stats():
    if not STATS_KEY or request.args.get("key") != STATS_KEY:
        return "forbidden", 403
    rows = {v: (0, 0, 0) for v in COPIES}
    err = ""
    if DATABASE_URL and psycopg:
        try:
            with _db() as conn:
                for v, *nums in conn.execute(STATS_SQL).fetchall():
                    if v in rows:
                        rows[v] = tuple(nums)
        except Exception as exc:
            err = "<p style='color:#b00'>Erro ao ler o banco: " + html.escape(str(exc)) + "</p>"
    else:
        err = "<p style='color:#b00'>Banco não configurado.</p>"
    trs = ""
    for v in COPIES:
        dms, people, cta = rows[v]
        trs += (
            f"<tr><th>{COPY_NAMES[v]}</th><td>{dms}</td><td>{people}</td>"
            f"<td>{_pct(people, dms)}</td><td>{cta}</td><td>{_pct(cta, people)}</td></tr>"
        )
    return STATS_PAGE.replace("__ERR__", err).replace("__ROWS__", trs), 200


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


def process_facebook_event(data: dict):
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "feed" or value.get("item") != "comment" or value.get("verb") != "add":
                continue
            comment_id = value.get("comment_id")
            from_user = value.get("from", {})

            if not comment_id or from_user.get("id") == entry.get("id"):
                continue
            # resposta a outro comentário (sub-comentário): ignora, só top-level
            if value.get("parent_id") and value.get("parent_id") != value.get("post_id"):
                continue
            if already_processed(comment_id):
                continue

            log.info("FB comentário de %s (%s)", from_user.get("name"), comment_id)

            requests.post(
                f"{FB_GRAPH_URL}/{comment_id}/comments",
                params={"access_token": FB_PAGE_ACCESS_TOKEN},
                data={"message": random.choice(PUBLIC_REPLIES).replace("direct", "inbox")},
            )
            variant = pick_variant()
            if variant in COPIES:
                message = {"text": copy_text(variant)}
            elif variant == "b":
                message = {"text": random.choice(DM_TEXTS_B).format(link=LINK_B)}
            else:
                message = {
                    "attachment": {
                        "type": "template",
                        "payload": {
                            "template_type": "button",
                            "text": random.choice(DM_TEXTS),
                            "buttons": [{"type": "web_url", "url": LINK_A, "title": DM_BUTTON_TITLE}],
                        },
                    }
                }
            resp = requests.post(
                f"{FB_GRAPH_URL}/me/messages",
                params={"access_token": FB_PAGE_ACCESS_TOKEN},
                json={"recipient": {"comment_id": comment_id}, "message": message},
            )
            if resp.ok:
                record(variant, "dm_sent", comment_id, "facebook")
            else:
                log.error("FB erro ao enviar mensagem %s: %s", comment_id, resp.text)


def process_event(data: dict):
    if data.get("object") == "page":
        if FB_PAGE_ACCESS_TOKEN:
            process_facebook_event(data)
        return
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            handle_messaging_event(entry, event)
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {})
            comment_id = value.get("id")
            from_user = value.get("from", {})
            username = from_user.get("username")

            own_ids = {IG_USER_ID, entry.get("id")}
            if (
                not comment_id
                or value.get("parent_id")
                or from_user.get("id") in own_ids
                or from_user.get("self_ig_scoped_id")
                or username == "dicas_da_cilene"
            ):
                continue

            if already_processed(comment_id):
                log.info("Comentário %s já processado, ignorando", comment_id)
                continue

            log.info("Comentário de %s (%s)", username, comment_id)

            reply_to_comment(comment_id, random.choice(PUBLIC_REPLIES))
            variant = pick_variant()
            if send_private_reply_with_click(comment_id, variant):
                record(variant, "dm_sent", comment_id, "instagram")


def reply_to_comment(comment_id: str, message: str):
    url = f"{GRAPH_URL}/{comment_id}/replies"
    resp = requests.post(
        url,
        params={"access_token": PAGE_ACCESS_TOKEN},
        data={"message": message},
    )
    if not resp.ok:
        log.error("Erro ao responder comentário %s: %s", comment_id, resp.text)


def _post_message(body: dict) -> requests.Response:
    return requests.post(
        f"{GRAPH_URL}/me/messages",
        params={"access_token": PAGE_ACCESS_TOKEN},
        json=body,
    )


def send_private_reply_with_click(comment_id: str, variant: str) -> bool:
    if variant in COPIES:
        resp = _post_message({"recipient": {"comment_id": comment_id}, "message": {"text": copy_text(variant)}})
        if resp.ok:
            log.info("Private Reply enviada (comment_id=%s, copy %s): %s", comment_id, variant, resp.text)
            return True
        log.error("Private Reply copy %s falhou (comment_id=%s): %s", variant, comment_id, resp.text)
        return False

    # Versão B: link escrito no texto, sem botão.
    if variant == "b":
        text_b = random.choice(DM_TEXTS_B).format(link=LINK_B)
        resp = _post_message({"recipient": {"comment_id": comment_id}, "message": {"text": text_b}})
        if resp.ok:
            log.info("Private Reply enviada (comment_id=%s, versão B, link no texto): %s", comment_id, resp.text)
            return True
        log.error("Private Reply versão B falhou (comment_id=%s): %s", comment_id, resp.text)
        return False

    # Versão A: botão de link direto. Se a API recusar, cai pro fluxo em
    # duas etapas (quick_reply -> segunda DM com o link).
    text = random.choice(DM_TEXTS)
    link_button_body = {
        "recipient": {"comment_id": comment_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": [{"type": "web_url", "url": LINK_A, "title": DM_BUTTON_TITLE}],
                },
            }
        },
    }
    resp = _post_message(link_button_body)
    if resp.ok:
        log.info("Private Reply enviada (comment_id=%s, versão A, link_button): %s", comment_id, resp.text)
        return True
    log.error("Private Reply com link_button recusada (comment_id=%s): %s", comment_id, resp.text)

    quick_reply_body = {
        "recipient": {"comment_id": comment_id},
        "message": {
            "text": text,
            "quick_replies": [
                {"content_type": "text", "title": CLICK_BUTTON_TITLE, "payload": CLICK_PAYLOAD}
            ],
        },
    }
    resp = _post_message(quick_reply_body)
    if resp.ok:
        log.info("Private Reply enviada (comment_id=%s, versão A, quick_reply): %s", comment_id, resp.text)
        return True
    log.error("Private Reply com quick_reply recusada (comment_id=%s): %s", comment_id, resp.text)

    postback_body = {
        "recipient": {"comment_id": comment_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": [
                        {"type": "postback", "title": CLICK_BUTTON_TITLE, "payload": CLICK_PAYLOAD}
                    ],
                },
            }
        },
    }
    resp = _post_message(postback_body)
    if resp.ok:
        log.info("Private Reply enviada (comment_id=%s, versão A, postback): %s", comment_id, resp.text)
        return True
    log.error("Erro ao enviar Private Reply (comment_id=%s, formato=postback): %s", comment_id, resp.text)
    return False


def handle_messaging_event(entry: dict, event: dict):
    sender_id = event.get("sender", {}).get("id")
    message = event.get("message") or {}
    postback = event.get("postback") or {}

    if message.get("is_echo") or sender_id in {IG_USER_ID, entry.get("id")}:
        return

    quick_reply_payload = (message.get("quick_reply") or {}).get("payload")
    payload = quick_reply_payload or postback.get("payload")
    if payload != CLICK_PAYLOAD:
        return

    via = "quick_reply" if quick_reply_payload else "postback"
    mid = message.get("mid") or postback.get("mid") or f"{sender_id}:{event.get('timestamp')}"
    if already_processed(f"click:{mid}"):
        log.info("Clique %s já processado, ignorando", mid)
        return

    log.info("Clique recebido (via=%s, payload=%s)", via, payload)
    log.info("IGSID identificado: %s", sender_id)
    send_final_dm(sender_id)


def send_final_dm(igsid: str):
    text = random.choice(FINAL_DM_TEXTS).format(link=LINK_A)
    resp = _post_message({"recipient": {"id": igsid}, "message": {"text": text}})
    if resp.ok:
        log.info("Segunda DM enviada (igsid=%s): %s", igsid, resp.text)
    else:
        log.error("Erro ao enviar segunda DM (igsid=%s): %s", igsid, resp.text)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
