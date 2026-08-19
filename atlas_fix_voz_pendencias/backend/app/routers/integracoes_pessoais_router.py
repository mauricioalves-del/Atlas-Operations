"""
Endpoints das integrações PESSOAIS de Gmail/Slack (19/08/2026 - ver
app/integracoes_pessoais.py pra entender o fluxo OAuth completo e como
configurar as credenciais no servidor).

IMPORTANTE: prefixo "/integracoes-pessoais", DIFERENTE de
"/integracoes" (routers/integracoes_router.py) - aquele é pra sistemas
externos empurrarem dados via webhook com chave fixa
(deps.verificar_chave_integracao); este aqui é login de PESSOA, via
Bearer token normal (deps.obter_usuario_atual) - nunca devem compartilhar
o mesmo router/prefixo, senão a dependência de chave fixa daquele
acabaria exigida aqui também (ou vice-versa)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import models, integracoes_pessoais
from ..database import get_db
from ..deps import obter_usuario_atual
from ..auth import criar_token, decodificar_token, TokenInvalido

router = APIRouter(prefix="/integracoes-pessoais", tags=["integracoes_pessoais"])

VALIDADE_STATE_HORAS = 0.25  # 15 min - tempo de sobra pra pessoa logar no Google/Slack


def _gerar_state(usuario: models.Usuario) -> str:
    """Reaproveita o mesmo mecanismo de token assinado da sessão (ver
    auth.criar_token) só que de validade bem curta - o callback do OAuth
    não recebe o header Authorization normal (é um redirect de navegador,
    não um fetch nosso), então é o parâmetro `state` que diz pro callback
    QUAL usuário do Atlas estava conectando."""
    return criar_token(usuario.username, usuario.papel, validade_horas=VALIDADE_STATE_HORAS)


def _usuario_do_state(state: str, db: Session) -> models.Usuario:
    try:
        payload = decodificar_token(state)
    except TokenInvalido as e:
        raise HTTPException(400, f"Link de conexão inválido ou expirado ({e}) - tente conectar de novo pelo Atlas.")
    usuario = db.query(models.Usuario).filter_by(username=payload["sub"]).first()
    if not usuario:
        raise HTTPException(400, "Usuário do Atlas não encontrado pra esta conexão.")
    return usuario


def _pagina_confirmacao(titulo: str, mensagem: str) -> HTMLResponse:
    """Página simples mostrada depois do redirect do Google/Slack (a
    pessoa não deveria continuar navegando ali - só fechar a aba e voltar
    pro Atlas, que já está aberto na outra aba)."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Atlas - {titulo}</title>
<style>body{{font-family:system-ui,sans-serif;background:#0e1420;color:#eef2f6;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:24px}}
.caixa{{max-width:420px}} h1{{font-size:20px}} p{{color:#9fb0c3}}</style></head>
<body><div class="caixa"><h1>{titulo}</h1><p>{mensagem}</p><p>Pode fechar esta aba e voltar ao Atlas.</p></div></body></html>""")


@router.get("/status")
def status_integracoes(usuario: models.Usuario = Depends(obter_usuario_atual)):
    """Usado pelo frontend pra decidir o que mostrar: botão "Conectar" ou
    o estado já conectado + se deve ativar o detector de "duas palmas"
    (só ativa escuta de palmas se tiver pelo menos 1 integração
    conectada)."""
    return {
        "gmail": {
            "disponivel_no_servidor": integracoes_pessoais.google_configurado(),
            "conectado": bool(usuario.google_refresh_token),
            "email": usuario.google_conectado_email,
        },
        "slack": {
            "disponivel_no_servidor": integracoes_pessoais.slack_configurado(),
            "conectado": bool(usuario.slack_user_token),
        },
    }


@router.get("/google/conectar")
def conectar_google(usuario: models.Usuario = Depends(obter_usuario_atual)):
    try:
        url = integracoes_pessoais.gerar_url_autorizacao_google(_gerar_state(usuario))
    except integracoes_pessoais.IntegracaoIndisponivel as erro:
        raise HTTPException(503, str(erro))
    return {"url": url}


@router.get("/google/callback")
def callback_google(code: str | None = Query(None), state: str | None = Query(None), erro: str | None = Query(None, alias="error"), db: Session = Depends(get_db)):
    if erro:
        return _pagina_confirmacao("Conexão com Gmail cancelada", f"O Google devolveu: {erro}.")
    if not code or not state:
        return _pagina_confirmacao("Link inválido", "Faltam parâmetros na resposta do Google.")

    usuario = _usuario_do_state(state, db)
    try:
        conexao = integracoes_pessoais.trocar_code_por_conexao_google(code)
    except integracoes_pessoais.IntegracaoIndisponivel as e:
        return _pagina_confirmacao("Não consegui conectar ao Gmail", str(e))

    usuario.google_refresh_token = conexao["refresh_token"]
    usuario.google_conectado_email = conexao.get("email")
    db.commit()
    return _pagina_confirmacao("Gmail conectado!", f"Conta {conexao.get('email') or ''} conectada ao Atlas com sucesso.")


@router.get("/slack/conectar")
def conectar_slack(usuario: models.Usuario = Depends(obter_usuario_atual)):
    try:
        url = integracoes_pessoais.gerar_url_autorizacao_slack(_gerar_state(usuario))
    except integracoes_pessoais.IntegracaoIndisponivel as erro:
        raise HTTPException(503, str(erro))
    return {"url": url}


@router.get("/slack/callback")
def callback_slack(code: str | None = Query(None), state: str | None = Query(None), erro: str | None = Query(None, alias="error"), db: Session = Depends(get_db)):
    if erro:
        return _pagina_confirmacao("Conexão com Slack cancelada", f"O Slack devolveu: {erro}.")
    if not code or not state:
        return _pagina_confirmacao("Link inválido", "Faltam parâmetros na resposta do Slack.")

    usuario = _usuario_do_state(state, db)
    try:
        conexao = integracoes_pessoais.trocar_code_por_conexao_slack(code)
    except integracoes_pessoais.IntegracaoIndisponivel as e:
        return _pagina_confirmacao("Não consegui conectar ao Slack", str(e))

    usuario.slack_user_token = conexao["access_token"]
    usuario.slack_conectado_user_id = conexao.get("user_id")
    usuario.slack_conectado_team_id = conexao.get("team_id")
    db.commit()
    return _pagina_confirmacao("Slack conectado!", "Sua conta do Slack foi conectada ao Atlas com sucesso.")


@router.post("/desconectar")
def desconectar(servico: str, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    if servico == "google":
        usuario.google_refresh_token = None
        usuario.google_conectado_email = None
    elif servico == "slack":
        usuario.slack_user_token = None
        usuario.slack_conectado_user_id = None
        usuario.slack_conectado_team_id = None
    else:
        raise HTTPException(400, "servico deve ser 'google' ou 'slack'.")
    db.commit()
    return {"status": "desconectado", "servico": servico}


@router.get("/pendencias")
def pendencias(usuario: models.Usuario = Depends(obter_usuario_atual)):
    """Endpoint principal acionado pelo gatilho de "duas palmas" (ou pelo
    botão equivalente, ver app.js) - junta Gmail (e-mails não lidos da
    caixa de entrada) e Slack (DMs não lidas + menções recentes) da conta
    PESSOAL conectada de quem está logado. Cada serviço é isolado: se um
    falhar (token expirado, provedor fora do ar), o outro continua
    aparecendo normalmente - nunca derruba a resposta inteira."""
    resultado = {
        "gmail": {"conectado": bool(usuario.google_refresh_token), "email": usuario.google_conectado_email, "nao_lidos": []},
        "slack": {"conectado": bool(usuario.slack_user_token), "mensagens_diretas_nao_lidas": [], "mencoes_recentes": []},
    }

    if usuario.google_refresh_token:
        try:
            resultado["gmail"]["nao_lidos"] = integracoes_pessoais.listar_emails_nao_lidos_google(usuario.google_refresh_token)
        except integracoes_pessoais.IntegracaoIndisponivel as e:
            resultado["gmail"]["indisponivel"] = str(e)
        except Exception as e:
            resultado["gmail"]["indisponivel"] = f"{e.__class__.__name__}: não consegui buscar os e-mails agora"

    if usuario.slack_user_token:
        try:
            slack = integracoes_pessoais.listar_pendencias_slack(
                usuario.slack_user_token, team_id=usuario.slack_conectado_team_id, user_id=usuario.slack_conectado_user_id
            )
            resultado["slack"]["mensagens_diretas_nao_lidas"] = slack.get("mensagens_diretas_nao_lidas", [])
            resultado["slack"]["mencoes_recentes"] = slack.get("mencoes_recentes", [])
        except Exception as e:
            resultado["slack"]["indisponivel"] = f"{e.__class__.__name__}: não consegui buscar as pendências do Slack agora"

    return resultado
