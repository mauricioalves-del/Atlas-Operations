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
from ..movimentados import atualizar_resumo_mensal, atualizar_resumo_transferencias_mensal
from ..fefo import recalcular_checagens_fefo, ALMOXARIFADO_FABRICA

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


@router.post("/snapshot")
def snapshot_manual(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Dispara manualmente o upsert do resumo mensal (ver
    ResumoMovimentacaoMensal) - o dashboard já chama isso automaticamente
    a cada carregamento, esse endpoint só existe pra dar controle/feedback
    explícito ("Atualizar histórico") na tela."""
    resultado = atualizar_resumo_mensal(db)
    db.commit()
    return resultado


@router.get("/dashboard/resumo")
def dashboard_resumo(
    mes: Optional[str] = Query(None, description="YYYY-MM"),
    almoxarifado: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    # mantém o resumo mensal persistido em dia a cada visita ao dashboard -
    # ver models.ResumoMovimentacaoMensal pro motivo disso existir.
    atualizar_resumo_mensal(db)
    db.commit()

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
    """Lê do resumo mensal PERSISTIDO (ResumoMovimentacaoMensal), não das
    tabelas de origem direto - é o que garante que meses antigos não
    desapareçam do gráfico se a planilha de movimentação for reimportada
    depois (ver docstring do modelo). Atualiza o snapshot antes de ler,
    então o mês corrente sempre reflete o estado mais recente."""
    atualizar_resumo_mensal(db)
    db.commit()

    permitidos = getattr(usuario, "almoxarifados_permitidos", None) or None

    if almoxarifado:
        if permitidos and almoxarifado not in permitidos:
            return []  # fora do escopo do usuário - vazio, sem erro (mesmo padrão de filtrar_por_almoxarifado_permitido)
        linhas = db.query(models.ResumoMovimentacaoMensal).filter(models.ResumoMovimentacaoMensal.almoxarifado == almoxarifado).order_by(models.ResumoMovimentacaoMensal.mes).all()
        return [
            {"mes": l.mes, "itens_analisados": l.itens_analisados, "itens_sem_divergencia": l.itens_sem_divergencia, "pct_acuracia": l.pct_acuracia}
            for l in linhas
        ]

    if not permitidos:
        # usuário sem restrição - lê direto a linha "geral" já pré-agregada (almoxarifado = None)
        linhas = db.query(models.ResumoMovimentacaoMensal).filter(models.ResumoMovimentacaoMensal.almoxarifado.is_(None)).order_by(models.ResumoMovimentacaoMensal.mes).all()
        return [
            {"mes": l.mes, "itens_analisados": l.itens_analisados, "itens_sem_divergencia": l.itens_sem_divergencia, "pct_acuracia": l.pct_acuracia}
            for l in linhas
        ]

    # usuário restrito a um subconjunto de almoxarifados - a linha "geral"
    # inclui almoxarifados fora do escopo dele, então soma na hora só as
    # linhas dos almoxarifados permitidos (ainda lendo do snapshot
    # persistido, não das tabelas de origem - só a agregação final é feita
    # aqui, sobre poucas linhas já calculadas).
    linhas = db.query(models.ResumoMovimentacaoMensal).filter(models.ResumoMovimentacaoMensal.almoxarifado.in_(permitidos)).all()
    por_mes = defaultdict(lambda: {"analisados": 0, "sem_divergencia": 0})
    for l in linhas:
        por_mes[l.mes]["analisados"] += l.itens_analisados
        por_mes[l.mes]["sem_divergencia"] += l.itens_sem_divergencia
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


# ---------------------------------------------------------------------------
# Dashboard de Acompanhamento (19/08/2026) - "movimentação" aqui é Transferência
# entre almoxarifados (o usuário esclareceu isso depois de eu ter interpretado
# como o par MovimentacaoHistorico/Divergencia acima - os dois indicadores
# ficam então lado a lado no sistema, servindo perguntas diferentes: o par
# acima é sobre RECONCILIAÇÃO diária sistema x físico; o que segue é sobre
# VOLUME de transferências entre almoxarifados e o critério de FEFO nas que
# saem da Fábrica). Ver models.ResumoTransferenciasMensal pro motivo do
# snapshot persistido.
# ---------------------------------------------------------------------------

def _atualizar_historico_transferencias(db: Session) -> dict:
    """Recalcula a checagem de FEFO (pra refletir transferências/lotes
    novos) e, em seguida, o resumo mensal de transferências - nessa ordem,
    porque o resumo depende do resultado mais recente da checagem."""
    resultado_fefo = recalcular_checagens_fefo(db)
    resultado_resumo = atualizar_resumo_transferencias_mensal(db)
    db.commit()
    return {"fefo": resultado_fefo, "resumo_transferencias": resultado_resumo}


@router.post("/snapshot-transferencias")
def snapshot_transferencias_manual(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Botão "Atualizar histórico" do Dashboard de Acompanhamento - a tela
    já chama isso sozinha ao carregar, esse endpoint só dá controle/
    feedback explícito ao usuário."""
    return _atualizar_historico_transferencias(db)


@router.get("/dashboard/transferencias-resumo")
def dashboard_transferencias_resumo(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Totais atuais (todas as transferências já importadas, sem recorte
    de período - Transferencia não tem um conceito de "mês corrente" bem
    definido pra filtro por período aqui). Atualiza a checagem de FEFO e o
    snapshot mensal antes de responder, então "quebras_fefo" já reflete o
    estado mais recente de Transferencia/LoteShelfLife."""
    _atualizar_historico_transferencias(db)

    transferencias = db.query(models.Transferencia).all()
    total = len(transferencias)
    quantidade_total = round(sum(t.quantidade or 0 for t in transferencias), 2)
    da_fabrica = sum(1 for t in transferencias if t.almoxarifado_origem == ALMOXARIFADO_FABRICA)

    return {
        "total_transferencias": total,
        "quantidade_total": quantidade_total,
        "transferencias_da_fabrica": da_fabrica,
    }


@router.get("/dashboard/transferencias-evolucao-mensal")
def dashboard_transferencias_evolucao_mensal(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Lê do resumo mensal PERSISTIDO (ResumoTransferenciasMensal), não de
    Transferencia/ChecagemFefo direto - garante que meses antigos não
    somem se a planilha de Transferências for reimportada depois (ela
    apaga e recria todas as linhas de Transferencia a cada envio - ver
    import_router.py). Atualiza o snapshot antes de ler."""
    _atualizar_historico_transferencias(db)

    linhas = db.query(models.ResumoTransferenciasMensal).order_by(models.ResumoTransferenciasMensal.mes).all()
    return [
        {
            "mes": l.mes,
            "total_transferencias": l.total_transferencias,
            "quantidade_total": l.quantidade_total,
            "transferencias_fabrica_avaliadas": l.transferencias_fabrica_avaliadas,
            "quebras_fefo": l.quebras_fefo,
            "taxa_quebra_fefo_pct": l.taxa_quebra_fefo_pct,
        }
        for l in linhas
    ]
