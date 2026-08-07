"""
Endpoints para sistemas externos empurrarem dados pro Atlas via webhook.

Hoje só tem a integração com as baixas operacionais (Avaria, Vencimento,
Descarte, Degustação, etc.) do sistema construído no Lovable - ver
baixas_operacionais.py pra entender a lógica de mapeamento e casamento
com divergências. Autenticação é por chave fixa (ver
deps.verificar_chave_integracao), não por login de usuário - quem chama
aqui é um sistema, não uma pessoa logada.
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import verificar_chave_integracao
from ..baixas_operacionais import processar_baixa_recebida, importar_lote, BaixaInvalida

router = APIRouter(prefix="/integracoes", tags=["integracoes_externas"], dependencies=[Depends(verificar_chave_integracao)])


@router.post("/lovable/baixas")
def receber_baixa_lovable(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Webhook de destino para o Database Webhook do Supabase configurado
    na tabela baixa_operacional do Lovable, nos eventos Insert E Update
    (a baixa nasce em status_fluxo=PENDENTE e só fica válida quando
    alguém aprova - ver baixas_operacionais.STATUS_FLUXO_APROVADO).
    Aceita tanto o envelope padrão do Supabase ({"type": "INSERT"|
    "UPDATE", "record": {...}, ...}) quanto um POST direto só com os
    campos da baixa - útil pra testar na mão."""
    tipo_evento = payload.get("type")
    if tipo_evento and tipo_evento not in ("INSERT", "UPDATE"):
        return {"status": "ignorado", "motivo": f"evento '{tipo_evento}' não é INSERT/UPDATE, nada a fazer"}

    record = payload.get("record") if isinstance(payload.get("record"), dict) else payload

    try:
        resultado = processar_baixa_recebida(db, record)
    except BaixaInvalida as e:
        # 400 de propósito: Supabase não vai ficar tentando de novo pra
        # sempre um payload que está estruturalmente errado (diferente de
        # um erro 5xx transitório, que ele reenvia).
        raise HTTPException(400, str(e))

    db.commit()
    return resultado


@router.post("/lovable/baixas/lote")
def receber_baixas_lote(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Importação em lote - usada pro backfill inicial (trazer pro Atlas
    as baixas que já existiam no Lovable antes da integração automática
    existir, de qualquer status) e pra sincronizações manuais futuras,
    sem depender de webhook nenhum. Espera {"registros": [ {...}, ... ]}
    - cada item com as mesmas colunas de uma linha de baixa_operacional."""
    registros = payload.get("registros")
    if not isinstance(registros, list):
        raise HTTPException(400, "Payload precisa ter uma lista em 'registros'.")
    resultado = importar_lote(db, registros)
    db.commit()
    return resultado
