"""
Retreino automático do modelo de ML, em background, dentro do próprio
processo do servidor - sem cron, sem Task Scheduler do Windows, sem
dependência nova (usa só threading/time da biblioteca padrão). Funciona
igual localmente e em qualquer deploy em nuvem, desde que o servidor
fique de pé.

Controlado por variáveis de ambiente (todas opcionais, com padrão
sensato pra uso local):
  ATLAS_ML_AUTO_RETREINO=false            desativa completamente
  ATLAS_ML_RETREINO_INTERVALO_HORAS=24    intervalo mínimo entre retreinos
  ATLAS_ML_RETREINO_MIN_CASOS_NOVOS=5     só retreina se houver pelo menos
                                           esse número de casos confirmados
                                           novos desde o último retreino
  ATLAS_ML_CHECAGEM_SEGUNDOS=1800         a cada quanto tempo verifica se
                                           já é hora (30 min por padrão)

As duas condições (intervalo de tempo E mínimo de casos novos) precisam
ser satisfeitas juntas - isso evita retreinar sem dado novo nenhum, e
evita retreinar toda hora só porque acumulou casos rápido demais.
"""
import os
import threading
import time
from datetime import datetime

from .database import SessionLocal
from . import models
from . import fefo
from .ml_ops import executar_retreino, obter_estado, CAMINHO_HISTORICO_PADRAO

ATIVO = os.environ.get("ATLAS_ML_AUTO_RETREINO", "true").strip().lower() not in ("false", "0", "nao", "não")
INTERVALO_HORAS = float(os.environ.get("ATLAS_ML_RETREINO_INTERVALO_HORAS", "24"))
MIN_CASOS_NOVOS = int(os.environ.get("ATLAS_ML_RETREINO_MIN_CASOS_NOVOS", "5"))
CHECAGEM_SEGUNDOS = int(os.environ.get("ATLAS_ML_CHECAGEM_SEGUNDOS", str(30 * 60)))


def _deveria_retreinar(db) -> tuple[bool, int]:
    if not os.path.exists(CAMINHO_HISTORICO_PADRAO):
        return False, 0
    estado = obter_estado(db)
    total_feedback = db.query(models.CasoMLFeedback).count()
    casos_novos = total_feedback - (estado.casos_feedback_no_ultimo_retreino or 0)

    if casos_novos < MIN_CASOS_NOVOS:
        return False, casos_novos
    if estado.ultimo_retreino_em is None:
        return True, casos_novos
    horas_desde_ultimo = (datetime.utcnow() - estado.ultimo_retreino_em).total_seconds() / 3600
    return horas_desde_ultimo >= INTERVALO_HORAS, casos_novos


def _loop():
    while True:
        time.sleep(CHECAGEM_SEGUNDOS)
        try:
            db = SessionLocal()
            deve, casos_novos = _deveria_retreinar(db)
            db.close()
            if deve:
                print(f"Atlas: {casos_novos} caso(s) novo(s) e intervalo cumprido - retreinando modelo de ML automaticamente...")
                resultado = executar_retreino(origem="automatico")
                print(f"Atlas: retreino automático concluído - {resultado['casos_feedback_incluidos']} casos de feedback, {len(resultado['classes_aprendidas'])} hipóteses.")
        except Exception as e:
            print(f"Atlas: falha no retreino automático ({type(e).__name__}: {e}) - tentando de novo no próximo ciclo.")


def iniciar_agendador():
    if not ATIVO:
        print("Atlas: retreino automático de ML desativado (ATLAS_ML_AUTO_RETREINO=false).")
        return
    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    print(
        f"Atlas: retreino automático de ML ativo - a cada {INTERVALO_HORAS}h "
        f"(mínimo {MIN_CASOS_NOVOS} casos novos), verificando a cada {CHECAGEM_SEGUNDOS // 60} min."
    )


# ═════════════════════════════════════════════════════════════════════════
# Recálculo automático do motor NATIVO de FEFO (20/08/2026) - "Esse
# processo precisa atualizar todos os dias" (instrução literal do usuário,
# ver claude/checagens-fefo-heuristica-quebrada.md no Atlas Operations).
# Mesmo padrão de thread em background do retreino de ML acima - sem cron,
# sem dependência nova. Guarda o último horário só em memória do processo
# (não em banco): um reinício do servidor só adianta o próximo recálculo,
# nunca atrasa além do previsto - inofensivo, porque
# fefo.recalcular_quebra_fefo_nativa é idempotente e reflete sempre o
# estado atual de LoteShelfLife/MovimentacaoLoteDiaria, não acumula
# histórico próprio.
#   ATLAS_FEFO_AUTO_RECALCULO=false          desativa completamente
#   ATLAS_FEFO_RECALCULO_INTERVALO_HORAS=24  intervalo mínimo entre recálculos automáticos
#   ATLAS_FEFO_CHECAGEM_SEGUNDOS=1800        a cada quanto tempo verifica se já é hora
# ═════════════════════════════════════════════════════════════════════════

FEFO_ATIVO = os.environ.get("ATLAS_FEFO_AUTO_RECALCULO", "true").strip().lower() not in ("false", "0", "nao", "não")
FEFO_INTERVALO_HORAS = float(os.environ.get("ATLAS_FEFO_RECALCULO_INTERVALO_HORAS", "24"))
FEFO_CHECAGEM_SEGUNDOS = int(os.environ.get("ATLAS_FEFO_CHECAGEM_SEGUNDOS", str(30 * 60)))

_ultimo_recalculo_fefo_em = None


def _loop_fefo():
    global _ultimo_recalculo_fefo_em
    while True:
        time.sleep(FEFO_CHECAGEM_SEGUNDOS)
        try:
            if _ultimo_recalculo_fefo_em is not None:
                horas_desde_ultimo = (datetime.utcnow() - _ultimo_recalculo_fefo_em).total_seconds() / 3600
                if horas_desde_ultimo < FEFO_INTERVALO_HORAS:
                    continue
            db = SessionLocal()
            try:
                resultado = fefo.recalcular_quebra_fefo_nativa(db)
                db.commit()
                _ultimo_recalculo_fefo_em = datetime.utcnow()
                print(
                    f"Atlas: recálculo automático de FEFO concluído - "
                    f"{resultado['movimentos_avaliados']} movimento(s) avaliado(s), "
                    f"{resultado['quebras_detectadas']} quebra(s)."
                )
            finally:
                db.close()
        except Exception as e:
            print(f"Atlas: falha no recálculo automático de FEFO ({type(e).__name__}: {e}) - tentando de novo no próximo ciclo.")


def iniciar_agendador_fefo():
    if not FEFO_ATIVO:
        print("Atlas: recálculo automático de FEFO desativado (ATLAS_FEFO_AUTO_RECALCULO=false).")
        return
    thread = threading.Thread(target=_loop_fefo, daemon=True)
    thread.start()
    print(
        f"Atlas: recálculo automático de FEFO ativo - a cada {FEFO_INTERVALO_HORAS}h, "
        f"verificando a cada {FEFO_CHECAGEM_SEGUNDOS // 60} min."
    )
