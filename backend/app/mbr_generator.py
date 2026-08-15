"""
Geração automática do MBR (Monthly Business Review) em PPTX (20/08/2026,
reescrita completa) - gera o relatório com DADOS REAIS lidos diretamente das
mesmas funções de negócio que alimentam as telas do Atlas (chamadas em
processo, como funções Python normais - não via HTTP), sem abrir navegador
nenhum. Substitui a versão anterior (prints de tela via Playwright/Chromium)
por decisão explícita do usuário, que pediu um relatório no estilo do MBR do
gestor dele (resumo executivo, leitura por frente, scorecard, decisões) com a
identidade visual da Mágio Chocolates, contando a história de cada módulo com
números e não com telas printadas.

Por que chamar as funções dos routers direto (ex.: fechamento_router.
dashboard_kpis(...)) em vez de bater no HTTP: cada uma delas tem
"usuario: models.Usuario = Depends(obter_usuario_atual)" e "db: Session =
Depends(get_db)" só como VALOR PADRÃO - "Depends(...)" é apenas um marcador
que o FastAPI interpreta na hora de uma requisição de verdade. Chamando a
função Python diretamente e passando um "usuario"/"db" reais no lugar, a
injeção de dependência do FastAPI nunca entra em ação - funciona como
qualquer chamada de função comum, sem round-trip de rede e sem os problemas
de Chromium/memória da versão anterior (ver histórico em ATUALIZANDO.md).

IMPORTANTE - limitações conhecidas e assumidas nesta versão:
  - Ícones: o sistema visual da Mágio pede ícones outline (Lucide/Heroicons),
    mas renderizá-los aqui exigiria ferramental Node.js (react-icons + sharp)
    que não faz parte do backend Python do Atlas. Substituído por hierarquia
    tipográfica + badges de cor (mesma linguagem de status, sem o ícone
    literal).
  - Fonte: usa Arial em todo o documento (título e corpo) de propósito, não
    "Poppins"/"TT Chocolates" como pede a identidade visual - Arial é uma das
    poucas fontes com garantia de existir em qualquer instalação do
    PowerPoint do usuário E de ter a MESMA largura de texto tanto aqui
    (pré-visualização via LibreOffice) quanto lá (não quebra layout depois de
    entregue). Quem tiver "Poppins"/"TT Chocolates" licenciada pode trocar a
    fonte de todo o arquivo em segundos pelo PowerPoint (Página Inicial >
    Substituir > Substituir Fontes).
  - Limiares de status ("Em avanço"/"Atenção"/"Crítico"): ver _LIMIARES logo
    abaixo - são um ponto de partida razoável, não uma meta oficial definida
    pela operação. Fácil de ajustar depois se não bater com o apetite de
    risco real do time.
"""
from datetime import datetime
from io import BytesIO

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from sqlalchemy.orm import Session

from . import models
from . import shelf_life as shelf_life_mod
from .routers import fechamento_router, baixas_operacionais_router, movimentados_router, fefo_router

# ---------------------------------------------------------------------------
# Identidade visual Mágio Chocolates
# ---------------------------------------------------------------------------
VERDE_AMAZONIA = RGBColor(0x4E, 0x7F, 0x84)      # cor primária
AZUL_INSTITUCIONAL = RGBColor(0x34, 0x43, 0x6C)  # cor secundária
AZUL_CLARO = RGBColor(0xB1, 0xBF, 0xE2)          # cor de apoio
OFF_WHITE = RGBColor(0xE4, 0xE0, 0xD5)           # cor neutra
BRANCO = RGBColor(0xFF, 0xFF, 0xFF)
CINZA_TEXTO = RGBColor(0x4A, 0x4A, 0x4A)
CINZA_CLARO = RGBColor(0xE2, 0xE4, 0xE8)
CINZA_LINHA_PAR = RGBColor(0xF4, 0xF5, 0xF7)

COR_SUCESSO = RGBColor(0x2E, 0x7D, 0x32)
COR_ATENCAO = RGBColor(0xF9, 0xA8, 0x25)
COR_ERRO = RGBColor(0xC6, 0x28, 0x28)
COR_INFO = RGBColor(0x15, 0x65, 0xC0)
COR_SEM_DADO = RGBColor(0x9E, 0x9E, 0x9E)

# Ver nota no docstring do módulo sobre a troca TT Chocolates/Poppins -> Arial.
FONTE_TITULO = "Arial"
FONTE_TEXTO = "Arial"

LARGURA_IN = 13.333
ALTURA_IN = 7.5
MARGEM_IN = 0.5

# (bom, atenção) - acima de "bom" é "Em avanço", entre os dois é "Atenção",
# abaixo do segundo é "Crítico". Documentado no docstring do módulo como
# ponto de partida ajustável, não meta oficial da operação.
_LIMIARES = {
    "acuracia": (95.0, 85.0),        # maior é melhor
    "fefo_quebra_pct": (5.0, 20.0),  # menor é melhor
}


def _status_maior_melhor(valor, bom, atencao):
    if valor is None:
        return ("Sem dado", COR_SEM_DADO)
    if valor >= bom:
        return ("Em avanço", COR_SUCESSO)
    if valor >= atencao:
        return ("Atenção", COR_ATENCAO)
    return ("Crítico", COR_ERRO)


def _status_menor_melhor(valor, bom, atencao):
    if valor is None:
        return ("Sem dado", COR_SEM_DADO)
    if valor <= bom:
        return ("Em avanço", COR_SUCESSO)
    if valor <= atencao:
        return ("Atenção", COR_ATENCAO)
    return ("Crítico", COR_ERRO)


# ---------------------------------------------------------------------------
# Formatação (padrão numérico brasileiro: milhar "." decimal ",")
# ---------------------------------------------------------------------------
def _fmt_num(valor, casas=0):
    if valor is None:
        return "—"
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_pct(valor, casas=1):
    if valor is None:
        return "—"
    return f"{_fmt_num(valor, casas)}%"


def _fmt_moeda(valor, casas=0):
    if valor is None:
        return "—"
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {_fmt_num(abs(valor), casas)}"


_NOMES_MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _nome_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{_NOMES_MESES[int(m) - 1]} de {ano}"


# ---------------------------------------------------------------------------
# Blocos visuais reutilizáveis
# ---------------------------------------------------------------------------
def _nova_apresentacao() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(LARGURA_IN)
    prs.slide_height = Inches(ALTURA_IN)
    return prs


def _slide_em_branco(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _fundo(slide, cor: RGBColor):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = cor


def _retangulo(slide, x, y, w, h, cor_fill=None, cor_borda=None, arredondado=True, raio=0.10):
    tipo = MSO_SHAPE.ROUNDED_RECTANGLE if arredondado else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(tipo, Inches(x), Inches(y), Inches(w), Inches(h))
    if arredondado:
        try:
            shape.adjustments[0] = raio
        except (IndexError, ValueError):
            pass
    if cor_fill is not None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = cor_fill
    else:
        shape.fill.background()
    if cor_borda is not None:
        shape.line.color.rgb = cor_borda
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _texto(slide, x, y, w, h, texto, tamanho=16, negrito=False, cor=CINZA_TEXTO,
           alinhamento=PP_ALIGN.LEFT, fonte=None, espacamento=1.0, ancora_meio=False, italico=False):
    caixa = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = caixa.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    if ancora_meio:
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    linhas = texto if isinstance(texto, (list, tuple)) else [texto]
    for i, linha in enumerate(linhas):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = linha
        p.font.size = Pt(tamanho)
        p.font.bold = negrito
        p.font.italic = italico
        p.font.color.rgb = cor
        p.font.name = fonte or FONTE_TEXTO
        p.alignment = alinhamento
        p.line_spacing = espacamento
    return caixa


def _cabecalho(slide, titulo, mes_label, pagina, subtitulo=None):
    _texto(slide, MARGEM_IN, 0.32, 9.5, 0.22, "RELATÓRIO EXECUTIVO · MÁGIO CHOCOLATES",
           tamanho=10, negrito=True, cor=VERDE_AMAZONIA)
    _texto(slide, MARGEM_IN, 0.58, 9.7, 0.55, titulo, tamanho=27, negrito=True,
           cor=AZUL_INSTITUCIONAL, fonte=FONTE_TITULO)
    if subtitulo:
        _texto(slide, MARGEM_IN, 1.10, 9.7, 0.35, subtitulo, tamanho=13, cor=CINZA_TEXTO)
    _texto(slide, LARGURA_IN - 2.9, 0.32, 2.4, 0.3, mes_label.upper(), tamanho=11,
           negrito=True, cor=VERDE_AMAZONIA, alinhamento=PP_ALIGN.RIGHT)
    _texto(slide, LARGURA_IN - 2.9, ALTURA_IN - 0.42, 2.4, 0.3, f"{pagina:02d}", tamanho=10,
           cor=CINZA_TEXTO, alinhamento=PP_ALIGN.RIGHT)


def _cartao_kpi(slide, x, y, w, h, valor_texto, rotulo, cor_valor=AZUL_INSTITUCIONAL, contexto=None, cor_contexto=None):
    _retangulo(slide, x, y, w, h, cor_fill=BRANCO, cor_borda=CINZA_CLARO, raio=0.14)
    pad = 0.18
    _texto(slide, x + pad, y + 0.16, w - 2 * pad, 0.55, valor_texto, tamanho=28,
           negrito=True, cor=cor_valor, fonte=FONTE_TITULO)
    y_rotulo = y + h - (0.58 if contexto else 0.34)
    _texto(slide, x + pad, y_rotulo, w - 2 * pad, 0.26, rotulo.upper(), tamanho=10.5, negrito=True, cor=CINZA_TEXTO)
    if contexto:
        _texto(slide, x + pad, y + h - 0.30, w - 2 * pad, 0.26, contexto, tamanho=10, cor=cor_contexto or CINZA_TEXTO)


def _linha_kpis(slide, y, kpis, altura=1.35):
    n = len(kpis)
    largura_total = LARGURA_IN - 2 * MARGEM_IN
    gap = 0.22
    largura_card = (largura_total - gap * (n - 1)) / n
    x = MARGEM_IN
    for k in kpis:
        _cartao_kpi(slide, x, y, largura_card, altura, k["valor"], k["rotulo"],
                    k.get("cor", AZUL_INSTITUCIONAL), k.get("contexto"), k.get("cor_contexto"))
        x += largura_card + gap


def _caber_no_espaco(texto, largura_in, altura_in, tamanho_pt, espacamento=1.12):
    """Corta o texto (com reticências ao final) se ele não couber na área
    reservada, dado o tamanho de fonte - rede de segurança genérica contra
    estourar a caixa quando o texto de origem varia de tamanho de um mês
    pro outro (ex.: resumo_narrado muda conforme quantas categorias/baixas
    existem no recorte, e as colunas de Avanços/Atenções/Decisões mudam de
    tamanho conforme quantos pontos existem no mês). Estimativa por
    largura média de caractere, não medição real de texto (python-pptx não
    faz layout de fonte) - por isso usa uma margem de segurança (0.82) em
    vez do limite teórico exato."""
    if not texto:
        return ""
    largura_media_char = (tamanho_pt / 72.0) * 0.52
    chars_por_linha = max(10, int(largura_in / largura_media_char))
    altura_linha = (tamanho_pt / 72.0) * espacamento * 1.22
    linhas_disponiveis = max(1, int(altura_in / altura_linha))
    max_chars = int(chars_por_linha * linhas_disponiveis * 0.82)
    if len(texto) <= max_chars:
        return texto
    cortado = texto[:max_chars].rsplit(" ", 1)[0].rstrip(",.;:—-")
    return cortado + "…"


def _caixa_leitura(slide, x, y, w, h, rotulo, texto, cor_fundo=OFF_WHITE, cor_rotulo=VERDE_AMAZONIA, tamanho_texto=13):
    _retangulo(slide, x, y, w, h, cor_fill=cor_fundo, raio=0.10)
    pad = 0.20
    altura_rotulo = 0.26
    _texto(slide, x + pad, y + pad * 0.6, w - 2 * pad, altura_rotulo, rotulo.upper(), tamanho=11, negrito=True, cor=cor_rotulo)
    y_texto = y + pad * 0.6 + altura_rotulo
    largura_texto = w - 2 * pad
    altura_texto = (y + h) - y_texto - pad * 0.5
    texto = _caber_no_espaco(texto, largura_texto, altura_texto, tamanho_texto)
    _texto(slide, x + pad, y_texto, largura_texto, altura_texto, texto,
           tamanho=tamanho_texto, cor=CINZA_TEXTO, espacamento=1.12)


def _linhas_estimadas(texto, largura_in, tamanho_pt, espacamento=1.1):
    """Estima quantas linhas um texto vai ocupar numa largura/fonte dadas -
    mesma lógica de _caber_no_espaco (proxy por largura média de caractere,
    já que python-pptx não faz layout de texto de verdade), usada aqui pra
    espaçar itens de lista sem empilhar um em cima do outro quando o texto
    quebra em mais linhas do que caberia com uma estimativa fixa."""
    largura_media_char = (tamanho_pt / 72.0) * 0.52
    chars_por_linha = max(10, int(largura_in / largura_media_char))
    return max(1, -(-len(texto) // chars_por_linha))  # teto da divisão


def _lista_com_marcadores(slide, x, y, w, h, itens, cor_marcador=VERDE_AMAZONIA, tamanho=12.5, espaco_linha=0.24):
    if not itens:
        itens = ["Sem observações relevantes neste recorte."]
    yy = y
    for item in itens:
        _texto(slide, x, yy, 0.18, 0.24, "•", tamanho=tamanho, negrito=True, cor=cor_marcador)
        _texto(slide, x + 0.22, yy, w - 0.22, 0.6, item, tamanho=tamanho, cor=CINZA_TEXTO, espacamento=1.1)
        linhas_estimadas = _linhas_estimadas(item, w - 0.22, tamanho)
        yy += espaco_linha * linhas_estimadas + 0.10
    return yy


def _badge_status(slide, x, y, w, h, texto, cor):
    shape = _retangulo(slide, x, y, w, h, cor_fill=cor, raio=0.5)
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = texto
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.name = FONTE_TEXTO
    p.font.color.rgb = BRANCO
    p.alignment = PP_ALIGN.CENTER
    return shape


def _grafico_categoria(slide, x, y, w, h, categorias, nome_serie, valores, tipo=XL_CHART_TYPE.COLUMN_CLUSTERED,
                        cor_serie=VERDE_AMAZONIA, cores_pontos=None, formato_numero='0"%"'):
    """Gráfico nativo de UM eixo/uma série só (convenção já usada nos
    dashboards do próprio Atlas: nunca eixo duplo) - cada categoria pode ter
    cor própria via cores_pontos (ex.: status por mês/farol)."""
    chart_data = CategoryChartData()
    chart_data.categories = categorias
    chart_data.add_series(nome_serie, valores)
    gframe = slide.shapes.add_chart(tipo, Inches(x), Inches(y), Inches(w), Inches(h), chart_data)
    chart = gframe.chart
    chart.has_legend = False
    chart.has_title = False

    plot = chart.plots[0]
    try:
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(10)
        plot.data_labels.font.color.rgb = CINZA_TEXTO
        plot.data_labels.number_format = formato_numero
        plot.data_labels.number_format_is_linked = False
    except Exception:
        pass

    serie = plot.series[0]
    serie.format.fill.solid()
    serie.format.fill.fore_color.rgb = cor_serie
    serie.format.line.fill.background()

    if cores_pontos:
        pontos = serie.points
        for i, cor in enumerate(cores_pontos):
            if cor is None or i >= len(valores):
                continue
            pontos[i].format.fill.solid()
            pontos[i].format.fill.fore_color.rgb = cor

    try:
        cat_ax = chart.category_axis
        cat_ax.tick_labels.font.size = Pt(10)
        cat_ax.tick_labels.font.color.rgb = CINZA_TEXTO
        cat_ax.format.line.color.rgb = CINZA_CLARO
        val_ax = chart.value_axis
        val_ax.tick_labels.font.size = Pt(10)
        val_ax.has_major_gridlines = True
        val_ax.major_gridlines.format.line.color.rgb = CINZA_CLARO
        val_ax.format.line.fill.background()
        val_ax.visible = True
    except Exception:
        pass
    return chart


def _tabela(slide, x, y, w, h, cabecalhos, linhas, larguras_relativas=None,
            cor_cabecalho=AZUL_INSTITUCIONAL, tamanho_fonte=12):
    n_linhas = len(linhas) + 1
    n_col = len(cabecalhos)
    shape = slide.shapes.add_table(n_linhas, n_col, Inches(x), Inches(y), Inches(w), Inches(h))
    tabela = shape.table

    if larguras_relativas:
        total = sum(larguras_relativas)
        for i, fracao in enumerate(larguras_relativas):
            tabela.columns[i].width = Inches(w * fracao / total)

    for j, cabecalho in enumerate(cabecalhos):
        cel = tabela.cell(0, j)
        cel.fill.solid()
        cel.fill.fore_color.rgb = cor_cabecalho
        cel.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cel.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = cabecalho
        p.font.size = Pt(tamanho_fonte)
        p.font.bold = True
        p.font.name = FONTE_TEXTO
        p.font.color.rgb = BRANCO

    for i, linha in enumerate(linhas, start=1):
        cor_fundo = BRANCO if i % 2 == 1 else CINZA_LINHA_PAR
        for j, valor in enumerate(linha):
            if isinstance(valor, tuple):
                texto_valor, cor_fonte, negrito = valor
            else:
                texto_valor, cor_fonte, negrito = valor, CINZA_TEXTO, False
            cel = tabela.cell(i, j)
            cel.fill.solid()
            cel.fill.fore_color.rgb = cor_fundo
            cel.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cel.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = "" if texto_valor is None else str(texto_valor)
            p.font.size = Pt(tamanho_fonte - 1)
            p.font.name = FONTE_TEXTO
            p.font.color.rgb = cor_fonte
            p.font.bold = negrito
    return tabela


# ---------------------------------------------------------------------------
# Coleta de dados (chama as funções de negócio do Atlas diretamente)
# ---------------------------------------------------------------------------
def _coletar_dados_mbr(db: Session, usuario: models.Usuario, mes: str) -> dict:
    ano_int, mes_int = (int(parte) for parte in mes.split("-"))

    return {
        "kpis_inventario": fechamento_router.dashboard_kpis(almoxarifado=None, mes=mes, usuario=usuario, db=db),
        "evolucao_inventario": fechamento_router.dashboard_evolucao_mensal(almoxarifado=None, usuario=usuario, db=db),
        "top_recorrentes": fechamento_router.dashboard_top_recorrentes(almoxarifado=None, limite=5, usuario=usuario, db=db),
        "comparativo_acuracia": fechamento_router.dashboard_comparativo_acuracia(almoxarifado=None, mes=mes, usuario=usuario, db=db),
        "evolucao_ponderada": fechamento_router.dashboard_evolucao_ponderada_mensal(almoxarifado=None, usuario=usuario, db=db),
        "resumo_passivos": baixas_operacionais_router.resumo_executivo(
            ano=ano_int, mes=mes_int, data_inicio=None, data_fim=None, almoxarifado=None, motivo=None, usuario=usuario, db=db
        ),
        "resumo_shelf_life": shelf_life_mod.calcular_resumo_shelf_life(db, incluir_itens=True, limite_itens=5),
        "resumo_transferencias": movimentados_router.dashboard_transferencias_resumo(usuario=usuario, db=db),
        "evolucao_transferencias": movimentados_router.dashboard_transferencias_evolucao_mensal(usuario=usuario, db=db),
        "resumo_fefo": fefo_router.dashboard_resumo(usuario=usuario, db=db),
    }


# ---------------------------------------------------------------------------
# Narrativa executiva automática (baseada nos números reais coletados acima)
# ---------------------------------------------------------------------------
def _analise_geral(d: dict):
    """Monta as 3 colunas do resumo executivo (Avanços / Atenções /
    Decisões) e a mensagem central, tudo derivado dos limiares reais - nada
    de texto fixo/genérico independente dos números do mês."""
    avancos, atencoes, decisoes = [], [], []

    kpis_inv = d["kpis_inventario"]
    comp = d["comparativo_acuracia"]
    passivos = d["resumo_passivos"]["passivos"]
    resultado_inv = d["resumo_passivos"]["resultado_inventario"]
    shelf = d["resumo_shelf_life"]
    fefo = d["resumo_fefo"]

    label_acuracia, _ = _status_maior_melhor(kpis_inv["acuracia_geral_pct"], *_LIMIARES["acuracia"])
    if kpis_inv["acuracia_geral_pct"] is not None:
        if label_acuracia == "Em avanço":
            avancos.append(f"Acurácia geral do inventário em {_fmt_pct(kpis_inv['acuracia_geral_pct'])}, dentro da faixa de controle (meta ≥ 95%).")
        else:
            atencoes.append(f"Acurácia geral do inventário em {_fmt_pct(kpis_inv['acuracia_geral_pct'])}, abaixo da meta de 95%.")

    gap = comp.get("gap_item_vs_iap_pp")
    if gap is not None and abs(gap) >= 3:
        atencoes.append(
            f"A leitura ponderada por valor (IAP) muda em {_fmt_pct(abs(gap))} a foto do item-a-item — "
            "sinal de que o risco financeiro está concentrado em poucos SKUs."
        )

    if passivos["valor"]:
        if passivos["valor"] > 0:
            atencoes.append(f"{_fmt_moeda(passivos['valor'])} em passivos aprovados mapeados no período ({_fmt_num(passivos['quantidade'])} baixas).")
        else:
            avancos.append("Nenhum passivo residual aprovado sem mapeamento no período.")
    else:
        avancos.append("Nenhum passivo residual aprovado sem mapeamento no período.")

    if resultado_inv["resultado_valor"] is not None:
        if resultado_inv["resultado_valor"] >= 0:
            avancos.append(f"Resultado de inventário acumulado positivo em {_fmt_moeda(resultado_inv['resultado_valor'])}.")
        else:
            atencoes.append(f"Resultado de inventário acumulado negativo em {_fmt_moeda(resultado_inv['resultado_valor'])}.")

    if shelf["valor_total"]:
        decisoes.append(f"Priorizar consumo/transferência dos {_fmt_moeda(shelf['valor_total'])} em lotes vencidos ou a vencer em até 90 dias ({_fmt_num(shelf['total_lotes_em_risco'])} lotes).")
    else:
        avancos.append("Sem valor relevante de estoque em risco de validade neste recorte.")

    if fefo.get("taxa_quebra_pct") is not None:
        label_fefo, _ = _status_menor_melhor(fefo["taxa_quebra_pct"], *_LIMIARES["fefo_quebra_pct"])
        if label_fefo == "Em avanço":
            avancos.append(f"Taxa de quebra de critério FEFO em {_fmt_pct(fefo['taxa_quebra_pct'])}, dentro do esperado.")
        else:
            decisoes.append(f"Reforçar o critério FEFO nas transferências — taxa de quebra em {_fmt_pct(fefo['taxa_quebra_pct'])}.")

    if not decisoes:
        decisoes.append("Manter a cadência atual de fechamento e monitoramento — sem decisão crítica pendente neste recorte.")

    if len(atencoes) == 0:
        mensagem = (
            "A operação está sob controle em todas as frentes mapeadas neste mês — inventário auditado, passivos "
            "mapeados, sem decisão crítica pendente. O ganho aqui é de visibilidade: o mesmo controle que antes "
            "vivia em planilhas isoladas agora é automático, a cada fechamento."
        )
    else:
        mensagem = (
            f"O mapeamento da operação mostra controle real do estoque, não percepção: {len(avancos)} frente(s) em "
            f"avanço e {len(atencoes)} de atenção neste mês, com as ações já priorizadas ao lado — inventário, "
            "passivos, validade e movimentação lidos juntos, pra agir antes que a atenção vire perda."
        )

    return {"avancos": avancos, "atencoes": atencoes, "decisoes": decisoes, "mensagem": mensagem}


def _linha_scorecard(frente, status_label, status_cor, leitura, proximo_passo):
    return {"frente": frente, "status_label": status_label, "status_cor": status_cor, "leitura": leitura, "proximo_passo": proximo_passo}


def _montar_scorecard(d: dict):
    kpis_inv = d["kpis_inventario"]
    passivos = d["resumo_passivos"]["passivos"]
    shelf = d["resumo_shelf_life"]
    fefo = d["resumo_fefo"]

    label_acuracia, cor_acuracia = _status_maior_melhor(kpis_inv["acuracia_geral_pct"], *_LIMIARES["acuracia"])
    linha_inventario = _linha_scorecard(
        "Painel de Inventário", label_acuracia, cor_acuracia,
        f"Acurácia geral {_fmt_pct(kpis_inv['acuracia_geral_pct'])} sobre {_fmt_num(kpis_inv['total_itens'])} itens avaliados.",
        "Investigar SKUs recorrentes." if kpis_inv["total_divergentes"] else "Manter cadência de fechamento atual.",
    )

    label_passivos = "Atenção" if passivos["valor"] else "Em avanço"
    cor_passivos = COR_ATENCAO if passivos["valor"] else COR_SUCESSO
    linha_passivos = _linha_scorecard(
        "Mapeamento de Passivos", label_passivos, cor_passivos,
        f"{_fmt_moeda(passivos['valor'])} em passivos aprovados mapeados no período.",
        "Classificar pendências como ajuste de processo ou perda real." if passivos["valor"] else "Sem pendência — manter monitoramento.",
    )

    label_shelf = "Atenção" if shelf["total_lotes_em_risco"] else "Em avanço"
    cor_shelf = COR_ATENCAO if shelf["total_lotes_em_risco"] else COR_SUCESSO
    linha_shelf = _linha_scorecard(
        "Shelf Life", label_shelf, cor_shelf,
        f"{_fmt_num(shelf['total_lotes_em_risco'])} lote(s) em risco de validade, {_fmt_moeda(shelf['valor_total'])} em valor exposto.",
        "Priorizar consumo/transferência dos lotes vencidos ou a vencer em 30 dias." if shelf["total_lotes_em_risco"] else "Sem lote em risco — manter monitoramento.",
    )

    label_fefo, cor_fefo = _status_menor_melhor(fefo.get("taxa_quebra_pct"), *_LIMIARES["fefo_quebra_pct"])
    linha_fefo = _linha_scorecard(
        "Movimentados & FEFO", label_fefo, cor_fefo,
        f"Taxa de quebra de critério FEFO em {_fmt_pct(fefo.get('taxa_quebra_pct'))} sobre {_fmt_num(fefo.get('total_transferencias_avaliadas'))} transferências avaliadas.",
        "Reforçar critério FEFO nas transferências de maior volume." if label_fefo != "Em avanço" else "Manter critério atual — dentro da meta.",
    )

    comp = d["comparativo_acuracia"]
    gap = comp.get("gap_item_vs_iap_pp")
    label_gap = "Atenção" if (gap is not None and abs(gap) >= 3) else "Em avanço"
    cor_gap = COR_ATENCAO if label_gap == "Atenção" else COR_SUCESSO
    linha_ponderada = _linha_scorecard(
        "Acurácia Ponderada", label_gap, cor_gap,
        f"IAP (ponderado por valor) em {_fmt_pct(comp.get('iap_pct'))}, {_fmt_pct(abs(gap)) if gap is not None else '—'} de distância do item-a-item.",
        "Priorizar SKUs de maior impacto financeiro na correção." if label_gap == "Atenção" else "Distorção sob controle — manter leitura mensal.",
    )

    return [linha_inventario, linha_passivos, linha_ponderada, linha_shelf, linha_fefo]


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------
def _slide_capa(prs: Presentation, mes_label: str):
    slide = _slide_em_branco(prs)
    _fundo(slide, AZUL_INSTITUCIONAL)
    _texto(slide, 1.0, 2.55, 11.3, 0.3, "MÁGIO CHOCOLATES", tamanho=14, negrito=True, cor=AZUL_CLARO)
    _texto(slide, 1.0, 2.95, 11.3, 1.1, "Relatório Executivo de Estoque", tamanho=40, negrito=True,
           cor=BRANCO, fonte=FONTE_TITULO)
    _texto(slide, 1.0, 3.80, 11.3, 0.5, "Inteligência e controle operacional · Atlas", tamanho=18, cor=AZUL_CLARO)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    _texto(slide, 1.0, 6.55, 11.3, 0.4, f"{mes_label}  ·  Gerado automaticamente pelo Atlas em {agora}",
           tamanho=13, cor=OFF_WHITE)
    return slide


def _slide_resumo_executivo(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Resumo Executivo", mes_label, pagina, "Controle operacional do estoque em números — o que mudou, o que exige decisão")

    kpis_inv = d["kpis_inventario"]
    passivos = d["resumo_passivos"]["passivos"]
    shelf = d["resumo_shelf_life"]
    fefo = d["resumo_fefo"]
    label_acuracia, cor_acuracia = _status_maior_melhor(kpis_inv["acuracia_geral_pct"], *_LIMIARES["acuracia"])
    label_fefo, cor_fefo = _status_menor_melhor(fefo.get("taxa_quebra_pct"), *_LIMIARES["fefo_quebra_pct"])

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_pct(kpis_inv["acuracia_geral_pct"]), "rotulo": "Acurácia do Inventário", "cor": AZUL_INSTITUCIONAL, "contexto": label_acuracia, "cor_contexto": cor_acuracia},
        {"valor": _fmt_moeda(passivos["valor"]), "rotulo": "Passivos Mapeados", "cor": AZUL_INSTITUCIONAL, "contexto": f"{_fmt_num(passivos['quantidade'])} baixas aprovadas"},
        {"valor": _fmt_moeda(shelf["valor_total"]), "rotulo": "Valor em Risco de Validade", "cor": AZUL_INSTITUCIONAL, "contexto": f"{_fmt_num(shelf['total_lotes_em_risco'])} lotes"},
        {"valor": _fmt_pct(fefo.get("taxa_quebra_pct")), "rotulo": "Quebra de Critério FEFO", "cor": AZUL_INSTITUCIONAL, "contexto": label_fefo, "cor_contexto": cor_fefo},
    ], altura=1.30)

    analise = _analise_geral(d)
    y_colunas = 3.10
    largura_col = (LARGURA_IN - 2 * MARGEM_IN - 2 * 0.25) / 3
    largura_texto_col = largura_col - 0.22

    # Quantos itens cada coluna acaba tendo varia todo mês (mais ou menos
    # avanços/atenções/decisões conforme os números do recorte) - por isso o
    # tamanho de fonte da lista e a posição da caixa "Mensagem Central" são
    # calculados a partir da altura que o conteúdo realmente vai ocupar
    # (_linhas_estimadas), não de um layout fixo que só foi testado com um
    # mês de exemplo. Tenta fontes menores até caber no espaço reservado
    # pras 3 colunas antes da caixa de mensagem; no pior caso (muitos itens
    # longos), fica no menor tamanho e aceita ficar mais apertado.
    y_zona_segura_fim = ALTURA_IN - 0.55  # reserva o rodapé (número de página)
    altura_reservada_mensagem = 1.05
    gap_antes_mensagem = 0.15
    orcamento_colunas = y_zona_segura_fim - y_colunas - 0.36 - gap_antes_mensagem - altura_reservada_mensagem

    tamanho_lista = 11.5
    espaco_linha = 0.24
    for tentativa in (11.5, 10.5, 9.5):
        espaco_tentativa = 0.24 * (tentativa / 11.5)
        maior_altura = max(
            sum(espaco_tentativa * _linhas_estimadas(item, largura_texto_col, tentativa) + 0.10 for item in analise[chave])
            for chave in ("avancos", "atencoes", "decisoes")
        )
        tamanho_lista, espaco_linha = tentativa, espaco_tentativa
        if maior_altura <= orcamento_colunas:
            break

    altura_lista_usada = max(
        sum(espaco_linha * _linhas_estimadas(item, largura_texto_col, tamanho_lista) + 0.10 for item in analise[chave])
        for chave in ("avancos", "atencoes", "decisoes")
    )
    altura_lista_usada = min(altura_lista_usada, orcamento_colunas)

    _texto(slide, MARGEM_IN, y_colunas, largura_col, 0.28, "AVANÇOS", tamanho=13, negrito=True, cor=COR_SUCESSO)
    _lista_com_marcadores(slide, MARGEM_IN, y_colunas + 0.36, largura_col, altura_lista_usada, analise["avancos"],
                           cor_marcador=COR_SUCESSO, tamanho=tamanho_lista, espaco_linha=espaco_linha)

    x2 = MARGEM_IN + largura_col + 0.25
    _texto(slide, x2, y_colunas, largura_col, 0.28, "ATENÇÕES", tamanho=13, negrito=True, cor=COR_ATENCAO)
    _lista_com_marcadores(slide, x2, y_colunas + 0.36, largura_col, altura_lista_usada, analise["atencoes"],
                           cor_marcador=COR_ATENCAO, tamanho=tamanho_lista, espaco_linha=espaco_linha)

    x3 = x2 + largura_col + 0.25
    _texto(slide, x3, y_colunas, largura_col, 0.28, "DECISÕES", tamanho=13, negrito=True, cor=AZUL_INSTITUCIONAL)
    _lista_com_marcadores(slide, x3, y_colunas + 0.36, largura_col, altura_lista_usada, analise["decisoes"],
                           cor_marcador=AZUL_INSTITUCIONAL, tamanho=tamanho_lista, espaco_linha=espaco_linha)

    y_mensagem = y_colunas + 0.36 + altura_lista_usada + gap_antes_mensagem
    altura_mensagem = max(altura_reservada_mensagem, y_zona_segura_fim - y_mensagem)
    _caixa_leitura(slide, MARGEM_IN, y_mensagem, LARGURA_IN - 2 * MARGEM_IN, altura_mensagem, "Mensagem Central",
                   analise["mensagem"], cor_fundo=OFF_WHITE, cor_rotulo=VERDE_AMAZONIA, tamanho_texto=12)
    return slide


def _slide_scorecard(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Scorecard do Mês", mes_label, pagina, "Leitura executiva e próximo passo por frente da operação")

    linhas_dados = _montar_scorecard(d)
    linhas_tabela = []
    for item in linhas_dados:
        linhas_tabela.append([
            (item["frente"], AZUL_INSTITUCIONAL, True),
            (item["status_label"], item["status_cor"], True),
            (item["leitura"], CINZA_TEXTO, False),
            (item["proximo_passo"], CINZA_TEXTO, False),
        ])

    _tabela(slide, MARGEM_IN, 1.65, LARGURA_IN - 2 * MARGEM_IN, 4.9,
            ["Frente", "Status", "Leitura Executiva", "Próximo Passo"], linhas_tabela,
            larguras_relativas=[2.0, 1.1, 3.4, 3.0], tamanho_fonte=13)
    return slide


def _slide_painel_inventario(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Painel de Inventário", mes_label, pagina, "Acurácia item a item, evolução mensal e SKUs recorrentes")

    kpis = d["kpis_inventario"]
    label, cor = _status_maior_melhor(kpis["acuracia_geral_pct"], *_LIMIARES["acuracia"])
    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_pct(kpis["acuracia_geral_pct"]), "rotulo": "Acurácia Geral", "contexto": label, "cor_contexto": cor},
        {"valor": _fmt_num(kpis["total_itens"]), "rotulo": "Itens Avaliados"},
        {"valor": _fmt_num(kpis["total_divergentes"]), "rotulo": "Itens Divergentes"},
        {"valor": _fmt_moeda(kpis["resultado_liquido"]), "rotulo": "Resultado Líquido", "cor": COR_SUCESSO if (kpis["resultado_liquido"] or 0) >= 0 else COR_ERRO},
    ], altura=1.25)

    evolucao = d["evolucao_inventario"][-6:]
    if evolucao:
        categorias = [_nome_mes(item["mes"])[:3] + "/" + item["mes"][2:4] for item in evolucao]
        valores = [item["acuracia_pct"] or 0 for item in evolucao]
        _texto(slide, MARGEM_IN, 3.05, 6.0, 0.28, "EVOLUÇÃO DA ACURÁCIA (ÚLTIMOS MESES)", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, 6.0, 3.35, categorias, "Acurácia geral", valores, cor_serie=VERDE_AMAZONIA)
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, 6.0, 3.65, "Evolução", "Sem histórico suficiente de fechamentos para montar a série mensal ainda.")

    x_direita = MARGEM_IN + 6.0 + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    _texto(slide, x_direita, 3.05, largura_direita, 0.28, "SKUS MAIS RECORRENTES", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
    top = d["top_recorrentes"]
    if top:
        linhas = [[t["sku"], (t["descricao"] or "—")[:26], _fmt_num(t["ocorrencias"]), _fmt_moeda(t["valor_total"])] for t in top]
        _tabela(slide, x_direita, 3.35, largura_direita, 3.35, ["SKU", "Descrição", "Ocor.", "Valor"], linhas,
                larguras_relativas=[1.1, 2.6, 0.8, 1.3], tamanho_fonte=11)
    else:
        _caixa_leitura(slide, x_direita, 3.35, largura_direita, 3.05, "SKUs recorrentes", "Nenhum SKU com divergência recorrente neste recorte.")
    return slide


def _slide_acuracia_ponderada(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Acurácia Ponderada", mes_label, pagina, "Item a item vs. ponderado por quantidade (IAQ) e por valor (IAP)")

    comp = d["comparativo_acuracia"]
    gap = comp.get("gap_item_vs_iap_pp")
    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_pct(comp.get("item_a_item_pct")), "rotulo": "Item a Item"},
        {"valor": _fmt_pct(comp.get("iaq_pct")), "rotulo": "IAQ (por Quantidade)"},
        {"valor": _fmt_pct(comp.get("iap_pct")), "rotulo": "IAP (por Valor)", "cor": VERDE_AMAZONIA},
        {"valor": _fmt_pct(abs(gap)) if gap is not None else "—", "rotulo": "Distorção (Item vs. IAP)",
         "cor": COR_ATENCAO if (gap is not None and abs(gap) >= 3) else COR_SUCESSO},
    ], altura=1.25)

    evolucao = d["evolucao_ponderada"][-6:]
    if evolucao:
        categorias = [item["mes"][2:] for item in evolucao]
        valores_iap = [item.get("iap_pct") or 0 for item in evolucao]
        _texto(slide, MARGEM_IN, 3.05, LARGURA_IN - 2 * MARGEM_IN, 0.28, "IAP MÊS A MÊS", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, LARGURA_IN - 2 * MARGEM_IN, 2.9, categorias, "IAP", valores_iap, cor_serie=AZUL_INSTITUCIONAL)
        _caixa_leitura(
            slide, MARGEM_IN, 6.35, LARGURA_IN - 2 * MARGEM_IN, 0.85, "Leitura",
            "O IAP pondera cada divergência pelo valor financeiro do SKU — quando ele fica bem abaixo do item a item, "
            "poucos itens de alto valor estão puxando o risco financeiro para baixo mesmo com a maioria dos SKUs certa.",
            cor_fundo=OFF_WHITE, tamanho_texto=11.5,
        )
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, LARGURA_IN - 2 * MARGEM_IN, 3.7, "Evolução Ponderada",
                       "Sem histórico suficiente de fechamentos para montar a série mensal do IAP ainda.")
    return slide


def _leitura_passivos(resumo: dict) -> str:
    """Versão curta (2-3 frases), pensada pra caber num slide, do mesmo
    dado por trás de _montar_resumo_narrado (baixas_operacionais_router) -
    aquele texto foi escrito pro pop-up de duplo-clique da tela (parágrafo
    longo, detalhando cada categoria uma por uma) e estoura qualquer caixa
    de slide de forma feia se usado direto aqui. Em vez de cortar esse
    texto no meio de uma frase, monta uma leitura própria e objetiva a
    partir dos MESMOS números - foco no insight que mais importa (o quanto
    do valor aprovado como baixa ainda não foi confirmado pelo inventário
    físico), por pedido explícito do usuário de "focar em resultado,
    números, menos teoria"."""
    passivos = resumo["passivos"]
    resultado_inv = resumo["resultado_inventario"]
    por_categoria = passivos.get("por_categoria", {})
    aguardando = por_categoria.get("aguardando_divergencia", {})

    partes = []
    if passivos["valor"]:
        if aguardando.get("valor"):
            partes.append(
                f"{_fmt_moeda(passivos['valor'])} em passivos aprovados no período, dos quais "
                f"{_fmt_moeda(aguardando['valor'])} ainda aguardam cruzamento com uma divergência."
            )
        else:
            partes.append(f"{_fmt_moeda(passivos['valor'])} em passivos aprovados no período, já mapeados por categoria.")
    else:
        partes.append("Nenhum passivo aprovado sem mapeamento neste recorte.")

    valor_resultado = resultado_inv.get("resultado_valor")
    if valor_resultado is not None:
        if valor_resultado >= 0:
            partes.append(f"O inventário acumulado no período é positivo em {_fmt_moeda(valor_resultado)}.")
        else:
            diferenca = abs(passivos["valor"] - abs(valor_resultado))
            partes.append(
                f"A perda física medida pelo inventário ({_fmt_moeda(abs(valor_resultado))}) é menor que o valor "
                f"aprovado como baixa — diferença de {_fmt_moeda(diferenca)}, possivelmente de baixas de um período "
                "ainda não coberto pelo inventário físico."
            )
    return " ".join(partes)


def _slide_mapeamento_passivos(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Mapeamento de Passivos", mes_label, pagina, "Passivos aprovados e resultado de inventário acumulado, por categoria de origem")

    resumo = d["resumo_passivos"]
    passivos = resumo["passivos"]
    resultado_inv = resumo["resultado_inventario"]

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_moeda(passivos["valor"]), "rotulo": "Passivos Aprovados"},
        {"valor": _fmt_num(passivos["quantidade"]), "rotulo": "Baixas Aprovadas"},
        {"valor": _fmt_moeda(resultado_inv["resultado_valor"]), "rotulo": "Resultado de Inventário",
         "cor": COR_SUCESSO if (resultado_inv["resultado_valor"] or 0) >= 0 else COR_ERRO},
        {"valor": _fmt_num(passivos["total_no_filtro"]), "rotulo": "Total no Recorte"},
    ], altura=1.25)

    por_categoria = passivos.get("por_categoria", {})
    categorias = [v["label"] for v in por_categoria.values()]
    valores = [v["valor"] for v in por_categoria.values()]
    if categorias and any(valores):
        _texto(slide, MARGEM_IN, 3.05, 7.1, 0.28, "PASSIVOS POR CATEGORIA DE MAPEAMENTO", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, 7.1, 3.35, categorias, "Valor (R$)", valores,
                            cor_serie=VERDE_AMAZONIA, formato_numero='#,##0')
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, 7.1, 3.65, "Por categoria", "Sem passivo aprovado por categoria neste recorte.")

    x_direita = MARGEM_IN + 7.1 + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    _caixa_leitura(slide, x_direita, 3.05, largura_direita, 3.65, "Leitura Executiva",
                   _leitura_passivos(resumo), cor_fundo=OFF_WHITE, tamanho_texto=12.5)
    return slide


def _slide_shelf_life(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Shelf Life", mes_label, pagina, "Farol de risco de validade — lotes ativos com quantidade em estoque")

    shelf = d["resumo_shelf_life"]
    resumo = shelf["resumo"]
    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_num(shelf["total_lotes_em_risco"]), "rotulo": "Lotes em Risco",
         "cor": COR_ATENCAO if shelf["total_lotes_em_risco"] else COR_SUCESSO},
        {"valor": _fmt_moeda(shelf["valor_total"]), "rotulo": "Valor Total Exposto"},
        {"valor": _fmt_num(resumo.get("vencido", {}).get("quantidade")), "rotulo": "Lotes Já Vencidos", "cor": COR_ERRO},
        {"valor": _fmt_num(shelf.get("total_itens")), "rotulo": "Total de Lotes Ativos Analisados"},
    ], altura=1.25)

    ordem_farol = [("vencido", "Vencido", COR_ERRO), ("30", "Até 30 dias", COR_ERRO),
                   ("60", "Até 60 dias", COR_ATENCAO), ("90", "Até 90 dias", COR_ATENCAO),
                   ("sem_validade", "Sem validade", COR_SEM_DADO)]
    categorias = [rotulo for _, rotulo, _ in ordem_farol]
    valores = [resumo.get(chave, {}).get("valor", 0) for chave, _, _ in ordem_farol]
    cores_pontos = [cor for _, _, cor in ordem_farol]

    _texto(slide, MARGEM_IN, 3.05, 7.3, 0.28, "VALOR EXPOSTO POR FAIXA DE VALIDADE", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
    _grafico_categoria(slide, MARGEM_IN, 3.35, 7.3, 3.35, categorias, "Valor (R$)", valores,
                        cor_serie=COR_ATENCAO, cores_pontos=cores_pontos, formato_numero='#,##0')

    x_direita = MARGEM_IN + 7.3 + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    itens = shelf.get("itens", [])[:5]
    if itens:
        linhas = [[it["sku"], (it["descricao_produto"] or "—")[:22], it.get("dias_para_vencer") if it.get("dias_para_vencer") is not None else "—"] for it in itens]
        _texto(slide, x_direita, 3.05, largura_direita, 0.28, "LOTES MAIS URGENTES", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _tabela(slide, x_direita, 3.35, largura_direita, 3.35, ["SKU", "Descrição", "Dias"], linhas,
                larguras_relativas=[1.0, 2.2, 0.8], tamanho_fonte=11)
    else:
        _caixa_leitura(slide, x_direita, 3.05, largura_direita, 3.65, "Lotes urgentes", "Nenhum lote em risco de validade neste recorte.")
    return slide


def _slide_movimentados_fefo(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Movimentados & FEFO", mes_label, pagina, "Transferências entre almoxarifados e aderência ao critério FEFO")

    transf = d["resumo_transferencias"]
    fefo = d["resumo_fefo"]
    label_fefo, cor_fefo = _status_menor_melhor(fefo.get("taxa_quebra_pct"), *_LIMIARES["fefo_quebra_pct"])

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_num(transf["total_transferencias"]), "rotulo": "Transferências Registradas"},
        {"valor": _fmt_num(fefo["total_transferencias_avaliadas"]), "rotulo": "Avaliadas p/ FEFO"},
        {"valor": _fmt_num(fefo["total_quebras_fefo"]), "rotulo": "Quebras de Critério", "cor": COR_ERRO if fefo["total_quebras_fefo"] else COR_SUCESSO},
        {"valor": _fmt_pct(fefo.get("taxa_quebra_pct")), "rotulo": "Taxa de Quebra", "contexto": label_fefo, "cor_contexto": cor_fefo},
    ], altura=1.25)

    evolucao = d["evolucao_transferencias"][-6:]
    if evolucao:
        categorias = [item["mes"][2:] for item in evolucao]
        valores = [item.get("taxa_quebra_fefo_pct") or 0 for item in evolucao]
        cores_pontos = [_status_menor_melhor(v, *_LIMIARES["fefo_quebra_pct"])[1] for v in valores]
        _texto(slide, MARGEM_IN, 3.05, 7.3, 0.28, "TAXA DE QUEBRA FEFO — ÚLTIMOS MESES", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, 7.3, 3.35, categorias, "Taxa de quebra", valores, cores_pontos=cores_pontos)
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, 7.3, 3.65, "Evolução FEFO", "Sem histórico mensal de transferências suficiente ainda.")

    x_direita = MARGEM_IN + 7.3 + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    top_skus = fefo.get("top_skus_com_quebra", [])[:5]
    if top_skus:
        linhas = [[t["sku"], _fmt_num(t["quebras"])] for t in top_skus]
        _texto(slide, x_direita, 3.05, largura_direita, 0.28, "SKUS COM MAIS QUEBRAS", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _tabela(slide, x_direita, 3.35, largura_direita, 3.35, ["SKU", "Quebras"], linhas,
                larguras_relativas=[1.6, 1.0], tamanho_fonte=11)
    else:
        _caixa_leitura(slide, x_direita, 3.05, largura_direita, 3.65, "Quebras por SKU", "Nenhuma quebra de critério FEFO neste recorte.")
    return slide


def _slide_proximos_passos(prs: Presentation, mes_label: str, pagina: int, d: dict):
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Próximos Passos", mes_label, pagina, "Ações priorizadas a partir dos pontos de atenção identificados acima")

    scorecard = _montar_scorecard(d)
    acoes = [item for item in scorecard if item["status_label"] != "Em avanço"]

    y_inicio = 1.65
    y_limite = ALTURA_IN - 1.55  # deixa espaço reservado pra caixa "Mensagem" no rodapé
    if not acoes:
        _caixa_leitura(slide, MARGEM_IN, y_inicio, LARGURA_IN - 2 * MARGEM_IN, 1.2, "Sem ação crítica pendente",
                       "Todas as frentes monitoradas estão dentro da faixa de controle neste recorte — manter a cadência atual de fechamento, mapeamento e monitoramento de validade.",
                       cor_fundo=OFF_WHITE)
    else:
        # Altura/gap calculados a partir de quantas ações existem (no máximo 5,
        # uma por frente do scorecard) pra nunca ultrapassar o espaço disponível
        # acima da caixa "Mensagem" - com poucas ações os blocos ficam maiores
        # (mais folgados), com mais ações eles encolhem proporcionalmente.
        n = len(acoes)
        gap = 0.16
        altura_bloco = min(1.05, ((y_limite - y_inicio) - gap * (n - 1)) / n)
        tamanho_indice = 26 if altura_bloco >= 0.95 else max(16, int(26 * altura_bloco / 1.05))
        tamanho_frente = 14 if altura_bloco >= 0.95 else 12
        tamanho_passo = 12 if altura_bloco >= 0.95 else 10.5
        y = y_inicio
        for i, item in enumerate(acoes, start=1):
            _retangulo(slide, MARGEM_IN, y, LARGURA_IN - 2 * MARGEM_IN, altura_bloco, cor_fill=BRANCO, cor_borda=CINZA_CLARO, raio=0.10)
            _texto(slide, MARGEM_IN + 0.22, y, 0.5, altura_bloco, str(i), tamanho=tamanho_indice, negrito=True,
                   cor=AZUL_CLARO, fonte=FONTE_TITULO, ancora_meio=True)
            _texto(slide, MARGEM_IN + 0.85, y + altura_bloco * 0.12, 6.0, altura_bloco * 0.4, item["frente"],
                   tamanho=tamanho_frente, negrito=True, cor=AZUL_INSTITUCIONAL)
            _texto(slide, MARGEM_IN + 0.85, y + altura_bloco * 0.48, LARGURA_IN - 2 * MARGEM_IN - 3.0, altura_bloco * 0.48,
                   item["proximo_passo"], tamanho=tamanho_passo, cor=CINZA_TEXTO)
            _badge_status(slide, LARGURA_IN - MARGEM_IN - 1.6, y + (altura_bloco - 0.38) / 2, 1.35, 0.38,
                          item["status_label"], item["status_cor"])
            y += altura_bloco + gap

    _caixa_leitura(
        slide, MARGEM_IN, ALTURA_IN - 1.35, LARGURA_IN - 2 * MARGEM_IN, 0.9, "Mensagem",
        "Este relatório é gerado automaticamente pelo Atlas a partir dos mesmos dados que alimentam as telas do dia a dia — "
        "qualquer ajuste em um fechamento, baixa ou lote se reflete aqui no próximo mês, sem retrabalho manual.",
        cor_fundo=OFF_WHITE, tamanho_texto=11,
    )
    return slide


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------
def montar_pptx_mbr(db: Session, usuario: models.Usuario, mes: str) -> bytes:
    """Gera o MBR completo (.pptx) para o mês informado ("AAAA-MM"),
    lendo os dados diretamente das funções de negócio do Atlas (sem HTTP,
    sem navegador) e aplicando a identidade visual da Mágio Chocolates."""
    dados = _coletar_dados_mbr(db, usuario, mes)
    mes_label = _nome_mes(mes)

    prs = _nova_apresentacao()
    _slide_capa(prs, mes_label)
    _slide_resumo_executivo(prs, mes_label, 2, dados)
    _slide_scorecard(prs, mes_label, 3, dados)
    _slide_painel_inventario(prs, mes_label, 4, dados)
    _slide_acuracia_ponderada(prs, mes_label, 5, dados)
    _slide_mapeamento_passivos(prs, mes_label, 6, dados)
    _slide_shelf_life(prs, mes_label, 7, dados)
    _slide_movimentados_fefo(prs, mes_label, 8, dados)
    _slide_proximos_passos(prs, mes_label, 9, dados)

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
