from collections import defaultdict
from datetime import date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, shelf_life
from ..database import get_db
from ..deps import obter_usuario_atual

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _data_corte(periodo: str | None):
    """Traduz o filtro de período do menu superior numa data de corte.
    None/"" /"tudo" = sem corte (usa todo o histórico)."""
    if not periodo or periodo == "tudo":
        return None
    hoje = date.today()
    if periodo == "mes_atual":
        return hoje.replace(day=1)
    if periodo == "30d":
        return hoje - timedelta(days=30)
    if periodo == "60d":
        return hoje - timedelta(days=60)
    if periodo == "90d":
        return hoje - timedelta(days=90)
    return None


@router.get("/kpis")
def kpis(periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    corte = _data_corte(periodo)
    q = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if corte:
        q = q.filter(models.Divergencia.data_deteccao >= corte)

    abertas = q.filter(models.Divergencia.status == "Aberta").count()
    em_investigacao = q.filter(models.Divergencia.status == "Em_Investigacao").count()
    resolvidas_q = q.filter(models.Divergencia.status == "Resolvida")
    resolvidas = resolvidas_q.count()

    valor_aberto = q.filter(models.Divergencia.status != "Resolvida").with_entities(func.sum(models.Divergencia.valor_estimado)).scalar() or 0

    total_resolvidas = resolvidas_q.all()
    if total_resolvidas:
        acertos = sum(1 for d in total_resolvidas if d.hipotese_ia == d.hipotese_confirmada)
        taxa_acerto = round(acertos / len(total_resolvidas) * 100, 1)
    else:
        taxa_acerto = None

    return {
        "divergencias_abertas": abertas,
        "em_investigacao": em_investigacao,
        "resolvidas": resolvidas,
        "valor_total_em_aberto": round(valor_aberto, 2),
        "taxa_acerto_modelo_pct": taxa_acerto,
    }


@router.get("/acuracia-por-dia")
def acuracia_por_dia(almoxarifado: str | None = None, periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Combina o histórico confirmado (movimentacoes_historico) com as
    divergências detectadas a partir de hoje (divergencias) para dar a
    curva real de itens inventariados x acurácia por dia."""
    corte = _data_corte(periodo)
    por_dia = defaultdict(lambda: {"itens": 0, "sem_divergencia": 0})

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario")
    if almoxarifado:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.almoxarifado == almoxarifado)
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    for m in q_hist.all():
        chave = str(m.data_movimento)
        por_dia[chave]["itens"] += 1
        if (m.divergencia or 0) == 0 or m.hipotese_confirmada == "Sem_Divergencia_Real":
            por_dia[chave]["sem_divergencia"] += 1

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if almoxarifado:
        q_div = q_div.filter(models.Divergencia.almoxarifado == almoxarifado)
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    for d in q_div.all():
        chave = str(d.data_deteccao)
        por_dia[chave]["itens"] += 1
        if d.hipotese_confirmada == "Sem_Divergencia_Real":
            por_dia[chave]["sem_divergencia"] += 1

    resultado = []
    for data_str, valores in sorted(por_dia.items()):
        itens = valores["itens"]
        acuracia = round(valores["sem_divergencia"] / itens * 100, 2) if itens else None
        resultado.append({"data": data_str, "itens_inventariados": itens, "acuracia_pct": acuracia})
    return resultado


@router.get("/acuracia-mensal")
def acuracia_mensal(almoxarifado: str | None = None, periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Agrega a série diária por mês e calcula a variação MoM em pontos
    percentuais (pp): cada mês é comparado com o mês imediatamente
    anterior, em sequência, cobrindo todos os meses disponíveis no
    período selecionado (não é uma comparação fixa contra um mês-base)."""
    diario = acuracia_por_dia(almoxarifado=almoxarifado, periodo=periodo, usuario=usuario, db=db)
    por_mes = defaultdict(lambda: {"itens": 0, "sem_divergencia": 0})
    for d in diario:
        mes = d["data"][:7]  # "YYYY-MM"
        itens = d["itens_inventariados"]
        sem_div = round((d["acuracia_pct"] or 0) / 100 * itens)
        por_mes[mes]["itens"] += itens
        por_mes[mes]["sem_divergencia"] += sem_div

    meses_ordenados = sorted(por_mes.keys())
    resultado = []
    anterior = None
    for mes in meses_ordenados:
        v = por_mes[mes]
        acuracia = round(v["sem_divergencia"] / v["itens"] * 100, 2) if v["itens"] else None
        variacao_pp = round(acuracia - anterior, 2) if (acuracia is not None and anterior is not None) else None
        resultado.append({"mes": mes, "acuracia_pct": acuracia, "variacao_mom_pp": variacao_pp, "itens_inventariados": v["itens"]})
        anterior = acuracia
    return resultado


@router.get("/distribuicao-causas")
def distribuicao_causas(periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Causas confirmadas - agora inclui o histórico categorizado (1367
    casos), não só as divergências novas resolvidas na v1 anterior."""
    corte = _data_corte(periodo)
    contagem = defaultdict(int)

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario").filter(models.MovimentacaoHistorico.hipotese_confirmada.isnot(None))
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    for m in q_hist.all():
        contagem[m.hipotese_confirmada] += 1

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario").filter(models.Divergencia.status == "Resolvida")
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    for d in q_div.all():
        if d.hipotese_confirmada:
            contagem[d.hipotese_confirmada] += 1

    return [{"hipotese": k, "quantidade": v} for k, v in sorted(contagem.items(), key=lambda x: -x[1])]


@router.get("/acuracia-por-almoxarifado")
def acuracia_por_almoxarifado(periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Acurácia acumulada (todo o recorte, não dia a dia) agrupada por
    almoxarifado - mesma lógica/critério de 'Sem_Divergencia_Real' já usado
    em acuracia_por_dia acima, só que agregando por almoxarifado em vez de
    por data. Alimenta o gráfico de barras invertido no card 'Almoxarifado
    × Hipótese' do Painel de Divergências (28/08/2026, pedido do Maurício:
    'Quero adicionar um grafico de barras invertido trazendo a acuracidade
    acumulada por Almoxarifado').

    Só respeita o filtro de PERÍODO, não o de almoxarifado - propositalmente
    igual aos outros indicadores desse mesmo grupo de cards (kpis,
    distribuicao-causas, heatmap-almoxarifado-hipotese, top-reincidentes,
    top-divergencias, todos chamados com `qsSemAlmox` no app.js): uma
    quebra POR almoxarifado não faz sentido nenhum se a tela já estiver
    filtrada pra um único almoxarifado."""
    corte = _data_corte(periodo)
    por_almox = defaultdict(lambda: {"itens": 0, "sem_divergencia": 0})

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario")
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    for m in q_hist.all():
        por_almox[m.almoxarifado]["itens"] += 1
        if (m.divergencia or 0) == 0 or m.hipotese_confirmada == "Sem_Divergencia_Real":
            por_almox[m.almoxarifado]["sem_divergencia"] += 1

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    for d in q_div.all():
        por_almox[d.almoxarifado]["itens"] += 1
        if d.hipotese_confirmada == "Sem_Divergencia_Real":
            por_almox[d.almoxarifado]["sem_divergencia"] += 1

    resultado = []
    for almox, valores in por_almox.items():
        itens = valores["itens"]
        acuracia = round(valores["sem_divergencia"] / itens * 100, 2) if itens else None
        resultado.append({"almoxarifado": almox, "acuracia_pct": acuracia, "itens_inventariados": itens})

    # pior acurácia primeiro (fica no topo do gráfico invertido, chamando
    # atenção pros almoxarifados problemáticos) - nulos (sem nenhum item no
    # recorte) vão pro final, não fazem sentido no meio do ranking.
    resultado.sort(key=lambda x: (x["acuracia_pct"] is None, x["acuracia_pct"]))
    return resultado


@router.get("/heatmap-almoxarifado-hipotese")
def heatmap(periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    corte = _data_corte(periodo)
    matriz = defaultdict(lambda: defaultdict(int))

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario").filter(models.MovimentacaoHistorico.hipotese_confirmada.isnot(None))
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    for m in q_hist.all():
        matriz[m.almoxarifado][m.hipotese_confirmada] += 1

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    for d in q_div.all():
        h = d.hipotese_ia or d.hipotese_confirmada or "Sem_Classificacao"
        matriz[d.almoxarifado][h] += 1

    resultado = []
    for almox, hipoteses in matriz.items():
        for h, qtd in hipoteses.items():
            resultado.append({"almoxarifado": almox, "hipotese": h, "quantidade": qtd})
    return resultado


@router.get("/top-reincidentes")
def top_reincidentes(limite: int = 10, periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    corte = _data_corte(periodo)
    por_sku, por_almox = defaultdict(int), defaultdict(int)

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario")
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    for m in q_hist.all():
        por_sku[m.sku] += 1
        por_almox[m.almoxarifado] += 1

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    for d in q_div.all():
        por_sku[d.sku] += 1
        por_almox[d.almoxarifado] += 1

    top_sku = sorted(por_sku.items(), key=lambda x: x[1], reverse=True)[:limite]
    top_almox = sorted(por_almox.items(), key=lambda x: x[1], reverse=True)[:limite]
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_([s for s, _ in top_sku])).all()}
    return {
        "top_skus": [{"sku": s, "descricao": descricoes.get(s), "quantidade": q} for s, q in top_sku],
        "top_almoxarifados": [{"almoxarifado": a, "quantidade": q} for a, q in top_almox],
    }


@router.get("/top-divergencias")
def top_divergencias(limite: int = 10, periodo: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    corte = _data_corte(periodo)

    q_hist = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem != "fechamento_inventario").filter(models.MovimentacaoHistorico.divergencia != 0)
    if corte:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.data_movimento >= corte)
    hist_rows = q_hist.all()
    itens_hist = [
        {
            "sku": m.sku, "almoxarifado": m.almoxarifado, "saldo_sistema": m.saldo_sistema,
            "saldo_fisico": m.saldo_fisico, "divergencia_qtd": m.divergencia, "status": "Historico_Resolvido",
        }
        for m in hist_rows
    ]

    q_div = db.query(models.Divergencia).filter(models.Divergencia.origem != "fechamento_inventario")
    if corte:
        q_div = q_div.filter(models.Divergencia.data_deteccao >= corte)
    div_rows = q_div.all()
    itens_div = [
        {
            "sku": d.sku, "almoxarifado": d.almoxarifado, "saldo_sistema": d.saldo_sistema,
            "saldo_fisico": d.saldo_fisico, "divergencia_qtd": d.divergencia_qtd, "status": d.status,
        }
        for d in div_rows
    ]

    todos = itens_hist + itens_div
    skus_envolvidos = {item["sku"] for item in todos}
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus_envolvidos)).all()}
    for item in todos:
        item["descricao_produto"] = descricoes.get(item["sku"])
    todos.sort(key=lambda x: abs(x["divergencia_qtd"] or 0), reverse=True)
    return todos[:limite]


@router.get("/itens-periodo")
def itens_periodo(
    data_inicio: date,
    data_fim: date,
    almoxarifado: str | None = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Lista os itens divergentes de um intervalo de datas (um dia só,
    quando data_inicio == data_fim, ou um mês inteiro) - alimenta o popup
    de duplo clique nas barras do Painel (gráfico diário e o MoM),
    reaproveitando as MESMAS duas fontes que compõem esses gráficos (ver
    acuracia_por_dia acima): divergências novas (tabela `divergencias`) e
    casos históricos já resolvidos que tiveram divergência real
    (`movimentacoes_historico`). Itens da tabela `divergencias` têm `id`
    (dá pra abrir a investigação); itens históricos não (já foram
    resolvidos e não têm mais uma investigação "aberta" pra ver)."""
    q_div = db.query(models.Divergencia).filter(
        models.Divergencia.origem != "fechamento_inventario",
        models.Divergencia.data_deteccao >= data_inicio,
        models.Divergencia.data_deteccao <= data_fim,
    )
    if almoxarifado:
        q_div = q_div.filter(models.Divergencia.almoxarifado == almoxarifado)
    divergencias = q_div.all()

    q_hist = db.query(models.MovimentacaoHistorico).filter(
        models.MovimentacaoHistorico.origem != "fechamento_inventario",
        models.MovimentacaoHistorico.divergencia != 0,
        models.MovimentacaoHistorico.data_movimento >= data_inicio,
        models.MovimentacaoHistorico.data_movimento <= data_fim,
    )
    if almoxarifado:
        q_hist = q_hist.filter(models.MovimentacaoHistorico.almoxarifado == almoxarifado)
    historicos = q_hist.all()

    skus = {d.sku for d in divergencias} | {h.sku for h in historicos}
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus)).all()}

    itens = []
    for d in divergencias:
        itens.append({
            "tipo": "divergencia",
            "id": d.id,
            "sku": d.sku,
            "descricao_produto": descricoes.get(d.sku),
            "almoxarifado": d.almoxarifado,
            "data": str(d.data_deteccao),
            "valor_estimado": d.valor_estimado,
            "divergencia_qtd": d.divergencia_qtd,
            "hipotese": d.hipotese_ia or d.hipotese_confirmada,
            "confianca": d.confianca_ia,
            "status": d.status,
        })
    for h in historicos:
        itens.append({
            "tipo": "historico",
            "id": None,
            "sku": h.sku,
            "descricao_produto": descricoes.get(h.sku),
            "almoxarifado": h.almoxarifado,
            "data": str(h.data_movimento),
            "valor_estimado": h.valor_divergencia,
            "divergencia_qtd": h.divergencia,
            "hipotese": h.hipotese_confirmada,
            "confianca": None,
            "status": "Historico_Resolvido",
        })
    itens.sort(key=lambda x: (x["data"], abs(x["divergencia_qtd"] or 0)), reverse=True)
    return {"itens": itens, "total": len(itens)}


# ---------------------------------------------------------------------------
# Mapa de Demandas de Gestão (painel fixo na tela Início) - agrega, num só
# lugar, os passivos e riscos que hoje exigem uma decisão de gestão:
#   1) baixas operacionais PENDENTES no Lovable (passivo em aberto - ainda
#      não foi aprovada nem reprovada, o valor ainda não saiu do estoque
#      contabilmente mas já foi solicitado);
#   2) risco de obsolescência por baixo giro (produto com saldo em estoque
#      mas sem nenhuma saída/venda recente - farol 30/60/90 dias);
#   3) risco de validade (Shelf Life) - farol vencido/30/60/90 dias
#      calculado em cima dos lotes cadastrados em LoteShelfLife (ver
#      shelf_life.py e shelf_life_router.py) - alimentado por importação
#      da planilha do sistema interno e/ou cadastro manual na tela
#      dedicada. Não é uma leitura do módulo Shelf Life do Lovable (sem
#      acesso de SQL editor lá, só a tela) - é uma fonte equivalente que o
#      próprio Atlas controla.
# ---------------------------------------------------------------------------

DIAS_MINIMO_RISCO_OBSOLESCENCIA = 30


def _calcular_baixas_pendentes(db: Session) -> dict:
    pendentes = db.query(models.BaixaOperacional).filter(models.BaixaOperacional.status_fluxo == "PENDENTE").all()
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_({b.sku for b in pendentes})).all()}

    por_motivo = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for b in pendentes:
        motivo = b.motivo_baixa_bruto or "Não informado"
        por_motivo[motivo]["quantidade"] += 1
        por_motivo[motivo]["valor"] += b.valor_total or 0

    itens = sorted(
        [
            {
                "id": b.id, "sku": b.sku, "descricao_produto": descricoes.get(b.sku),
                "almoxarifado": b.almoxarifado, "motivo": b.motivo_baixa_bruto,
                "quantidade": b.quantidade, "valor_total": b.valor_total,
                "solicitante_nome": b.solicitante_nome, "data_baixa": str(b.data_baixa) if b.data_baixa else None,
            }
            for b in pendentes
        ],
        key=lambda x: x["valor_total"] or 0,
        reverse=True,
    )

    return {
        "total": len(pendentes),
        "valor_total": round(sum(b.valor_total or 0 for b in pendentes), 2),
        "por_motivo": [{"motivo": k, **v} for k, v in sorted(por_motivo.items(), key=lambda x: -x[1]["valor"])],
        "itens": itens[:100],
    }


def _calcular_risco_obsolescencia(db: Session, dias_minimo: int = DIAS_MINIMO_RISCO_OBSOLESCENCIA) -> dict:
    """Farol de baixo giro: produto com saldo em estoque (> 0) mas sem
    nenhuma saída de movimentação bruta NEM venda faturada nos últimos N
    dias. "Última atividade" é a mais recente entre: última saída
    (qtd_sai > 0) no livro-caixa bruto do sistema, e a última venda
    faturada (Faturamento) - o que vier depois, porque uma transferência
    de entrada não conta como "o produto girou", só saída/venda real
    conta."""
    hoje = date.today()

    linha_num = func.row_number().over(
        partition_by=(models.MovimentacaoBruta.sku, models.MovimentacaoBruta.almoxarifado),
        order_by=(models.MovimentacaoBruta.data.desc(), models.MovimentacaoBruta.id.desc()),
    ).label("rn")
    subq_saldo = db.query(
        models.MovimentacaoBruta.sku,
        models.MovimentacaoBruta.almoxarifado,
        models.MovimentacaoBruta.saldo,
        models.MovimentacaoBruta.data,
        linha_num,
    ).subquery()
    saldo_atual = db.query(subq_saldo).filter(subq_saldo.c.rn == 1, subq_saldo.c.saldo > 0).all()

    ultima_saida = {
        (r.sku, r.almoxarifado): r.ultima_saida
        for r in (
            db.query(
                models.MovimentacaoBruta.sku, models.MovimentacaoBruta.almoxarifado,
                func.max(models.MovimentacaoBruta.data).label("ultima_saida"),
            )
            .filter(models.MovimentacaoBruta.qtd_sai > 0)
            .group_by(models.MovimentacaoBruta.sku, models.MovimentacaoBruta.almoxarifado)
            .all()
        )
    }
    ultima_venda = {
        r.sku: r.ultima_venda
        for r in (
            db.query(models.Faturamento.sku, func.max(models.Faturamento.data_faturamento).label("ultima_venda"))
            .group_by(models.Faturamento.sku)
            .all()
        )
    }
    custos = {p.sku: p.custo_unitario for p in db.query(models.Produto.sku, models.Produto.custo_unitario).all()}
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto.sku, models.Produto.descricao).all()}

    itens = []
    for sku, almox, saldo, data_ult_mov, _rn in saldo_atual:
        candidatos = [d for d in (ultima_saida.get((sku, almox)), ultima_venda.get(sku), data_ult_mov) if d]
        ultima_atividade = max(candidatos) if candidatos else None
        if not ultima_atividade:
            continue
        dias = (hoje - ultima_atividade).days
        if dias < dias_minimo:
            continue
        faixa = "90" if dias >= 90 else ("60" if dias >= 60 else "30")
        custo = custos.get(sku) or 0
        itens.append({
            "sku": sku,
            "descricao_produto": descricoes.get(sku),
            "almoxarifado": almox,
            "saldo_atual": saldo,
            "dias_sem_movimento": dias,
            "ultima_atividade": str(ultima_atividade),
            "valor_estimado": round(saldo * custo, 2),
            "faixa": faixa,
        })
    itens.sort(key=lambda x: x["valor_estimado"], reverse=True)

    resumo = {"30": {"quantidade": 0, "valor": 0.0}, "60": {"quantidade": 0, "valor": 0.0}, "90": {"quantidade": 0, "valor": 0.0}}
    for it in itens:
        resumo[it["faixa"]]["quantidade"] += 1
        resumo[it["faixa"]]["valor"] += it["valor_estimado"]
    for faixa in resumo:
        resumo[faixa]["valor"] = round(resumo[faixa]["valor"], 2)

    return {"resumo": resumo, "itens": itens[:100], "total_itens": len(itens)}


@router.get("/mapa-demandas")
def mapa_demandas(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Painel fixo da tela Início - baixas operacionais pendentes
    (passivo em aberto), risco de obsolescência por baixo giro (farol
    30/60/90 dias) e risco de validade / Shelf Life (farol vencido/30/60/
    90 dias + pendente de validade), calculado a partir dos lotes
    cadastrados na tela Shelf Life (ver shelf_life.py)."""
    return {
        "baixas_pendentes": _calcular_baixas_pendentes(db),
        "obsolescencia": _calcular_risco_obsolescencia(db),
        "shelf_life": shelf_life.calcular_resumo_shelf_life(db, incluir_itens=False),
    }
