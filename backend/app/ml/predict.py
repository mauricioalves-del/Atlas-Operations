import os
import joblib
import pandas as pd

from .train import NOMES_SINAIS_CONTEXTO
from ..feature_extraction import extrair_sinais_contexto

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.joblib")

_modelo_cache = None


def _carregar_modelo():
    global _modelo_cache
    if _modelo_cache is None:
        if not os.path.exists(MODEL_PATH):
            return None
        _modelo_cache = joblib.load(MODEL_PATH)
    return _modelo_cache


def prever(sku, almoxarifado, categoria_produto, divergencia_qtd, valor_estimado, data_deteccao, db=None) -> dict:
    """Retorna None se o modelo ainda não foi treinado (fail-soft: o motor
    de regras continua funcionando de qualquer forma - o ML é um sinal
    adicional, não uma dependência obrigatória).

    `db` é opcional só por retrocompatibilidade de assinatura - sem ele,
    os sinais de contexto (OP, BOM, faturamento, transferência, pedido de
    compra) entram como 0/ausente, e a previsão fica baseada só nas
    features originais (almoxarifado/categoria/quantidade/valor/dia).
    Passe `db` sempre que possível para a previsão usar o mesmo contexto
    que o motor de regras vê."""
    modelo = _carregar_modelo()
    if modelo is None:
        return None

    dia_semana = pd.to_datetime(str(data_deteccao)).dayofweek if data_deteccao else -1

    linha = {
        "almoxarifado": almoxarifado or "Desconhecido",
        "categoria_produto": categoria_produto or "Desconhecido",
        "divergencia_qtd": divergencia_qtd or 0,
        "valor": valor_estimado or 0,
        "dia_semana": dia_semana,
    }
    if db is not None:
        sinais = extrair_sinais_contexto(db, sku=sku, almoxarifado=almoxarifado, data_referencia=data_deteccao, divergencia_qtd=divergencia_qtd)
        linha.update({nome: int(sinais[nome]) for nome in NOMES_SINAIS_CONTEXTO})
    else:
        linha.update({nome: 0 for nome in NOMES_SINAIS_CONTEXTO})

    X = pd.DataFrame([linha])

    # o modelo pode ter sido treinado sem alguma coluna nova (modelo
    # antigo carregado em cache) - preenche o que faltar com 0 em vez de
    # quebrar, e ignora colunas que o modelo não conhece.
    colunas_esperadas = list(modelo.named_steps["pre"].feature_names_in_)
    for c in colunas_esperadas:
        if c not in X.columns:
            X[c] = 0
    X = X[colunas_esperadas]

    proba = modelo.predict_proba(X)[0]
    classes = modelo.named_steps["rf"].classes_
    ranked = sorted(zip(classes, proba), key=lambda t: t[1], reverse=True)
    top_hipotese, top_conf = ranked[0]

    return {
        "hipotese_predita": top_hipotese,
        "confianca": round(float(top_conf) * 100, 1),
        "distribuicao": [
            {"hipotese": c, "confianca": round(float(p) * 100, 1)}
            for c, p in ranked if p > 0.01
        ],
    }


def invalidar_cache():
    global _modelo_cache
    _modelo_cache = None
