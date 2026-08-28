"""
Endpoints das integrações PESSOAIS de Gmail/Slack (19/08/2026, simplificado
em 09/08/2026 - ver app/integracoes_pessoais.py pra entender o modelo atual
de configuração e por que ele mudou de "OAuth por usuário" pra "credenciais
fixas no servidor").

IMPORTANTE (dois pontos de segurança):
1. Prefixo "/integracoes-pessoais", DIFERENTE de "/integracoes"
   (routers/integracoes_router.py) - aquele é pra sistemas externos
   empurrarem dados via webhook com chave fixa
   (deps.verificar_chave_integracao); este aqui é login de PESSOA, via
   Bearer token normal - nunca devem compartilhar o mesmo router/prefixo.
2. Restrito a ADMIN (`Depends(requer_papel("admin"))`). Como as credenciais
   configuradas (ver integracoes_pessoais.py) são de UMA conta pessoal (não
   por usuário do Atlas), sem essa restrição qualquer pessoa logada no
   Atlas conseguiria ver a caixa de entrada/Slack pessoal de quem
   configurou as credenciais - isso é aceitável pro caso de uso combinado
   (Maurício administra o Atlas e é o dono das credenciais), mas seria um
   problema de privacidade se deixado aberto pra qualquer papel."""
from fastapi import APIRouter, Depends

from .. import models, integracoes_pessoais
from ..deps import requer_papel

router = APIRouter(prefix="/integracoes-pessoais", tags=["integracoes_pessoais"])


@router.get("/status")
def status_integracoes(usuario: models.Usuario = Depends(requer_papel("admin"))):
    """Usado pelo frontend pra decidir o que mostrar no painel de
    pendências: texto de "não configurado" (faltam as variáveis de
    ambiente) ou "configurado" (pronto pra consultar) - não existe mais um
    estado "conectado/desconectado" por usuário, já que as credenciais são
    fixas no servidor."""
    return {
        "gmail": {"configurado": integracoes_pessoais.gmail_configurado()},
        "slack": {"configurado": integracoes_pessoais.slack_configurado()},
    }


@router.get("/pendencias")
def pendencias(usuario: models.Usuario = Depends(requer_papel("admin"))):
    """Endpoint principal acionado pelo gatilho de voz "Atlas, Mensagens"
    (ou pelo botão equivalente, ver app.js) - junta Gmail (e-mails não lidos da
    caixa de entrada) e Slack (DMs não lidas + menções recentes) da conta
    configurada no servidor. Cada serviço é isolado: se um falhar (IMAP
    fora do ar, token do Slack revogado), o outro continua aparecendo
    normalmente - nunca derruba a resposta inteira."""
    resultado = {
        "gmail": {"configurado": integracoes_pessoais.gmail_configurado(), "total_nao_lidos": 0, "itens": []},
        "slack": {"configurado": integracoes_pessoais.slack_configurado(), "mensagens_diretas_nao_lidas": [], "mencoes_recentes": []},
    }

    if resultado["gmail"]["configurado"]:
        try:
            gmail = integracoes_pessoais.listar_emails_nao_lidos_gmail()
            resultado["gmail"]["total_nao_lidos"] = gmail.get("total_nao_lidos", 0)
            resultado["gmail"]["itens"] = gmail.get("itens", [])
        except integracoes_pessoais.IntegracaoIndisponivel as e:
            resultado["gmail"]["indisponivel"] = str(e)
        except Exception as e:
            resultado["gmail"]["indisponivel"] = f"{e.__class__.__name__}: não consegui buscar os e-mails agora"

    if resultado["slack"]["configurado"]:
        try:
            slack = integracoes_pessoais.listar_pendencias_slack()
            resultado["slack"]["mensagens_diretas_nao_lidas"] = slack.get("mensagens_diretas_nao_lidas", [])
            resultado["slack"]["mencoes_recentes"] = slack.get("mencoes_recentes", [])
        except integracoes_pessoais.IntegracaoIndisponivel as e:
            resultado["slack"]["indisponivel"] = str(e)
        except Exception as e:
            resultado["slack"]["indisponivel"] = f"{e.__class__.__name__}: não consegui buscar as pendências do Slack agora"

    return resultado
