from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..investigation import investigar, reconciliar
from ..ml import predict as ml_predict
from ..deps import requer_papel, obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/divergencias", tags=["divergencias"])

PESO_MIN, PESO_MAX = 5.0, 60.0
INCREMENTO_ACERTO = 2.0
DECREMENTO_ERRO = 2.0


def _preencher_descricao_produto(db: Session, divergencias: list):
    """Anexa descricao_produto (vindo do cadastro de produtos) a cada
    divergência antes de serializar - um atributo transiente, não uma
    coluna, então não precisa migração de banco."""
    skus = {d.sku for d in divergencias}
    produtos = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus)).all()}
    for d in divergencias:
        d.descricao_produto = produtos.get(d.sku)
    return divergencias


def _marcar_investigacao_pendente(db: Session, divergencias: list):
    """Sinaliza (tem_investigacao_pendente) quando o mesmo SKU já tem
    outro caso marcado 'Em_Investigacao' que ainda não foi resolvido -
    usado pra mostrar o ícone de atenção quando a divergência reaparece
    antes de a investigação anterior ter sido concluída."""
    if not divergencias:
        return divergencias
    skus = {d.sku for d in divergencias}
    em_investigacao = (
        db.query(models.Divergencia.sku, models.Divergencia.id)
        .filter(models.Divergencia.sku.in_(skus), models.Divergencia.status == "Em_Investigacao")
        .all()
    )
    ids_por_sku = {}
    for sku, id_ in em_investigacao:
        ids_por_sku.setdefault(sku, set()).add(id_)
    for d in divergencias:
        ids_pendentes = ids_por_sku.get(d.sku, set())
        d.tem_investigacao_pendente = bool(ids_pendentes - {d.id})
    return divergencias


@router.post("/recalcular-valores")
def recalcular_valores(usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Reaplica o custo unitário cadastrado (Produto.custo_unitario) sobre
    as divergências ainda não resolvidas - útil quando você cadastra ou
    atualiza custos depois que as divergências já foram detectadas."""
    abertas = db.query(models.Divergencia).filter(models.Divergencia.status != "Resolvida").all()
    atualizadas = 0
    custos = {p.sku: p.custo_unitario for p in db.query(models.Produto).all() if p.custo_unitario is not None}
    for d in abertas:
        custo = custos.get(d.sku)
        if custo is None:
            continue
        novo_valor = round(abs(d.divergencia_qtd) * custo, 2)
        if novo_valor != d.valor_estimado:
            d.valor_estimado = novo_valor
            atualizadas += 1
    registrar_log(db, usuario.username, "recalcular_valores", detalhes={"atualizadas": atualizadas, "verificadas": len(abertas)})
    db.commit()
    return {"divergencias_verificadas": len(abertas), "divergencias_atualizadas": atualizadas}


@router.get("")
def listar(
    almoxarifado: Optional[str] = None,
    status: Optional[str] = None,
    hipotese: Optional[str] = None,
    incluir_fechamento_inventario: bool = False,
    pagina: int = Query(1, ge=1),
    tamanho_pagina: int = Query(50, ge=1, le=500),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.Divergencia)
    if not incluir_fechamento_inventario:
        q = q.filter(models.Divergencia.origem != "fechamento_inventario")
    if almoxarifado:
        q = q.filter(models.Divergencia.almoxarifado == almoxarifado)
    if status:
        q = q.filter(models.Divergencia.status == status)
    if hipotese:
        q = q.filter(models.Divergencia.hipotese_ia == hipotese)

    total = q.count()
    q = q.order_by(models.Divergencia.data_deteccao.desc())
    divergencias = q.offset((pagina - 1) * tamanho_pagina).limit(tamanho_pagina).all()
    _preencher_descricao_produto(db, divergencias)
    _marcar_investigacao_pendente(db, divergencias)

    return {
        "itens": [schemas.DivergenciaOut.model_validate(d).model_dump() for d in divergencias],
        "total": total,
        "pagina": pagina,
        "paginas": max(1, -(-total // tamanho_pagina)),
    }


@router.get("/{div_id}", response_model=schemas.DivergenciaOut)
def detalhar(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")
    _preencher_descricao_produto(db, [div])
    _marcar_investigacao_pendente(db, [div])
    return div


@router.post("/{div_id}/marcar-investigacao", response_model=schemas.DivergenciaOut)
def marcar_investigacao(div_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Marca a divergência como 'Em investigação' sem confirmar uma causa
    ainda - usado quando alguém já está apurando o caso, mas não tem uma
    conclusão. Enquanto estiver nesse status, qualquer nova divergência do
    mesmo SKU aparece com um ícone de atenção na lista."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")
    if div.status == "Resolvida":
        raise HTTPException(400, "Essa divergência já foi resolvida.")
    div.status = "Em_Investigacao"
    registrar_log(db, usuario.username, "marcar_em_investigacao", entidade="divergencia", entidade_id=div.id)
    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    _marcar_investigacao_pendente(db, [div])
    return div


@router.get("/{div_id}/historico-sku")
def historico_sku(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Linha do tempo do SKU desta divergência: todo registro (resolvido
    ou não, de qualquer origem) com esse SKU, pra visualizar quando as
    divergências aconteceram e quando estabilizaram, e por qual
    almoxarifado passaram os últimos apontamentos."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    pontos = []
    for h in db.query(models.MovimentacaoHistorico).filter_by(sku=div.sku).all():
        pontos.append({
            "data": str(h.data_movimento), "almoxarifado": h.almoxarifado,
            "divergencia_qtd": h.divergencia or 0, "status": "Resolvido",
            "hipotese": h.hipotese_confirmada, "origem": h.origem,
        })
    for d in db.query(models.Divergencia).filter_by(sku=div.sku).all():
        pontos.append({
            "data": str(d.data_deteccao), "almoxarifado": d.almoxarifado,
            "divergencia_qtd": d.divergencia_qtd, "status": d.status,
            "hipotese": d.hipotese_confirmada or d.hipotese_ia, "origem": d.origem,
        })

    pontos.sort(key=lambda p: p["data"])
    return pontos


@router.post("/{div_id}/reinvestigar", response_model=schemas.DivergenciaOut)
def reinvestigar(div_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Roda o motor de investigação de novo sobre um caso já existente -
    útil quando o motor ganha uma capacidade nova (ex: leitura da
    observação da planilha) e você quer que casos antigos se beneficiem
    dela sem precisar reimportar o arquivo inteiro."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    resultado_regras = investigar(db, div)
    resultado_ml = ml_predict.prever(div.sku, div.almoxarifado, div.categoria_produto, div.divergencia_qtd, div.valor_estimado, div.data_deteccao, db=db)
    hipotese_final, confianca_final = reconciliar(
        resultado_regras["scores_normalizados"],
        resultado_ml["distribuicao"] if resultado_ml else [],
    )

    div.hipotese_regras = resultado_regras["hipotese_regras"]
    div.confianca_regras = resultado_regras["confianca_regras"]
    div.evidencias = resultado_regras["evidencias"]
    div.casos_similares = resultado_regras["casos_similares"]
    div.hipotese_ml = resultado_ml["hipotese_predita"] if resultado_ml else None
    div.confianca_ml = resultado_ml["confianca"] if resultado_ml else None
    div.distribuicao_probabilidades = resultado_ml["distribuicao"] if resultado_ml else resultado_regras["scores_normalizados"]
    div.hipotese_ia = hipotese_final
    div.confianca_ia = confianca_final

    registrar_log(db, usuario.username, "reinvestigar_divergencia", entidade="divergencia", entidade_id=div.id,
                  detalhes={"nova_hipotese_ia": hipotese_final, "confianca_ia": confianca_final})
    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    return div


@router.post("/{div_id}/confirmar", response_model=schemas.DivergenciaOut)
def confirmar(div_id: int, payload: schemas.ConfirmarDivergencia, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    hipotese_valida = db.query(models.Hipotese).filter_by(codigo=payload.hipotese_confirmada).first()
    if not hipotese_valida:
        raise HTTPException(400, f"Hipótese '{payload.hipotese_confirmada}' não existe no catálogo oficial")

    div.hipotese_confirmada = payload.hipotese_confirmada
    div.solucao_aplicada = payload.solucao_aplicada
    div.responsavel = payload.responsavel or usuario.nome_exibicao or usuario.username
    div.tempo_resolucao_minutos = payload.tempo_resolucao_minutos
    div.status = "Resolvida"
    div.resolvido_em = datetime.utcnow()

    # --- loop de aprendizado: ajusta peso da hipótese que o motor de regras sugeriu ---
    if div.hipotese_regras:
        h = db.query(models.Hipotese).filter_by(codigo=div.hipotese_regras).first()
        if h:
            if div.hipotese_regras == payload.hipotese_confirmada:
                h.peso_padrao = min(PESO_MAX, h.peso_padrao + INCREMENTO_ACERTO)
            else:
                h.peso_padrao = max(PESO_MIN, h.peso_padrao - DECREMENTO_ERRO)

    # --- registra caso para o próximo retreino do ML ---
    db.add(models.CasoMLFeedback(
        divergencia_id=div.id, sku=div.sku, almoxarifado=div.almoxarifado,
        categoria_produto=div.categoria_produto, divergencia_qtd=div.divergencia_qtd,
        valor_estimado=div.valor_estimado, data_deteccao=div.data_deteccao,
        hipotese_confirmada=payload.hipotese_confirmada,
    ))

    registrar_log(db, usuario.username, "confirmar_divergencia", entidade="divergencia", entidade_id=div.id,
                  detalhes={"hipotese_confirmada": payload.hipotese_confirmada, "solucao": payload.solucao_aplicada})

    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    return div
