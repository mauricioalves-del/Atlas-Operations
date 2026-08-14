"""
Cálculo de checagens de FEFO (First-Expired-First-Out) - ver docstring de
models.ChecagemFefo pra regra completa e a suposição documentada. Isolado
num módulo próprio (fora do router) pra facilitar troca da regra sem tocar
em HTTP/permissões.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session

from . import models

ALMOXARIFADO_FABRICA = "Almox_SP_Fabrica"
JANELA_DIAS_UTEIS = 5  # prazo operacional de movimentação mencionado pelo usuário (18/08/2026)


def _dias_uteis_entre(data_inicio: date, data_fim: date) -> int:
    """Dias úteis (seg-sex) entre duas datas, sem contar a data_inicio -
    não considera feriados (não há calendário de feriados no sistema hoje;
    se isso importar, dá pra plugar uma lista de feriados aqui depois)."""
    if not data_inicio or not data_fim or data_fim <= data_inicio:
        return 0
    dias = 0
    d = data_inicio
    while d < data_fim:
        d += timedelta(days=1)
        if d.weekday() < 5:
            dias += 1
    return dias


def calcular_checagem_fefo(db: Session, transferencia: models.Transferencia, hoje: date = None) -> dict:
    """Calcula o resultado de uma checagem de FEFO pra uma Transferencia
    elegível (origem = Fábrica) - ver models.ChecagemFefo pra regra
    completa. Retorna um dict pronto pra popular/atualizar um
    ChecagemFefo (sem tocar no banco - quem chama decide se faz upsert)."""
    hoje = hoje or date.today()

    base = {
        "transferencia_id": transferencia.id,
        "sku": transferencia.sku,
        "descricao_produto": transferencia.descricao,
        "almoxarifado_origem": transferencia.almoxarifado_origem,
        "almoxarifado_destino": transferencia.almoxarifado_destino,
        "data_saida": transferencia.data_saida,
        "quantidade_transferida": transferencia.quantidade,
    }

    lotes_sku_fabrica = db.query(models.LoteShelfLife).filter(
        models.LoteShelfLife.sku == transferencia.sku,
        models.LoteShelfLife.almoxarifado == ALMOXARIFADO_FABRICA,
        models.LoteShelfLife.ativo.is_(True),
    ).all()

    if not lotes_sku_fabrica:
        # não temos NENHUM lote cadastrado desse SKU na Fábrica (planilha
        # de Lote_Sistema nunca trouxe esse SKU, ou ele não é rastreado
        # por lote/validade) - não dá pra avaliar FEFO sem essa base.
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Sem_Dado_Suficiente"}

    candidatos = [l for l in lotes_sku_fabrica if l.data_validade and (l.quantidade or 0) > 0]
    if not candidatos:
        # temos cadastro do SKU na Fábrica, mas nenhum lote com validade
        # conhecida E estoque positivo sobrando lá - nada em risco.
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Dentro_Do_Criterio"}

    if not transferencia.data_saida:
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Sem_Dado_Suficiente"}

    lote_mais_antigo = min(candidatos, key=lambda l: l.data_validade)
    dias_uteis = _dias_uteis_entre(transferencia.data_saida, hoje)
    resultado = "Quebra_Fefo" if dias_uteis > JANELA_DIAS_UTEIS else "Dentro_Do_Criterio"

    return {
        **base,
        "lote_mais_antigo_sku": lote_mais_antigo.lote,
        "validade_lote_mais_antigo": lote_mais_antigo.data_validade,
        "quantidade_remanescente_lote_antigo": lote_mais_antigo.quantidade,
        "dias_uteis_em_aberto": dias_uteis,
        "resultado": resultado,
    }


def recalcular_checagens_fefo(db: Session, hoje: date = None) -> dict:
    """Roda a checagem pra toda Transferencia elegível (origem = Fábrica,
    com sku e data_saida preenchidos) e faz upsert em ChecagemFefo por
    transferencia_id. Idempotente - pode ser chamado quantas vezes quiser
    (ex: de novo depois de reimportar a planilha de lotes, ou num
    agendador diário)."""
    transferencias = db.query(models.Transferencia).filter(
        models.Transferencia.almoxarifado_origem == ALMOXARIFADO_FABRICA,
        models.Transferencia.sku.isnot(None),
    ).all()

    criadas, atualizadas = 0, 0
    for transf in transferencias:
        campos = calcular_checagem_fefo(db, transf, hoje=hoje)
        existente = db.query(models.ChecagemFefo).filter_by(transferencia_id=transf.id).first()
        if existente:
            for chave, valor in campos.items():
                setattr(existente, chave, valor)
            from datetime import datetime
            existente.calculado_em = datetime.utcnow()
            atualizadas += 1
        else:
            db.add(models.ChecagemFefo(**campos))
            criadas += 1

    return {"transferencias_avaliadas": len(transferencias), "checagens_criadas": criadas, "checagens_atualizadas": atualizadas}
