"""
Módulo FEFO (First-Expired-First-Out) - detecção de quebras na
movimentação de saída da Fábrica (18/08/2026). Ver app/fefo.py pra regra
de cálculo (documentada lá, com a suposição sinalizada pra validação do
usuário) e models.ChecagemFefo pro formato do resultado guardado.
"""
from collections import Counter
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import obter_usuario_atual, requer_papel
from ..audit import registrar_log
from ..fefo import recalcular_checagens_fefo

router = APIRouter(prefix="/fefo", tags=["fefo"])


@router.post("/recalcular")
def recalcular(usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Roda a checagem de FEFO pra toda transferência elegível (origem =
    Fábrica) e atualiza o resultado guardado - chamar depois de reimportar
    a planilha de lotes (Lote_Sistema) ou o livro-caixa bruto/
    transferências, pra refletir o estado mais recente."""
    resultado = recalcular_checagens_fefo(db)
    registrar_log(db, usuario.username, "recalcular_fefo", detalhes=resultado)
    db.commit()
    return resultado


@router.get("/checagens", response_model=list[schemas.ChecagemFefoOut])
def listar_checagens(
    resultado: Optional[str] = Query(None, description="Quebra_Fefo | Dentro_Do_Criterio | Sem_Dado_Suficiente"),
    sku: Optional[str] = None,
    almoxarifado_destino: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.ChecagemFefo)
    if resultado:
        q = q.filter(models.ChecagemFefo.resultado == resultado)
    if sku:
        q = q.filter(models.ChecagemFefo.sku == sku)
    if almoxarifado_destino:
        q = q.filter(models.ChecagemFefo.almoxarifado_destino == almoxarifado_destino)
    return q.order_by(models.ChecagemFefo.data_saida.desc()).all()


@router.get("/dashboard/resumo")
def dashboard_resumo(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Total de transferências avaliadas (saídas da Fábrica com checagem
    já calculada), quantas quebraram o critério de FEFO, taxa de quebra,
    e os SKUs/destinos mais frequentes nas quebras - pro indicador do
    MBR. Rodar POST /fefo/recalcular antes se os dados de transferência ou
    de lotes tiverem mudado desde a última checagem."""
    checagens = db.query(models.ChecagemFefo).all()
    total = len(checagens)
    quebras = [c for c in checagens if c.resultado == "Quebra_Fefo"]
    sem_dado = [c for c in checagens if c.resultado == "Sem_Dado_Suficiente"]

    top_skus = Counter(c.sku for c in quebras).most_common(10)
    top_destinos = Counter(c.almoxarifado_destino for c in quebras if c.almoxarifado_destino).most_common(10)

    avaliaveis = total - len(sem_dado)  # taxa de quebra só faz sentido sobre o que pôde ser avaliado

    return {
        "total_transferencias_avaliadas": total,
        "total_quebras_fefo": len(quebras),
        "total_dentro_do_criterio": total - len(quebras) - len(sem_dado),
        "total_sem_dado_suficiente": len(sem_dado),
        "taxa_quebra_pct": round(len(quebras) / avaliaveis * 100, 2) if avaliaveis else None,
        "top_skus_com_quebra": [{"sku": sku, "quebras": qtd} for sku, qtd in top_skus],
        "top_destinos_com_quebra": [{"almoxarifado_destino": destino, "quebras": qtd} for destino, qtd in top_destinos],
    }
