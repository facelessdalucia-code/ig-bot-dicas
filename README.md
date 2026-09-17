# Bot @dicas_da_cilene — comentário → DM

Responde publicamente qualquer comentário em posts da conta e manda uma DM
com o link do teste/receita.

## Como funciona
- Instagram manda um webhook de "comments" pra `/webhook`.
- O bot responde o comentário publicamente ("Te mandei no direct! 📩").
- O bot manda a DM (private reply) usando o `comment_id` — só funciona
  dentro da janela de tempo que a Meta permite pra private reply
  (normalmente até 7 dias, mas o ideal é responder rápido).

## Configuração necessária no Meta (do zero)

1. **Conta Instagram profissional (Business/Creator)** vinculada a uma
   Página do Facebook. Sem isso a Graph API não funciona.
2. Criar um app em https://developers.facebook.com/apps
   - Tipo: "Business"
   - Adicionar o produto "Instagram Graph API" (ou "Instagram" conforme a
     versão atual do painel).
3. Conectar a conta do Instagram (@dicas_da_cilene) e a Página do Facebook
   ao app.
4. Gerar um **Page Access Token** de longa duração com as permissões:
   - `instagram_basic`
   - `instagram_manage_comments`
   - `instagram_manage_messages`
   - `pages_show_list` / `pages_read_engagement` (dependendo da versão)
5. Configurar o **Webhook** do produto Instagram:
   - URL: `https://<seu-dominio-no-render>/webhook`
   - Verify token: qualquer string que você definir (vai em `VERIFY_TOKEN`)
   - Campo a assinar: `comments`
6. Se a conta/app ainda estiver em modo de desenvolvimento, só usuários
   testadores conseguem interagir. Pra funcionar com o público em geral,
   o app precisa passar pela **revisão do Meta (App Review)** solicitando
   as permissões acima — processo parecido com o que já foi feito pro
   bot do @o.nutricius.

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `VERIFY_TOKEN` | String que você escolhe, usada na verificação do webhook |
| `PAGE_ACCESS_TOKEN` | Token gerado no passo 4 |
| `IG_USER_ID` | ID numérico da conta do Instagram (@dicas_da_cilene) |

## Deploy

Pensado pra rodar no Render (mesmo padrão do bot do @o.nutricius):
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Configurar as 3 variáveis de ambiente acima no painel do Render.

## Rodando local pra testar

```
pip install -r requirements.txt
set VERIFY_TOKEN=teste123
set PAGE_ACCESS_TOKEN=xxx
set IG_USER_ID=xxx
python app.py
```
