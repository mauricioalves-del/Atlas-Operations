"""
Motor de investigação (regras + evidências).

Correção estrutural em relação à versão anterior: aqui a saída deste motor
(`hipotese_regras`/`confianca_regras`, com distribuição completa em
`_scores_normalizados`) é DEPOIS combinada com a saída do modelo estatístico
(`ml/predict.py`) em `reconciliar()`, gerando uma única `hipotese_ia` /
`confianca_ia` auditável. Antes, regras e ML eram dois "cérebros" que nunca
se falavam.
"""
from collections import defaultdict
from datetime import timedelta
from sqlalchemy.orm import Session

from . import models
from .hipoteses_config import buscar_evidencias_texto


def _peso(db: Session, codigo_hipotese: str) -> float:
    h = db.query(models.Hipotese).filter_by(codigo=codigo_hipotese).first()
    return h.peso_padrao if h else 20.0


def investigar(db: Session, div: models.Divergencia) -> dict:
    """Roda a árvore de hipóteses sobre uma Divergencia recém-criada.
    Retorna dict com evidencias, scores normalizados (0-100 por hipótese),
    hipótese/confiança do motor de regras e casos similares."""
    evidencias = []
    scores = defaultdict(float)

    def registrar(hipotese, nome_evidencia, encontrado, peso=None):
        peso = peso if peso is not None else _peso(db, hipotese)
        evidencias.append({
            "hipotese": hipotese,
            "verificacao": nome_evidencia,
            "encontrado": bool(encontrado),
            "peso_aplicado": peso if encontrado else 0,
        })
        if encontrado:
            scores[hipotese] += peso

    # 0) Observação original da planilha (texto livre, escrita à mão por
    #    quem fez a contagem). Isso costuma ser a pista mais direta que
    #    existe - "avaria", "consumo interno", "transf. pendente" etc já
    #    dizem a causa. Entra como evidência igual às outras, não decide
    #    por si só (mais de uma palavra-chave pode bater, ou nenhuma).
    for codigo_hipotese, palavra_chave in buscar_evidencias_texto(getattr(div, "observacao_origem", None)):
        registrar(codigo_hipotese, f"observacao_planilha_menciona('{palavra_chave}')", True)

    # 1) Transferência pendente: saída registrada sem entrada, no mesmo SKU,
    #    tendo o almoxarifado da divergência como origem ou destino.
    transf_pendente = (
        db.query(models.Transferencia)
        .filter(
            models.Transferencia.sku == div.sku,
            models.Transferencia.data_entrada.is_(None),
        )
        .filter(
            (models.Transferencia.almoxarifado_origem == div.almoxarifado)
            | (models.Transferencia.almoxarifado_destino == div.almoxarifado)
        )
        .first()
    )
    registrar("Transferencia_Pendente", "transferencia_sem_entrada_correspondente", transf_pendente is not None)

    # 1b) Pedido de compra pendente (controle de estoque externo): se a
    #     divergência é uma FALTA (saldo físico < sistema) e existe
    #     pedido de compra em aberto/parcial pra esse SKU+almoxarifado com
    #     saldo pendente, a "falta" provavelmente é mercadoria ainda em
    #     trânsito com o fornecedor, não perda real. Peso cheio se a
    #     magnitude da falta bate com o pendente (tolerância de 20%),
    #     peso parcial se só existe pedido aberto mas a magnitude não bate.
    pedido_pendente_encontrado = False
    peso_pedido = None
    if div.divergencia_qtd is not None and div.divergencia_qtd < 0:
        pedidos_abertos = (
            db.query(models.PedidoCompra)
            .filter(
                models.PedidoCompra.sku == div.sku,
                models.PedidoCompra.almoxarifado_destino == div.almoxarifado,
                models.PedidoCompra.status.in_(["Aberto", "Parcialmente_Recebido"]),
            )
            .all()
        )
        pendente_total = 0.0
        for p in pedidos_abertos:
            recebido = sum(r.quantidade_recebida for r in db.query(models.RecebimentoPedido).filter_by(pedido_id=p.id).all())
            pendente_total += max(0, p.quantidade_pedida - recebido)
        if pendente_total > 0:
            pedido_pendente_encontrado = True
            falta = abs(div.divergencia_qtd)
            diferenca_relativa = abs(falta - pendente_total) / pendente_total
            peso_base = _peso(db, "Pedido_Compra_Pendente")
            peso_pedido = peso_base if diferenca_relativa <= 0.2 else peso_base * 0.5
    registrar("Pedido_Compra_Pendente", "pedido_compra_em_aberto_com_saldo_pendente_compativel", pedido_pendente_encontrado, peso=peso_pedido)

    # 2) Consumo parcial de OP: existe OP aberta (não Produzida) para o SKU,
    #    ou consumo registrado divergente do previsto na ficha técnica.
    op_aberta = (
        db.query(models.OrdemProducao)
        .filter(
            models.OrdemProducao.sku_produto_final == div.sku,
            models.OrdemProducao.status != "Produzida",
        )
        .first()
    )
    consumo_divergente = (
        db.query(models.ConsumoOP)
        .filter(
            models.ConsumoOP.sku_material == div.sku,
            models.ConsumoOP.qtd_diferenca != 0,
        )
        .first()
    )
    registrar("Consumo_Parcial_OP", "op_aberta_para_sku", op_aberta is not None)
    registrar("Consumo_Parcial_OP", "consumo_diferente_do_previsto_ficha_tecnica", consumo_divergente is not None, peso=_peso(db, "Consumo_Parcial_OP") * 0.5)

    # 3) Pendência de faturamento: existe nota de faturamento para o SKU
    #    próxima (+/- 5 dias) da data de detecção.
    fat_proxima = (
        db.query(models.Faturamento)
        .filter(
            models.Faturamento.sku == div.sku,
            models.Faturamento.data_faturamento >= div.data_deteccao - timedelta(days=5),
            models.Faturamento.data_faturamento <= div.data_deteccao + timedelta(days=5),
        )
        .first()
    )
    registrar("Pendencia_Faturamento", "faturamento_proximo_a_data_deteccao", fat_proxima is not None)

    # 4) Divergência de ficha técnica: SKU aparece como item numa BOM mas
    #    o consumo real diverge de forma sistemática (proxy simples).
    bom = db.query(models.FichaTecnicaBOM).filter(models.FichaTecnicaBOM.sku_item == div.sku).first()
    registrar("Divergencia_Ficha_Tecnica", "sku_e_item_de_ficha_tecnica_com_consumo_divergente", bom is not None and consumo_divergente is not None, peso=_peso(db, "Divergencia_Ficha_Tecnica") * 0.6)

    # 5) Reincidência: mesmo SKU ou almoxarifado com divergência resolvida
    #    nos últimos 90 dias -> reforça a hipótese mais comum encontrada.
    janela = div.data_deteccao - timedelta(days=90)
    reincidencias = (
        db.query(models.Divergencia)
        .filter(
            models.Divergencia.status == "Resolvida",
            models.Divergencia.data_deteccao >= janela,
            models.Divergencia.data_deteccao < div.data_deteccao,
        )
        .filter((models.Divergencia.sku == div.sku) | (models.Divergencia.almoxarifado == div.almoxarifado))
        .all()
    )
    if reincidencias:
        contagem = defaultdict(int)
        for r in reincidencias:
            if r.hipotese_confirmada:
                contagem[r.hipotese_confirmada] += 1
        if contagem:
            top_reincidente = max(contagem, key=contagem.get)
            registrar(top_reincidente, "reincidencia_sku_ou_almoxarifado_90_dias", True, peso=_peso(db, top_reincidente) * 0.4)

    # 6) Falha de inventário: nenhuma evidência documental encontrada em
    #    nenhuma das checagens acima -> divergência "pura", provável erro
    #    de contagem física/sistema.
    nenhuma_evidencia_documental = not any(e["encontrado"] for e in evidencias)
    registrar("Falha_Inventario", "ausencia_de_qualquer_documento_associado", nenhuma_evidencia_documental)

    # 7) Erro operacional: divergência pequena (proxy: <= 2 unidades ou <=1% do saldo de sistema) sem nenhum documento.
    saldo_base = abs(div.saldo_sistema) if div.saldo_sistema else 0
    pequena = abs(div.divergencia_qtd) <= 2 or (saldo_base > 0 and abs(div.divergencia_qtd) / saldo_base <= 0.01)
    registrar("Erro_Operacional", "divergencia_pequena_sem_documento", pequena and nenhuma_evidencia_documental)

    # --- normalização 0-100 ---
    total = sum(scores.values())
    scores_normalizados = {h: round(v / total * 100, 1) for h, v in scores.items()} if total > 0 else {}

    hipotese_regras = max(scores_normalizados, key=scores_normalizados.get) if scores_normalizados else None
    confianca_regras = scores_normalizados.get(hipotese_regras) if hipotese_regras else None

    casos_similares = _buscar_casos_similares(db, div)

    return {
        "evidencias": evidencias,
        "scores_normalizados": scores_normalizados,
        "hipotese_regras": hipotese_regras,
        "confianca_regras": confianca_regras,
        "casos_similares": casos_similares,
    }


def _buscar_casos_similares(db: Session, div: models.Divergencia, limite: int = 8) -> list:
    """Casos já resolvidos (histórico + divergências já confirmadas nesta
    versão do sistema) com o mesmo SKU (prioridade) ou mesma combinação
    categoria+almoxarifado. Traz dados suficientes pra reconstruir uma
    mini linha do tempo do SKU sem precisar de outra consulta."""
    resultado = []

    mesmo_sku_historico = (
        db.query(models.MovimentacaoHistorico)
        .filter(models.MovimentacaoHistorico.sku == div.sku, models.MovimentacaoHistorico.hipotese_confirmada.isnot(None))
        .order_by(models.MovimentacaoHistorico.data_movimento.desc())
        .limit(limite)
        .all()
    )
    for c in mesmo_sku_historico:
        resultado.append({
            "sku": c.sku, "hipotese_confirmada": c.hipotese_confirmada, "data": str(c.data_movimento),
            "criterio": "mesmo_sku", "almoxarifado": c.almoxarifado, "divergencia_qtd": c.divergencia,
            "valor": c.valor_divergencia, "fonte": "historico",
        })

    mesmo_sku_resolvidas = (
        db.query(models.Divergencia)
        .filter(
            models.Divergencia.sku == div.sku, models.Divergencia.status == "Resolvida",
            models.Divergencia.hipotese_confirmada.isnot(None), models.Divergencia.id != (div.id or -1),
        )
        .order_by(models.Divergencia.data_deteccao.desc())
        .limit(limite)
        .all()
    )
    for c in mesmo_sku_resolvidas:
        resultado.append({
            "sku": c.sku, "hipotese_confirmada": c.hipotese_confirmada, "data": str(c.data_deteccao),
            "criterio": "mesmo_sku", "almoxarifado": c.almoxarifado, "divergencia_qtd": c.divergencia_qtd,
            "valor": c.valor_estimado, "fonte": "divergencia_resolvida",
            "solucao_aplicada": c.solucao_aplicada, "responsavel": c.responsavel,
        })

    resultado.sort(key=lambda x: x["data"], reverse=True)
    resultado = resultado[:limite]

    if len(resultado) < limite:
        similares = (
            db.query(models.MovimentacaoHistorico)
            .filter(
                models.MovimentacaoHistorico.categoria_produto == div.categoria_produto,
                models.MovimentacaoHistorico.almoxarifado == div.almoxarifado,
                models.MovimentacaoHistorico.hipotese_confirmada.isnot(None),
                models.MovimentacaoHistorico.sku != div.sku,
            )
            .order_by(models.MovimentacaoHistorico.data_movimento.desc())
            .limit(limite - len(resultado))
            .all()
        )
        for c in similares:
            resultado.append({
                "sku": c.sku, "hipotese_confirmada": c.hipotese_confirmada, "data": str(c.data_movimento),
                "criterio": "categoria_e_almoxarifado_semelhantes", "almoxarifado": c.almoxarifado,
                "divergencia_qtd": c.divergencia, "valor": c.valor_divergencia, "fonte": "historico",
            })

    # descrição do produto - essencial pra não obrigar quem está lendo a
    # decorar/adivinhar o que cada código de SKU significa, principalmente
    # nos casos "categoria_e_almoxarifado_semelhantes" que são de OUTRO SKU.
    skus_envolvidos = {c["sku"] for c in resultado}
    if skus_envolvidos:
        descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus_envolvidos)).all()}
        for c in resultado:
            c["descricao_produto"] = descricoes.get(c["sku"])

    return resultado


def reconciliar(scores_regras: dict, distribuicao_ml: list, peso_regras: float = 0.5) -> tuple:
    """Funde o sinal do motor de regras com o sinal do modelo estatístico
    num único score por hipótese, e devolve (hipotese_final, confianca_final).

    distribuicao_ml: lista de {"hipotese": str, "confianca": float(0-100)}
    """
    combinado = defaultdict(float)
    for h, v in (scores_regras or {}).items():
        combinado[h] += v * peso_regras
    for item in (distribuicao_ml or []):
        combinado[item["hipotese"]] += item["confianca"] * (1 - peso_regras)

    if not combinado:
        return None, None

    hipotese_final = max(combinado, key=combinado.get)
    confianca_final = round(combinado[hipotese_final], 1)
    return hipotese_final, confianca_final
