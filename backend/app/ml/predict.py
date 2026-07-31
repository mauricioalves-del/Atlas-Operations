import os
import joblib
import pandas as pd

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.joblib")

_modelo_cache = None


def _carregar_modelo():
    global _modelo_cache
    if _modelo_cache is None:
        if not os.path.exists(MODEL_PATH):
            return None
        _modelo_cache = joblib.load(MODEL_PATH)
    return _modelo_cache


def prever(sku, almoxarifado, categoria_produto, divergencia_qtd, valor_estimado, data_deteccao) -> dict:
    """Retorna None se o modelo ainda não foi treinado (fail-soft: o motor
    de regras continua funcionando de qualquer forma - o ML é um sinal
    adicional, não uma dependência obrigatória)."""
    modelo = _carregar_modelo()
    if modelo is None:
        return None

    dia_semana = pd.to_datetime(str(data_deteccao)).dayofweek if data_deteccao else -1

    X = pd.DataFrame([{
        "almoxarifado": almoxarifado or "Desconhecido",
        "categoria_produto": categoria_produto or "Desconhecido",
        "divergencia_qtd": divergencia_qtd or 0,
        "valor": valor_estimado or 0,
        "dia_semana": dia_semana,
    }])

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
