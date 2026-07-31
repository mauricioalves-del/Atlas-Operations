"""
Lógica de retreino compartilhada entre o botão manual ("Retreinar agora")
e o agendador automático (app/scheduler.py) - um único caminho de
código, pra não ter duas implementações que podem divergir.
"""
import os
from datetime import datetime

from .database import SessionLocal
from . import models
from .ml.predict import invalidar_cache
from .bootstrap import SEED_DIR
from .audit import registrar_log

CAMINHO_HISTORICO_PADRAO = os.path.join(SEED_DIR, "atlas_casos_historicos_categorizados.csv")


def obter_estado(db) -> models.EstadoTreinoML:
    estado = db.query(models.EstadoTreinoML).get(1)
    if not estado:
        estado = models.EstadoTreinoML(id=1, casos_feedback_no_ultimo_retreino=0)
        db.add(estado)
        db.commit()
        db.refresh(estado)
    return estado


def executar_retreino(origem: str = "manual", usuario_username: str | None = None) -> dict:
    """origem: 'manual' (disparado pela tela) ou 'automatico' (agendador
    em background). Levanta FileNotFoundError se o histórico bruto não
    estiver disponível - quem chama decide como comunicar isso."""
    if not os.path.exists(CAMINHO_HISTORICO_PADRAO):
        raise FileNotFoundError(f"Histórico bruto não encontrado em {CAMINHO_HISTORICO_PADRAO}")

    from .ml.train import treinar  # import tardio - evita ciclo de import no startup

    db = SessionLocal()
    try:
        total_feedback = db.query(models.CasoMLFeedback).count()
        modelo = treinar(CAMINHO_HISTORICO_PADRAO, incluir_feedback=True)
        invalidar_cache()
        classes = list(modelo.named_steps["rf"].classes_)

        estado = obter_estado(db)
        estado.ultimo_retreino_em = datetime.utcnow()
        estado.casos_feedback_no_ultimo_retreino = total_feedback
        estado.origem_ultimo_retreino = origem

        registrar_log(
            db, usuario_username or "sistema (automático)", "retreinar_modelo_ml",
            detalhes={"origem": origem, "casos_feedback_incluidos": total_feedback, "classes": len(classes)},
        )
        db.commit()
        return {"casos_feedback_incluidos": total_feedback, "classes_aprendidas": classes}
    finally:
        db.close()
