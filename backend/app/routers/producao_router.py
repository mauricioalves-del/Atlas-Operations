"""
Painel de Produção / Ordens de Produção (18/08/2026) - hoje só cobre o
indicador "Testes de Inovação" do MBR (Ordens de Produção de teste/
amostra/piloto, fora da produção normal).

IMPORTANTE - suposição documentada: OrdemProducao/ConsumoOP não têm hoje
nenhum campo que marque uma OP como "teste industrial" vs "produção
normal" (confirmado ao ler models.py e o importador). Pra não travar o
indicador esperando um campo novo ser preenchido em algum sistema
externo, a classificação aqui é por PALAVRA-CHAVE na descrição do
produto final (case-insensitive) - configurável via query param
`termos`, com um default razoável. Se isso classificar OPs erradas (ou
deixar de pegar alguma), é só ajustar os termos na chamada ou pedir pra
eu trocar a régua por outra coisa (ex: uma lista fixa de SKUs, ou um
campo novo que passe a vir da planilha)."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import obter_usuario_atual

router = APIRouter(prefix="/producao", tags=["producao"])

TERMOS_INOVACAO_PADRAO = ["teste", "amostra", "inovac", "piloto", "sensorial"]


def _mes_para_intervalo(mes: str):
    ano, mes_num = mes.split("-")
    ano, mes_num = int(ano), int(mes_num)
    inicio = date(ano, mes_num, 1)
    fim = date(ano + 1, 1, 1) if mes_num == 12 else date(ano, mes_num + 1, 1)
    return inicio, fim


@router.get("/dashboard/testes-inovacao")
def dashboard_testes_inovacao(
    mes: Optional[str] = Query(None, description="YYYY-MM - filtra por data_producao"),
    termos: Optional[str] = Query(None, description="lista separada por vírgula - substitui os termos-padrão de classificação"),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    lista_termos = [t.strip().lower() for t in termos.split(",") if t.strip()] if termos else TERMOS_INOVACAO_PADRAO

    q = db.query(models.OrdemProducao).filter(
        or_(*[models.OrdemProducao.descricao_produto.ilike(f"%{t}%") for t in lista_termos])
    )
    if mes:
        inicio, fim = _mes_para_intervalo(mes)
        q = q.filter(models.OrdemProducao.data_producao >= inicio, models.OrdemProducao.data_producao < fim)
    ops = q.all()

    if not ops:
        return {
            "mes": mes, "termos_usados": lista_termos, "qtd_ops": 0, "qtd_itens_consumidos": 0,
            "custo_total": 0.0, "custo_medio_por_op": None, "ops": [],
        }

    numeros_op = [o.numero_op for o in ops]
    consumos = db.query(models.ConsumoOP).filter(models.ConsumoOP.numero_op.in_(numeros_op)).all()

    skus_material = {c.sku_material for c in consumos if c.sku_material}
    custos = {
        p.sku: p.custo_unitario
        for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus_material), models.Produto.custo_unitario.isnot(None)).all()
    }

    custo_total = 0.0
    itens_com_custo = 0
    for c in consumos:
        custo = custos.get(c.sku_material)
        if custo is not None:
            custo_total += abs(c.qtd_consumo or 0) * custo
            itens_com_custo += 1

    return {
        "mes": mes,
        "termos_usados": lista_termos,
        "qtd_ops": len(ops),
        "qtd_itens_consumidos": len(consumos),
        "qtd_itens_com_custo_cadastrado": itens_com_custo,
        "custo_total": round(custo_total, 2),
        "custo_medio_por_op": round(custo_total / len(ops), 2) if ops else None,
        "ops": [
            {"numero_op": o.numero_op, "sku_produto_final": o.sku_produto_final, "descricao_produto": o.descricao_produto, "data_producao": str(o.data_producao) if o.data_producao else None, "qtd_produzida": o.qtd_produzida}
            for o in sorted(ops, key=lambda o: o.data_producao or date.min, reverse=True)
        ],
    }
