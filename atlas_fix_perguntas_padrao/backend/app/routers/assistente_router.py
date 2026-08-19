"""
Assistente Atlas por voz/texto (25/08/2026 - ver app/assistente_ia.py).
Endpoint único, chamado tanto pelo comando de voz contínuo do hub (quando
"Atlas, [algo]" não bate com nenhum módulo conhecido - ver
configurarComandoDeVoz() em app.js) quanto por uma pergunta digitada no
próprio painel do assistente na tela Início."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, assistente_ia, assistente_perguntas_padrao, ia_generativa
from ..database import get_db
from ..deps import obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/assistente", tags=["assistente"])


class PerguntaAssistente(BaseModel):
    pergunta: str


@router.get("/perguntas-padrao")
def perguntas_padrao(usuario: models.Usuario = Depends(obter_usuario_atual)):
    """Catálogo de perguntas padrão (ver app/assistente_perguntas_padrao.py) -
    usado pelo frontend pra montar os botões de pergunta rápida na tela
    Início (carregarPerguntasPadraoAssistente() em app.js). Lê direto do
    mesmo catálogo usado no roteamento abaixo - fonte única, sem duplicar a
    lista entre backend e frontend."""
    return assistente_perguntas_padrao.listar_perguntas_padrao()


@router.post("/perguntar")
def perguntar(
    corpo: PerguntaAssistente,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Monta o retrato atual do Atlas (montar_contexto) e manda pra IA
    generativa junto com a pergunta. Devolve 503 (nunca 500) se a IA não
    estiver configurada ou a chamada falhar - mesmo tratamento de erro já
    usado no resto da integração de IA generativa (ver
    app/ia_generativa.py).

    Pré-validação (19/08/2026): antes de montar o retrato, compara a
    pergunta contra o catálogo de perguntas padrão (ver
    app/assistente_perguntas_padrao.py) - sem gastar outra chamada de IA
    generativa pra classificar a pergunta. Quando bate com uma pergunta
    conhecida, isso dá um detalhamento extra de dados (quando a entrada tem
    contexto_extra_fn) e uma instrução mais precisa de onde focar a
    resposta, resultando numa resposta mais embasada pras perguntas mais
    comuns."""
    pergunta = (corpo.pergunta or "").strip()
    if not pergunta:
        raise HTTPException(400, "Pergunta vazia.")

    pergunta_padrao = assistente_perguntas_padrao.identificar_pergunta_padrao(pergunta)

    contexto = assistente_ia.montar_contexto(db, usuario, pergunta_padrao=pergunta_padrao)
    try:
        resposta = assistente_ia.responder_pergunta_assistente(pergunta, contexto, pergunta_padrao=pergunta_padrao)
    except ia_generativa.IAGenerativaIndisponivel as erro:
        raise HTTPException(503, str(erro))

    registrar_log(
        db, usuario.username, "assistente_pergunta",
        detalhes={"pergunta": pergunta, "pergunta_padrao": pergunta_padrao["chave"] if pergunta_padrao else None},
    )
    db.commit()
    return {"pergunta": pergunta, "resposta": resposta}
