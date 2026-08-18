"""
Cálculo de checagens de FEFO (First-Expired-First-Out) - ver docstring de
models.ChecagemFefo pra regra completa e a suposição documentada. Isolado
num módulo próprio (fora do router) pra facilitar troca da regra sem tocar
em HTTP/permissões.
"""
import re
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from . import models
from .csv_utils import parse_sku, parse_decimal, limpar_texto
from .hipoteses_config import normalizar_almoxarifado

ALMOXARIFADO_FABRICA = "Almox_SP_Fabrica"
JANELA_DIAS_UTEIS = 5  # prazo operacional de movimentação mencionado pelo usuário (18/08/2026)


def _dias_uteis_entre(data_inicio: date, data_fim: date) -> int:
    """Dias úteis (seg-sex) entre duas datas, sem contar a data_inicio -
    não considera feriados (não há calendário de feriados no sistema hoje;
    se isso importar, dá pra plugar uma lista de feriados aqui depois)."""
    if not data_inicio or not data_fim or data_fim <= data_inicio:
        return 0
    dias = 0
    d = data_inicio
    while d < data_fim:
        d += timedelta(days=1)
        if d.weekday() < 5:
            dias += 1
    return dias


def calcular_checagem_fefo(db: Session, transferencia: models.Transferencia, hoje: date = None) -> dict:
    """Calcula o resultado de uma checagem de FEFO pra uma Transferencia
    elegível (origem = Fábrica) - ver models.ChecagemFefo pra regra
    completa. Retorna um dict pronto pra popular/atualizar um
    ChecagemFefo (sem tocar no banco - quem chama decide se faz upsert)."""
    hoje = hoje or date.today()

    base = {
        "transferencia_id": transferencia.id,
        "sku": transferencia.sku,
        "descricao_produto": transferencia.descricao,
        "almoxarifado_origem": transferencia.almoxarifado_origem,
        "almoxarifado_destino": transferencia.almoxarifado_destino,
        "data_saida": transferencia.data_saida,
        "quantidade_transferida": transferencia.quantidade,
    }

    lotes_sku_fabrica = db.query(models.LoteShelfLife).filter(
        models.LoteShelfLife.sku == transferencia.sku,
        models.LoteShelfLife.almoxarifado == ALMOXARIFADO_FABRICA,
        models.LoteShelfLife.ativo.is_(True),
    ).all()

    if not lotes_sku_fabrica:
        # não temos NENHUM lote cadastrado desse SKU na Fábrica (planilha
        # de Lote_Sistema nunca trouxe esse SKU, ou ele não é rastreado
        # por lote/validade) - não dá pra avaliar FEFO sem essa base.
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Sem_Dado_Suficiente"}

    candidatos = [l for l in lotes_sku_fabrica if l.data_validade and (l.quantidade or 0) > 0]
    if not candidatos:
        # temos cadastro do SKU na Fábrica, mas nenhum lote com validade
        # conhecida E estoque positivo sobrando lá - nada em risco.
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Dentro_Do_Criterio"}

    if not transferencia.data_saida:
        return {**base, "lote_mais_antigo_sku": None, "validade_lote_mais_antigo": None,
                "quantidade_remanescente_lote_antigo": None, "dias_uteis_em_aberto": None,
                "resultado": "Sem_Dado_Suficiente"}

    lote_mais_antigo = min(candidatos, key=lambda l: l.data_validade)
    dias_uteis = _dias_uteis_entre(transferencia.data_saida, hoje)
    resultado = "Quebra_Fefo" if dias_uteis > JANELA_DIAS_UTEIS else "Dentro_Do_Criterio"

    return {
        **base,
        "lote_mais_antigo_sku": lote_mais_antigo.lote,
        "validade_lote_mais_antigo": lote_mais_antigo.data_validade,
        "quantidade_remanescente_lote_antigo": lote_mais_antigo.quantidade,
        "dias_uteis_em_aberto": dias_uteis,
        "resultado": resultado,
    }


def recalcular_checagens_fefo(db: Session, hoje: date = None) -> dict:
    """Roda a checagem pra toda Transferencia elegível (origem = Fábrica,
    com sku e data_saida preenchidos) e faz upsert em ChecagemFefo por
    transferencia_id. Idempotente - pode ser chamado quantas vezes quiser
    (ex: de novo depois de reimportar a planilha de lotes, ou num
    agendador diário)."""
    transferencias = db.query(models.Transferencia).filter(
        models.Transferencia.almoxarifado_origem == ALMOXARIFADO_FABRICA,
        models.Transferencia.sku.isnot(None),
    ).all()

    criadas, atualizadas = 0, 0
    for transf in transferencias:
        campos = calcular_checagem_fefo(db, transf, hoje=hoje)
        existente = db.query(models.ChecagemFefo).filter_by(transferencia_id=transf.id).first()
        if existente:
            for chave, valor in campos.items():
                setattr(existente, chave, valor)
            from datetime import datetime
            existente.calculado_em = datetime.utcnow()
            atualizadas += 1
        else:
            db.add(models.ChecagemFefo(**campos))
            criadas += 1

    return {"transferencias_avaliadas": len(transferencias), "checagens_criadas": criadas, "checagens_atualizadas": atualizadas}


# ═════════════════════════════════════════════════════════════════════════
# Auditoria FEFO importada (20/08/2026, pedido do usuário: "consolide o
# histórico e suba pro atlas [...] baseado nas ferramentas de importação
# que já existem, consolide o relatório dentro do Atlas") - ver
# models.AuditoriaFefo pro que isso é e por que é diferente de
# ChecagemFefo/calcular_checagem_fefo acima.
# ═════════════════════════════════════════════════════════════════════════

FONTE_AUDITORIA_DIARIA = "auditoria_diaria"
FONTE_DASHBOARD_CONSOLIDADO = "dashboard_consolidado"

STATUS_DESTINO_NAO_AUDITADO = "Destino (não auditado)"

# Cabeçalho exato da aba "Todas as Movimentações" do Excel de auditoria
# diária (ver Auditar_FEFO.ipynb do estagiário, função gerar_excel/COLUNAS) -
# usado pra validar o arquivo antes de importar.
COLUNAS_AUDITORIA_FEFO_DIARIA = (
    "Data", "ID Produto", "Descrição", "Movimento", "Almoxarifado",
    "Lote Movimentado", "Qtd Lote Movimentado", "Validade Lote Movimentado",
    "Quebra FEFO", "Status", "Lote Mais Antigo Disponível",
    "Qtd Lote Mais Antigo Disponível", "Validade Mais Antiga Disponível",
)
ABA_AUDITORIA_FEFO_DIARIA = "Todas as Movimentações"


def _data_valor(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    texto = str(v).strip()
    if not texto or texto.lower() == "nan":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _num_valor(v):
    if v is None:
        return None
    try:
        texto = str(v).strip()
        if not texto or texto.lower() == "nan":
            return None
        return float(texto.replace(".", "").replace(",", ".")) if "," in texto and "." in texto else float(texto.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _texto_valor(v):
    if v is None:
        return None
    texto = str(v).strip()
    return texto or None


def extrair_destino_movimento(movimento) -> str | None:
    """Extrai o texto de destino a partir de 'Origem -> Destino'/'Origem
    --> Destino' (o próprio arquivo de origem não é consistente no
    separador) - usado só pros agrupamentos do relatório do Atlas, não
    reaproveita a função equivalente do estagiário (ela lia o campo errado
    pro que o nome sugeria - ver DashBoard_FEFO.ipynb)."""
    if not movimento:
        return None
    partes = re.split(r"-+>", str(movimento))
    if len(partes) < 2:
        return str(movimento).strip() or None
    return partes[-1].strip() or None


def _linha_auditoria_diaria_para_campos(linha: dict, arquivo_origem: str) -> dict | None:
    data_val = _data_valor(linha.get("Data"))
    if data_val is None:
        return None
    return {
        "data": data_val,
        "sku": _texto_valor(linha.get("ID Produto")),
        "descricao_produto": _texto_valor(linha.get("Descrição")),
        "movimento": _texto_valor(linha.get("Movimento")),
        "almoxarifado": _texto_valor(linha.get("Almoxarifado")),
        "lote_movimentado": _texto_valor(linha.get("Lote Movimentado")),
        "qtd_lote_movimentado": _num_valor(linha.get("Qtd Lote Movimentado")),
        "validade_lote_movimentado": _data_valor(linha.get("Validade Lote Movimentado")),
        "quebra_fefo": (_texto_valor(linha.get("Quebra FEFO")) or "").upper() == "SIM",
        "status": _texto_valor(linha.get("Status")),
        "lote_mais_antigo_disponivel": _texto_valor(linha.get("Lote Mais Antigo Disponível")),
        "qtd_lote_mais_antigo_disponivel": _num_valor(linha.get("Qtd Lote Mais Antigo Disponível")),
        "validade_mais_antiga_disponivel": _data_valor(linha.get("Validade Mais Antiga Disponível")),
        "fonte": FONTE_AUDITORIA_DIARIA,
        "arquivo_origem": arquivo_origem,
    }


def importar_auditoria_fefo_diaria(db: Session, linhas: list[dict], arquivo_origem: str, usuario: str) -> dict:
    """Importa a aba 'Todas as Movimentações' de UM Excel de auditoria
    diária (um arquivo = um dia, ver docstring de models.AuditoriaFefo).
    Substitui por completo as linhas já importadas daquele MESMO dia com
    fonte='auditoria_diaria' (reimportar o mesmo dia corrige em vez de
    duplicar) - não toca em outros dias, nem em linhas
    'dashboard_consolidado' desse mesmo dia (a auditoria diária é sempre
    preferida quando as duas existem - ver importar_auditoria_fefo_consolidada)."""
    campos_validos = [c for c in (_linha_auditoria_diaria_para_campos(l, arquivo_origem) for l in linhas) if c is not None]
    ignoradas = len(linhas) - len(campos_validos)

    datas = sorted({c["data"] for c in campos_validos})
    removidas = 0
    for d in datas:
        removidas += db.query(models.AuditoriaFefo).filter_by(data=d, fonte=FONTE_AUDITORIA_DIARIA).delete()

    for campos in campos_validos:
        db.add(models.AuditoriaFefo(**campos, importado_por=usuario))

    auditaveis = [c for c in campos_validos if c["status"] != STATUS_DESTINO_NAO_AUDITADO]
    quebras = [c for c in auditaveis if c["quebra_fefo"]]

    return {
        "dias_importados": [str(d) for d in datas],
        "linhas_importadas": len(campos_validos),
        "linhas_ignoradas_sem_data": ignoradas,
        "linhas_substituidas": removidas,
        "movimentos_auditaveis": len(auditaveis),
        "quebras_no_arquivo": len(quebras),
    }


def _linha_consolidada_para_campos(registro: dict, arquivo_origem: str) -> dict | None:
    data_val = _data_valor(registro.get("data"))
    if data_val is None:
        return None
    categoria = registro.get("categoria")
    return {
        "data": data_val,
        "sku": None,  # o dashboard consolidado do estagiário não guarda o ID do produto, só a descrição
        "descricao_produto": _texto_valor(registro.get("descricao")),
        "movimento": _texto_valor(registro.get("movimento")),
        "almoxarifado": _texto_valor(registro.get("almox")),
        "lote_movimentado": None,
        "qtd_lote_movimentado": _num_valor(registro.get("qtd")),
        "validade_lote_movimentado": None,
        "quebra_fefo": categoria == "quebra",
        "status": _texto_valor(registro.get("status")),
        "lote_mais_antigo_disponivel": None,
        "qtd_lote_mais_antigo_disponivel": None,
        "validade_mais_antiga_disponivel": None,
        "fonte": FONTE_DASHBOARD_CONSOLIDADO,
        "arquivo_origem": arquivo_origem,
    }


def extrair_registros_dashboard_consolidado(html_content: str) -> list[dict]:
    """Extrai o array `const RAW = [...]` embutido no HTML do dashboard que
    o estagiário já consolidava localmente (ver DashBoard_FEFO.ipynb) - é
    JSON puro (json.dumps no próprio script dele), só precisa achar onde
    começa e termina dentro do <script>."""
    m = re.search(r"const RAW\s*=\s*(\[.*?\])\s*;", html_content, re.DOTALL)
    if not m:
        raise ValueError("Não encontrei 'const RAW = [...]' no HTML - não é o dashboard consolidado esperado.")
    return json.loads(m.group(1))


def importar_auditoria_fefo_consolidada(db: Session, registros: list[dict], arquivo_origem: str, usuario: str) -> dict:
    """Importa os registros do dashboard consolidado (menos detalhado - ver
    docstring de models.AuditoriaFefo) só pra estender o histórico a dias
    que NÃO têm um Excel de auditoria diária já importado (fonte
    'auditoria_diaria' sempre vence quando as duas existem pro mesmo dia -
    dias pulados aqui não são substituídos, só ignorados, então reimportar
    depois de subir mais dias de auditoria diária não sobrescreve nada
    sozinho; se quiser forçar a prevalência da diária depois de importar o
    consolidado primeiro, reimporte a diária - ela sempre limpa o dia dela).
    Substitui por completo o que já existia com fonte='dashboard_consolidado'
    (é sempre a mesma fonte única, reimportar corrige em vez de duplicar)."""
    dias_com_auditoria_diaria = {
        d for (d,) in db.query(models.AuditoriaFefo.data).filter_by(fonte=FONTE_AUDITORIA_DIARIA).distinct().all()
    }

    campos_validos = []
    dias_pulados = set()
    for registro in registros:
        campos = _linha_consolidada_para_campos(registro, arquivo_origem)
        if campos is None:
            continue
        if campos["data"] in dias_com_auditoria_diaria:
            dias_pulados.add(campos["data"])
            continue
        campos_validos.append(campos)

    db.query(models.AuditoriaFefo).filter_by(fonte=FONTE_DASHBOARD_CONSOLIDADO).delete()
    for campos in campos_validos:
        db.add(models.AuditoriaFefo(**campos, importado_por=usuario))

    quebras = sum(1 for c in campos_validos if c["quebra_fefo"])
    dias_importados = sorted({c["data"] for c in campos_validos})

    return {
        "linhas_importadas": len(campos_validos),
        "linhas_no_arquivo": len(registros),
        "dias_importados": len(dias_importados),
        "periodo_importado": (str(dias_importados[0]), str(dias_importados[-1])) if dias_importados else None,
        "dias_pulados_ja_cobertos_por_auditoria_diaria": sorted(str(d) for d in dias_pulados),
        "quebras_no_periodo_importado": quebras,
    }


def calcular_resumo_auditoria_fefo(db: Session, data_inicio: date = None, data_fim: date = None) -> dict:
    """Agrega o histórico importado de AuditoriaFefo pro painel nativo do
    Atlas (tela FEFO) - exclui 'Destino (não auditado)' das métricas de taxa
    de quebra, do mesmo jeito que o próprio processo do estagiário faz no
    dashboard dele (essas linhas nunca chegaram a ser avaliadas)."""
    q = db.query(models.AuditoriaFefo)
    if data_inicio:
        q = q.filter(models.AuditoriaFefo.data >= data_inicio)
    if data_fim:
        q = q.filter(models.AuditoriaFefo.data <= data_fim)
    registros = q.all()

    auditaveis = [r for r in registros if r.status != STATUS_DESTINO_NAO_AUDITADO]
    quebras = [r for r in auditaveis if r.quebra_fefo]
    sem_correspondencia = [r for r in auditaveis if r.status and "não encontrado" in r.status.lower()]

    por_dia_contagem: dict[date, dict] = {}
    for r in auditaveis:
        bucket = por_dia_contagem.setdefault(r.data, {"total": 0, "quebras": 0})
        bucket["total"] += 1
        if r.quebra_fefo:
            bucket["quebras"] += 1
    por_dia = [
        {"data": str(d), "total": v["total"], "quebras": v["quebras"]}
        for d, v in sorted(por_dia_contagem.items())
    ]

    top_produtos = Counter((r.descricao_produto or r.sku or "—") for r in quebras).most_common(10)
    top_destinos = Counter(extrair_destino_movimento(r.movimento) or "—" for r in quebras).most_common(10)

    datas_cobertas = sorted({r.data for r in registros})
    fontes_cobertas = sorted({r.fonte for r in registros})

    return {
        "total_movimentos": len(registros),
        "total_auditaveis": len(auditaveis),
        "total_quebras": len(quebras),
        "taxa_quebra_pct": round(len(quebras) / len(auditaveis) * 100, 1) if auditaveis else None,
        "total_sem_correspondencia": len(sem_correspondencia),
        "periodo_coberto": [str(datas_cobertas[0]), str(datas_cobertas[-1])] if datas_cobertas else None,
        "dias_com_dado": len(datas_cobertas),
        "fontes_no_periodo": fontes_cobertas,
        "por_dia": por_dia,
        "top_produtos_com_quebra": [{"produto": p, "quebras": q} for p, q in top_produtos],
        "top_destinos_com_quebra": [{"destino": d, "quebras": q} for d, q in top_destinos],
    }


# ═════════════════════════════════════════════════════════════════════════
# Motor NATIVO de checagem de FEFO por lote movimentado (20/08/2026) - pedido
# do usuário depois de constatar que calcular_checagem_fefo/ChecagemFefo
# (topo deste arquivo) nunca comparou de fato o lote que saiu ("Continua
# trazendo dados errados", 89,85% de quebra): "Primeiro deixe registrado o
# que já foi mapeado [...] Depois, crie um motor investigativo, sem
# ferramenta genérica. Com base na tabela de movimentação, pegue tudo que
# saiu da fabrica e compare com o lote mais próximo da data de vencimento.
# Se lote não for igual, quebra de FEFO. Esse processo precisa atualizar
# todos os dias." Ver claude/checagens-fefo-heuristica-quebrada.md
# (histórico/decisão) no Atlas Operations.
#
# Reproduz a lógica de analisar_fefo()/ler_movimentacao() do
# Auditar_FEFO.ipynb do estagiário (André) sobre a MESMA planilha bruta que
# ele já usa ("Movimentação - Lt.xlsx", por lote - ver
# models.MovimentacaoLoteDiaria), em vez da Transferencia agregada por
# SKU/dia (que nunca carrega o lote na importação diária - ver docstring de
# models.Transferencia.lote). Grava o resultado em ChecagemFefoMovimento,
# tabela nova e independente de ChecagemFefo (mantida só como registro
# histórico, desativada) e de AuditoriaFefo (feature separada, pros
# relatórios já prontos que o André importa - ver seção "Auditoria FEFO
# importada" acima; não há fusão/precedência entre as duas).
#
# LIMITAÇÃO CONHECIDA (ainda não implementada, decisão consciente pra não
# atrasar a entrega - avisar o usuário): o processo do André tem uma
# planilha de exceções validadas manualmente (Excecoes_FEFO.xlsx, pares
# produto + "lote mais antigo disponível" que um humano já revisou e
# confirmou que está OK apesar da ordem). Esse motor NÃO importa essa
# planilha ainda - toda vez que existir um lote mais antigo do mesmo SKU na
# Fábrica que não foi o lote movimentado, isso é reportado como quebra, sem
# suprimir os casos já validados como exceção pelo André. Se isso gerar
# muito falso positivo conhecido, dá pra construir a importação da planilha
# de exceções depois.
# ═════════════════════════════════════════════════════════════════════════

STATUS_QUEBRA_NATIVA = "⚠️ QUEBRA DE FEFO"
STATUS_OK = "OK"
STATUS_OK_ALMOX_VAZIO = "OK (almox vazio para este produto)"
STATUS_INCONCLUSIVO = "Inconclusivo (lotes sem validade cadastrada no almox)"
STATUS_SEM_VALIDADE_LOTE_MOVIMENTADO = "Sem validade (lote não encontrado)"

# Cabeçalho exato da planilha "Movimentação - Lt.xlsx" (aba com os dados,
# mesma que o André lê em ler_movimentacao() no Auditar_FEFO.ipynb) - usado
# pra validar o arquivo antes de importar.
COLUNAS_MOVIMENTACAO_LOTE_DIARIA = (
    "id_produto", "descricao", "Data", "doc", "desc_movimento", "desc_almox", "qtd", "id_lote",
)


def _movimento_eh_origem_fabrica(movimento, almoxarifado_raw) -> bool:
    """Confirma que a Fábrica é a ORIGEM deste movimento (não o destino) -
    precisa confirmar a direção porque `desc_almox`/almoxarifado_raw é só
    "de qual almoxarifado esse registro foi exportado", e o mesmo movimento
    físico pode aparecer no arquivo uma vez por almoxarifado envolvido (ver
    identificar_almox_origem/fabrica_eh_origem do André - mesma ideia,
    versão mais simples aqui). Confirma em duas camadas: (1) o almoxarifado
    desta linha normaliza pra Fábrica, e (2) o texto ANTES do separador
    "->"/"-->" no movimento (a origem textual) menciona fábrica - se o texto
    antes da seta falar de outro lugar, a Fábrica é o DESTINO desse
    movimento, não a origem, e fica fora do escopo deste motor."""
    if not movimento:
        return False
    if normalizar_almoxarifado(almoxarifado_raw or "") != ALMOXARIFADO_FABRICA:
        return False
    partes = re.split(r"-+>", str(movimento))
    if len(partes) < 2:
        return False
    origem_texto = partes[0].strip().lower()
    return any(p in origem_texto for p in ("fabrica", "fábrica", "frabrica", "frabica"))


def _linha_movimentacao_lote_para_campos(linha: dict, arquivo_origem: str) -> dict | None:
    data_val = _data_valor(linha.get("Data"))
    if data_val is None:
        return None
    return {
        "data": data_val,
        "sku": parse_sku(linha.get("id_produto")),
        "descricao_produto": limpar_texto(linha.get("descricao")),
        "documento": limpar_texto(linha.get("doc")),
        "movimento": limpar_texto(linha.get("desc_movimento")),
        "almoxarifado_raw": limpar_texto(linha.get("desc_almox")),
        "quantidade": parse_decimal(linha.get("qtd")),
        "lote_movimentado": limpar_texto(linha.get("id_lote")),
        "arquivo_origem": arquivo_origem,
    }


def importar_movimentacao_lote_diaria(db: Session, linhas: list[dict], arquivo_origem: str, usuario: str) -> dict:
    """Importa a planilha bruta de movimentação por lote (um arquivo pode
    trazer vários dias de uma vez, é assim que o sistema de origem exporta).
    Reimportar substitui só os dias presentes no arquivo novo (escopo por
    data) - remove primeiro as ChecagemFefoMovimento que dependem desses
    dias (FK), depois a movimentação bruta, e recalcula na sequência."""
    campos_validos = [c for c in (_linha_movimentacao_lote_para_campos(l, arquivo_origem) for l in linhas) if c is not None]
    ignoradas = len(linhas) - len(campos_validos)

    datas = sorted({c["data"] for c in campos_validos})
    linhas_substituidas = 0
    for d in datas:
        ids_do_dia = [id_ for (id_,) in db.query(models.MovimentacaoLoteDiaria.id).filter_by(data=d).all()]
        if ids_do_dia:
            db.query(models.ChecagemFefoMovimento).filter(
                models.ChecagemFefoMovimento.movimentacao_lote_diaria_id.in_(ids_do_dia)
            ).delete(synchronize_session=False)
        linhas_substituidas += db.query(models.MovimentacaoLoteDiaria).filter_by(data=d).delete()

    for campos in campos_validos:
        db.add(models.MovimentacaoLoteDiaria(**campos, importado_por=usuario))
    db.flush()

    resultado_recalculo = recalcular_quebra_fefo_nativa(db, datas=datas)

    return {
        "dias_importados": [str(d) for d in datas],
        "linhas_importadas": len(campos_validos),
        "linhas_ignoradas_sem_data": ignoradas,
        "linhas_substituidas": linhas_substituidas,
        **resultado_recalculo,
    }


def _avaliar_quebra_fefo(
    mov: "models.MovimentacaoLoteDiaria",
    validade_por_lote: dict,
    lotes_fabrica_por_sku: dict,
    skus_fabrica_com_lote_sem_validade: set,
) -> dict:
    """Avalia UM movimento de saída da Fábrica contra os lotes do mesmo SKU
    que continuam lá - "pegue tudo que saiu da fábrica e compare com o lote
    mais próximo da data de vencimento. Se lote não for igual, quebra de
    FEFO" (instrução literal do usuário). Espelha analisar_fefo() do André:
    a validade do lote que saiu é procurada GLOBALMENTE (qualquer
    almoxarifado - é o mesmo lote físico em qualquer lugar do sistema);
    os candidatos "deveria ter saído primeiro" são só os lotes do mesmo SKU
    que estão HOJE na Fábrica, com validade conhecida e quantidade > 0."""
    base = {
        "data": mov.data,
        "sku": mov.sku,
        "descricao_produto": mov.descricao_produto,
        "movimento": mov.movimento,
        "almoxarifado_destino": extrair_destino_movimento(mov.movimento),
        "lote_movimentado": mov.lote_movimentado,
        "qtd_lote_movimentado": mov.quantidade,
    }

    validade_movido = validade_por_lote.get(mov.lote_movimentado) if mov.lote_movimentado else None
    base["validade_lote_movimentado"] = validade_movido

    sem_resultado = {
        "lote_mais_antigo_disponivel": None,
        "qtd_lote_mais_antigo_disponivel": None,
        "validade_mais_antiga_disponivel": None,
    }

    if validade_movido is None:
        return {**base, **sem_resultado, "quebra_fefo": False, "status": STATUS_SEM_VALIDADE_LOTE_MOVIMENTADO}

    candidatos = [l for l in lotes_fabrica_por_sku.get(mov.sku, []) if l.lote != mov.lote_movimentado]
    if not candidatos:
        status = STATUS_INCONCLUSIVO if mov.sku in skus_fabrica_com_lote_sem_validade else STATUS_OK_ALMOX_VAZIO
        return {**base, **sem_resultado, "quebra_fefo": False, "status": status}

    mais_antigos = [l for l in candidatos if l.data_validade < validade_movido]
    if not mais_antigos:
        return {**base, **sem_resultado, "quebra_fefo": False, "status": STATUS_OK}

    lote_antigo = min(mais_antigos, key=lambda l: l.data_validade)
    return {
        **base,
        "quebra_fefo": True,
        "status": STATUS_QUEBRA_NATIVA,
        "lote_mais_antigo_disponivel": lote_antigo.lote,
        "qtd_lote_mais_antigo_disponivel": lote_antigo.quantidade,
        "validade_mais_antiga_disponivel": lote_antigo.data_validade,
    }


def recalcular_quebra_fefo_nativa(db: Session, datas: list[date] | None = None) -> dict:
    """Recalcula ChecagemFefoMovimento - todo o histórico de
    MovimentacaoLoteDiaria (chamado sem argumento, ex: pelo agendador diário
    em scheduler.py, pra refletir o LoteShelfLife mais atual mesmo em dias
    sem reimportação nova) ou só os dias informados em `datas` (chamado
    depois de importar um arquivo novo). Idempotente: apaga e recria as
    ChecagemFefoMovimento dos dias recalculados antes de gravar de novo."""
    q = db.query(models.MovimentacaoLoteDiaria)
    if datas:
        q = q.filter(models.MovimentacaoLoteDiaria.data.in_(datas))
    movimentos = q.all()

    validade_por_lote: dict[str, date] = {}
    lotes_fabrica_por_sku: dict[str, list] = defaultdict(list)
    skus_fabrica_com_lote_sem_validade: set[str] = set()

    for l in db.query(models.LoteShelfLife).filter(models.LoteShelfLife.ativo.is_(True)).all():
        if l.lote and l.data_validade and l.lote not in validade_por_lote:
            validade_por_lote[l.lote] = l.data_validade
        if l.almoxarifado == ALMOXARIFADO_FABRICA and l.sku and (l.quantidade or 0) > 0:
            if l.data_validade:
                lotes_fabrica_por_sku[l.sku].append(l)
            else:
                skus_fabrica_com_lote_sem_validade.add(l.sku)

    datas_afetadas = sorted({m.data for m in movimentos})
    if movimentos:
        ids_afetados = [m.id for m in movimentos]
        db.query(models.ChecagemFefoMovimento).filter(
            models.ChecagemFefoMovimento.movimentacao_lote_diaria_id.in_(ids_afetados)
        ).delete(synchronize_session=False)

    total_avaliados = 0
    total_quebras = 0
    for mov in movimentos:
        if not _movimento_eh_origem_fabrica(mov.movimento, mov.almoxarifado_raw):
            continue  # Fábrica é destino (ou almoxarifado não identificado) - fora do escopo deste motor
        total_avaliados += 1
        campos = _avaliar_quebra_fefo(mov, validade_por_lote, lotes_fabrica_por_sku, skus_fabrica_com_lote_sem_validade)
        if campos["quebra_fefo"]:
            total_quebras += 1
        db.add(models.ChecagemFefoMovimento(movimentacao_lote_diaria_id=mov.id, **campos))

    return {
        "movimentos_avaliados": total_avaliados,
        "quebras_detectadas": total_quebras,
        "dias_recalculados": [str(d) for d in datas_afetadas],
    }


def calcular_resumo_checagem_fefo_movimento(db: Session) -> dict:
    """Agrega ChecagemFefoMovimento pro card do dashboard/MBR - MESMOS
    nomes de campo do resumo antigo (baseado em ChecagemFefo), de propósito,
    pra não precisar tocar no frontend que já consome esse contrato (só o
    texto do rótulo mudou - ver claude/checagens-fefo-heuristica-quebrada.md).
    O que muda de fato é a fonte e o critério por trás de cada número."""
    checagens = db.query(models.ChecagemFefoMovimento).all()
    total = len(checagens)
    quebras = [c for c in checagens if c.quebra_fefo]
    sem_dado = [c for c in checagens if c.status in (STATUS_SEM_VALIDADE_LOTE_MOVIMENTADO, STATUS_INCONCLUSIVO)]

    top_skus = Counter(c.sku for c in quebras if c.sku).most_common(10)
    top_destinos = Counter(c.almoxarifado_destino for c in quebras if c.almoxarifado_destino).most_common(10)

    avaliaveis = total - len(sem_dado)

    return {
        "total_transferencias_avaliadas": total,
        "total_quebras_fefo": len(quebras),
        "total_dentro_do_criterio": total - len(quebras) - len(sem_dado),
        "total_sem_dado_suficiente": len(sem_dado),
        "taxa_quebra_pct": round(len(quebras) / avaliaveis * 100, 2) if avaliaveis else None,
        "top_skus_com_quebra": [{"sku": sku, "quebras": qtd} for sku, qtd in top_skus],
        "top_destinos_com_quebra": [{"almoxarifado_destino": destino, "quebras": qtd} for destino, qtd in top_destinos],
    }
