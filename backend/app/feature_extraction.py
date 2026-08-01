"""
Extração dos sinais de contexto (transferência pendente, pedido de compra
pendente, OP aberta, consumo divergente da ficha técnica, item de BOM
comprado de fornecedor, faturamento próximo) - usados tanto pelo motor de
regras (investigation.py) quanto pelo modelo de ML (ml/train.py,
ml/predict.py).

Ter isso num lugar só é o ponto principal: antes, cada verificação vivia
duplicada dentro de investigation.py, e o ML nunca via nenhum desses
sinais - ele só usava almoxarifado/categoria/quantidade/valor/dia da
semana, sem noção de contexto operacional (não sabia se tinha uma OP
aberta ou um pedido de compra pendente pra aquele SKU). Com essa função
compartilhada, o motor de regras aplica peso fixo pra cada evidência, e o
ML aprende empiricamente o quanto cada sinal realmente importa - os dois
"cérebros" agora enxergam o mesmo contexto.
"""
from datetime import timedelta, date
from sqlalchemy.orm import Session

from . import models
from .hipoteses_config import normalizar_almoxarifado

NOMES_SINAIS_CONTEXTO = [
    "tem_transferencia_pendente",
    "tem_pedido_compra_pendente",
    "tem_op_aberta",
    "tem_consumo_divergente_bom",
    "e_item_de_ficha_tecnica",
    "item_gera_oc",
    "tem_faturamento_proximo",
    "tem_faturamento_mesmo_almoxarifado",
]


def extrair_sinais_contexto(db: Session, sku: str, almoxarifado: str, data_referencia: date | None, divergencia_qtd: float | None = None) -> dict:
    """Retorna um dict {nome_sinal: bool} - sempre com as mesmas chaves
    (NOMES_SINAIS_CONTEXTO), mesmo quando não há dado suficiente pra
    avaliar algum sinal (fica False, não None - simplifica o uso tanto
    como evidência quanto como feature numérica pro ML)."""
    sinais = {nome: False for nome in NOMES_SINAIS_CONTEXTO}

    transf_pendente = (
        db.query(models.Transferencia)
        .filter(models.Transferencia.sku == sku, models.Transferencia.data_entrada.is_(None))
        .filter((models.Transferencia.almoxarifado_origem == almoxarifado) | (models.Transferencia.almoxarifado_destino == almoxarifado))
        .first()
    )
    sinais["tem_transferencia_pendente"] = transf_pendente is not None

    if divergencia_qtd is not None and divergencia_qtd < 0:
        pedidos_abertos = (
            db.query(models.PedidoCompra)
            .filter(
                models.PedidoCompra.sku == sku,
                models.PedidoCompra.almoxarifado_destino == almoxarifado,
                models.PedidoCompra.status.in_(["Aberto", "Parcialmente_Recebido"]),
            )
            .all()
        )
        pendente_total = 0.0
        for p in pedidos_abertos:
            recebido = sum(r.quantidade_recebida for r in db.query(models.RecebimentoPedido).filter_by(pedido_id=p.id).all())
            pendente_total += max(0, p.quantidade_pedida - recebido)
        sinais["tem_pedido_compra_pendente"] = pendente_total > 0

    op_aberta = (
        db.query(models.OrdemProducao)
        .filter(models.OrdemProducao.sku_produto_final == sku, models.OrdemProducao.status != "Produzida")
        .first()
    )
    sinais["tem_op_aberta"] = op_aberta is not None

    consumo_divergente = (
        db.query(models.ConsumoOP)
        .filter(models.ConsumoOP.sku_material == sku, models.ConsumoOP.qtd_diferenca != 0)
        .first()
    )
    sinais["tem_consumo_divergente_bom"] = consumo_divergente is not None

    bom = db.query(models.FichaTecnicaBOM).filter(models.FichaTecnicaBOM.sku_item == sku).first()
    sinais["e_item_de_ficha_tecnica"] = bom is not None
    sinais["item_gera_oc"] = bool(bom.gera_oc) if (bom and bom.gera_oc is not None) else False

    if data_referencia is not None:
        faturamentos_proximos = (
            db.query(models.Faturamento)
            .filter(
                models.Faturamento.sku == sku,
                models.Faturamento.data_faturamento >= data_referencia - timedelta(days=5),
                models.Faturamento.data_faturamento <= data_referencia + timedelta(days=5),
            )
            .all()
        )
        sinais["tem_faturamento_proximo"] = len(faturamentos_proximos) > 0
        sinais["tem_faturamento_mesmo_almoxarifado"] = any(
            f.origem and normalizar_almoxarifado(f.origem) == almoxarifado for f in faturamentos_proximos
        )

    return sinais
