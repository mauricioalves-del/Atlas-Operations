"""
Controle de Movimentados (18/08/2026) - indicador do MBR (slide 15) sobre a
qualidade da reconciliação diária de MOVIMENTAÇÃO (livro-caixa bruto: saídas/
entradas do dia), separado da reconciliação de CONTAGEM FÍSICA periódica
(essa já tem seu próprio painel - "Painel de Inventário"/Fechamento).

IMPORTANTE - suposição documentada: não existe hoje uma tabela dedicada de
"itens analisados na reconciliação de movimentação" - o que existe são as
DUAS tabelas que o motor de investigação já escreve quando compara saldo do
sistema x saldo físico de um item: MovimentacaoHistorico (item já resolvido -
"sem divergência" quando o campo divergencia == 0, ou divergência já
confirmada/resolvida quando != 0) e Divergencia (item com divergência aberta
hoje, ainda em investigação). Juntando as duas, com origem == "movimentacao"
(pra não misturar com o fluxo de Fechamento de Inventário, que usa
origem == "fechamento_inventario" nas duas tabelas), dá o universo de "itens
analisados" desse indicador:

    itens_analisados   = count(MovimentacaoHistorico) + count(Divergencia)
    sem_divergencia     = count(MovimentacaoHistorico onde divergencia == 0)
    com_divergencia      = itens_analisados - sem_divergencia
    pct_acuracia        = sem_divergencia / itens_analisados

Se essa não for a leitura certa do indicador do MBR (por exemplo, se
"Controle de Movimentados" for sobre outra coisa, como cobertura de
transferências casadas), é só pedir pra eu ajustar - a lógica de agregação
está isolada nas duas funções auxiliares abaixo, fácil de trocar sem afetar
o resto do sistema.
"""
from collections import defaultdict
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import obter_usuario_atual, filtrar_por_almoxarifado_permitido

router = APIRouter(prefix="/movimentados", tags=["movimentados"])


def _mes_str(d):
    return f"{d.year:04d}-{d.month:02d}" if d else None


def _mes_para_intervalo(mes: str):
    ano, mes_num = mes.split("-")
    ano, mes_num = int(ano), int(mes_num)
    inicio = date(ano, mes_num, 1)
    fim = date(ano + 1, 1, 1) if mes_num == 12 else date(ano, mes_num + 1, 1)
    return inicio, fim


def _query_base(db: Session, usuario, almoxarifado: Optional[str], mes: Optional[str]):
    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem == "movimentacao")
    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem == "movimentacao")

    q_hist = filtrar_por_almoxarifado_permitido(q_hist, models.MovimentacaoHistorico.almoxarifado, usuario, almoxarifado)
    q_div = filtrar_por_almoxarifado_permitido(q_div, models.Divergencia.almoxarifado, usuario, almoxarifado)

    if mes:
        inicio, fim = _mes_para_intervalo(mes)
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= inicio, models.MovimentacaoHistorico.data_movimento < fim)
        q_div = q_div.filter(models.Divergencia.data_deteccao >= inicio, models.Divergencia.data_deteccao < fim)

    return q_hist, q_div


@router.get("/dashboard/resumo")
def dashboard_resumo(
    mes: Optional[str] = Query(None, description="YYYY-MM"),
    almoxarifado: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q_hist, q_div = _query_base(db, usuario, almoxarifado, mes)
    historico = q_hist.all()
    divergencias = q_div.all()

    sem_divergencia = sum(1 for h in historico if not h.divergencia)
    com_divergencia_historico = len(historico) - sem_divergencia
    itens_analisados = len(historico) + len(divergencias)
    com_divergencia = com_divergencia_historico + len(divergencias)

    return {
        "mes": mes,
        "almoxarifado": almoxarifado,
        "itens_analisados": itens_analisados,
        "itens_sem_divergencia": sem_divergencia,
        "itens_com_divergencia": com_divergencia,
        "pct_acuracia": round(sem_divergencia / itens_analisados * 100, 2) if itens_analisados else None,
        "valor_total_divergencias": round(
            sum(abs(h.valor_divergencia or 0) for h in historico if h.divergencia) + sum(abs(d.valor_estimado or 0) for d in divergencias), 2
        ),
    }


@router.get("/dashboard/evolucao-mensal")
def dashboard_evolucao_mensal(
    almoxarifado: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q_hist, q_div = _query_base(db, usuario, almoxarifado, None)

    por_mes = defaultdict(lambda: {"analisados": 0, "sem_divergencia": 0})
    for h in q_hist.all():
        chave = _mes_str(h.data_movimento)
        if not chave:
            continue
        por_mes[chave]["analisados"] += 1
        if not h.divergencia:
            por_mes[chave]["sem_divergencia"] += 1
    for d in q_div.all():
        chave = _mes_str(d.data_deteccao)
        if not chave:
            continue
        por_mes[chave]["analisados"] += 1

    return [
        {
            "mes": mes,
            "itens_analisados": v["analisados"],
            "itens_sem_divergencia": v["sem_divergencia"],
            "pct_acuracia": round(v["sem_divergencia"] / v["analisados"] * 100, 2) if v["analisados"] else None,
        }
        for mes, v in sorted(por_mes.items())
    ]


@router.get("/dashboard/por-almoxarifado")
def dashboard_por_almoxarifado(
    mes: Optional[str] = Query(None, description="YYYY-MM"),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q_hist, q_div = _query_base(db, usuario, None, mes)

    por_almox = defaultdict(lambda: {"analisados": 0, "sem_divergencia": 0})
    for h in q_hist.all():
        por_almox[h.almoxarifado]["analisados"] += 1
        if not h.divergencia:
            por_almox[h.almoxarifado]["sem_divergencia"] += 1
    for d in q_div.all():
        por_almox[d.almoxarifado]["analisados"] += 1

    return [
        {
            "almoxarifado": almox,
            "itens_analisados": v["analisados"],
            "itens_sem_divergencia": v["sem_divergencia"],
            "pct_acuracia": round(v["sem_divergencia"] / v["analisados"] * 100, 2) if v["analisados"] else None,
        }
        for almox, v in sorted(por_almox.items())
    ]
