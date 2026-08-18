"""
Lógica de negócio do controle de Shelf Life (risco de validade de lote) do
Atlas.

Contexto: Maurício tem um módulo "Shelf Life" no sistema construído no
Lovable (mapeamento de risco + ações de lote), mas sem acesso ao SQL
editor de lá - só a tela. Sem um jeito de ler os dados de origem, o Atlas
não pode se conectar a esse módulo. Em vez disso, este módulo constrói o
MESMO tipo de farol de risco (vencido / 30 / 60 / 90 dias / sem validade)
usando uma fonte de dados que o próprio Atlas controla: a planilha
"Lote_Sistema.xlsx" exportada do sistema interno da empresa (aba
"Lote_Sistema", com Dt_Validade real por lote) mais cadastro manual direto
na tela Shelf Life.

Farol de risco é sempre CALCULADO em cima de (data_validade - hoje), nunca
armazenado - evita farol desatualizado se um lote ficar dias sem
reimportar/revisar.
"""
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from . import models
from .csv_utils import parse_sku, parse_decimal, parse_data, limpar_texto
from .hipoteses_config import normalizar_almoxarifado

# Cabeçalhos esperados na aba "Lote_Sistema" do arquivo exportado pelo
# sistema interno da empresa (Lote_Sistema.xlsx, enviado por Maurício em
# 2026-08). Se o layout de exportação mudar, ajuste aqui em vez de mudar a
# lógica de importação.
COLUNAS_LOTE_SISTEMA = {
    "ativo": "Ativo",
    "tipo_material": "TipoMaterial",
    "sku": "Id_produto",
    "descricao": "descricao",
    "unidade": "um",
    "origem": "Origem",
    "quantidade": "Qtd",
    "lote": "Lote",
    "data_validade": "Dt_Validade",
    "peso_kg": "Peso_Kg",
    "custo": "Custo_Vlr",
    "ean": "EAN",
    # "Grupo" (ex: Produto Acabado, Embalagem, Ativo Imobilizado, Materia Prima...)
    # passou a vir na exportação a partir de 20/08/2026 - NÃO é obrigatória (ver
    # COLUNAS_OBRIGATORIAS_LOTE_SISTEMA abaixo), pra continuar aceitando uma
    # exportação mais antiga sem essa coluna. Quando ausente, a exclusão de
    # Embalagens no indicador cai pro fallback por palavra-chave na descrição
    # (ver GRUPOS_EXCLUIDOS_SHELF_LIFE / _eh_item_embalagem).
    "grupo": "Grupo",
}

COLUNAS_OBRIGATORIAS_LOTE_SISTEMA = (COLUNAS_LOTE_SISTEMA["sku"], COLUNAS_LOTE_SISTEMA["lote"], COLUNAS_LOTE_SISTEMA["data_validade"])

FAROL_VENCIDO = "vencido"
FAROL_30 = "30"
FAROL_60 = "60"
FAROL_90 = "90"
FAROL_OK = "ok"
FAROL_SEM_VALIDADE = "sem_validade"

FAROIS_DE_RISCO = (FAROL_VENCIDO, FAROL_30, FAROL_60, FAROL_90)  # não inclui ok nem sem_validade

# Palavras-chave pra excluir embalagens (caixas, sacolas, rótulos, tampas...)
# do indicador de Shelf Life (pedido do usuário, 18/08/2026: "desconsidere o
# grupo de produtos Embalagens da análise, pois não deveriam impactar o
# indicador de Shelf"). O cadastro de Lote Shelf Life não tem hoje um campo
# de grupo/categoria de produto (só tipo_material: MateriaPrima / Produto /
# SubConjunto / Diversos) - a validade de uma embalagem não representa o
# mesmo tipo de risco de perda que a de uma matéria-prima/produto perecível,
# então a saída escolhida foi um filtro por palavra-chave na descrição do
# item, sem precisar recadastrar/reimportar nada. Ajuste esta lista se
# aparecer um falso positivo/negativo real (ex: um item de embalagem que não
# contém nenhuma destas palavras, ou um item perecível cuja descrição
# contém uma delas por coincidência).
PALAVRAS_CHAVE_EMBALAGEM = (
    "embalagem", "sacola", "rótulo", "rotulo", "etiqueta", "fita adesiva",
    "lacre", "filme", "bobina", "tampa", "válvula", "valvula", "envelope",
    "blister",
    # "caixa"/"pote"/"frasco"/"saco"/"display" ficaram FORA de propósito
    # (20/08/2026, achado numa QA de ponta a ponta): produto chocolateiro
    # comumente é vendido "em caixa"/"em pote"/"em display" (ex.: "Bombom
    # Trufado Caixa 12un" é um PRODUTO acabado perecível, não uma embalagem)
    # - como palavra isolada, esses termos geram falso positivo justamente
    # no tipo de item que este indicador precisa monitorar. Versão qualificada
    # dessas mesmas palavras, restrita a contextos claramente de insumo de
    # embalagem (não de produto acabado embalado):
    "caixa de papelão", "caixa papelão", "caixa vazia", "caixa de embalagem",
    "saco plástico", "saco de papel", "pote vazio", "frasco vazio",
    "display vazio", "display de papelão",
)


def _eh_item_embalagem(descricao) -> bool:
    texto = (descricao or "").lower()
    return any(palavra in texto for palavra in PALAVRAS_CHAVE_EMBALAGEM)


# Grupos de produto excluídos do indicador de Shelf Life (pedido do usuário,
# 20/08/2026): Embalagem e Ativo Imobilizado não representam o mesmo tipo de
# risco de perda por validade que matéria-prima/produto perecível - uma
# embalagem "vencendo" ou um ativo imobilizado (ex: equipamento com validade
# de calibração cadastrada por engano num campo de validade) não deveriam
# contar pro indicador. Comparação normalizada (minúsculo + sem espaço extra)
# contra o valor exato vindo da coluna "Grupo" da planilha - cobre tanto a
# forma singular quanto a plural, caso a exportação varie.
GRUPOS_EXCLUIDOS_SHELF_LIFE = ("embalagem", "embalagens", "ativo imobilizado", "ativos imobilizados")

# Almoxarifados excluídos do indicador de Shelf Life (pedido do usuário,
# 20/08/2026): Box e Box 2 são áreas de triagem/trânsito de embalagens e
# materiais diversos, não estoque de produto/matéria-prima em risco real de
# obsolescência - mesmo raciocínio da exclusão por Grupo acima, mas por
# almoxarifado. Usa o código já normalizado (ver hipoteses_config.
# normalizar_almoxarifado) pra não depender de como o almoxarifado chegou
# escrito na planilha de origem.
ALMOXARIFADOS_EXCLUIDOS_SHELF_LIFE = ("Almox_Box", "Almox_Box_2")


def _grupo_excluido(grupo_produto) -> bool:
    if not grupo_produto:
        return False
    return grupo_produto.strip().lower() in GRUPOS_EXCLUIDOS_SHELF_LIFE


def _item_excluido_do_indicador(lote) -> bool:
    """Decide se um LoteShelfLife deve ficar de fora do Farol/Mapeamento de
    Risco. Prioriza o Grupo vindo da planilha (mais confiável) quando
    presente; só cai pro filtro por palavra-chave na descrição
    (_eh_item_embalagem) quando o lote não tem Grupo cadastrado (planilha
    antiga sem essa coluna, ou lote cadastrado manualmente na tela)."""
    if lote.grupo_produto:
        return _grupo_excluido(lote.grupo_produto)
    return _eh_item_embalagem(lote.descricao_produto)


def _data_excel_serial(valor_serial) -> date:
    """Converte um número serial de data do Excel (dias desde 30/12/1899 -
    a 'época' do Excel, que inclui um dia bissexto fictício em 1900) pra
    date do Python. Só chamado quando a célula chega como número puro em
    vez de datetime - openpyxl converte células com formatação de data
    normalmente, mas uma célula sem essa formatação (mesmo contendo uma
    data) chega como int/float bruto. Visto pelo menos 1 vez na planilha
    real (Dt_Validade = 46476 -> 2027-03-01)."""
    return date(1899, 12, 30) + timedelta(days=int(valor_serial))


def parse_data_validade(valor):
    """Aceita datetime (caso normal - openpyxl já converteu), date, número
    serial do Excel (ver _data_excel_serial acima) ou vazio/None. None é
    um resultado válido e esperado: significa material sem validade
    rastreada no sistema de origem (ex: itens 'Diversos'), não um erro de
    leitura - tratado como farol próprio (FAROL_SEM_VALIDADE), nunca
    descartado silenciosamente."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        if valor != valor:  # NaN
            return None
        return _data_excel_serial(valor)
    s = str(valor).strip()
    if s == "" or s.lower() == "nan":
        return None
    return parse_data(s)


def calcular_farol(data_validade, hoje=None):
    """Farol de risco a partir de dias até o vencimento (data_validade -
    hoje). Sem validade cadastrada não conta como 'ok' (isso escondería um
    problema de cadastro) nem é forçado pra um risco (adivinharia errado)
    - fica na sua própria categoria (FAROL_SEM_VALIDADE), igual ao KPI
    'Pendente de Validade' do módulo de referência que Maurício mostrou no
    Lovable."""
    if data_validade is None:
        return FAROL_SEM_VALIDADE
    hoje = hoje or date.today()
    dias = (data_validade - hoje).days
    if dias < 0:
        return FAROL_VENCIDO
    if dias <= 30:
        return FAROL_30
    if dias <= 60:
        return FAROL_60
    if dias <= 90:
        return FAROL_90
    return FAROL_OK


def _linha_para_campos(linha: dict):
    """Traduz uma linha bruta (dict cabeçalho->valor, vinda da aba
    Lote_Sistema) pros campos do modelo LoteShelfLife. Retorna None se a
    linha não tem SKU (linha em branco/separadora da planilha) - não é
    erro, só é ignorada."""
    sku = parse_sku(linha.get(COLUNAS_LOTE_SISTEMA["sku"]))
    if not sku:
        return None
    origem_bruta = limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["origem"]))
    ativo_bruto = str(linha.get(COLUNAS_LOTE_SISTEMA["ativo"]) or "").strip().upper()
    return {
        "sku": sku,
        "descricao_produto": limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["descricao"])),
        "tipo_material": limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["tipo_material"])),
        # .get(..., None) explícito (em vez de .get(chave)) só por clareza - o dict já
        # vem de zip(cabecalho, linha), então uma planilha sem a coluna "Grupo"
        # simplesmente não tem essa chave, e .get devolve None do mesmo jeito.
        "grupo_produto": limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["grupo"], None)),
        "almoxarifado": normalizar_almoxarifado(origem_bruta) if origem_bruta else None,
        "almoxarifado_origem": origem_bruta,
        "lote": limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["lote"])),
        "quantidade": parse_decimal(linha.get(COLUNAS_LOTE_SISTEMA["quantidade"], 0)),
        "unidade": limpar_texto(linha.get(COLUNAS_LOTE_SISTEMA["unidade"])),
        "data_validade": parse_data_validade(linha.get(COLUNAS_LOTE_SISTEMA["data_validade"])),
        "peso_kg": parse_decimal(linha.get(COLUNAS_LOTE_SISTEMA["peso_kg"], 0)),
        # Custo_Vlr na planilha de origem é custo unitário do item (não o
        # valor total do lote) - confere com a magnitude real dos dados
        # enviados (ex: R$0,94/PC numa caixa, R$79,79/PC numa cerâmica) e
        # com a convenção usada em todo o resto do Atlas (custo_unitario x
        # quantidade = valor estimado).
        "custo_unitario": parse_decimal(linha.get(COLUNAS_LOTE_SISTEMA["custo"], 0)),
        "ativo": ativo_bruto not in ("N", "NAO", "NÃO", "FALSE", "0"),
    }


def importar_linhas_lote_sistema(db: Session, linhas: list[dict], usuario: str) -> dict:
    """Upsert por chave natural (sku, lote, almoxarifado) - reimportar a
    mesma planilha (ou uma exportação mais recente) atualiza os lotes já
    conhecidos em vez de duplicar. Ao contrário do padrão 'substituição
    completa' usado em outras importações do Atlas (Faturamento, BOM...),
    aqui NÃO apaga o que não está na planilha nova: lotes cadastrados à
    mão na tela, ou vindos de uma importação anterior e já consumidos na
    planilha mais nova, continuam existindo (a planilha é uma fonte entre
    outras, não a única - e query de "consumido" não é objetivo deste
    importador)."""
    criados, atualizados, ignorados_sem_sku, nao_mapeados = 0, 0, 0, set()
    for linha in linhas:
        campos = _linha_para_campos(linha)
        if campos is None:
            ignorados_sem_sku += 1
            continue
        if campos["almoxarifado"] and campos["almoxarifado"].startswith("NAO_MAPEADO__"):
            nao_mapeados.add(campos["almoxarifado_origem"])

        existente = db.query(models.LoteShelfLife).filter_by(
            sku=campos["sku"], lote=campos["lote"], almoxarifado=campos["almoxarifado"],
        ).first()
        if existente:
            for chave, valor in campos.items():
                setattr(existente, chave, valor)
            existente.origem_cadastro = "importacao_planilha"
            existente.atualizado_em = datetime.utcnow()
            atualizados += 1
        else:
            db.add(models.LoteShelfLife(**campos, origem_cadastro="importacao_planilha", criado_por=usuario))
            criados += 1

    return {
        "criados": criados,
        "atualizados": atualizados,
        "ignorados_sem_sku": ignorados_sem_sku,
        "almoxarifados_nao_mapeados": sorted(nao_mapeados),
    }


def calcular_resumo_shelf_life(db: Session, incluir_itens: bool = True, limite_itens: int = 200) -> dict:
    """Farol de risco de validade - alimenta tanto a tela dedicada de
    Shelf Life quanto o bloco de Shelf Life do Mapa de Demandas (tela
    Início). Só considera lotes ativos com quantidade > 0 - lote zerado
    ou inativado (Ativo=N na planilha de origem) não é risco: já saiu do
    estoque ou foi descartado, não deveria continuar aparecendo. Também
    desconsidera os grupos Embalagem/Ativo Imobilizado (_item_excluido_do_
    indicador) e os almoxarifados Box/Box 2 (ALMOXARIFADOS_EXCLUIDOS_SHELF_LIFE),
    pedido do usuário (20/08/2026)."""
    hoje = date.today()
    lotes = db.query(models.LoteShelfLife).filter(models.LoteShelfLife.ativo.is_(True)).all()

    resumo = {
        FAROL_VENCIDO: {"quantidade": 0, "valor": 0.0},
        FAROL_30: {"quantidade": 0, "valor": 0.0},
        FAROL_60: {"quantidade": 0, "valor": 0.0},
        FAROL_90: {"quantidade": 0, "valor": 0.0},
        FAROL_SEM_VALIDADE: {"quantidade": 0, "valor": 0.0},
    }
    itens = []
    itens_excluidos_grupo = 0
    itens_excluidos_almoxarifado = 0
    for l in lotes:
        if not l.quantidade or l.quantidade <= 0:
            continue
        if l.almoxarifado in ALMOXARIFADOS_EXCLUIDOS_SHELF_LIFE:
            itens_excluidos_almoxarifado += 1
            continue
        if _item_excluido_do_indicador(l):
            itens_excluidos_grupo += 1
            continue
        farol = calcular_farol(l.data_validade, hoje)
        valor = round((l.quantidade or 0) * (l.custo_unitario or 0), 2)
        if farol == FAROL_OK:
            continue
        resumo[farol]["quantidade"] += 1
        resumo[farol]["valor"] += valor
        if incluir_itens:
            itens.append({
                "id": l.id,
                "sku": l.sku,
                "descricao_produto": l.descricao_produto,
                "lote": l.lote,
                "almoxarifado": l.almoxarifado,
                "quantidade": l.quantidade,
                "unidade": l.unidade,
                "data_validade": str(l.data_validade) if l.data_validade else None,
                "dias_para_vencer": (l.data_validade - hoje).days if l.data_validade else None,
                "valor_estimado": valor,
                "farol": farol,
            })
    for f in resumo:
        resumo[f]["valor"] = round(resumo[f]["valor"], 2)
    itens.sort(key=lambda x: x["dias_para_vencer"] if x["dias_para_vencer"] is not None else 999999)

    total_lotes_em_risco = sum(resumo[f]["quantidade"] for f in FAROIS_DE_RISCO)
    valor_total_em_risco = round(sum(resumo[f]["valor"] for f in FAROIS_DE_RISCO), 2)

    return {
        "resumo": resumo,
        "total_lotes_em_risco": total_lotes_em_risco,
        "valor_total": valor_total_em_risco,
        "pendente_validade": resumo[FAROL_SEM_VALIDADE],
        "itens": itens[:limite_itens],
        "total_itens": len(itens),
        "itens_excluidos_grupo": itens_excluidos_grupo,
        "itens_excluidos_almoxarifado": itens_excluidos_almoxarifado,
    }


# Janela de "giro recente" usada pra cruzar risco de validade com consumo real
# (ver calcular_mapeamento_risco_obsolescencia) - mesma ordem de grandeza do
# horizonte de risco do Farol (vencido/30/60/90 dias), pra comparar maçã com
# maçã: "esse lote vai vencer em até 90 dias, será que o ritmo de saída dos
# últimos 90 dias é suficiente pra escoar o estoque a tempo?".
JANELA_GIRO_DIAS = 90


def calcular_mapeamento_risco_obsolescencia(db: Session, janela_dias: int = JANELA_GIRO_DIAS, limite_itens: int = 200) -> dict:
    """Mapeamento de Risco por obsolescência (pedido do usuário, 18/08/2026):
    "Mapeamento de risco, baseado nos itens que representam um risco para o
    negócio por obsolescência". Só "vai vencer em breve" (Farol de Shelf
    Life) não é o mesmo que "risco real de virar perda" - um lote pode estar
    perto de vencer mas ter saída rápida o bastante pra escoar antes; outro
    pode ter validade longa mas estar tão parado que, no ritmo atual, nunca
    vai escoar. Este indicador cruza os dois sinais:

      1. Risco de validade (mesmo cálculo do Farol de Shelf Life -
         calcular_farol - restrito a vencido/30/60/90 dias; itens "ok" ou
         sem validade cadastrada não entram aqui, mesmo com giro baixo,
         porque validade longa por si só não é risco iminente).
      2. Giro recente = soma de saída (Movimentados, origem == "movimentacao",
         MESMA fonte usada pelo Controle de Movimentados - ver
         movimentados_router.py) nos últimos `janela_dias` dias, por SKU.

    Classificação (heurística simples, não um forecast estatístico):
      - "Crítico": zero saída registrada na janela - lote parado, vencendo.
      - "Atenção": giro recente é MENOR que a quantidade em estoque hoje -
        no ritmo atual de saída, o lote não escoa antes de vencer.
      - Giro suficiente (>= quantidade em estoque): não entra na lista -
        risco de validade existe, mas o consumo real já está dando conta.

    Mesma exclusão de Embalagem/Ativo Imobilizado e de almoxarifado
    (Box/Box 2) do Farol de Shelf Life (_item_excluido_do_indicador /
    ALMOXARIFADOS_EXCLUIDOS_SHELF_LIFE) - uma embalagem ou ativo imobilizado
    "vencendo" parado numa área de triagem não é o mesmo tipo de risco de
    negócio que um insumo/produto perecível parado no estoque."""
    hoje = date.today()
    inicio_janela = hoje - timedelta(days=janela_dias)

    lotes = db.query(models.LoteShelfLife).filter(models.LoteShelfLife.ativo.is_(True)).all()
    candidatos = []
    for l in lotes:
        if not l.quantidade or l.quantidade <= 0:
            continue
        if l.almoxarifado in ALMOXARIFADOS_EXCLUIDOS_SHELF_LIFE:
            continue
        if _item_excluido_do_indicador(l):
            continue
        farol = calcular_farol(l.data_validade, hoje)
        if farol not in FAROIS_DE_RISCO:
            continue
        candidatos.append((l, farol))

    if not candidatos:
        return {
            "tem_dados": False, "janela_dias": janela_dias, "quantidade_itens": 0,
            "valor_total_risco": 0.0, "quantidade_criticos": 0, "valor_criticos": 0.0, "itens": [],
        }

    skus = sorted({l.sku for l, _ in candidatos})
    giro_por_sku = dict.fromkeys(skus, 0.0)
    linhas_mov = (
        db.query(models.MovimentacaoHistorico.sku, models.MovimentacaoHistorico.saida)
        .filter(
            models.MovimentacaoHistorico.sku.in_(skus),
            models.MovimentacaoHistorico.origem == "movimentacao",
            models.MovimentacaoHistorico.data_movimento >= inicio_janela,
        )
        .all()
    )
    for sku, saida in linhas_mov:
        giro_por_sku[sku] = giro_por_sku.get(sku, 0.0) + (saida or 0.0)

    itens = []
    for l, farol in candidatos:
        giro = giro_por_sku.get(l.sku, 0.0)
        if giro <= 0:
            classificacao = "Crítico"
        elif giro < (l.quantidade or 0):
            classificacao = "Atenção"
        else:
            continue  # giro já dá conta do estoque no ritmo atual - não é risco de obsolescência
        valor = round((l.quantidade or 0) * (l.custo_unitario or 0), 2)
        itens.append({
            "sku": l.sku,
            "descricao_produto": l.descricao_produto,
            "lote": l.lote,
            "almoxarifado": l.almoxarifado,
            "quantidade": l.quantidade,
            "unidade": l.unidade,
            "data_validade": str(l.data_validade) if l.data_validade else None,
            "dias_para_vencer": (l.data_validade - hoje).days if l.data_validade else None,
            "valor_estimado": valor,
            "giro_recente": round(giro, 2),
            "farol": farol,
            "classificacao": classificacao,
        })
    itens.sort(key=lambda x: (-(x["valor_estimado"] or 0)))

    return {
        "tem_dados": True,
        "janela_dias": janela_dias,
        "quantidade_itens": len(itens),
        "valor_total_risco": round(sum(i["valor_estimado"] for i in itens), 2),
        "quantidade_criticos": sum(1 for i in itens if i["classificacao"] == "Crítico"),
        "valor_criticos": round(sum(i["valor_estimado"] for i in itens if i["classificacao"] == "Crítico"), 2),
        "itens": itens[:limite_itens],
    }
