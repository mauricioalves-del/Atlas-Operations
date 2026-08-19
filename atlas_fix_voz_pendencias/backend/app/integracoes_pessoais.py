"""
Integrações PESSOAIS com Gmail e Slack (19/08/2026 - pedido do Maurício):
"liste todas as minhas pendências no e-mail e no Slack". Cada usuário do
Atlas conecta a PRÓPRIA conta (OAuth) - diferente das outras integrações
externas do projeto:

- app/ia_generativa.py: 1 chave só, configurada pelo servidor, usada por
  todo mundo que aciona o recurso.
- app/routers/integracoes_router.py: sistema externo (Lovable/Supabase)
  empurrando dados PRO Atlas via webhook com chave fixa.
- ESTA aqui: cada pessoa loga na própria conta Google/Slack, e só vê as
  PRÓPRIAS pendências - por isso os tokens ficam por usuário (ver
  Usuario.google_refresh_token/slack_user_token em models.py), não numa
  variável de ambiente única.

Como funciona o fluxo OAuth (igual pros dois provedores):
1. Frontend chama GET /integracoes-pessoais/{google,slack}/conectar (com
   Bearer token normal) - devolve a URL de autorização do provedor.
2. Frontend abre essa URL numa aba nova - a pessoa loga e autoriza no
   próprio Google/Slack.
3. O provedor redireciona o navegador pra
   GET /integracoes-pessoais/{google,slack}/callback?code=...&state=...
   - essa chamada NÃO tem o header Authorization (é um redirect de
   navegador, não um fetch nosso) - por isso quem identifica QUAL usuário
   do Atlas estava conectando é o parâmetro `state`: um token assinado
   (reaproveita auth.criar_token/decodificar_token, o mesmo mecanismo de
   sessão que já existe, só que de validade bem curta - 15 min) contendo o
   username. O callback decodifica esse state pra saber em qual Usuario
   gravar o resultado.
4. O callback troca o `code` pelos tokens de acesso e grava no Usuario
   (refresh_token do Google - de longa duração; access token do Slack -
   também de longa duração no fluxo padrão, sem necessidade de refresh).

Configuração (variáveis de ambiente no servidor, mesmo padrão ATLAS_* do
resto do projeto - análogo ao processo já usado pra
ATLAS_IA_GENERATIVA_API_KEY, só que aqui são credenciais de OAuth, não uma
chave simples):

Google (criar em https://console.cloud.google.com/apis/credentials -
"OAuth client ID", tipo "Web application"):
- ATLAS_GOOGLE_CLIENT_ID
- ATLAS_GOOGLE_CLIENT_SECRET
- ATLAS_GOOGLE_REDIRECT_URI - precisa ser EXATAMENTE a URL pública do Atlas
  + "/api/integracoes-pessoais/google/callback" (ex:
  https://seu-atlas.onrender.com/api/integracoes-pessoais/google/callback),
  e essa mesma URL precisa estar cadastrada em "Authorized redirect URIs"
  no Google Cloud Console.
  Escopo pedido: gmail.readonly (só LEITURA - o Atlas nunca envia nem
  apaga e-mail) + userinfo.email (só pra mostrar qual conta está
  conectada).
  Como o app provavelmente vai ficar em modo "Testing" na tela de
  consentimento OAuth (sem passar pela verificação do Google, que não é
  necessária pra uso interno da empresa), é preciso adicionar cada
  e-mail que for conectar como "Test user" no Google Cloud Console -
  senão o Google recusa o login com "app não verificado".

Slack (criar em https://api.slack.com/apps - "Create New App" → "From
scratch"):
- ATLAS_SLACK_CLIENT_ID
- ATLAS_SLACK_CLIENT_SECRET
- ATLAS_SLACK_REDIRECT_URI - análogo ao do Google, cadastrado em "OAuth &
  Permissions" → "Redirect URLs" no app do Slack.
  Escopos de USUÁRIO (User Token Scopes, não Bot Token Scopes - queremos
  ler COMO a pessoa, não como um bot): im:read, mpim:read, search:read.

Sem essas variáveis configuradas, os endpoints de conectar devolvem 503
com uma mensagem clara (nunca 500) - o resto do Atlas continua
funcionando normalmente sem essa integração.

Sobre "pendências": Gmail = e-mails não lidos da caixa de entrada (padrão
mais direto e sem ambiguidade). Slack é mais limitado pela própria API
pública: DMs e grupos de DM (mpim) com mensagem não lida têm um contador
confiável (`unread_count` via conversations.info); MENÇÕES não têm um
endpoint de "não lidas" de verdade pra apps de terceiros - o que existe
aqui é uma busca das menções mais RECENTES (search.messages), não
necessariamente só as não lidas. Isso está deixado explícito no rótulo
que a API devolve ("menções recentes", não "menções não lidas"), pra não
prometer uma precisão que a API do Slack não permite entregar.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_PADRAO_SEGUNDOS = 12
LIMITE_EMAILS_NAO_LIDOS = 10
LIMITE_CONVERSAS_SLACK_VERIFICADAS = 20  # trava de segurança - não varre a conta inteira a cada consulta
LIMITE_MENCOES_SLACK = 10


class IntegracaoIndisponivel(Exception):
    """Credenciais de OAuth não configuradas no servidor (variáveis de
    ambiente ausentes) - diferente de "usuário ainda não conectou a
    própria conta", que não é um erro, é só um estado normal (ver
    status_integracoes)."""


# ---------- configuração ----------

def _config_google() -> dict:
    return {
        "client_id": os.environ.get("ATLAS_GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("ATLAS_GOOGLE_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("ATLAS_GOOGLE_REDIRECT_URI"),
    }


def _config_slack() -> dict:
    return {
        "client_id": os.environ.get("ATLAS_SLACK_CLIENT_ID"),
        "client_secret": os.environ.get("ATLAS_SLACK_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("ATLAS_SLACK_REDIRECT_URI"),
    }


def google_configurado() -> bool:
    cfg = _config_google()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def slack_configurado() -> bool:
    cfg = _config_slack()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def _requisitar(url: str, dados: dict | None = None, metodo: str = "GET", headers: dict | None = None) -> dict:
    """Helper único pras chamadas HTTP deste módulo (urllib puro, mesmo
    padrão do resto do projeto - ver ia_generativa.py). `dados` vira
    querystring no GET e corpo url-encoded no POST (os 3 provedores usados
    aqui - Google token endpoint, Slack oauth.v2.access, Slack Web API -
    aceitam application/x-www-form-urlencoded)."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Atlas-Magio-Chocolates/1.0 (+integracao-pessoal)")
    corpo = None
    # doseq=True permite passar um valor de lista pra repetir a mesma chave
    # na querystring (ex: metadataHeaders=From&metadataHeaders=Subject, do
    # jeito que o Gmail espera pra pedir mais de um cabeçalho) - sem isso,
    # urlencode transformaria a lista Python inteira numa string só.
    if metodo == "GET" and dados:
        url = f"{url}?{urllib.parse.urlencode(dados, doseq=True)}"
    elif dados:
        corpo = urllib.parse.urlencode(dados, doseq=True).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    requisicao = urllib.request.Request(url, data=corpo, method=metodo, headers=headers)
    with urllib.request.urlopen(requisicao, timeout=TIMEOUT_PADRAO_SEGUNDOS) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def _requisitar_bearer(url: str, token: str, dados: dict | None = None) -> dict:
    return _requisitar(url, dados=dados, metodo="GET", headers={"Authorization": f"Bearer {token}"})


# ---------- Google / Gmail ----------

ESCOPO_GOOGLE = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"


def gerar_url_autorizacao_google(state: str) -> str:
    if not google_configurado():
        raise IntegracaoIndisponivel(
            "Integração com Gmail não configurada neste ambiente: defina "
            "ATLAS_GOOGLE_CLIENT_ID, ATLAS_GOOGLE_CLIENT_SECRET e "
            "ATLAS_GOOGLE_REDIRECT_URI no servidor do Atlas (ver instruções no "
            "topo de app/integracoes_pessoais.py)."
        )
    cfg = _config_google()
    parametros = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": ESCOPO_GOOGLE,
        "access_type": "offline",  # obrigatório pra receber refresh_token
        "prompt": "consent",  # força devolver refresh_token mesmo numa reconexão
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(parametros)}"


def trocar_code_por_conexao_google(code: str) -> dict:
    """Troca o `code` do redirect pelo refresh_token + descobre o e-mail
    conectado. Levanta IntegracaoIndisponivel (com mensagem apresentável)
    se a troca falhar - código expirado/já usado, credenciais erradas
    etc."""
    cfg = _config_google()
    try:
        tokens = _requisitar(
            "https://oauth2.googleapis.com/token",
            metodo="POST",
            dados={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": cfg["redirect_uri"],
                "grant_type": "authorization_code",
            },
        )
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="ignore")
        raise IntegracaoIndisponivel(f"Google recusou a conexão (HTTP {erro.code}): {detalhe[:300]}")
    except (urllib.error.URLError, TimeoutError) as erro:
        raise IntegracaoIndisponivel(f"Não consegui contactar o Google agora: {erro}")

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token:
        # Acontece se a pessoa já tinha autorizado antes e o Google não achou
        # necessário emitir um refresh_token novo - com access_type=offline +
        # prompt=consent isso não deveria ocorrer, mas fica um erro claro
        # em vez de silenciosamente "funcionar por 1 hora e parar".
        raise IntegracaoIndisponivel(
            "O Google não devolveu um refresh_token nesta conexão - tente desconectar "
            "e conectar de novo (ou revogar o acesso do Atlas em "
            "https://myaccount.google.com/permissions e reconectar)."
        )

    try:
        userinfo = _requisitar_bearer("https://www.googleapis.com/oauth2/v2/userinfo", access_token)
        email = userinfo.get("email")
    except Exception:
        email = None

    return {"refresh_token": refresh_token, "email": email}


def _renovar_access_token_google(refresh_token: str) -> str:
    cfg = _config_google()
    try:
        tokens = _requisitar(
            "https://oauth2.googleapis.com/token",
            metodo="POST",
            dados={
                "refresh_token": refresh_token,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "grant_type": "refresh_token",
            },
        )
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="ignore")
        raise IntegracaoIndisponivel(
            f"Não consegui renovar o acesso ao Gmail (HTTP {erro.code}) - pode ser que o "
            f"acesso tenha sido revogado; desconecte e conecte de novo. Detalhe: {detalhe[:200]}"
        )
    except (urllib.error.URLError, TimeoutError) as erro:
        raise IntegracaoIndisponivel(f"Não consegui contactar o Google agora: {erro}")
    access_token = tokens.get("access_token")
    if not access_token:
        raise IntegracaoIndisponivel("Google não devolveu um access_token válido ao renovar.")
    return access_token


def listar_emails_nao_lidos_google(refresh_token: str, limite: int = LIMITE_EMAILS_NAO_LIDOS) -> list:
    """Lista os e-mails não lidos da caixa de entrada (mais recentes
    primeiro, como o Gmail já devolve por padrão). Uma chamada de LISTA +
    1 chamada de METADADOS por e-mail (assunto/remetente/trecho) - o
    `format=metadata` evita baixar o corpo inteiro da mensagem, só o
    cabeçalho e o snippet."""
    access_token = _renovar_access_token_google(refresh_token)
    lista = _requisitar_bearer(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        access_token,
        dados={"q": "is:unread in:inbox", "maxResults": limite},
    )
    mensagens = lista.get("messages", [])

    itens = []
    for m in mensagens:
        try:
            detalhe = _requisitar_bearer(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                access_token,
                dados={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            )
        except Exception:
            continue
        cabecalhos = {h["name"]: h["value"] for h in detalhe.get("payload", {}).get("headers", [])}
        itens.append({
            "id": m["id"],
            "remetente": cabecalhos.get("From", "Remetente desconhecido"),
            "assunto": cabecalhos.get("Subject") or detalhe.get("snippet", "(sem assunto)")[:80],
            "resumo": detalhe.get("snippet", ""),
            "link": f"https://mail.google.com/mail/u/0/#inbox/{m['id']}",
        })
    return itens


# ---------- Slack ----------

ESCOPO_USUARIO_SLACK = "im:read,mpim:read,search:read"


def gerar_url_autorizacao_slack(state: str) -> str:
    if not slack_configurado():
        raise IntegracaoIndisponivel(
            "Integração com Slack não configurada neste ambiente: defina "
            "ATLAS_SLACK_CLIENT_ID, ATLAS_SLACK_CLIENT_SECRET e "
            "ATLAS_SLACK_REDIRECT_URI no servidor do Atlas (ver instruções no "
            "topo de app/integracoes_pessoais.py)."
        )
    cfg = _config_slack()
    parametros = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "user_scope": ESCOPO_USUARIO_SLACK,
        "state": state,
    }
    return f"https://slack.com/oauth/v2/authorize?{urllib.parse.urlencode(parametros)}"


def trocar_code_por_conexao_slack(code: str) -> dict:
    cfg = _config_slack()
    try:
        resposta = _requisitar(
            "https://slack.com/api/oauth.v2.access",
            metodo="POST",
            dados={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": cfg["redirect_uri"],
            },
        )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as erro:
        raise IntegracaoIndisponivel(f"Não consegui contactar o Slack agora: {erro}")

    if not resposta.get("ok"):
        raise IntegracaoIndisponivel(f"Slack recusou a conexão: {resposta.get('error', 'erro desconhecido')}")

    authed_user = resposta.get("authed_user", {})
    access_token = authed_user.get("access_token")
    if not access_token:
        raise IntegracaoIndisponivel(
            "O Slack não devolveu um token de usuário nesta conexão - confirme que o app do "
            "Slack está configurado com User Token Scopes (im:read, mpim:read, search:read), "
            "não só Bot Token Scopes."
        )
    return {
        "access_token": access_token,
        "user_id": authed_user.get("id"),
        "team_id": (resposta.get("team") or {}).get("id"),
    }


def listar_pendencias_slack(user_token: str, team_id: str | None = None, user_id: str | None = None) -> dict:
    """Devolve {"mensagens_diretas_nao_lidas": [...], "mencoes_recentes": [...]}.
    As duas listas são calculadas de forma independente (uma falhar não
    derruba a outra) - mesmo padrão de resiliência usado no resto do
    Atlas (ver assistente_ia._seguro)."""
    resultado = {}

    try:
        conversas = _requisitar_bearer(
            "https://slack.com/api/conversations.list",
            user_token,
            dados={"types": "im,mpim", "limit": LIMITE_CONVERSAS_SLACK_VERIFICADAS, "exclude_archived": "true"},
        )
        if not conversas.get("ok"):
            raise RuntimeError(conversas.get("error", "erro desconhecido"))

        nao_lidas = []
        for canal in conversas.get("channels", [])[:LIMITE_CONVERSAS_SLACK_VERIFICADAS]:
            canal_id = canal["id"]
            try:
                info = _requisitar_bearer("https://slack.com/api/conversations.info", user_token, dados={"channel": canal_id})
                if not info.get("ok") or not info.get("channel", {}).get("unread_count", 0):
                    continue
                previa = _requisitar_bearer(
                    "https://slack.com/api/conversations.history", user_token, dados={"channel": canal_id, "limit": 1}
                )
                texto_previa = ""
                if previa.get("ok") and previa.get("messages"):
                    texto_previa = previa["messages"][0].get("text", "")
                nao_lidas.append({
                    "canal_id": canal_id,
                    "nao_lidas": info["channel"]["unread_count"],
                    "previa": texto_previa[:200],
                    "link": f"https://slack.com/app_redirect?channel={canal_id}" + (f"&team={team_id}" if team_id else ""),
                })
            except Exception:
                continue
        resultado["mensagens_diretas_nao_lidas"] = nao_lidas
    except Exception as erro:
        resultado["mensagens_diretas_nao_lidas"] = {"indisponivel": str(erro)[:200]}

    try:
        mencoes = []
        if user_id:
            busca = _requisitar_bearer(
                "https://slack.com/api/search.messages",
                user_token,
                dados={"query": f"<@{user_id}>", "sort": "timestamp", "sort_dir": "desc", "count": LIMITE_MENCOES_SLACK},
            )
            if not busca.get("ok"):
                raise RuntimeError(busca.get("error", "erro desconhecido"))
            for m in busca.get("messages", {}).get("matches", [])[:LIMITE_MENCOES_SLACK]:
                canal_id = (m.get("channel") or {}).get("id")
                mencoes.append({
                    "canal": (m.get("channel") or {}).get("name", "canal desconhecido"),
                    "texto": (m.get("text") or "")[:200],
                    "link": m.get("permalink") or (f"https://slack.com/app_redirect?channel={canal_id}" if canal_id else None),
                })
        resultado["mencoes_recentes"] = mencoes
    except Exception as erro:
        resultado["mencoes_recentes"] = {"indisponivel": str(erro)[:200]}

    return resultado
