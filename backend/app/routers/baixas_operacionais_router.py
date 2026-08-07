"""
Relatório de Baixa - visão dentro do Atlas de todas as baixas
operacionais (Avaria, Vencimento, Descarte, Degustação, etc.) importadas
do sistema Lovable, de qualquer status (Pendente, Aprovada, Reprovada).
Diferente de baixas_operacionais.py (a lógica de importação/casamento),
este router só lê o que já foi importado - é pra tela de relatório, não
pra receber webhook."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import obter_usuario_atual

router = APIRouter(prefix="/baixas-operacionais", tags=["baixas_operacionais"])


@router.get("")
def listar_baixas(
    status_fluxo: str | None = Query(None, description="PENDENTE | APROVADA | REPROVADA"),
    almoxarifado: str | None = None,
    hipotese_aplicada: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.BaixaOperacional)
    if status_fluxo:
        q = q.filter(models.BaixaOperacional.status_fluxo == status_fluxo.upper())
    if almoxarifado:
        q = q.filter(models.BaixaOperacional.almoxarifado == almoxarifado)
    if hipotese_aplicada:
        q = q.filter(models.BaixaOperacional.hipotese_aplicada == hipotese_aplicada)
    if data_inicio:
        q = q.filter(models.BaixaOperacional.data_baixa >= data_inicio)
    if data_fim:
        q = q.filter(models.BaixaOperacional.data_baixa <= data_fim)

    linhas = q.order_by(models.BaixaOperacional.data_baixa.desc()).all()

    resumo = {
        "total": len(linhas),
        "pendentes": sum(1 for l in linhas if l.status_fluxo == "PENDENTE"),
        "aprovadas": sum(1 for l in linhas if l.status_fluxo == "APROVADA"),
        "reprovadas": sum(1 for l in linhas if l.status_fluxo == "REPROVADA"),
        "resolvidas_automaticamente": sum(1 for l in linhas if l.divergencia_vinculada_id),
        "aguardando_divergencia": sum(1 for l in linhas if l.status_fluxo == "APROVADA" and not l.divergencia_vinculada_id),
        "valor_total": sum(l.valor_total or 0 for l in linhas),
    }

    itens = [
        {
            "id": l.id,
            "sku": l.sku,
            "almoxarifado": l.almoxarifado,
            "almoxarifado_origem": l.almoxarifado_origem,
            "motivo": l.motivo_baixa_bruto,
            "hipotese_aplicada": l.hipotese_aplicada,
            "quantidade": l.quantidade,
            "valor_total": l.valor_total,
            "status_fluxo": l.status_fluxo,
            "solicitante_nome": l.solicitante_nome,
            "data_baixa": l.data_baixa,
            "divergencia_vinculada_id": l.divergencia_vinculada_id,
            "recebido_em": l.recebido_em,
        }
        for l in linhas
    ]
    return {"resumo": resumo, "itens": itens}
