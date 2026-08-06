from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..investigation import investigar, reconciliar
from ..ml import predict as ml_predict
from ..deps import requer_papel, obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/divergencias", tags=["divergencias"])

PESO_MIN, PESO_MAX = 5.0, 60.0
INCREMENTO_ACERTO = 2.0
DECREMENTO_ERRO = 2.0


def _preencher_descricao_produto(db: Session, divergencias: list):
    """Anexa descricao_produto (vindo do cadastro de produtos) a cada
    divergência antes de serializar - um atributo transiente, não uma
    coluna, então não precisa migração de banco."""
    skus = {d.sku for d in divergencias}
    produtos = {p.sku: p.descricao for p in db.query(models.Produto).filter(models.Produto.sku.in_(skus)).all()}
    for d in divergencias:
        d.descricao_produto = produtos.get(d.sku)
    return divergencias


def _marcar_investigacao_pendente(db: Session, divergencias: list):
    """Sinaliza (tem_investigacao_pendente) quando o mesmo SKU já tem
    outro caso marcado 'Em_Investigacao' que ainda não foi resolvido -
    usado pra mostrar o ícone de atenção quando a divergência reaparece
    antes de a investigação anterior ter sido concluída."""
    if not divergencias:
        return divergencias
    skus = {d.sku for d in divergencias}
    em_investigacao = (
        db.query(models.Divergencia.sku, models.Divergencia.id)
        .filter(models.Divergencia.sku.in_(skus), models.Divergencia.status == "Em_Investigacao")
        .all()
    )
    ids_por_sku = {}
    for sku, id_ in em_investigacao:
        ids_por_sku.setdefault(sku, set()).add(id_)
    for d in divergencias:
        ids_pendentes = ids_por_sku.get(d.sku, set())
        d.tem_investigacao_pendente = bool(ids_pendentes - {d.id})
    return divergencias


@router.post("/recalcular-valores")
def recalcular_valores(usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Reaplica o custo unitário cadastrado (Produto.custo_unitario) sobre
    as divergências ainda não resolvidas - útil quando você cadastra ou
    atualiza custos depois que as divergências já foram detectadas."""
    abertas = db.query(models.Divergencia).filter(models.Divergencia.status != "Resolvida").all()
    atualizadas = 0
    custos = {p.sku: p.custo_unitario for p in db.query(models.Produto).all() if p.custo_unitario is not None}
    for d in abertas:
        custo = custos.get(d.sku)
        if custo is None:
            continue
        novo_valor = round(abs(d.divergencia_qtd) * custo, 2)
        if novo_valor != d.valor_estimado:
            d.valor_estimado = novo_valor
            atualizadas += 1
    registrar_log(db, usuario.username, "recalcular_valores", detalhes={"atualizadas": atualizadas, "verificadas": len(abertas)})
    db.commit()
    return {"divergencias_verificadas": len(abertas), "divergencias_atualizadas": atualizadas}


@router.get("")
def listar(
    almoxarifado: Optional[str] = None,
    status: Optional[str] = None,
    hipotese: Optional[str] = None,
    incluir_fechamento_inventario: bool = False,
    pagina: int = Query(1, ge=1),
    tamanho_pagina: int = Query(50, ge=1, le=500),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.Divergencia)
    if not incluir_fechamento_inventario:
        q = q.filter(models.Divergencia.origem != "fechamento_inventario")
    if almoxarifado:
        q = q.filter(models.Divergencia.almoxarifado == almoxarifado)
    if status:
        q = q.filter(models.Divergencia.status == status)
    if hipotese:
        q = q.filter(models.Divergencia.hipotese_ia == hipotese)

    total = q.count()
    q = q.order_by(models.Divergencia.data_deteccao.desc())
    divergencias = q.offset((pagina - 1) * tamanho_pagina).limit(tamanho_pagina).all()
    _preencher_descricao_produto(db, divergencias)
    _marcar_investigacao_pendente(db, divergencias)

    return {
        "itens": [schemas.DivergenciaOut.model_validate(d).model_dump() for d in divergencias],
        "total": total,
        "pagina": pagina,
        "paginas": max(1, -(-total // tamanho_pagina)),
    }


def _dias_movimentacao_bruta_por_almoxarifado(db: Session, data_inicio, data_fim) -> dict:
    """Só o livro-caixa bruto do sistema (qualquer transação, de
    qualquer tipo) - é a "movimentação sistêmica importada" de verdade,
    sem nenhuma mistura com dado de conciliação."""
    from collections import defaultdict
    dias = defaultdict(set)
    for o in db.query(models.DiaOperacional.almoxarifado, models.DiaOperacional.data).filter(
        models.DiaOperacional.data >= data_inicio, models.DiaOperacional.data <= data_fim,
    ).all():
        if o.almoxarifado and o.data:
            dias[o.almoxarifado].add(o.data)
    return dias


def _dias_conciliacao_fluxo_antigo_por_almoxarifado(db: Session, data_inicio, data_fim) -> dict:
    """Dias do fluxo antigo de importação diária (planilha Sistema x
    Contagem) - cada linha importada aqui JÁ É a conciliação em si (o
    próprio import compara sistema x contagem), não é "movimentação
    bruta". Só serve de fallback pra almoxarifado que ainda não usa o
    livro-caixa bruto - nunca é combinado com ele pro mesmo almoxarifado,
    pra não contar conciliação como se fosse o próprio universo dela."""
    from collections import defaultdict
    dias = defaultdict(set)
    for h in db.query(models.MovimentacaoHistorico.almoxarifado, models.MovimentacaoHistorico.data_movimento).filter(
        models.MovimentacaoHistorico.data_movimento >= data_inicio, models.MovimentacaoHistorico.data_movimento <= data_fim,
        models.MovimentacaoHistorico.origem != "fechamento_inventario",
    ).all():
        if h.almoxarifado and h.data_movimento:
            dias[h.almoxarifado].add(h.data_movimento)
    for d in db.query(models.Divergencia.almoxarifado, models.Divergencia.data_deteccao).filter(
        models.Divergencia.data_deteccao >= data_inicio, models.Divergencia.data_deteccao <= data_fim,
        models.Divergencia.origem != "fechamento_inventario",
    ).all():
        if d.almoxarifado and d.data_deteccao:
            dias[d.almoxarifado].add(d.data_deteccao)
    return dias


def _dias_inventario_por_almoxarifado(db: Session, data_inicio, data_fim) -> dict:
    """Só os ajustes de "Inventario" do livro-caixa bruto - a conciliação
    de verdade, quando o almoxarifado usa esse fluxo novo."""
    from collections import defaultdict
    dias = defaultdict(set)
    for c in db.query(models.ConferenciaRealizada.almoxarifado, models.ConferenciaRealizada.data).filter(
        models.ConferenciaRealizada.data >= data_inicio, models.ConferenciaRealizada.data <= data_fim,
    ).all():
        if c.almoxarifado and c.data:
            dias[c.almoxarifado].add(c.data)
    return dias


def _calcular_furos(dias_operacionais_ordenados: list, dias_conferidos: set) -> list:
    """Varre só os dias OPERACIONAIS (não o calendário inteiro) e agrupa
    sequências consecutivas de dias sem conferência em "furos" - medido
    em dias de calendário decorridos entre o primeiro e o último dia sem
    conferência daquela sequência (reflete quanto tempo real o
    almoxarifado ficou sem controle, mesmo que nem todo dia no meio
    tivesse movimentação)."""
    furos, inicio_furo, fim_furo = [], None, None
    for dia in dias_operacionais_ordenados:
        if dia not in dias_conferidos:
            if inicio_furo is None:
                inicio_furo = dia
            fim_furo = dia
        else:
            if inicio_furo is not None:
                furos.append({"inicio": str(inicio_furo), "fim": str(fim_furo), "dias": (fim_furo - inicio_furo).days + 1})
                inicio_furo = None
    if inicio_furo is not None:
        furos.append({"inicio": str(inicio_furo), "fim": str(fim_furo), "dias": (fim_furo - inicio_furo).days + 1})
    return sorted(furos, key=lambda f: -f["dias"])


@router.get("/dashboard/cobertura-conferencia")
def cobertura_conferencia(dias: int = 90, almoxarifado: str | None = None, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Dias conferidos × dias pendentes de conferência, por almoxarifado -
    mede a saúde do PROCESSO de controle, não do estoque em si.

    Universo (denominador) = qualquer dia com registro de sistema, de
    QUALQUER fonte (livro-caixa bruto + fluxo antigo de importação
    diária, somados). Conferido (numerador) = todo dia do fluxo antigo
    (cada linha dele já É a conciliação em si) + os ajustes de
    "Inventario" do livro-caixa bruto, também somados. As duas fontes
    nunca se excluem - só se somam - porque um almoxarifado pode
    conciliar por um fluxo, pelo outro, ou pelos dois ao mesmo tempo em
    dias diferentes.

    A análise sempre trabalha em D-1 (hoje ainda não está encerrado
    operacionalmente)."""
    from datetime import date, timedelta
    data_fim = date.today() - timedelta(days=1)
    data_inicio = data_fim - timedelta(days=dias - 1)

    q = db.query(models.Almoxarifado).filter_by(ativo=True, participa_contagem_diaria=True)
    if almoxarifado:
        q = q.filter_by(codigo=almoxarifado)
    almoxarifados_cadastrados = [a.codigo for a in q.all()]

    bruta_por_almox = _dias_movimentacao_bruta_por_almoxarifado(db, data_inicio, data_fim)
    antiga_por_almox = _dias_conciliacao_fluxo_antigo_por_almoxarifado(db, data_inicio, data_fim)
    inventario_por_almox = _dias_inventario_por_almoxarifado(db, data_inicio, data_fim)

    resultado = []
    for almox in almoxarifados_cadastrados:
        bruta = bruta_por_almox.get(almox, set())
        antiga = antiga_por_almox.get(almox, set())
        inventario = inventario_por_almox.get(almox, set())

        # universo = qualquer dia com registro de sistema, de qualquer
        # fonte (livro-caixa bruto OU fluxo antigo de importação diária).
        # conferido = fluxo antigo inteiro (cada linha dele já É a
        # conciliação em si) + os ajustes de Inventario do livro-caixa
        # bruto. As duas fontes se somam, nunca uma exclui a outra - foi
        # exatamente isso que causou dois bugs opostos antes: ignorar o
        # livro-caixa bruto inflava a cobertura pra 100% contando fluxo
        # antigo esparso como se cobrisse tudo; ignorar o fluxo antigo
        # zerava a cobertura de almoxarifado que só concilia por ele.
        operacionais = sorted(bruta | antiga)
        conferidos = inventario | antiga
        if bruta and antiga:
            fonte = "livro_caixa_bruto + fluxo_antigo"
        elif bruta:
            fonte = "livro_caixa_bruto"
        elif antiga:
            fonte = "fluxo_antigo_importacao_diaria"
        else:
            fonte = None

        if not operacionais:
            resultado.append({
                "almoxarifado": almox, "dias_conferidos": 0, "dias_totais": 0, "pct_cobertura": None,
                "dias_desde_ultima_conferencia": None, "maior_furo_dias": 0, "maior_furo_periodo": None,
                "furos": [], "sem_dados": True, "fonte": None,
            })
            continue

        conferidos_no_universo = {d for d in operacionais if d in conferidos}
        furos = _calcular_furos(operacionais, conferidos)
        ultima_conferencia = max(conferidos_no_universo) if conferidos_no_universo else None
        # referência é o último dia OPERACIONAL de verdade desse
        # almoxarifado, não o D-1 fixo - se a operação é seg-sex e hoje é
        # segunda, o último dia operacional é a sexta anterior, não
        # domingo/sábado (que nunca tiveram movimento pra começo). Sem
        # isso, fim de semana/feriado inflava artificialmente o "atraso".
        referencia = max(operacionais)
        dias_desde_ultima = (referencia - ultima_conferencia).days if ultima_conferencia else None

        resultado.append({
            "almoxarifado": almox,
            "dias_conferidos": len(conferidos_no_universo),
            "dias_totais": len(operacionais),
            "pct_cobertura": round(len(conferidos_no_universo) / len(operacionais) * 100, 1),
            "dias_desde_ultima_conferencia": dias_desde_ultima,
            "maior_furo_dias": furos[0]["dias"] if furos else 0,
            "maior_furo_periodo": f"{formatar_data_curta_py(furos[0]['inicio'])} a {formatar_data_curta_py(furos[0]['fim'])}" if furos else None,
            "furos": furos[:10],
            "sem_dados": False,
            "fonte": fonte,
        })

    resultado.sort(key=lambda r: (r["pct_cobertura"] is None, r["pct_cobertura"]))
    return {
        "periodo_dias": dias, "data_inicio": str(data_inicio), "data_fim": str(data_fim),
        "por_almoxarifado": resultado,
    }


def formatar_data_curta_py(data_iso: str) -> str:
    partes = data_iso.split("-")
    return f"{partes[2]}/{partes[1]}" if len(partes) == 3 else data_iso


@router.get("/dashboard/calendario-conferencia")
def calendario_conferencia(almoxarifado: str, dias: int = 90, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Dia a dia de um almoxarifado específico - mesma regra de somar as
    duas fontes (ver cobertura_conferencia)."""
    from datetime import date, timedelta
    data_fim = date.today() - timedelta(days=1)
    data_inicio = data_fim - timedelta(days=dias - 1)

    bruta = _dias_movimentacao_bruta_por_almoxarifado(db, data_inicio, data_fim).get(almoxarifado, set())
    antiga = _dias_conciliacao_fluxo_antigo_por_almoxarifado(db, data_inicio, data_fim).get(almoxarifado, set())
    inventario = _dias_inventario_por_almoxarifado(db, data_inicio, data_fim).get(almoxarifado, set())

    operacionais = sorted(bruta | antiga)
    conferidos = inventario | antiga

    return [{"data": str(d), "conferido": d in conferidos} for d in operacionais]


@router.get("/dashboard/detalhe-dia-conferencia")
def detalhe_dia_conferencia(almoxarifado: str, data: str, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Todos os itens que se moveram num dia específico, num almoxarifado
    específico - alimenta o pop-up de duplo clique no calendário de
    conferência. Cada item traz um status: se já existe uma divergência
    registrada pra esse SKU (nesse almoxarifado, na data ou depois - ou
    seja, algo que pode ter sido causado ou revelado pelo furo de
    conferência daquele dia), com o id pra abrir direto; se não existe
    ainda, entra como candidato pra abrir uma investigação agora."""
    from datetime import datetime as dt
    try:
        data_alvo = dt.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Data inválida - use o formato AAAA-MM-DD.")

    itens_brutos = (
        db.query(models.MovimentacaoBruta)
        .filter(models.MovimentacaoBruta.almoxarifado == almoxarifado, models.MovimentacaoBruta.data == data_alvo)
        .all()
    )

    from collections import defaultdict
    por_sku = defaultdict(lambda: {"descricao": None, "qtd_sai": 0.0, "qtd_ent": 0.0, "operacoes": set()})
    for i in itens_brutos:
        d = por_sku[i.sku]
        d["descricao"] = d["descricao"] or i.descricao
        d["qtd_sai"] += i.qtd_sai or 0
        d["qtd_ent"] += i.qtd_ent or 0
        if i.operacao:
            d["operacoes"].add(i.operacao)

    skus = list(por_sku.keys())
    divergencias_por_sku = {}
    if skus:
        for div in db.query(models.Divergencia).filter(
            models.Divergencia.sku.in_(skus), models.Divergencia.almoxarifado == almoxarifado,
            models.Divergencia.data_deteccao >= data_alvo,
        ).order_by(models.Divergencia.data_deteccao.asc()).all():
            divergencias_por_sku.setdefault(div.sku, div)  # a primeira (mais próxima da data) fica

    itens = []
    for sku, d in sorted(por_sku.items()):
        div = divergencias_por_sku.get(sku)
        itens.append({
            "sku": sku, "descricao": d["descricao"],
            "qtd_saida": round(d["qtd_sai"], 3), "qtd_entrada": round(d["qtd_ent"], 3),
            "operacoes": sorted(d["operacoes"]),
            "tem_divergencia": div is not None,
            "divergencia_id": div.id if div else None,
            "divergencia_status": div.status if div else None,
            "divergencia_data": str(div.data_deteccao) if div else None,
        })

    return {"almoxarifado": almoxarifado, "data": data, "total_itens": len(itens), "itens": itens}


@router.get("/{div_id}", response_model=schemas.DivergenciaOut)
def detalhar(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")
    _preencher_descricao_produto(db, [div])
    _marcar_investigacao_pendente(db, [div])
    return div


@router.post("/{div_id}/marcar-investigacao", response_model=schemas.DivergenciaOut)
def marcar_investigacao(div_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Marca a divergência como 'Em investigação' sem confirmar uma causa
    ainda - usado quando alguém já está apurando o caso, mas não tem uma
    conclusão. Enquanto estiver nesse status, qualquer nova divergência do
    mesmo SKU aparece com um ícone de atenção na lista."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")
    if div.status == "Resolvida":
        raise HTTPException(400, "Essa divergência já foi resolvida.")
    div.status = "Em_Investigacao"
    registrar_log(db, usuario.username, "marcar_em_investigacao", entidade="divergencia", entidade_id=div.id)
    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    _marcar_investigacao_pendente(db, [div])
    return div


def _acuracia_pct(saldo_sistema, divergencia_qtd):
    """% de acurácia de um único apontamento - mesma lógica usada em todo
    o resto do sistema (min(contagem,sistema)/sistema), só que a partir
    da divergência já calculada em vez de saldo_fisico bruto."""
    if not saldo_sistema:
        return 100.0 if not divergencia_qtd else 0.0
    return round(max(0.0, 1 - abs(divergencia_qtd or 0) / abs(saldo_sistema)) * 100, 1)


@router.get("/{div_id}/historico-sku")
def historico_sku(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Linha do tempo do SKU desta divergência: todo registro (resolvido
    ou não, de qualquer origem) com esse SKU, pra visualizar quando as
    divergências aconteceram e quando estabilizaram, e por qual
    almoxarifado passaram os últimos apontamentos. Cada ponto já vem com
    % de acurácia e o tipo de origem (movimentação diária vs fechamento
    de inventário), pra alimentar o seletor "Linear / Movimentados /
    Inventários" e a projeção de tendência no front-end."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    pontos = []
    for h in db.query(models.MovimentacaoHistorico).filter_by(sku=div.sku).all():
        pontos.append({
            "data": str(h.data_movimento), "almoxarifado": h.almoxarifado,
            "divergencia_qtd": h.divergencia or 0, "status": "Resolvido",
            "hipotese": h.hipotese_confirmada, "origem": h.origem,
            "tipo_origem": "fechamento_inventario" if h.origem == "fechamento_inventario" else "movimentacao",
            "acuracia_pct": _acuracia_pct(h.saldo_sistema, h.divergencia),
        })
    for d in db.query(models.Divergencia).filter_by(sku=div.sku).all():
        pontos.append({
            "data": str(d.data_deteccao), "almoxarifado": d.almoxarifado,
            "divergencia_qtd": d.divergencia_qtd, "status": d.status,
            "hipotese": d.hipotese_confirmada or d.hipotese_ia, "origem": d.origem,
            "tipo_origem": "fechamento_inventario" if d.origem == "fechamento_inventario" else "movimentacao",
            "acuracia_pct": _acuracia_pct(d.saldo_sistema, d.divergencia_qtd),
        })

    pontos.sort(key=lambda p: p["data"])
    return pontos


@router.get("/{div_id}/faltas-sobras-mensal")
def faltas_sobras_mensal(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Falta e sobra do SKU comparadas mês a mês - sobra e falta contam
    separadamente (não se cancelam), pra ver se o padrão de divergência
    desse item está mudando de direção ao longo do tempo (sinal de causa
    diferente) ou é consistente. Junta as duas fontes de histórico
    (MovimentacaoHistorico + Divergencia) - a maior parte do histórico de
    um SKU normalmente vive em MovimentacaoHistorico (importações
    resolvidas), não em Divergencia (casos ainda em aberto/rastreados)."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    from collections import defaultdict
    por_mes = defaultdict(lambda: {"qtd_faltas": 0.0, "qtd_sobras": 0.0, "valor_faltas": 0.0, "valor_sobras": 0.0})

    for h in db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.sku == div.sku, models.MovimentacaoHistorico.divergencia != 0).all():
        if not h.data_movimento:
            continue
        mes = h.data_movimento.strftime("%Y-%m")
        if (h.divergencia or 0) < 0:
            por_mes[mes]["qtd_faltas"] += abs(h.divergencia)
            por_mes[mes]["valor_faltas"] += abs(h.valor_divergencia or 0)
        else:
            por_mes[mes]["qtd_sobras"] += h.divergencia
            por_mes[mes]["valor_sobras"] += abs(h.valor_divergencia or 0)

    for d in db.query(models.Divergencia).filter(models.Divergencia.sku == div.sku, models.Divergencia.divergencia_qtd != 0).all():
        if not d.data_deteccao:
            continue
        mes = d.data_deteccao.strftime("%Y-%m")
        if (d.divergencia_qtd or 0) < 0:
            por_mes[mes]["qtd_faltas"] += abs(d.divergencia_qtd)
            por_mes[mes]["valor_faltas"] += abs(d.valor_estimado or 0)
        else:
            por_mes[mes]["qtd_sobras"] += d.divergencia_qtd
            por_mes[mes]["valor_sobras"] += abs(d.valor_estimado or 0)

    return [
        {"mes": mes, **{k: round(v, 2) for k, v in valores.items()}}
        for mes, valores in sorted(por_mes.items())
    ]


@router.get("/{div_id}/motivos-sku")
def motivos_sku(div_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Todas as divergências já identificadas para este SKU, agrupadas
    por motivo (hipótese confirmada, ou a última sugestão da IA se ainda
    não confirmada) - pra ver rapidamente se um item tem uma causa
    dominante ou é uma mistura de causas diferentes. Mesma junção de
    fontes do endpoint de falta/sobra, pelo mesmo motivo."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    from collections import Counter
    contagem = Counter()
    for h in db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.sku == div.sku, models.MovimentacaoHistorico.divergencia != 0).all():
        contagem[h.hipotese_confirmada or "Sem diagnóstico ainda"] += 1
    for d in db.query(models.Divergencia).filter(models.Divergencia.sku == div.sku, models.Divergencia.divergencia_qtd != 0).all():
        contagem[d.hipotese_confirmada or d.hipotese_ia or "Sem diagnóstico ainda"] += 1

    return [{"hipotese": h, "quantidade": q} for h, q in contagem.most_common()]


@router.get("/{div_id}/correlacao-rede")
def correlacao_rede(div_id: int, janela_dias: int = 15, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Sugestão de rede: se esta divergência é uma FALTA, procura por uma
    SOBRA do mesmo SKU em OUTRO almoxarifado dentro de uma janela de
    tempo próxima (e vice-versa) - não confirma uma transferência (isso
    já é checado em Transferência Pendente), só aponta a possibilidade
    de que o estoque certo existe, só está no lugar errado."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")
    if not div.divergencia_qtd or not div.data_deteccao:
        return {"encontrado": False, "candidatos": []}

    from datetime import timedelta
    janela_min = div.data_deteccao - timedelta(days=janela_dias)
    janela_max = div.data_deteccao + timedelta(days=janela_dias)

    candidatos_brutos = []
    for c in (
        db.query(models.Divergencia)
        .filter(
            models.Divergencia.sku == div.sku, models.Divergencia.almoxarifado != div.almoxarifado, models.Divergencia.id != div.id,
            models.Divergencia.data_deteccao >= janela_min, models.Divergencia.data_deteccao <= janela_max,
        )
        .all()
    ):
        candidatos_brutos.append({"divergencia_qtd": c.divergencia_qtd, "almoxarifado": c.almoxarifado, "valor_estimado": c.valor_estimado, "data": c.data_deteccao, "status": c.status})
    for h in (
        db.query(models.MovimentacaoHistorico)
        .filter(
            models.MovimentacaoHistorico.sku == div.sku, models.MovimentacaoHistorico.almoxarifado != div.almoxarifado,
            models.MovimentacaoHistorico.data_movimento >= janela_min, models.MovimentacaoHistorico.data_movimento <= janela_max,
        )
        .all()
    ):
        candidatos_brutos.append({"divergencia_qtd": h.divergencia, "almoxarifado": h.almoxarifado, "valor_estimado": h.valor_divergencia, "data": h.data_movimento, "status": "Resolvido"})

    # sinal oposto: se esta é falta (negativa), procura sobra (positiva) em outro almoxarifado, e vice-versa
    candidatos = [c for c in candidatos_brutos if (c["divergencia_qtd"] or 0) * div.divergencia_qtd < 0]
    candidatos.sort(key=lambda c: abs(abs(c["divergencia_qtd"]) - abs(div.divergencia_qtd)))

    return {
        "encontrado": bool(candidatos),
        "tipo_desta_divergencia": "falta" if div.divergencia_qtd < 0 else "sobra",
        "candidatos": [
            {"almoxarifado": c["almoxarifado"], "divergencia_qtd": c["divergencia_qtd"], "valor_estimado": c["valor_estimado"], "data_deteccao": str(c["data"]), "status": c["status"]}
            for c in candidatos[:5]
        ],
    }


@router.get("/{div_id}/detalhes-mes")
def detalhes_mes(div_id: int, mes: str, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Detalhe de todos os apontamentos deste SKU num mês específico -
    alimenta o pop-up de duplo clique no gráfico Falta × Sobra: produto,
    sistema, contagem, diferença e data de cada ocorrência daquele mês."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    itens = []
    for h in db.query(models.MovimentacaoHistorico).filter(models.MovimentacaoHistorico.sku == div.sku, models.MovimentacaoHistorico.divergencia != 0).all():
        if h.data_movimento and h.data_movimento.strftime("%Y-%m") == mes:
            itens.append({
                "data": str(h.data_movimento), "almoxarifado": h.almoxarifado,
                "saldo_sistema": h.saldo_sistema, "saldo_fisico": h.saldo_fisico,
                "divergencia_qtd": h.divergencia, "valor_estimado": h.valor_divergencia, "hipotese": h.hipotese_confirmada,
            })
    for d in db.query(models.Divergencia).filter(models.Divergencia.sku == div.sku, models.Divergencia.divergencia_qtd != 0).all():
        if d.data_deteccao and d.data_deteccao.strftime("%Y-%m") == mes:
            itens.append({
                "data": str(d.data_deteccao), "almoxarifado": d.almoxarifado,
                "saldo_sistema": d.saldo_sistema, "saldo_fisico": d.saldo_fisico,
                "divergencia_qtd": d.divergencia_qtd, "valor_estimado": d.valor_estimado, "hipotese": d.hipotese_confirmada or d.hipotese_ia,
            })

    itens.sort(key=lambda i: i["data"])
    produto = db.query(models.Produto).filter_by(sku=div.sku).first()
    return {"sku": div.sku, "descricao_produto": produto.descricao if produto else None, "mes": mes, "itens": itens}


@router.post("/reinvestigar-falhas")
def reinvestigar_falhas(usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Reprocessa em lote só as divergências que NUNCA chegaram a ter um
    diagnóstico de verdade - hipotese_regras nula é a marca exata disso
    (toda investigação bem sucedida sempre atribui uma hipótese, mesmo
    que seja "Falha_Inventario" como conclusão; nula só acontece quando a
    investigação quebrou no meio do processo, ex: modelo de ML
    incompatível). Não toca em nenhum caso que já tem diagnóstico real -
    mesmo que a equipe não concorde com ele, isso não é reprocessado
    aqui (use "Reinvestigar" individual pra isso)."""
    afetadas = db.query(models.Divergencia).filter(models.Divergencia.hipotese_regras.is_(None)).all()
    corrigidas, ainda_com_erro = 0, []

    for div in afetadas:
        try:
            resultado_regras = investigar(db, div)
            resultado_ml = ml_predict.prever(div.sku, div.almoxarifado, div.categoria_produto, div.divergencia_qtd, div.valor_estimado, div.data_deteccao, db=db)
            hipotese_final, confianca_final = reconciliar(
                resultado_regras["scores_normalizados"], resultado_ml["distribuicao"] if resultado_ml else []
            )
            div.hipotese_regras = resultado_regras["hipotese_regras"]
            div.confianca_regras = resultado_regras["confianca_regras"]
            div.evidencias = resultado_regras["evidencias"]
            div.casos_similares = resultado_regras["casos_similares"]
            div.hipotese_ml = resultado_ml["hipotese_predita"] if resultado_ml else None
            div.confianca_ml = resultado_ml["confianca"] if resultado_ml else None
            div.distribuicao_probabilidades = resultado_ml["distribuicao"] if resultado_ml else resultado_regras["scores_normalizados"]
            div.hipotese_ia = hipotese_final
            div.confianca_ia = confianca_final
            corrigidas += 1
        except Exception as e:
            ainda_com_erro.append({"id": div.id, "sku": div.sku, "erro": str(e)})

    registrar_log(db, usuario.username, "reinvestigar_falhas_em_lote", detalhes={"total_afetadas": len(afetadas), "corrigidas": corrigidas, "ainda_com_erro": len(ainda_com_erro)})
    db.commit()
    return {"total_afetadas": len(afetadas), "corrigidas": corrigidas, "ainda_com_erro": ainda_com_erro}


@router.post("/{div_id}/reinvestigar", response_model=schemas.DivergenciaOut)
def reinvestigar(div_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Roda o motor de investigação de novo sobre um caso já existente -
    útil quando o motor ganha uma capacidade nova (ex: leitura da
    observação da planilha) e você quer que casos antigos se beneficiem
    dela sem precisar reimportar o arquivo inteiro."""
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    resultado_regras = investigar(db, div)
    resultado_ml = ml_predict.prever(div.sku, div.almoxarifado, div.categoria_produto, div.divergencia_qtd, div.valor_estimado, div.data_deteccao, db=db)
    hipotese_final, confianca_final = reconciliar(
        resultado_regras["scores_normalizados"],
        resultado_ml["distribuicao"] if resultado_ml else [],
    )

    div.hipotese_regras = resultado_regras["hipotese_regras"]
    div.confianca_regras = resultado_regras["confianca_regras"]
    div.evidencias = resultado_regras["evidencias"]
    div.casos_similares = resultado_regras["casos_similares"]
    div.hipotese_ml = resultado_ml["hipotese_predita"] if resultado_ml else None
    div.confianca_ml = resultado_ml["confianca"] if resultado_ml else None
    div.distribuicao_probabilidades = resultado_ml["distribuicao"] if resultado_ml else resultado_regras["scores_normalizados"]
    div.hipotese_ia = hipotese_final
    div.confianca_ia = confianca_final

    registrar_log(db, usuario.username, "reinvestigar_divergencia", entidade="divergencia", entidade_id=div.id,
                  detalhes={"nova_hipotese_ia": hipotese_final, "confianca_ia": confianca_final})
    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    return div


@router.post("/{div_id}/confirmar", response_model=schemas.DivergenciaOut)
def confirmar(div_id: int, payload: schemas.ConfirmarDivergencia, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    div = db.query(models.Divergencia).get(div_id)
    if not div:
        raise HTTPException(404, "Divergência não encontrada")

    hipotese_valida = db.query(models.Hipotese).filter_by(codigo=payload.hipotese_confirmada).first()
    if not hipotese_valida:
        raise HTTPException(400, f"Hipótese '{payload.hipotese_confirmada}' não existe no catálogo oficial")

    div.hipotese_confirmada = payload.hipotese_confirmada
    div.solucao_aplicada = payload.solucao_aplicada
    div.responsavel = payload.responsavel or usuario.nome_exibicao or usuario.username
    div.tempo_resolucao_minutos = payload.tempo_resolucao_minutos
    div.status = "Resolvida"
    div.resolvido_em = datetime.utcnow()

    # --- loop de aprendizado: ajusta peso da hipótese que o motor de regras sugeriu ---
    if div.hipotese_regras:
        h = db.query(models.Hipotese).filter_by(codigo=div.hipotese_regras).first()
        if h:
            if div.hipotese_regras == payload.hipotese_confirmada:
                h.peso_padrao = min(PESO_MAX, h.peso_padrao + INCREMENTO_ACERTO)
            else:
                h.peso_padrao = max(PESO_MIN, h.peso_padrao - DECREMENTO_ERRO)

    # --- registra caso para o próximo retreino do ML ---
    db.add(models.CasoMLFeedback(
        divergencia_id=div.id, sku=div.sku, almoxarifado=div.almoxarifado,
        categoria_produto=div.categoria_produto, divergencia_qtd=div.divergencia_qtd,
        valor_estimado=div.valor_estimado, data_deteccao=div.data_deteccao,
        hipotese_confirmada=payload.hipotese_confirmada,
    ))

    registrar_log(db, usuario.username, "confirmar_divergencia", entidade="divergencia", entidade_id=div.id,
                  detalhes={"hipotese_confirmada": payload.hipotese_confirmada, "solucao": payload.solucao_aplicada})

    db.commit()
    db.refresh(div)
    _preencher_descricao_produto(db, [div])
    return div
