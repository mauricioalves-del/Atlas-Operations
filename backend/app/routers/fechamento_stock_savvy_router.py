"""
Fechamento Mensal — Stock Savvy (09/09/2026, pedido do usuário: "adicionar
ao MBR um modelo criado na outra ferramenta de controle [...] para
substituir o resultado da análise [...] para números reais obtidos e
mapeados através da implementação"). O admin sobe aqui, todo mês, o .pptx
nativo que o Stock Savvy exporta no fechamento (capa + Resumo Executivo +
Resultado Financeiro de Shelf Life + rankings Top 10 + Mapeamento por
Módulo + Destaques de Risco) - o Atlas extrai só o resumo executivo
compacto (ver fechamento_stock_savvy_extrator.py) e injeta como slide no
MBR daquele mês, substituindo a antiga análise genérica "Atlas + Stock
Savvy".

Diferente de Outros Dashboards (dashboards_externos_router.py, um slot
"sempre o mais recente"), aqui é upsert por MÊS ("AAAA-MM") - o MBR de
agosto precisa do fechamento de agosto, não do último enviado, então cada
mês guarda seu próprio arquivo.
"""
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import requer_papel
from ..audit import registrar_log
from ..fechamento_stock_savvy_extrator import extrair_fechamento_stock_savvy

router = APIRouter(prefix="/fechamento-stock-savvy", tags=["fechamento_stock_savvy"])

_RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validar_mes(mes: str):
    if not mes or not _RE_MES.match(mes):
        raise HTTPException(400, "Mês inválido - use o formato AAAA-MM (ex.: 2026-08).")


@router.get("")
def listar_fechamentos(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Um registro por mês já enviado - não devolve o .pptx em si (pode ser
    grande), só quem/quando enviou. Ordenado do mais recente pro mais
    antigo."""
    registros = db.query(models.FechamentoStockSavvy).order_by(models.FechamentoStockSavvy.mes.desc()).all()
    return [
        {
            "mes": r.mes,
            "nome_arquivo_original": r.nome_arquivo_original,
            "enviado_por": r.enviado_por,
            "enviado_em": r.enviado_em.isoformat() if r.enviado_em else None,
        }
        for r in registros
    ]


@router.get("/{mes}")
def status_fechamento(mes: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Status de um mês específico + prévia do resumo já extraído (pra
    conferência visual no front antes de fechar o MBR daquele mês)."""
    _validar_mes(mes)
    r = db.query(models.FechamentoStockSavvy).filter_by(mes=mes).first()
    if not r:
        return {"mes": mes, "enviado": False}
    try:
        resumo = extrair_fechamento_stock_savvy(r.arquivo_pptx)
    except Exception:
        resumo = None
    return {
        "mes": mes,
        "enviado": True,
        "nome_arquivo_original": r.nome_arquivo_original,
        "enviado_por": r.enviado_por,
        "enviado_em": r.enviado_em.isoformat() if r.enviado_em else None,
        "resumo_extraido": resumo,
        "erro_extracao": resumo is None,
    }


@router.post("/{mes}/upload")
async def enviar_fechamento(
    mes: str,
    arquivo: UploadFile = File(...),
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Recebe o .pptx de fechamento do Stock Savvy pro mês informado e
    substitui o arquivo anterior do mesmo mês, se houver (upsert por mês).
    Valida a extração ANTES de salvar (não aceita um .pptx que não bate com
    o formato esperado do Stock Savvy - evita salvar lixo que sempre viraria
    "—" em todos os cards do MBR)."""
    _validar_mes(mes)
    if not arquivo.filename or not arquivo.filename.lower().endswith(".pptx"):
        raise HTTPException(400, "Envie um arquivo .pptx (o fechamento mensal nativo exportado pelo Stock Savvy).")

    conteudo = await arquivo.read()
    if extrair_fechamento_stock_savvy(conteudo) is None:
        raise HTTPException(
            400,
            "Não consegui reconhecer este arquivo como um fechamento do Stock Savvy "
            "(nenhum dos números esperados foi encontrado). Confira se é o .pptx correto.",
        )

    existente = db.query(models.FechamentoStockSavvy).filter_by(mes=mes).first()
    if existente:
        existente.arquivo_pptx = conteudo
        existente.nome_arquivo_original = arquivo.filename
        existente.enviado_por = usuario.username
        existente.enviado_em = datetime.utcnow()
    else:
        db.add(models.FechamentoStockSavvy(
            mes=mes, arquivo_pptx=conteudo, nome_arquivo_original=arquivo.filename,
            enviado_por=usuario.username,
        ))

    registrar_log(
        db, usuario.username, "enviar_fechamento_stock_savvy", entidade="fechamento_stock_savvy", entidade_id=mes,
        detalhes={"arquivo": arquivo.filename, "tamanho_bytes": len(conteudo)},
    )
    db.commit()
    return {"ok": True, "mes": mes}


@router.delete("/{mes}")
def remover_fechamento(mes: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    _validar_mes(mes)
    r = db.query(models.FechamentoStockSavvy).filter_by(mes=mes).first()
    if not r:
        raise HTTPException(404, "Esse mês ainda não teve nenhum fechamento enviado.")
    db.delete(r)
    registrar_log(db, usuario.username, "remover_fechamento_stock_savvy", entidade="fechamento_stock_savvy", entidade_id=mes)
    db.commit()
    return {"ok": True}
