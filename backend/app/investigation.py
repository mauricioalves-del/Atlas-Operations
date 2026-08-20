"""
Motor de investigação (regras + evidências).

Correção estrutural em relação à versão anterior: aqui a saída deste motor
(`hipotese_regras`/`confianca_regras`, com distribuição completa em
`_scores_normalizados`) é DEPOIS combinada com a saída do modelo estatístico
(`ml/predict.py`) em `reconciliar()`, gerando uma única `hipotese_ia` /
`confianca_ia` auditável. Antes, regras e ML eram dois "cérebros" que nunca
se falavam.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from sqlalchemy.orm import Session

from . import models, baixas_operacionais
from .hipoteses_config import buscar_evidencias_texto, normalizar_almoxarifado
from .feature_extraction import extrair_sinais_contexto


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

    # 0b) Baixa operacional APROVADA (Avaria, Vencimento, Descarte,
    #     Degustação, Cortesia, Perda/Furto, Uso e Consumo,
    #     Envio/Laboratório, Sensorial/Inovações - sistema Lovable, ver
    #     baixas_operacionais.py) compatível com este SKU+almoxarifado,
    #     dentro da janela de tolerância de data, e que ainda não foi
    #     vinculada a nenhuma outra divergência.
    #
    #     ESTE ERA O ELO QUE FALTAVA (achado em 20/08/2026, a pedido do
    #     Maurício): buscar_baixa_compativel() já existia em
    #     baixas_operacionais.py desde a integração original, e o
    #     docstring do módulo já dizia que "o motor de investigação
    #     procura baixas recebidas que ainda não foram vinculadas a
    #     nenhuma divergência" - mas essa função nunca era chamada por
    #     nenhum motor de verdade. Sem isso, o motor não tinha absolutamente
    #     nenhum jeito de saber se existe (ou não) um registro REAL de
    #     baixa pra esta divergência específica - ele só enxergava padrões
    #     indiretos, como reincidência (item 5 abaixo: "esse SKU já foi
    #     resolvido como Avaria antes, então deve ser Avaria de novo"),
    #     o que pode confirmar uma causa que não tem nenhum documento por
    #     trás desta vez.
    #
    #     Uma baixa já APROVADA é o sinal mais forte que existe neste
    #     motor inteiro (é um documento real, já decidido no fluxo
    #     operacional) - por isso, além de virar evidência de peso bem
    #     acima do normal, ela resolve a divergência automaticamente aqui
    #     mesmo (mesmo efeito que já acontecia no sentido contrário,
    #     quando a baixa chega DEPOIS da divergência - ver
    #     processar_baixa_recebida). Data ainda importa aqui porque
    #     resolver automaticamente é uma ação definitiva - continua usando
    #     buscar_baixa_compativel (SKU + Almoxarifado + janela de data).
    baixa_aprovada_compativel = baixas_operacionais.buscar_baixa_compativel(db, div.sku, div.almoxarifado, div.data_deteccao)
    if (
        baixa_aprovada_compativel
        and baixa_aprovada_compativel.hipotese_aplicada
        and baixa_aprovada_compativel.status_fluxo == baixas_operacionais.STATUS_FLUXO_APROVADO
    ):
        descricao_evidencia = (
            f"baixa_operacional_aprovada_compativel"
            f"('{baixa_aprovada_compativel.motivo_baixa_bruto}', qtd {baixa_aprovada_compativel.quantidade})"
        )
        registrar(baixa_aprovada_compativel.hipotese_aplicada, descricao_evidencia, True,
                   peso=_peso(db, baixa_aprovada_compativel.hipotese_aplicada) * 3.0)
        if div.status != "Resolvida":
            baixas_operacionais.resolver_divergencia_automaticamente(db, div, baixa_aprovada_compativel)

    # 0c) Conciliação com o Relatório de Baixa - baixas ainda PENDENTES
    #     (reformulado em 20/08/2026, a pedido do Maurício: "a tela de
    #     divergência precisa fazer uma conciliação com o relatório de
    #     baixa... considerar Almoxarifado x Item x Quantidade e verificar
    #     se a diferença tem correlação com a baixa pendente,
    #     desconsiderando aprovados e reprovados nessa análise").
    #     Deliberadamente SEM janela de data (ver
    #     calcular_correlacao_baixas_pendentes) - o que conta aqui é se o
    #     Almoxarifado x Item x Quantidade se sustentam, somando todas as
    #     baixas pendentes desse SKU+Almoxarifado, não se a data bate.
    #     Nunca resolve nada sozinho - só entra como evidência (mais forte
    #     que reincidência, mais fraca que uma baixa já aprovada) - a
    #     baixa pendente ainda pode ser reprovada. A tela de divergências
    #     mostra esse mesmo aviso separadamente (ver
    #     buscar_avisos_baixa_pendente, chamado em divergencias_router.py).
    correlacao_pendente = baixas_operacionais.calcular_correlacao_baixas_pendentes(
        db, div.sku, div.almoxarifado, div.divergencia_qtd
    )
    if correlacao_pendente:
        contagem_hipoteses = Counter(
            b.hipotese_aplicada for b in correlacao_pendente["baixas"] if b.hipotese_aplicada
        )
        if contagem_hipoteses:
            hipotese_dominante, _ = contagem_hipoteses.most_common(1)[0]
            descricao_evidencia = (
                f"baixa_operacional_pendente_correlacionada(soma_qtd_pendente="
                f"{correlacao_pendente['soma_quantidade_pendente']:g}, "
                f"diferenca_relativa={round(correlacao_pendente['diferenca_relativa'] * 100, 1)}%)"
            )
            peso_correlacao = _peso(db, hipotese_dominante) * (1.75 if correlacao_pendente["correlaciona_bem"] else 1.1)
            registrar(hipotese_dominante, descricao_evidencia, True, peso=peso_correlacao)

    # Sinais de contexto (transferência, pedido de compra, OP, ficha
    # técnica, faturamento) - extraídos numa função compartilhada com o
    # ML (feature_extraction.py), pra regra e modelo estatístico
    # enxergarem exatamente o mesmo contexto operacional.
    sinais = extrair_sinais_contexto(db, div.sku, div.almoxarifado, div.data_deteccao, div.divergencia_qtd)

    # 1) Transferência pendente: saída registrada sem entrada, no mesmo SKU,
    #    tendo o almoxarifado da divergência como origem ou destino.
    registrar("Transferencia_Pendente", "transferencia_sem_entrada_correspondente", sinais["tem_transferencia_pendente"])

    # 1b) Pedido de compra pendente (controle de estoque externo): se a
    #     divergência é uma FALTA (saldo físico < sistema) e existe
    #     pedido de compra em aberto/parcial pra esse SKU+almoxarifado com
    #     saldo pendente, a "falta" provavelmente é mercadoria ainda em
    #     trânsito com o fornecedor, não perda real. Peso cheio se a
    #     magnitude da falta bate com o pendente (tolerância de 20%),
    #     peso parcial se só existe pedido aberto mas a magnitude não bate.
    peso_pedido = None
    if sinais["tem_pedido_compra_pendente"]:
        pedidos_abertos = (
            db.query(models.PedidoCompra)
            .filter(
                models.PedidoCompra.sku == div.sku,
                models.PedidoCompra.almoxarifado_destino == div.almoxarifado,
                models.PedidoCompra.status.in_(["Aberto", "Parcialmente_Recebido"]),
            )
            .all()
        )
        pendente_total = sum(
            max(0, p.quantidade_pedida - sum(r.quantidade_recebida for r in db.query(models.RecebimentoPedido).filter_by(pedido_id=p.id).all()))
            for p in pedidos_abertos
        )
        falta = abs(div.divergencia_qtd or 0)
        diferenca_relativa = abs(falta - pendente_total) / pendente_total if pendente_total else 1.0
        peso_base = _peso(db, "Pedido_Compra_Pendente")
        peso_pedido = peso_base if diferenca_relativa <= 0.2 else peso_base * 0.5
    registrar("Pedido_Compra_Pendente", "pedido_compra_em_aberto_com_saldo_pendente_compativel", sinais["tem_pedido_compra_pendente"], peso=peso_pedido)

    # 2) Consumo parcial de OP: existe OP aberta (não Produzida) para o SKU,
    #    ou consumo registrado divergente do previsto na ficha técnica.
    registrar("Consumo_Parcial_OP", "op_aberta_para_sku", sinais["tem_op_aberta"])
    registrar("Consumo_Parcial_OP", "consumo_diferente_do_previsto_ficha_tecnica", sinais["tem_consumo_divergente_bom"], peso=_peso(db, "Consumo_Parcial_OP") * 0.5)

    # 3) Pendência de faturamento: existe nota de faturamento para o SKU
    #    próxima (+/- 5 dias) da data de detecção. Peso cheio quando a
    #    origem do faturamento é o MESMO almoxarifado da divergência (o
    #    sinal fica bem mais forte: a venda aconteceu ali e pode não ter
    #    sido baixada do sistema corretamente) - peso reduzido quando só
    #    bate SKU+data, sem confirmar o local (ainda vale olhar, mas com
    #    menos confiança).
    peso_fat = None
    if sinais["tem_faturamento_proximo"]:
        peso_fat = _peso(db, "Pendencia_Faturamento") if sinais["tem_faturamento_mesmo_almoxarifado"] else _peso(db, "Pendencia_Faturamento") * 0.5
    registrar(
        "Pendencia_Faturamento",
        "faturamento_proximo_a_data_deteccao" + (" (mesmo_almoxarifado)" if sinais["tem_faturamento_mesmo_almoxarifado"] else ""),
        sinais["tem_faturamento_proximo"], peso=peso_fat,
    )

    # 4) Divergência de ficha técnica: SKU aparece como item numa BOM mas
    #    o consumo real diverge de forma sistemática (proxy simples).
    registrar(
        "Divergencia_Ficha_Tecnica", "sku_e_item_de_ficha_tecnica_com_consumo_divergente",
        sinais["e_item_de_ficha_tecnica"] and sinais["tem_consumo_divergente_bom"], peso=_peso(db, "Divergencia_Ficha_Tecnica") * 0.6,
    )

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


def _num_ou_none(valor):
    """Converte NaN pra None antes de ir pro JSON - um float NaN
    serializa como o token literal `NaN`, que não é JSON válido (RFC
    8259). O SQLite nunca cobrou isso ao gravar numa coluna JSON, mas o
    Postgres valida a sintaxe de verdade e rejeita a linha inteira."""
    try:
        if valor is None or (isinstance(valor, float) and valor != valor):  # NaN != NaN é sempre True
            return None
    except Exception:
        return None
    return valor


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
            "criterio": "mesmo_sku", "almoxarifado": c.almoxarifado, "divergencia_qtd": _num_ou_none(c.divergencia),
            "valor": _num_ou_none(c.valor_divergencia), "fonte": "historico",
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
            "criterio": "mesmo_sku", "almoxarifado": c.almoxarifado, "divergencia_qtd": _num_ou_none(c.divergencia_qtd),
            "valor": _num_ou_none(c.valor_estimado), "fonte": "divergencia_resolvida",
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
                "divergencia_qtd": _num_ou_none(c.divergencia), "valor": _num_ou_none(c.valor_divergencia), "fonte": "historico",
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
