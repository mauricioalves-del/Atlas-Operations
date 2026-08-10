"""
Relatório de Baixa - visão dentro do Atlas de todas as baixas
operacionais (Avaria, Vencimento, Descarte, Degustação, etc.) importadas
do sistema Lovable, de qualquer status (Pendente, Aprovada, Reprovada).
Diferente de baixas_operacionais.py (a lógica de importação/casamento),
este router só lê o que já foi importado - é pra tela de relatório, não
pra receber webhook."""
from collections import defaultdict
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import obter_usuario_atual
from ..baixas_operacionais import sincronizar_com_lovable, SincronizacaoIndisponivel, importar_lote

router = APIRouter(prefix="/baixas-operacionais", tags=["baixas_operacionais"])


@router.post("/importar-lote")
def importar_lote_colado(
    payload: dict = Body(...),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Fecha manualmente uma lacuna histórica entre o que existe no
    Lovable e o que já foi importado pro Atlas (ex: linhas de antes do
    webhook automático existir, ou alguma falha pontual de entrega).
    Protegido por login (mesmo usuário logado na tela, não pela chave de
    integração - por isso fica aqui, junto do relatório, e não em
    integracoes_router.py) porque quem aciona isso é uma pessoa colando
    um export tirado na mão do SQL editor do Lovable, não um sistema
    automático. Espera {"registros": [ {...}, ... ]} - mesmo formato de
    linha que .../integracoes/lovable/baixas/lote. Upsert por origem_id,
    então pode ser rodado de novo com o mesmo lote sem duplicar nada."""
    registros = payload.get("registros")
    if not isinstance(registros, list):
        raise HTTPException(400, "Payload precisa ter uma lista em 'registros'.")
    resultado = importar_lote(db, registros)
    db.commit()
    return resultado


@router.post("/sincronizar")
def sincronizar(
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Botão "Sincronizar agora" da tela Relatório de Baixa: busca ao vivo
    o estado atual da tabela baixa_operacional no Supabase do Lovable e
    reimporta tudo pro Atlas (upsert por origem_id - atualiza o que mudou
    de status lá, ex: Pendente -> Aprovada, sem duplicar nada)."""
    try:
        resultado = sincronizar_com_lovable(db)
    except SincronizacaoIndisponivel as e:
        raise HTTPException(500, str(e))
    db.commit()
    return resultado


@router.get("")
def listar_baixas(
    status_fluxo: str | None = Query(None, description="PENDENTE | APROVADA | REPROVADA"),
    almoxarifado: str | None = None,
    hipotese_aplicada: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.BaixaOperacional)
    if status_fluxo:
        q = q.filter(models.BaixaOperacional.status_fluxo == status_fluxo.upper())
    if almoxarifado:
        q = q.filter(models.BaixaOperacional.almoxarifado == almoxarifado)
    if hipotese_aplicada:
        q = q.filter(models.BaixaOperacional.hipotese_aplicada == hipotese_aplicada)
    if data_inicio:
        q = q.filter(models.BaixaOperacional.data_baixa >= data_inicio)
    if data_fim:
        q = q.filter(models.BaixaOperacional.data_baixa <= data_fim)

    linhas = q.order_by(models.BaixaOperacional.data_baixa.desc()).all()

    resumo = {
        "total": len(linhas),
        "pendentes": sum(1 for l in linhas if l.status_fluxo == "PENDENTE"),
        "aprovadas": sum(1 for l in linhas if l.status_fluxo == "APROVADA"),
        "reprovadas": sum(1 for l in linhas if l.status_fluxo == "REPROVADA"),
        "resolvidas_automaticamente": sum(1 for l in linhas if l.divergencia_vinculada_id),
        "aguardando_divergencia": sum(1 for l in linhas if l.status_fluxo == "APROVADA" and not l.divergencia_vinculada_id),
        "valor_total": sum(l.valor_total or 0 for l in linhas),
    }

    itens = [
        {
            "id": l.id,
            "sku": l.sku,
            "almoxarifado": l.almoxarifado,
            "almoxarifado_origem": l.almoxarifado_origem,
            "motivo": l.motivo_baixa_bruto,
            "hipotese_aplicada": l.hipotese_aplicada,
            "quantidade": l.quantidade,
            "valor_total": l.valor_total,
            "status_fluxo": l.status_fluxo,
            "solicitante_nome": l.solicitante_nome,
            "data_baixa": l.data_baixa,
            "divergencia_vinculada_id": l.divergencia_vinculada_id,
            "recebido_em": l.recebido_em,
        }
        for l in linhas
    ]
    return {"resumo": resumo, "itens": itens}


# ---------------------------------------------------------------------------
# Dashboard "Mapeamento de Passivos" - visão gerencial de todas as baixas
# operacionais já trazidas do Lovable (não é a origem/webhook, é análise
# sobre o que já está importado). Cobre:
#   1) status operacionais usados (Pendente/Aprovada/Reprovada) - pizza;
#   2) de onde veio o mapeamento de cada baixa aprovada: de uma
#      divergência achada no Inventário Mensal (Divergencia.origem ==
#      "fechamento_inventario"), de uma divergência do dia a dia
#      (Divergencia.origem == "movimentacao"), aprovada mas ainda sem
#      casar com nenhuma divergência, ou nem chegou a ser decidida
#      (Pendente/Reprovada) - coluna;
#   3) evolução mês a mês (MoM) do valor de baixas aplicadas + taxa de
#      resolução automática - coluna+linha;
#   4) Top 10 SKUs mais recorrentes em baixa e Top 10 por impacto
#      financeiro - tabelas.
# Todo clique num gráfico/linha/linha de tabela abre o mesmo pop de
# drill-down (GET .../dashboard/itens) filtrado pela categoria clicada.
# ---------------------------------------------------------------------------

CATEGORIA_MAPEAMENTO_LABELS = {
    "inventario_mensal": "Mapeada via Inventário Mensal",
    "movimentacao_diaria": "Mapeada via Movimentação Diária",
    "aguardando_divergencia": "Aprovada, aguardando divergência",
    "nao_decidida": "Pendente/Reprovada (não decidida)",
}


def _mapa_divergencias_das_baixas(db: Session, baixas: list) -> dict:
    ids = {b.divergencia_vinculada_id for b in baixas if b.divergencia_vinculada_id}
    if not ids:
        return {}
    return {d.id: d for d in db.query(models.Divergencia).filter(models.Divergencia.id.in_(ids)).all()}


def _categoria_mapeamento(baixa, divergencias_por_id: dict) -> str:
    if not baixa.divergencia_vinculada_id:
        return "aguardando_divergencia" if baixa.status_fluxo == "APROVADA" else "nao_decidida"
    div = divergencias_por_id.get(baixa.divergencia_vinculada_id)
    if div and div.origem == "fechamento_inventario":
        return "inventario_mensal"
    return "movimentacao_diaria"


def _filtrar_baixas_dashboard(
    db: Session, status_fluxo: str | None, categoria_mapeamento: str | None, mes: str | None, sku: str | None,
) -> list:
    q = db.query(models.BaixaOperacional)
    if status_fluxo:
        q = q.filter(models.BaixaOperacional.status_fluxo == status_fluxo.upper())
    if sku:
        q = q.filter(models.BaixaOperacional.sku == sku)
    baixas = q.all()
    if mes:
        baixas = [b for b in baixas if b.data_baixa and str(b.data_baixa)[:7] == mes]
    if categoria_mapeamento:
        divergencias_por_id = _mapa_divergencias_das_baixas(db, baixas)
        baixas = [b for b in baixas if _categoria_mapeamento(b, divergencias_por_id) == categoria_mapeamento]
    return baixas


@router.get("/dashboard/kpis")
def dashboard_passivos_kpis(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    baixas = db.query(models.BaixaOperacional).all()
    divergencias_por_id = _mapa_divergencias_das_baixas(db, baixas)

    por_categoria = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for b in baixas:
        cat = _categoria_mapeamento(b, divergencias_por_id)
        por_categoria[cat]["quantidade"] += 1
        por_categoria[cat]["valor"] += b.valor_total or 0

    aprovadas = [b for b in baixas if b.status_fluxo == "APROVADA"]
    mapeamento = {
        chave: {"label": rotulo, "quantidade": por_categoria[chave]["quantidade"], "valor": round(por_categoria[chave]["valor"], 2)}
        for chave, rotulo in CATEGORIA_MAPEAMENTO_LABELS.items()
    }

    return {
        "total": len(baixas),
        "valor_total": round(sum(b.valor_total or 0 for b in baixas), 2),
        "pendentes": sum(1 for b in baixas if b.status_fluxo == "PENDENTE"),
        "aprovadas": len(aprovadas),
        "reprovadas": sum(1 for b in baixas if b.status_fluxo == "REPROVADA"),
        "valor_aprovadas": round(sum(b.valor_total or 0 for b in aprovadas), 2),
        "mapeamento": mapeamento,
    }


@router.get("/dashboard/status-pizza")
def dashboard_passivos_status_pizza(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Status operacionais usados (Pendente/Aprovada/Reprovada) - todas as
    baixas já trazidas do Lovable, de qualquer origem de mapeamento."""
    baixas = db.query(models.BaixaOperacional).all()
    por_status = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for b in baixas:
        chave = b.status_fluxo or "NAO_INFORMADO"
        por_status[chave]["quantidade"] += 1
        por_status[chave]["valor"] += b.valor_total or 0
    rotulos = {"PENDENTE": "Pendente", "APROVADA": "Aprovada", "REPROVADA": "Reprovada", "NAO_INFORMADO": "Não informado"}
    return [
        {"status_fluxo": k, "label": rotulos.get(k, k), "quantidade": v["quantidade"], "valor": round(v["valor"], 2)}
        for k, v in por_status.items()
    ]


@router.get("/dashboard/mapeamento-origem")
def dashboard_passivos_mapeamento_origem(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """De onde vem o mapeamento de cada baixa - Inventário Mensal vs
    Movimentação Diária vs ainda sem decisão/casamento. Ver
    CATEGORIA_MAPEAMENTO_LABELS e _categoria_mapeamento acima."""
    baixas = db.query(models.BaixaOperacional).all()
    divergencias_por_id = _mapa_divergencias_das_baixas(db, baixas)
    por_categoria = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for b in baixas:
        cat = _categoria_mapeamento(b, divergencias_por_id)
        por_categoria[cat]["quantidade"] += 1
        por_categoria[cat]["valor"] += b.valor_total or 0
    return [
        {"categoria": chave, "label": rotulo, "quantidade": por_categoria[chave]["quantidade"], "valor": round(por_categoria[chave]["valor"], 2)}
        for chave, rotulo in CATEGORIA_MAPEAMENTO_LABELS.items()
    ]


@router.get("/dashboard/evolucao-mensal")
def dashboard_passivos_evolucao_mensal(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """MoM de todas as baixas APROVADAS (as que de fato foram aplicadas -
    Pendente/Reprovada não é passivo real ainda/nunca vai ser), mês a mês
    por data_baixa: valor total (coluna) e taxa de resolução automática -
    % que casou com uma divergência, seja de inventário mensal seja de
    movimentação (linha) - a "curva de evolução do processo" pedida."""
    aprovadas = db.query(models.BaixaOperacional).filter(models.BaixaOperacional.status_fluxo == "APROVADA").all()
    por_mes = defaultdict(lambda: {"quantidade": 0, "valor": 0.0, "resolvidas": 0})
    for b in aprovadas:
        if not b.data_baixa:
            continue
        mes = str(b.data_baixa)[:7]
        por_mes[mes]["quantidade"] += 1
        por_mes[mes]["valor"] += b.valor_total or 0
        if b.divergencia_vinculada_id:
            por_mes[mes]["resolvidas"] += 1

    resultado = []
    for mes in sorted(por_mes.keys()):
        v = por_mes[mes]
        taxa = round(v["resolvidas"] / v["quantidade"] * 100, 1) if v["quantidade"] else None
        resultado.append({"mes": mes, "quantidade": v["quantidade"], "valor": round(v["valor"], 2), "taxa_resolucao_automatica_pct": taxa})
    return resultado


def _top_10_por_sku(baixas: list, db: Session, chave_ordenacao) -> list:
    por_sku = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    for b in baixas:
        if not b.sku:
            continue
        por_sku[b.sku]["quantidade"] += 1
        por_sku[b.sku]["valor"] += b.valor_total or 0
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(por_sku.keys())).all()}
    itens = [{"sku": sku, "descricao_produto": descricoes.get(sku), "quantidade": v["quantidade"], "valor": round(v["valor"], 2)} for sku, v in por_sku.items()]
    itens.sort(key=chave_ordenacao, reverse=True)
    return itens[:10]


@router.get("/dashboard/top-recorrentes")
def dashboard_passivos_top_recorrentes(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Top 10 SKUs que mais vezes tiveram baixa aprovada - recorrência
    (quantidade de ocorrências), não valor - ver top-impacto-financeiro
    para o ranking por valor."""
    aprovadas = db.query(models.BaixaOperacional).filter(models.BaixaOperacional.status_fluxo == "APROVADA").all()
    return _top_10_por_sku(aprovadas, db, chave_ordenacao=lambda x: x["quantidade"])


@router.get("/dashboard/top-impacto-financeiro")
def dashboard_passivos_top_impacto_financeiro(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Top 10 SKUs com maior valor total baixado (aprovado)."""
    aprovadas = db.query(models.BaixaOperacional).filter(models.BaixaOperacional.status_fluxo == "APROVADA").all()
    return _top_10_por_sku(aprovadas, db, chave_ordenacao=lambda x: x["valor"])


@router.get("/dashboard/itens")
def dashboard_passivos_itens(
    status_fluxo: str | None = None,
    categoria_mapeamento: str | None = Query(None, description="inventario_mensal | movimentacao_diaria | aguardando_divergencia | nao_decidida"),
    mes: str | None = Query(None, description="YYYY-MM"),
    sku: str | None = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Drill-down usado por TODOS os gráficos/tabelas do dashboard
    Mapeamento de Passivos - clicar numa fatia da pizza, numa coluna do
    mapeamento por origem, num mês do MoM ou numa linha de um Top 10 cai
    aqui, com o filtro correspondente."""
    baixas = _filtrar_baixas_dashboard(db, status_fluxo, categoria_mapeamento, mes, sku)
    divergencias_por_id = _mapa_divergencias_das_baixas(db, baixas)
    descricoes = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_({b.sku for b in baixas if b.sku})).all()}

    itens = [
        {
            "id": b.id, "sku": b.sku, "descricao_produto": descricoes.get(b.sku),
            "almoxarifado": b.almoxarifado, "motivo": b.motivo_baixa_bruto,
            "quantidade": b.quantidade, "valor_total": b.valor_total,
            "status_fluxo": b.status_fluxo, "solicitante_nome": b.solicitante_nome,
            "data_baixa": str(b.data_baixa) if b.data_baixa else None,
            "divergencia_vinculada_id": b.divergencia_vinculada_id,
            "categoria_mapeamento": _categoria_mapeamento(b, divergencias_por_id),
        }
        for b in baixas
    ]
    itens.sort(key=lambda x: (x["data_baixa"] or "", abs(x["valor_total"] or 0)), reverse=True)
    return {"itens": itens, "total": len(itens), "valor_total": round(sum(b.valor_total or 0 for b in baixas), 2)}
