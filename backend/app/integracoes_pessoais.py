"""
Integrações PESSOAIS com Gmail e Slack (19/08/2026 - pedido do Maurício:
"liste todas as minhas pendências no e-mail e no Slack"; simplificado em
09/08/2026 - pedido do Maurício: "se for só pra mim, é mais simples?").

Modelo ATUAL (simplificado): credenciais fixas no SERVIDOR, iguais para
qualquer pessoa que consultar - mesmo padrão de app/ia_generativa.py (1
chave configurada pelo servidor, usada por quem aciona o recurso), não o
modelo "cada pessoa loga na própria conta" (OAuth por usuário) que existia
antes. Isso é deliberadamente mais simples de configurar (sem Google Cloud
Console, sem tela de consentimento OAuth, sem callback), mas em troca só
funciona pra UMA conta - a de quem configurou as credenciais.

Por isso o acesso a este recurso (ver routers/integracoes_pessoais_router.py)
é restrito a admin (`Depends(requer_papel("admin"))`) - sem essa restrição,
qualquer pessoa logada no Atlas veria a caixa de entrada/Slack PESSOAL de
quem configurou as credenciais, o que seria um problema de privacidade.
Isso é adequado pro caso de uso combinado com o Maurício (uso pessoal, ele é
quem administra o Atlas) - se um dia o Atlas precisar disso pra VÁRIAS
pessoas ao mesmo tempo, o modelo OAuth por usuário (mais trabalhoso de
configurar, mas com um usuário/instância) é o caminho certo, e o código
anterior a esta simplificação (com `Usuario.google_refresh_token` etc. em
models.py, hoje sem uso) pode servir de referência.

Configuração (variáveis de ambiente no servidor):

Gmail via IMAP (SEM precisar registrar nenhum app no Google Cloud Console):
- ATLAS_GMAIL_EMAIL - o endereço Gmail a consultar.
- ATLAS_GMAIL_APP_SENHA - uma "senha de app" do Google (NÃO é a senha normal
  da conta): Conta Google → Segurança → Verificação em duas etapas (precisa
  estar ATIVADA) → Senhas de app → gerar uma nova, com qualquer nome (ex:
  "Atlas"). É uma senha de 16 letras, só pra esse uso - pode ser revogada a
  qualquer momento sem afetar a senha normal da conta.
- Além disso, o IMAP precisa estar HABILITADO nas configurações do Gmail:
  Configurações (⚙) → "Ver todas as configurações" → aba "Encaminhamento e
  POP/IMAP" → "Ativar IMAP" → Salvar alterações.
- Acesso É SOMENTE LEITURA (só busca e-mails não lidos, nunca envia, marca
  como lido ou apaga nada).

Slack (ainda precisa de um Slack App, mas sem o vai-e-volta de OAuth por
usuário - só um token fixo, gerado uma vez):
- Criar em https://api.slack.com/apps → "Create New App" → "From scratch".
- Na página do app, "OAuth & Permissions" → em "User Token Scopes" (NÃO
  "Bot Token Scopes" - queremos ler COMO a pessoa, não como um bot),
  adicionar: im:read, mpim:read, search:read.
- No topo da mesma página, "Install to Workspace" (ou "Reinstall to
  Workspace" se já tiver instalado antes) → autorizar. Isso mostra um "User
  OAuth Token" (começa com xoxp-) - copiar esse valor.
- ATLAS_SLACK_USER_TOKEN - o token copiado acima.

Sem essas variáveis configuradas, os endpoints devolvem 503 com uma
mensagem clara (nunca 500) - o resto do Atlas continua funcionando
normalmente sem essa integração.

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
import email
import imaplib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from email.header import decode_header

TIMEOUT_PADRAO_SEGUNDOS = 12
LIMITE_EMAILS_NAO_LIDOS = 10
LIMITE_CONVERSAS_SLACK_VERIFICADAS = 20  # trava de segurança - não varre a conta inteira a cada consulta
LIMITE_MENCOES_SLACK = 10


class IntegracaoIndisponivel(Exception):
    """Credenciais não configuradas no servidor (variáveis de ambiente
    ausentes), ou o provedor (Gmail/Slack) recusou a operação (login IMAP
    inválido, token do Slack revogado etc.) - sempre com uma mensagem
    apresentável pro usuário."""


# ---------- Gmail (via IMAP + senha de app) ----------

def _config_gmail_imap() -> dict:
    return {
        "email": os.environ.get("ATLAS_GMAIL_EMAIL"),
        "senha_app": os.environ.get("ATLAS_GMAIL_APP_SENHA"),
    }


def gmail_configurado() -> bool:
    cfg = _config_gmail_imap()
    return bool(cfg["email"] and cfg["senha_app"])


def _decodificar_cabecalho(valor: str | None) -> str:
    """Cabeçalhos de e-mail (From/Subject) podem vir codificados
    (RFC 2047, ex: "=?UTF-8?B?...?=") quando têm acento/emoji - decodifica
    pra texto legível. Sem isso, assunto/remetente apareceriam com esse
    código bruto em vez do texto de verdade."""
    if not valor:
        return ""
    partes = decode_header(valor)
    saida = []
    for texto, codificacao in partes:
        if isinstance(texto, bytes):
            try:
                saida.append(texto.decode(codificacao or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                saida.append(texto.decode("utf-8", errors="replace"))
        else:
            saida.append(texto)
    return "".join(saida)


def listar_emails_nao_lidos_gmail(limite: int = LIMITE_EMAILS_NAO_LIDOS) -> dict:
    """Devolve {"total_nao_lidos": N, "itens": [{"remetente", "assunto"}]}.
    Usa IMAP (biblioteca padrão do Python, `imaplib` - nenhuma dependência
    nova) direto na caixa configurada via ATLAS_GMAIL_EMAIL/ATLAS_GMAIL_APP_SENHA.
    Só busca CABEÇALHOS (`BODY.PEEK[HEADER...]` - o `.PEEK` evita marcar a
    mensagem como lida só por tê-la consultado), nunca o corpo completo, e
    nunca marca/apaga nada."""
    if not gmail_configurado():
        raise IntegracaoIndisponivel(
            "Integração com Gmail não configurada neste ambiente: defina ATLAS_GMAIL_EMAIL "
            "e ATLAS_GMAIL_APP_SENHA no servidor do Atlas (ver instruções no topo de "
            "app/integracoes_pessoais.py)."
        )
    cfg = _config_gmail_imap()
    try:
        caixa = imaplib.IMAP4_SSL("imap.gmail.com", timeout=TIMEOUT_PADRAO_SEGUNDOS)
    except (OSError, TimeoutError) as erro:
        raise IntegracaoIndisponivel(f"Não consegui conectar ao Gmail agora: {erro}")

    try:
        try:
            caixa.login(cfg["email"], cfg["senha_app"])
        except imaplib.IMAP4.error as erro:
            raise IntegracaoIndisponivel(
                f"Gmail recusou o login por IMAP: {erro}. Confirme o e-mail e a senha de app "
                "(ATLAS_GMAIL_EMAIL/ATLAS_GMAIL_APP_SENHA), e que o IMAP está habilitado nas "
                "configurações do Gmail (Configurações → Encaminhamento e POP/IMAP → Ativar IMAP)."
            )

        status, _ = caixa.select("INBOX", readonly=True)
        if status != "OK":
            raise IntegracaoIndisponivel("Não consegui abrir a caixa de entrada (INBOX) por IMAP.")

        status, dados = caixa.search(None, "UNSEEN")
        if status != "OK":
            raise IntegracaoIndisponivel("Gmail (IMAP) recusou a busca por e-mails não lidos.")

        ids = dados[0].split()
        total = len(ids)
        itens = []
        for msg_id in reversed(ids[-limite:]):  # mais recentes primeiro
            try:
                status_f, msg_dados = caixa.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                if status_f != "OK" or not msg_dados or not msg_dados[0]:
                    continue
                msg = email.message_from_bytes(msg_dados[0][1])
                itens.append({
                    "remetente": _decodificar_cabecalho(msg.get("From")) or "Remetente desconhecido",
                    "assunto": _decodificar_cabecalho(msg.get("Subject")) or "(sem assunto)",
                })
            except Exception:
                continue
        return {"total_nao_lidos": total, "itens": itens}
    finally:
        try:
            caixa.logout()
        except Exception:
            pass


# ---------- Slack (token de usuário fixo) ----------

def _config_slack_token() -> str | None:
    return os.environ.get("ATLAS_SLACK_USER_TOKEN")


def slack_configurado() -> bool:
    return bool(_config_slack_token())


def _requisitar(url: str, dados: dict | None = None, metodo: str = "GET", headers: dict | None = None) -> dict:
    """Helper único pras chamadas HTTP deste módulo (urllib puro, mesmo
    padrão do resto do projeto - ver ia_generativa.py)."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Atlas-Magio-Chocolates/1.0 (+integracao-pessoal)")
    corpo = None
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


def _obter_identidade_slack(token: str) -> dict:
    """`auth.test` devolve de quem é o token (user_id/team_id) - evita
    precisar de mais variáveis de ambiente só pra isso; o token já basta."""
    try:
        resposta = _requisitar_bearer("https://slack.com/api/auth.test", token)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as erro:
        raise IntegracaoIndisponivel(f"Não consegui contactar o Slack agora: {erro}")
    if not resposta.get("ok"):
        raise IntegracaoIndisponivel(
            f"Slack recusou o token configurado (ATLAS_SLACK_USER_TOKEN): {resposta.get('error', 'erro desconhecido')}."
        )
    return {"user_id": resposta.get("user_id"), "team_id": resposta.get("team_id")}


def listar_pendencias_slack() -> dict:
    """Devolve {"mensagens_diretas_nao_lidas": [...], "mencoes_recentes": [...]}
    usando o token fixo configurado (ATLAS_SLACK_USER_TOKEN). As duas
    listas são calculadas de forma independente (uma falhar não derruba a
    outra) - mesmo padrão de resiliência usado no resto do Atlas (ver
    assistente_ia._seguro)."""
    if not slack_configurado():
        raise IntegracaoIndisponivel(
            "Integração com Slack não configurada neste ambiente: defina ATLAS_SLACK_USER_TOKEN "
            "no servidor do Atlas (ver instruções no topo de app/integracoes_pessoais.py)."
        )
    token = _config_slack_token()
    identidade = _obter_identidade_slack(token)
    team_id = identidade.get("team_id")
    user_id = identidade.get("user_id")

    resultado = {}

    try:
        conversas = _requisitar_bearer(
            "https://slack.com/api/conversations.list",
            token,
            dados={"types": "im,mpim", "limit": LIMITE_CONVERSAS_SLACK_VERIFICADAS, "exclude_archived": "true"},
        )
        if not conversas.get("ok"):
            raise RuntimeError(conversas.get("error", "erro desconhecido"))

        nao_lidas = []
        for canal in conversas.get("channels", [])[:LIMITE_CONVERSAS_SLACK_VERIFICADAS]:
            canal_id = canal["id"]
            try:
                info = _requisitar_bearer("https://slack.com/api/conversations.info", token, dados={"channel": canal_id})
                if not info.get("ok") or not info.get("channel", {}).get("unread_count", 0):
                    continue
                previa = _requisitar_bearer(
                    "https://slack.com/api/conversations.history", token, dados={"channel": canal_id, "limit": 1}
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
                token,
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
