"""
Assistente Atlas por voz/texto (25/08/2026 - ver app/assistente_ia.py).
Endpoint único, chamado tanto pelo comando de voz contínuo do hub (quando
"Atlas, [algo]" não bate com nenhum módulo conhecido - ver
configurarComandoDeVoz() em app.js) quanto por uma pergunta digitada no
próprio painel do assistente na tela Início."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, assistente_ia, ia_generativa
from ..database import get_db
from ..deps import obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/assistente", tags=["assistente"])


class PerguntaAssistente(BaseModel):
    pergunta: str


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
    app/ia_generativa.py)."""
    pergunta = (corpo.pergunta or "").strip()
    if not pergunta:
        raise HTTPException(400, "Pergunta vazia.")

    contexto = assistente_ia.montar_contexto(db, usuario)
    try:
        resposta = assistente_ia.responder_pergunta_assistente(pergunta, contexto)
    except ia_generativa.IAGenerativaIndisponivel as erro:
        raise HTTPException(503, str(erro))

    registrar_log(db, usuario.username, "assistente_pergunta", detalhes={"pergunta": pergunta})
    db.commit()
    return {"pergunta": pergunta, "resposta": resposta}
