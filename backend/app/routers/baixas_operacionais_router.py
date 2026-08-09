"""
Relatório de Baixa - visão dentro do Atlas de todas as baixas
operacionais (Avaria, Vencimento, Descarte, Degustação, etc.) importadas
do sistema Lovable, de qualquer status (Pendente, Aprovada, Reprovada).
Diferente de baixas_operacionais.py (a lógica de importação/casamento),
este router só lê o que já foi importado - é pra tela de relatório, não
pra receber webhook."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import obter_usuario_atual
from ..baixas_operacionais import sincronizar_com_lovable, SincronizacaoIndisponivel, importar_lote

router = APIRouter(prefix="/baixas-operacionais", tags=["baixas_operacionais"])


@router.post("/importar-lote")
def importar_lote_colado(
    payload: dict = Body(...),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Fecha manualmente uma lacuna histórica entre o que existe no
    Lovable e o que já foi importado pro Atlas (ex: linhas de antes do
    webhook automático existir, ou alguma falha pontual de entrega).
    Protegido por login (mesmo usuário logado na tela, não pela chave de
    integração - por isso fica aqui, junto do relatório, e não em
    integracoes_router.py) porque quem aciona isso é uma pessoa colando
    um export tirado na mão do SQL editor do Lovable, não um sistema
    automático. Espera {"registros": [ {...}, ... ]} - mesmo formato de
    linha que .../integracoes/lovable/baixas/lote. Upsert por origem_id,
    então pode ser rodado de novo com o mesmo lote sem duplicar nada."""
    registros = payload.get("registros")
    if not isinstance(registros, list):
        raise HTTPException(400, "Payload precisa ter uma lista em 'registros'.")
    resultado = importar_lote(db, registros)
    db.commit()
    return resultado


@router.post("/sincronizar")
def sincronizar(
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Botão "Sincronizar agora" da tela Relatório de Baixa: busca ao vivo
    o estado atual da tabela baixa_operacional no Supabase do Lovable e
    reimporta tudo pro Atlas (upsert por origem_id - atualiza o que mudou
    de status lá, ex: Pendente -> Aprovada, sem duplicar nada)."""
    try:
        resultado = sincronizar_com_lovable(db)
    except SincronizacaoIndisponivel as e:
        raise HTTPException(500, str(e))
    db.commit()
    return resultado


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
