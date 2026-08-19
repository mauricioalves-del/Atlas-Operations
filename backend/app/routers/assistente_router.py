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
from ..deps import obter_usuario_atual, requer_papel
from ..audit import registrar_log

router = APIRouter(prefix="/assistente", tags=["assistente"])


class PerguntaAssistente(BaseModel):
    pergunta: str


class PerguntaPadraoPersonalizadaCorpo(BaseModel):
    rotulo: str
    pergunta: str
    gatilhos: list[str]
    instrucao_extra: str | None = None


@router.get("/perguntas-padrao")
def perguntas_padrao(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Catálogo de perguntas padrão (ver app/assistente_perguntas_padrao.py) -
    usado pelo frontend pra montar os botões de pergunta rápida na tela
    Início (carregarPerguntasPadraoAssistente() em app.js). Junta o
    catálogo fixo do código com as perguntas personalizadas criadas por
    admins (ver POST/PUT/DELETE abaixo) - fonte única, sem duplicar a
    lista entre backend e frontend."""
    return assistente_perguntas_padrao.listar_perguntas_padrao(db)


@router.post("/perguntas-padrao")
def criar_pergunta_padrao(
    corpo: PerguntaPadraoPersonalizadaCorpo,
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Módulo de configuração de perguntas padrão (09/08/2026 - pedido do
    Maurício): permite criar uma pergunta padrão nova pelo próprio app, sem
    precisar de uma alteração de código. Restrito a admin. Ver
    app/assistente_perguntas_padrao.py (criar_pergunta_personalizada) pra
    detalhes de como isso se combina com o catálogo fixo."""
    try:
        linha = assistente_perguntas_padrao.criar_pergunta_personalizada(
            db, usuario, corpo.rotulo, corpo.pergunta, corpo.gatilhos, corpo.instrucao_extra,
        )
    except ValueError as erro:
        raise HTTPException(400, str(erro))
    registrar_log(db, usuario.username, "pergunta_padrao_criada", detalhes={"chave": linha.chave, "rotulo": linha.rotulo})
    db.commit()
    return {"chave": linha.chave, "rotulo": linha.rotulo, "pergunta": linha.pergunta, "personalizada": True}


@router.put("/perguntas-padrao/{chave}")
def editar_pergunta_padrao(
    chave: str,
    corpo: PerguntaPadraoPersonalizadaCorpo,
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    try:
        linha = assistente_perguntas_padrao.atualizar_pergunta_personalizada(
            db, chave, corpo.rotulo, corpo.pergunta, corpo.gatilhos, corpo.instrucao_extra,
        )
    except ValueError as erro:
        raise HTTPException(400, str(erro))
    registrar_log(db, usuario.username, "pergunta_padrao_editada", detalhes={"chave": chave})
    db.commit()
    return {"chave": linha.chave, "rotulo": linha.rotulo, "pergunta": linha.pergunta, "personalizada": True}


@router.delete("/perguntas-padrao/{chave}")
def remover_pergunta_padrao(
    chave: str,
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    try:
        assistente_perguntas_padrao.excluir_pergunta_personalizada(db, chave)
    except ValueError as erro:
        raise HTTPException(400, str(erro))
    registrar_log(db, usuario.username, "pergunta_padrao_excluida", detalhes={"chave": chave})
    db.commit()
    return {"ok": True}


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

    pergunta_padrao = assistente_perguntas_padrao.identificar_pergunta_padrao(pergunta, db)

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
