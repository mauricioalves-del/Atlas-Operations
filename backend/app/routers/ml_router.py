import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import requer_papel, obter_usuario_atual
from ..ml.predict import MODEL_PATH
from ..ml_ops import executar_retreino, obter_estado, CAMINHO_HISTORICO_PADRAO
from .. import scheduler

router = APIRouter(prefix="/ml", tags=["machine_learning"])


@router.get("/status")
def status(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    existe_modelo = os.path.exists(MODEL_PATH)
    info = {"modelo_treinado": existe_modelo}
    if existe_modelo:
        info["tamanho_kb"] = round(os.path.getsize(MODEL_PATH) / 1024, 1)
        info["modificado_em"] = os.path.getmtime(MODEL_PATH)
        try:
            import joblib
            m = joblib.load(MODEL_PATH)
            info["classes"] = list(m.named_steps["rf"].classes_)
        except Exception:
            info["classes"] = None

    total_feedback = db.query(models.CasoMLFeedback).count()
    info["casos_feedback_acumulados"] = total_feedback
    info["historico_bruto_disponivel"] = os.path.exists(CAMINHO_HISTORICO_PADRAO)

    estado = obter_estado(db)
    casos_novos = total_feedback - (estado.casos_feedback_no_ultimo_retreino or 0)
    info["automatico"] = {
        "ativo": scheduler.ATIVO,
        "intervalo_horas": scheduler.INTERVALO_HORAS,
        "minimo_casos_novos": scheduler.MIN_CASOS_NOVOS,
        "ultimo_retreino_em": estado.ultimo_retreino_em.isoformat() if estado.ultimo_retreino_em else None,
        "origem_ultimo_retreino": estado.origem_ultimo_retreino,
        "casos_novos_desde_ultimo_retreino": casos_novos,
    }
    return info


@router.post("/retreinar")
def retreinar(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Retreina o modelo agora, direto pela tela - sem precisar de acesso
    a terminal (importante pra quem está em deploy na nuvem). Usa o
    histórico bruto em seed_data/ + todos os casos confirmados pela
    equipe até agora (CasoMLFeedback)."""
    try:
        resultado = executar_retreino(origem="manual", usuario_username=usuario.username)
    except FileNotFoundError as e:
        raise HTTPException(
            400,
            f"{e}. Sem esse arquivo não há como retreinar por aqui - use "
            "'python -m app.ml.train --historico <caminho>' com o arquivo em mãos.",
        )
    except Exception as e:
        raise HTTPException(500, f"Falha ao retreinar: {type(e).__name__}: {e}")

    return {
        "ok": True,
        **resultado,
        "mensagem": "Modelo retreinado e recarregado - já vale pra próxima divergência detectada.",
    }
