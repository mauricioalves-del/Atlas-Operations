"""
Cálculo/snapshot do resumo mensal de "Controle de Movimentados" - ver
models.ResumoMovimentacaoMensal pro motivo de existir uma tabela separada
em vez do dashboard só consultar MovimentacaoHistorico/Divergencia direto
a cada carregamento (resumo: essas duas tabelas de origem não são
garantidas estáveis no longo prazo - o livro-caixa bruto é substituído
por completo a cada reimportação de um almoxarifado).
"""
from collections import defaultdict
from datetime import datetime
from sqlalchemy.orm import Session

from . import models


def _mes_str(d):
    return f"{d.year:04d}-{d.month:02d}" if d else None


def atualizar_resumo_mensal(db: Session) -> dict:
    """Recalcula e faz upsert do resumo mensal (linha geral por mês, com
    almoxarifado=None, + uma linha por almoxarifado) a partir do estado
    ATUAL de MovimentacaoHistorico/Divergencia (origem == "movimentacao" -
    não mistura com o fluxo de Fechamento de Inventário). Idempotente -
    seguro de chamar a cada carregamento do dashboard: o valor de um mês já
    fechado só muda se a fonte ainda tiver dados pra ele; se a fonte for
    substituída/esvaziada depois, o último valor calculado aqui permanece
    guardado (não é apagado nem recalculado pra zero)."""
    historico = db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.origem == "movimentacao").all()
    divergencias = db.query(models.Divergencia).filter(models.Divergencia.origem == "movimentacao").all()

    agregados = defaultdict(lambda: {"analisados": 0, "sem_divergencia": 0, "valor": 0.0})

    for h in historico:
        mes = _mes_str(h.data_movimento)
        if not mes:
            continue
        for chave in ((mes, None), (mes, h.almoxarifado)):
            agregados[chave]["analisados"] += 1
            if not h.divergencia:
                agregados[chave]["sem_divergencia"] += 1
            else:
                agregados[chave]["valor"] += abs(h.valor_divergencia or 0)

    for d in divergencias:
        mes = _mes_str(d.data_deteccao)
        if not mes:
            continue
        for chave in ((mes, None), (mes, d.almoxarifado)):
            agregados[chave]["analisados"] += 1
            agregados[chave]["valor"] += abs(d.valor_estimado or 0)

    criadas, atualizadas = 0, 0
    for (mes, almox), v in agregados.items():
        analisados = v["analisados"]
        sem_div = v["sem_divergencia"]
        campos = dict(
            itens_analisados=analisados,
            itens_sem_divergencia=sem_div,
            itens_com_divergencia=analisados - sem_div,
            pct_acuracia=round(sem_div / analisados * 100, 2) if analisados else None,
            valor_total_divergencias=round(v["valor"], 2),
            atualizado_em=datetime.utcnow(),
        )
        existente = db.query(models.ResumoMovimentacaoMensal).filter_by(mes=mes, almoxarifado=almox).first()
        if existente:
            for chave, valor in campos.items():
                setattr(existente, chave, valor)
            atualizadas += 1
        else:
            db.add(models.ResumoMovimentacaoMensal(mes=mes, almoxarifado=almox, **campos))
            criadas += 1

    return {
        "meses_processados": len({mes for mes, _ in agregados}),
        "linhas_criadas": criadas,
        "linhas_atualizadas": atualizadas,
    }


def atualizar_resumo_transferencias_mensal(db: Session) -> dict:
    """Recalcula e faz upsert do resumo mensal de Transferências (uma
    linha por mês, baseada em data_saida) cruzado com a checagem de FEFO
    (ChecagemFefo, por transferencia_id) - ver
    models.ResumoTransferenciasMensal pro motivo de guardar isso numa
    tabela separada em vez de recalcular direto de Transferencia/
    ChecagemFefo a cada carregamento. Não recalcula a checagem de FEFO em
    si - quem chama decide se roda fefo.recalcular_checagens_fefo antes
    (o dashboard chama os dois em sequência, ver movimentados_router)."""
    transferencias = db.query(models.Transferencia).filter(models.Transferencia.data_saida.isnot(None)).all()
    checagens_por_transferencia = {c.transferencia_id: c for c in db.query(models.ChecagemFefo).all()}

    por_mes = defaultdict(lambda: {"total": 0, "quantidade": 0.0, "avaliadas": 0, "quebras": 0})
    for t in transferencias:
        mes = _mes_str(t.data_saida)
        if not mes:
            continue
        v = por_mes[mes]
        v["total"] += 1
        v["quantidade"] += t.quantidade or 0
        checagem = checagens_por_transferencia.get(t.id)
        if checagem and checagem.resultado != "Sem_Dado_Suficiente":
            v["avaliadas"] += 1
            if checagem.resultado == "Quebra_Fefo":
                v["quebras"] += 1

    criadas, atualizadas = 0, 0
    for mes, v in por_mes.items():
        campos = dict(
            total_transferencias=v["total"],
            quantidade_total=round(v["quantidade"], 2),
            transferencias_fabrica_avaliadas=v["avaliadas"],
            quebras_fefo=v["quebras"],
            taxa_quebra_fefo_pct=round(v["quebras"] / v["avaliadas"] * 100, 2) if v["avaliadas"] else None,
            atualizado_em=datetime.utcnow(),
        )
        existente = db.query(models.ResumoTransferenciasMensal).filter_by(mes=mes).first()
        if existente:
            for chave, valor in campos.items():
                setattr(existente, chave, valor)
            atualizadas += 1
        else:
            db.add(models.ResumoTransferenciasMensal(mes=mes, **campos))
            criadas += 1

    return {"meses_processados": len(por_mes), "linhas_criadas": criadas, "linhas_atualizadas": atualizadas}
