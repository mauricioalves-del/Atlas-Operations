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
from .routers import (
    fechamento_router, baixas_operacionais_router, movimentados_router, fefo_router,
    divergencias_router,
)

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


def _altura_necessaria_caixa_leitura(texto, largura_caixa, tamanho_pt, altura_rotulo=0.26, pad=0.20, espacamento=1.12):
    """Calcula a altura mínima que uma _caixa_leitura precisa pra caber `texto`
    sem acionar a rede de segurança de truncamento de _caber_no_espaco -
    replica exatamente a mesma estimativa de largura de caractere/altura de
    linha usada lá (proxy por largura média, não medição real de fonte), pra
    que a altura recomendada aqui seja consistente com o que de fato caberia
    (20/08/2026: corrige caixas com altura fixa que truncavam texto normal do
    mês porque a altura reservada tinha sido um chute, não calculada a partir
    do texto real que a caixa acaba recebendo)."""
    if not texto:
        return altura_rotulo + pad * 1.1
    largura_texto = largura_caixa - 2 * pad
    largura_media_char = (tamanho_pt / 72.0) * 0.52
    chars_por_linha = max(10, int(largura_texto / largura_media_char))
    max_chars_linha = max(1, int(chars_por_linha * 0.82))
    linhas_necessarias = max(1, -(-len(texto) // max_chars_linha))  # teto da divisão
    altura_linha = (tamanho_pt / 72.0) * espacamento * 1.22
    return pad * 0.6 + altura_rotulo + linhas_necessarias * altura_linha + pad * 0.5


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


def _grafico_categoria_multi(slide, x, y, w, h, categorias, series, tipo=XL_CHART_TYPE.COLUMN_CLUSTERED, formato_numero='#,##0'):
    """Mesma convenção de UM eixo/UMA escala só (nunca dual-axis) - só que
    com VÁRIAS séries lado a lado sobre esse único eixo (ex.: Passivos vs.
    Resultado de Inventário, ambos em R$; Entradas vs. Saídas, idem). `series`
    é uma lista de (nome, valores, cor). Isso NÃO é eixo duplo - é a mesma
    régua compartilhada por todas as séries, só que com mais de uma coluna
    por categoria (20/08/2026, pros slides de Passivos/Fluxo de Inventário)."""
    chart_data = CategoryChartData()
    chart_data.categories = categorias
    for nome, valores, _cor in series:
        chart_data.add_series(nome, valores)
    gframe = slide.shapes.add_chart(tipo, Inches(x), Inches(y), Inches(w), Inches(h), chart_data)
    chart = gframe.chart
    chart.has_legend = True
    try:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(10)
        chart.legend.font.color.rgb = CINZA_TEXTO
    except Exception:
        pass
    chart.has_title = False

    plot = chart.plots[0]
    try:
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(9)
        plot.data_labels.font.color.rgb = CINZA_TEXTO
        plot.data_labels.number_format = formato_numero
        plot.data_labels.number_format_is_linked = False
    except Exception:
        pass

    for serie_obj, (_nome, _valores, cor) in zip(plot.series, series):
        serie_obj.format.fill.solid()
        serie_obj.format.fill.fore_color.rgb = cor
        serie_obj.format.line.fill.background()

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
        # Pareto (concentração de valor) e distribuição por magnitude - já recortados pelo
        # mês do relatório (não o histórico inteiro), pra "mais exemplos do período" serem
        # de fato exemplos DESTE mês (20/08/2026).
        "concentracao_valor": fechamento_router.dashboard_concentracao_valor(almoxarifado=None, mes=mes, top_n=10, usuario=usuario, db=db),
        "distribuicao_magnitude": fechamento_router.dashboard_distribuicao_magnitude(almoxarifado=None, mes=mes, usuario=usuario, db=db),
        # Cobertura de Conferência (divergencias_router) - saúde do PROCESSO de conferência
        # (dias conferidos x pendentes por almoxarifado), usada pra reforçar/contextualizar
        # a curva de evolução de acurácia do Painel de Inventário (20/08/2026).
        "cobertura_conferencia": divergencias_router.cobertura_conferencia(dias=90, almoxarifado=None, usuario=usuario, db=db),
        "resumo_passivos": baixas_operacionais_router.resumo_executivo(
            ano=ano_int, mes=mes_int, data_inicio=None, data_fim=None, almoxarifado=None, motivo=None, usuario=usuario, db=db
        ),
        # Evolução mensal REAL de Passivos, já cruzada com o Fluxo de Inventário
        # (entradas/saídas/resultado de TODOS os inventários) mês a mês - histórico
        # completo, sem filtro de ano/mês (o slide usa os últimos meses, mesmo padrão
        # de evolucao_inventario/evolucao_ponderada acima) (20/08/2026).
        "evolucao_passivos_fluxo": baixas_operacionais_router.dashboard_passivos_evolucao_mensal(
            ano=None, mes=None, data_inicio=None, data_fim=None, almoxarifado=None, motivo=None, usuario=usuario, db=db
        ),
        "resultado_por_almoxarifado": baixas_operacionais_router.dashboard_resultado_por_almoxarifado(
            ano=None, mes=None, data_inicio=None, data_fim=None, almoxarifado=None, motivo=None, usuario=usuario, db=db
        ),
        "resumo_shelf_life": shelf_life_mod.calcular_resumo_shelf_life(db, incluir_itens=True, limite_itens=5),
        # Controle de Movimentados (reconciliação diária sistema x físico, origem ==
        # "movimentacao") - indicador PRÓPRIO, separado do Fechamento de Inventário
        # periódico. Ver docstring de movimentados_router.py (20/08/2026).
        "resumo_movimentados": movimentados_router.dashboard_resumo(mes=mes, almoxarifado=None, usuario=usuario, db=db),
        "evolucao_movimentados": movimentados_router.dashboard_evolucao_mensal(almoxarifado=None, usuario=usuario, db=db),
        "resumo_transferencias": movimentados_router.dashboard_transferencias_resumo(usuario=usuario, db=db),
        "evolucao_transferencias": movimentados_router.dashboard_transferencias_evolucao_mensal(usuario=usuario, db=db),
        "resumo_fefo": fefo_router.dashboard_resumo(usuario=usuario, db=db),
    }


# ---------------------------------------------------------------------------
# Narrativa executiva automática (baseada nos números reais coletados acima)
# ---------------------------------------------------------------------------
def _recorte_periodo(d: dict) -> dict:
    """"Recorte do período" (20/08/2026, pedido do usuário): compara o mês do
    relatório com o anterior nas frentes que TÊM série histórica real (mesma
    unidade - pontos percentuais - pra comparação fazer sentido) e aponta o
    maior avanço e a maior involução MoM. Passivos (R$) fica de fora dessa
    comparação de "maior/menor" (unidade diferente, R$ não é comparável a pp
    de acurácia) e ganha uma linha própria, à parte.

    Só usa séries que o Atlas de fato calcula mês a mês - não inventa
    comparação pra frente que não tem histórico (Shelf Life hoje é uma foto,
    não uma série)."""
    comparaveis = []

    evol_inv = d["evolucao_inventario"]
    if len(evol_inv) >= 2 and evol_inv[-1].get("variacao_mom_pp") is not None:
        comparaveis.append({"frente": "Acurácia do Inventário", "delta_pp": evol_inv[-1]["variacao_mom_pp"]})

    evol_pond = d["evolucao_ponderada"]
    if len(evol_pond) >= 2 and evol_pond[-1].get("variacao_iap_pp") is not None:
        comparaveis.append({"frente": "Acurácia Ponderada (IAP)", "delta_pp": evol_pond[-1]["variacao_iap_pp"]})

    evol_mov = d["evolucao_movimentados"]
    if len(evol_mov) >= 2 and evol_mov[-1].get("pct_acuracia") is not None and evol_mov[-2].get("pct_acuracia") is not None:
        comparaveis.append({"frente": "Controle de Movimentados", "delta_pp": round(evol_mov[-1]["pct_acuracia"] - evol_mov[-2]["pct_acuracia"], 2)})

    maior_avanco = max(comparaveis, key=lambda c: c["delta_pp"]) if comparaveis else None
    if maior_avanco and maior_avanco["delta_pp"] <= 0:
        maior_avanco = None
    maior_involucao = min(comparaveis, key=lambda c: c["delta_pp"]) if comparaveis else None
    if maior_involucao and maior_involucao["delta_pp"] >= 0:
        maior_involucao = None
    # evita apontar a MESMA frente como avanço e involução (só acontece com 1 item comparável)
    if maior_avanco and maior_involucao and maior_avanco["frente"] == maior_involucao["frente"]:
        maior_involucao = None

    variacao_passivos_valor = None
    evol_passivos = d["evolucao_passivos_fluxo"]
    if len(evol_passivos) >= 2:
        variacao_passivos_valor = round(evol_passivos[-1]["valor"] - evol_passivos[-2]["valor"], 2)

    return {
        "comparaveis": comparaveis,
        "maior_avanco": maior_avanco,
        "maior_involucao": maior_involucao,
        "variacao_passivos_valor": variacao_passivos_valor,
    }


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
    movimentados = d["resumo_movimentados"]
    evol_mov = d["evolucao_movimentados"]

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

    # Controle de Movimentados (item pedido explicitamente pelo usuário, 20/08/2026):
    # destaca como AÇÃO com impacto mensurável na acurácia desde a implantação - primeiro
    # mês com dado no snapshot mensal (ResumoMovimentacaoMensal) é lido como "implantação".
    if evol_mov and evol_mov[0].get("pct_acuracia") is not None and movimentados.get("pct_acuracia") is not None:
        primeiro = evol_mov[0]
        delta_implantacao = round(movimentados["pct_acuracia"] - primeiro["pct_acuracia"], 2)
        if len(evol_mov) >= 2 and delta_implantacao > 0:
            avancos.append(
                f"Controle de Movimentados: acurácia da reconciliação diária subiu de {_fmt_pct(primeiro['pct_acuracia'])} "
                f"(em {_nome_mes(primeiro['mes'])}, primeiro mês monitorado) para {_fmt_pct(movimentados['pct_acuracia'])} agora "
                f"(+{_fmt_pct(delta_implantacao)}) — ação com impacto direto e mensurável na acurácia."
            )
        elif movimentados.get("pct_acuracia") is not None:
            atencoes.append(
                f"Controle de Movimentados: acurácia da reconciliação diária em {_fmt_pct(movimentados['pct_acuracia'])} "
                f"desde a implantação (em {_nome_mes(primeiro['mes'])}) — ainda sem ganho consistente frente ao ponto de partida."
            )
    elif movimentados.get("itens_analisados"):
        avancos.append(f"Controle de Movimentados ativo: {_fmt_num(movimentados['itens_analisados'])} item(ns) reconciliado(s) neste mês.")

    # FEFO (20/08/2026) - suavizado por pedido do usuário: a "quebra de FEFO" hoje compara a
    # transferência com o estoque de lote ATIVO NO MOMENTO DO CÁLCULO, não com uma leitura de
    # disponibilidade tirada na hora exata da transferência (essa medição não existe na base
    # hoje) - por isso o número não entra mais como fato consolidado em avanços/decisões.
    # O acompanhamento detalhado do dashboard de FEFO que a equipe já mantém fica em
    # Auditoria > Outros Dashboards.
    fefo = d["resumo_fefo"]
    if fefo.get("total_transferencias_avaliadas"):
        decisoes.append(
            "Critério de FEFO: acompanhar pelo dashboard dedicado (Auditoria > Outros Dashboards > Controle de FEFO) — "
            "a taxa de quebra calculada aqui usa o estoque de lote ATUAL, não uma leitura de disponibilidade tirada no "
            "momento exato de cada transferência, então não é tratada como número fechado neste relatório."
        )

    if not decisoes:
        decisoes.append("Manter a cadência atual de fechamento e monitoramento — sem decisão crítica pendente neste recorte.")

    recorte = _recorte_periodo(d)

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

    return {"avancos": avancos, "atencoes": atencoes, "decisoes": decisoes, "mensagem": mensagem, "recorte_periodo": recorte}


def _linha_scorecard(frente, status_label, status_cor, leitura, proximo_passo):
    return {"frente": frente, "status_label": status_label, "status_cor": status_cor, "leitura": leitura, "proximo_passo": proximo_passo}


def _montar_scorecard(d: dict):
    kpis_inv = d["kpis_inventario"]
    passivos = d["resumo_passivos"]["passivos"]
    shelf = d["resumo_shelf_life"]
    movimentados = d["resumo_movimentados"]

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

    # Controle de Movimentados (20/08/2026) - substitui a antiga linha "Movimentados & FEFO":
    # a taxa de quebra de FEFO saiu do scorecard (ver _analise_geral) porque hoje ela compara
    # a transferência com o estoque de lote ATUAL, não com uma leitura de disponibilidade
    # tirada no momento exato da transferência - não é um número fechado o bastante pra virar
    # status de scorecard. Essa linha agora reflete a reconciliação diária de verdade.
    label_mov, cor_mov = _status_maior_melhor(movimentados.get("pct_acuracia"), *_LIMIARES["acuracia"])
    linha_movimentados = _linha_scorecard(
        "Controle de Movimentados", label_mov, cor_mov,
        f"Acurácia da reconciliação diária em {_fmt_pct(movimentados.get('pct_acuracia'))} sobre {_fmt_num(movimentados.get('itens_analisados'))} item(ns) analisado(s) no mês.",
        "Investigar itens com divergência não resolvida." if movimentados.get("itens_com_divergencia") else "Manter cadência de conferência diária.",
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

    return [linha_inventario, linha_passivos, linha_ponderada, linha_shelf, linha_movimentados]


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
    movimentados = d["resumo_movimentados"]
    label_acuracia, cor_acuracia = _status_maior_melhor(kpis_inv["acuracia_geral_pct"], *_LIMIARES["acuracia"])
    label_mov, cor_mov = _status_maior_melhor(movimentados.get("pct_acuracia"), *_LIMIARES["acuracia"])

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_pct(kpis_inv["acuracia_geral_pct"]), "rotulo": "Acurácia do Inventário", "cor": AZUL_INSTITUCIONAL, "contexto": label_acuracia, "cor_contexto": cor_acuracia},
        {"valor": _fmt_moeda(passivos["valor"]), "rotulo": "Passivos Mapeados", "cor": AZUL_INSTITUCIONAL, "contexto": f"{_fmt_num(passivos['quantidade'])} baixas aprovadas"},
        {"valor": _fmt_moeda(shelf["valor_total"]), "rotulo": "Valor em Risco de Validade", "cor": AZUL_INSTITUCIONAL, "contexto": f"{_fmt_num(shelf['total_lotes_em_risco'])} lotes"},
        {"valor": _fmt_pct(movimentados.get("pct_acuracia")), "rotulo": "Controle de Movimentados", "cor": AZUL_INSTITUCIONAL, "contexto": label_mov, "cor_contexto": cor_mov},
    ], altura=1.30)

    analise = _analise_geral(d)

    # "Recorte do Período" (20/08/2026, pedido do usuário): uma linha de destaque logo
    # abaixo dos KPIs com o maior avanço e a maior involução MoM entre as frentes que têm
    # série histórica comparável (mesma unidade - pp) - ver _recorte_periodo.
    recorte = analise["recorte_periodo"]
    y_recorte = 2.95
    altura_recorte = 0.42
    partes_recorte = []
    if recorte["maior_avanco"]:
        partes_recorte.append(("▲ Maior avanço do mês: ", CINZA_TEXTO, False))
        partes_recorte.append((f"{recorte['maior_avanco']['frente']} (+{_fmt_pct(recorte['maior_avanco']['delta_pp'])})", COR_SUCESSO, True))
    if recorte["maior_involucao"]:
        if partes_recorte:
            partes_recorte.append(("     ", CINZA_TEXTO, False))
        partes_recorte.append(("▼ Maior involução do mês: ", CINZA_TEXTO, False))
        partes_recorte.append((f"{recorte['maior_involucao']['frente']} ({_fmt_pct(recorte['maior_involucao']['delta_pp'])})", COR_ERRO, True))
    if recorte["variacao_passivos_valor"] is not None and recorte["variacao_passivos_valor"] != 0:
        if partes_recorte:
            partes_recorte.append(("     ", CINZA_TEXTO, False))
        sinal = "+" if recorte["variacao_passivos_valor"] > 0 else ""
        cor_passivo_var = COR_ERRO if recorte["variacao_passivos_valor"] > 0 else COR_SUCESSO
        partes_recorte.append(("Passivos aprovados: ", CINZA_TEXTO, False))
        partes_recorte.append((f"{sinal}{_fmt_moeda(recorte['variacao_passivos_valor'])} vs. mês anterior", cor_passivo_var, True))

    if partes_recorte:
        _retangulo(slide, MARGEM_IN, y_recorte, LARGURA_IN - 2 * MARGEM_IN, altura_recorte, cor_fill=OFF_WHITE, raio=0.08)
        tf_recorte = slide.shapes.add_textbox(Inches(MARGEM_IN + 0.18), Inches(y_recorte), Inches(LARGURA_IN - 2 * MARGEM_IN - 0.36), Inches(altura_recorte)).text_frame
        tf_recorte.word_wrap = True
        tf_recorte.vertical_anchor = MSO_ANCHOR.MIDDLE
        p_recorte = tf_recorte.paragraphs[0]
        for texto_parte, cor_parte, negrito_parte in partes_recorte:
            run = p_recorte.add_run()
            run.text = texto_parte
            run.font.size = Pt(11.5)
            run.font.name = FONTE_TEXTO
            run.font.bold = negrito_parte
            run.font.color.rgb = cor_parte
        y_colunas = y_recorte + altura_recorte + 0.18
    else:
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
    # Altura reservada calculada a partir do texto real da mensagem (20/08/2026: antes era
    # um valor fixo de 1.05 que não escalava com o tamanho da mensagem - truncava com
    # reticências em meses normais, não só no pior caso).
    altura_reservada_mensagem = max(1.05, _altura_necessaria_caixa_leitura(analise["mensagem"], LARGURA_IN - 2 * MARGEM_IN, 12))
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

    # altura_topo encolhido (era 3.35, depois 2.55) pra abrir espaço suficiente pro rodapé de
    # Cobertura de Conferência sem estourar o limite do slide (20/08/2026: a versão anterior
    # não validava se título + tabela + texto do rodapé realmente cabiam no espaço restante e
    # acabava desenhando o texto de insight abaixo do limite físico do slide).
    altura_topo = 1.75
    evolucao = d["evolucao_inventario"][-6:]
    if evolucao:
        categorias = [_nome_mes(item["mes"])[:3] + "/" + item["mes"][2:4] for item in evolucao]
        valores = [item["acuracia_pct"] or 0 for item in evolucao]
        _texto(slide, MARGEM_IN, 3.05, 6.0, 0.28, "EVOLUÇÃO DA ACURÁCIA (ÚLTIMOS MESES)", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, 6.0, altura_topo, categorias, "Acurácia geral", valores, cor_serie=VERDE_AMAZONIA)
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, 6.0, altura_topo + 0.30, "Evolução", "Sem histórico suficiente de fechamentos para montar a série mensal ainda.")

    x_direita = MARGEM_IN + 6.0 + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    _texto(slide, x_direita, 3.05, largura_direita, 0.28, "SKUS MAIS RECORRENTES", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
    # Limitado a 4 (era 5) e coluna SKU alargada (20/08/2026: com altura_topo encolhido pra
    # abrir espaço pra Cobertura de Conferência, 5 linhas + cabeçalho com "SKU-CHOC-XXX"
    # quebrando em 2 linhas por coluna estreita demais estourava a tabela sobre o título da
    # seção abaixo; a coluna mais larga evita a quebra e 4 linhas cabem com folga)
    top = d["top_recorrentes"][:4]
    if top:
        linhas = [[t["sku"], (t["descricao"] or "—")[:26], _fmt_num(t["ocorrencias"]), _fmt_moeda(t["valor_total"])] for t in top]
        _tabela(slide, x_direita, 3.35, largura_direita, altura_topo, ["SKU", "Descrição", "Ocor.", "Valor"], linhas,
                larguras_relativas=[1.5, 2.2, 0.7, 1.3], tamanho_fonte=11)
    else:
        _caixa_leitura(slide, x_direita, 3.35, largura_direita, altura_topo - 0.30, "SKUs recorrentes", "Nenhum SKU com divergência recorrente neste recorte.")

    # Cobertura de Conferência (20/08/2026, pedido do usuário) - reforça a curva de evolução
    # acima: uma queda/estabilidade de acurácia lida junto com baixa cobertura de conferência
    # é um sinal diferente de queda com cobertura alta (aqui é falta de dado, lá é perda real).
    # Layout com orçamento vertical explícito (mostra só as 3 piores, e o texto de insight usa
    # altura calculada a partir do texto real + _caber_no_espaco) pra nunca estourar o rodapé.
    y_zona_segura_fim = ALTURA_IN - 0.55  # reserva o rodapé (número de página)
    largura_cheia = LARGURA_IN - 2 * MARGEM_IN
    y_cobertura = 3.35 + altura_topo + 0.18
    cobertura = d["cobertura_conferencia"]
    por_almox = [linha for linha in cobertura["por_almoxarifado"] if not linha.get("sem_dados")]
    _texto(slide, MARGEM_IN, y_cobertura, largura_cheia, 0.24,
           f"COBERTURA DE CONFERÊNCIA (ÚLTIMOS {cobertura['periodo_dias']} DIAS) — SUSTENTA A LEITURA DE EVOLUÇÃO ACIMA",
           tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
    if por_almox:
        piores = por_almox[:3]  # já vem ordenado do pior pro melhor
        linhas_cobertura = [
            [
                linha["almoxarifado"],
                _fmt_pct(linha["pct_cobertura"]),
                f'{_fmt_num(linha["dias_desde_ultima_conferencia"])} dia(s)' if linha["dias_desde_ultima_conferencia"] is not None else "—",
                f'{_fmt_num(linha["maior_furo_dias"])} dia(s)' if linha["maior_furo_dias"] else "—",
            ]
            for linha in piores
        ]
        y_tabela_cobertura = y_cobertura + 0.25
        altura_tabela_cobertura = 0.24 + 0.24 * len(piores)  # cabeçalho + 1 linha por almoxarifado
        _tabela(slide, MARGEM_IN, y_tabela_cobertura, largura_cheia, altura_tabela_cobertura,
                ["Almoxarifado (pior cobertura primeiro)", "% Cobertura", "Dias s/ conferência", "Maior furo"],
                linhas_cobertura, larguras_relativas=[2.4, 1.1, 1.5, 1.1], tamanho_fonte=10.5)

        abaixo_70 = [linha for linha in por_almox if (linha["pct_cobertura"] or 0) < 70]
        if abaixo_70:
            pior = por_almox[0]
            insight_cobertura = (
                f"{_fmt_num(len(abaixo_70))} almoxarifado(s) com cobertura de conferência abaixo de 70% — "
                f"pior caso: {pior['almoxarifado']} ({_fmt_pct(pior['pct_cobertura'])}). Acurácia baixa combinada com "
                "cobertura baixa é falta de dado, não perda confirmada; vale reforçar a rotina de conferência antes de tratar como perda real."
            )
        else:
            insight_cobertura = "Cobertura de conferência acima de 70% em todos os almoxarifados neste recorte — a curva de acurácia acima reflete o estoque de fato, não uma lacuna de dado."

        y_insight = y_tabela_cobertura + altura_tabela_cobertura + 0.06
        altura_insight = min(
            _altura_necessaria_caixa_leitura(insight_cobertura, largura_cheia, 10.5, altura_rotulo=0, pad=0),
            max(0.22, y_zona_segura_fim - y_insight),
        )
        texto_insight_cortado = _caber_no_espaco(insight_cobertura, largura_cheia, altura_insight, 10.5)
        _texto(slide, MARGEM_IN, y_insight, largura_cheia, altura_insight, texto_insight_cortado, tamanho=10.5, cor=CINZA_TEXTO)
    else:
        _texto(slide, MARGEM_IN, y_cobertura + 0.30, largura_cheia, 0.4,
               "Sem almoxarifado com dado de conferência suficiente neste recorte ainda.", tamanho=11, cor=CINZA_TEXTO)
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
        categorias = [_nome_mes(item["mes"])[:3] + "/" + item["mes"][2:4] for item in evolucao]
        valores_iaq = [item.get("iaq_pct") or 0 for item in evolucao]
        valores_iap = [item.get("iap_pct") or 0 for item in evolucao]
        # Gráfico encolhido (era 2.55) pra abrir espaço suficiente pra caixa de Leitura MoM
        # abaixo não truncar em meses com frase mais longa (20/08/2026) - ver altura dinâmica
        # da caixa logo abaixo, calculada a partir do texto real em vez de um valor fixo.
        altura_grafico = 2.05
        _texto(slide, MARGEM_IN, 3.05, LARGURA_IN - 2 * MARGEM_IN, 0.28, "IAQ E IAP MÊS A MÊS", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria_multi(
            slide, MARGEM_IN, 3.35, LARGURA_IN - 2 * MARGEM_IN, altura_grafico,
            categorias, [("IAQ (quantidade)", valores_iaq, VERDE_AMAZONIA), ("IAP (valor)", valores_iap, AZUL_INSTITUCIONAL)],
        )

        # Análise MoM detalhada (20/08/2026, pedido do usuário: "mais exemplos do período") -
        # variação ponto a ponto do ÚLTIMO mês frente ao anterior, já calculada por
        # dashboard_evolucao_ponderada_mensal, incluindo o "Valor Mod" (impacto financeiro
        # total do mês, sobra e falta juntos) - leitura em R$, não só em %.
        ultimo = evolucao[-1]
        frases_mom = []
        if ultimo.get("variacao_iap_pp") is not None:
            direcao = "melhorou" if ultimo["variacao_iap_pp"] > 0 else ("piorou" if ultimo["variacao_iap_pp"] < 0 else "manteve")
            frases_mom.append(f"o IAP {direcao} {_fmt_pct(abs(ultimo['variacao_iap_pp']))} frente ao mês anterior")
        if ultimo.get("variacao_iaq_pp") is not None:
            direcao_q = "melhorou" if ultimo["variacao_iaq_pp"] > 0 else ("piorou" if ultimo["variacao_iaq_pp"] < 0 else "manteve")
            frases_mom.append(f"o IAQ {direcao_q} {_fmt_pct(abs(ultimo['variacao_iaq_pp']))}")
        if ultimo.get("valor_mod") is not None:
            frases_mom.append(f"R$ {_fmt_num(ultimo['valor_mod'], 2)} em jogo neste mês entre sobra e falta (Valor Mod)")
        texto_mom = (
            ("Este mês, " + ", ".join(frases_mom) + ". ") if frases_mom else ""
        ) + (
            "O IAP pondera cada divergência pelo valor financeiro do SKU — quando ele fica bem abaixo do item a item, "
            "poucos itens de alto valor estão puxando o risco financeiro para baixo mesmo com a maioria dos SKUs certa."
        )
        y_leitura_mom = 3.35 + altura_grafico + 0.20
        y_zona_segura_fim = ALTURA_IN - 0.55  # reserva o rodapé (número de página)
        largura_caixa_mom = LARGURA_IN - 2 * MARGEM_IN
        altura_leitura_mom = min(
            max(1.05, _altura_necessaria_caixa_leitura(texto_mom, largura_caixa_mom, 11.5)),
            y_zona_segura_fim - y_leitura_mom,
        )
        _caixa_leitura(slide, MARGEM_IN, y_leitura_mom, largura_caixa_mom, altura_leitura_mom, "Leitura MoM", texto_mom,
                       cor_fundo=OFF_WHITE, tamanho_texto=11.5)
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, LARGURA_IN - 2 * MARGEM_IN, 3.7, "Evolução Ponderada",
                       "Sem histórico suficiente de fechamentos para montar a série mensal do IAP ainda.")
    return slide


def _slide_acuracia_ponderada_detalhe(prs: Presentation, mes_label: str, pagina: int, d: dict):
    """Segundo slide de Acurácia Ponderada (20/08/2026, pedido do usuário):
    curva de Pareto (concentração de valor) e distribuição por magnitude da
    divergência, com exemplos REAIS do mês (não do histórico inteiro) - ver
    _coletar_dados_mbr, concentracao_valor/distribuicao_magnitude já
    recortados por `mes`."""
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Acurácia Ponderada — Concentração de Risco", mes_label, pagina,
               "Curva de Pareto e distribuição por magnitude — onde o valor em risco está concentrado neste mês")

    pareto = d["concentracao_valor"]
    largura_esquerda = 7.3
    itens_pareto = pareto.get("itens", [])[:10]
    if itens_pareto:
        categorias = [item["sku"] for item in itens_pareto]
        valores_pct_acum = [item["pct_valor_acumulado"] for item in itens_pareto]
        _texto(slide, MARGEM_IN, 1.65, largura_esquerda, 0.28, "CURVA DE PARETO — % DO VALOR ACUMULADO (TOP 10 SKUS DO MÊS)",
               tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 1.95, largura_esquerda, 2.55, categorias, "% acumulado", valores_pct_acum,
                            tipo=XL_CHART_TYPE.LINE_MARKERS, cor_serie=VERDE_AMAZONIA)

        top_n_pct = pareto.get("top_n_pct_do_valor")
        top_n = pareto.get("top_n")
        linha_pareto_texto = (
            f"Os {top_n} maiores SKUs divergentes concentram {_fmt_pct(top_n_pct)} do valor em risco do mês "
            f"({_fmt_moeda(pareto.get('valor_total'))} no total, {_fmt_num(pareto.get('total_itens_divergentes'))} itens divergentes)."
            if top_n_pct is not None else "Concentração de valor não disponível neste recorte."
        )
        _texto(slide, MARGEM_IN, 4.60, largura_esquerda, 0.5, linha_pareto_texto, tamanho=10.5, cor=CINZA_TEXTO)

        top_3 = itens_pareto[:3]
        linhas_top3 = [[it["sku"], (it.get("descricao") or "—")[:24], _fmt_moeda(it["valor"]), _fmt_pct(it["pct_valor_acumulado"])] for it in top_3]
        _texto(slide, MARGEM_IN, 5.15, largura_esquerda, 0.26, "3 MAIORES EXEMPLOS DO MÊS", tamanho=10.5, negrito=True, cor=AZUL_INSTITUCIONAL)
        _tabela(slide, MARGEM_IN, 5.42, largura_esquerda, 1.55, ["SKU", "Descrição", "Valor", "% Acum."], linhas_top3,
                larguras_relativas=[1.1, 2.6, 1.1, 0.9], tamanho_fonte=10.5)
    else:
        _caixa_leitura(slide, MARGEM_IN, 1.65, largura_esquerda, 5.3, "Curva de Pareto",
                       "Sem item divergente com custo cadastrado neste recorte para montar a curva de concentração de valor.")

    x_direita = MARGEM_IN + largura_esquerda + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    magnitude = d["distribuicao_magnitude"]
    faixas = magnitude.get("faixas", [])
    if faixas and magnitude.get("total_divergentes"):
        categorias_mag = [f["faixa"] for f in faixas]
        valores_mag = [f["quantidade_itens"] for f in faixas]
        cores_mag = [COR_SUCESSO, COR_INFO, COR_ATENCAO, COR_ERRO]
        _texto(slide, x_direita, 1.65, largura_direita, 0.28, "DISTRIBUIÇÃO POR MAGNITUDE (ITENS)", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, x_direita, 1.95, largura_direita, 2.55, categorias_mag, "Itens", valores_mag,
                            cores_pontos=cores_mag[:len(valores_mag)], formato_numero='0')
        pct_pequenas = magnitude.get("pct_divergencias_pequenas")
        texto_magnitude = (
            f"{_fmt_pct(pct_pequenas)} das divergências do mês são pequenas (0 a 5 unidades) — a métrica item a item trata "
            "essas igual às grandes, mesmo pesando muito menos no risco financeiro real."
            if pct_pequenas is not None else "Sem divergência neste recorte para distribuir por magnitude."
        )
        _texto(slide, x_direita, 4.60, largura_direita, 0.65, texto_magnitude, tamanho=10.5, cor=CINZA_TEXTO)

        linhas_faixas = [[f["faixa"], _fmt_num(f["quantidade_itens"]), _fmt_moeda(f["valor_total"])] for f in faixas]
        _texto(slide, x_direita, 5.35, largura_direita, 0.26, "VALOR POR FAIXA", tamanho=10.5, negrito=True, cor=AZUL_INSTITUCIONAL)
        _tabela(slide, x_direita, 5.62, largura_direita, 1.35, ["Faixa", "Itens", "Valor"], linhas_faixas,
                larguras_relativas=[1.6, 0.9, 1.3], tamanho_fonte=10.5)
    else:
        _caixa_leitura(slide, x_direita, 1.65, largura_direita, 5.3, "Distribuição por magnitude",
                       "Sem divergência neste recorte para distribuir por magnitude.")
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


def _slide_passivos_evolucao(prs: Presentation, mes_label: str, pagina: int, d: dict):
    """Segundo slide de Mapeamento de Passivos (20/08/2026, pedido do
    usuário): curva de evolução do processo mês a mês, distinguindo baixa
    por PASSIVO REAL (BaixaOperacional aprovada) de RESULTADO DE FECHAMENTO
    DE INVENTÁRIO (AjusteInventarioOficial - entradas/saídas de TODOS os
    inventários), e onde estão concentradas as maiores perdas por
    almoxarifado."""
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    # Título encurtado (era "Mapeamento de Passivos — Evolução e Concentração", 54 caracteres -
    # 20/08/2026: quebrava em 2 linhas e sobrepunha o subtítulo, que fica em posição fixa)
    _cabecalho(slide, "Passivos — Evolução e Concentração", mes_label, pagina,
               "Passivo aprovado vs. resultado de fechamento de inventário, mês a mês, e onde estão as maiores perdas")

    largura_esquerda = 7.3
    evolucao = d["evolucao_passivos_fluxo"][-6:]
    if evolucao:
        categorias = [_nome_mes(item["mes"])[:3] + "/" + item["mes"][2:4] for item in evolucao]
        valores_passivos = [item["valor"] for item in evolucao]
        valores_resultado_inv = [item["resultado_inventario_mes"] for item in evolucao]
        _texto(slide, MARGEM_IN, 1.65, largura_esquerda, 0.28, "PASSIVO APROVADO vs. RESULTADO DE FECHAMENTO (R$/MÊS)",
               tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria_multi(
            slide, MARGEM_IN, 1.95, largura_esquerda, 2.75, categorias,
            [("Passivo aprovado (baixa real)", valores_passivos, COR_ERRO), ("Resultado do fechamento de inventário", valores_resultado_inv, VERDE_AMAZONIA)],
            formato_numero='#,##0',
        )
        ultimo = evolucao[-1]
        texto_distincao = (
            f"Em {_nome_mes(ultimo['mes'])}: {_fmt_moeda(ultimo['valor'])} em passivo aprovado (baixa operacional real, já decidida) "
            f"contra {_fmt_moeda(ultimo['resultado_inventario_mes'])} de resultado do fechamento de inventário (entradas − saídas de "
            "TODOS os inventários no mês) — são duas contas diferentes: uma é decisão já tomada sobre um item específico, a outra é o "
            "saldo físico de todo o estoque contado naquele fechamento."
        )
        _texto(slide, MARGEM_IN, 4.80, largura_esquerda, 0.85, texto_distincao, tamanho=10.5, cor=CINZA_TEXTO)
    else:
        _caixa_leitura(slide, MARGEM_IN, 1.65, largura_esquerda, 3.9, "Evolução",
                       "Sem histórico mensal suficiente de passivos/fechamento de inventário ainda.")

    x_direita = MARGEM_IN + largura_esquerda + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    por_almox = d["resultado_por_almoxarifado"][:6]
    if por_almox:
        categorias_almox = [linha["almoxarifado"] for linha in por_almox]
        valores_passivos_almox = [linha["passivos_valor"] for linha in por_almox]
        valores_inv_almox = [linha["inventario_valor_abs"] for linha in por_almox]
        _texto(slide, x_direita, 1.65, largura_direita, 0.28, "ONDE ESTÃO AS MAIORES PERDAS (TOP 6)", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria_multi(
            slide, x_direita, 1.95, largura_direita, 3.35, categorias_almox,
            [("Passivos (R$)", valores_passivos_almox, COR_ERRO), ("Resultado inventário (abs., R$)", valores_inv_almox, AZUL_INSTITUCIONAL)],
            tipo=XL_CHART_TYPE.BAR_CLUSTERED, formato_numero='#,##0',
        )
        pior = por_almox[0]
        _texto(slide, x_direita, 5.45, largura_direita, 0.55,
               f"Maior concentração: {pior['almoxarifado']} ({_fmt_moeda(pior['valor_acumulado'])} acumulado no período).",
               tamanho=10.5, cor=CINZA_TEXTO)
    else:
        _caixa_leitura(slide, x_direita, 1.65, largura_direita, 3.9, "Por almoxarifado",
                       "Sem passivo ou ajuste de inventário por almoxarifado neste recorte.")
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


def _slide_controle_movimentados(prs: Presentation, mes_label: str, pagina: int, d: dict):
    """Controle de Movimentados (20/08/2026, pedido do usuário) - slide
    próprio, separado de FEFO: mede a reconciliação diária sistema x físico
    (livro-caixa bruto) desde a implantação, e destaca explicitamente o
    ganho de acurácia como uma AÇÃO com impacto mensurável - não só mais um
    número solto."""
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "Controle de Movimentados", mes_label, pagina,
               "Reconciliação diária (sistema x físico) — impacto na acurácia desde a implantação")

    resumo = d["resumo_movimentados"]
    evolucao = d["evolucao_movimentados"]
    label_mov, cor_mov = _status_maior_melhor(resumo.get("pct_acuracia"), *_LIMIARES["acuracia"])

    delta_implantacao = None
    primeiro = evolucao[0] if evolucao else None
    if primeiro and primeiro.get("pct_acuracia") is not None and resumo.get("pct_acuracia") is not None:
        delta_implantacao = round(resumo["pct_acuracia"] - primeiro["pct_acuracia"], 2)

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_num(resumo.get("itens_analisados")), "rotulo": "Itens Analisados no Mês"},
        {"valor": _fmt_pct(resumo.get("pct_acuracia")), "rotulo": "Acurácia da Reconciliação", "contexto": label_mov, "cor_contexto": cor_mov},
        {"valor": _fmt_num(resumo.get("itens_com_divergencia")), "rotulo": "Itens com Divergência",
         "cor": COR_ATENCAO if resumo.get("itens_com_divergencia") else COR_SUCESSO},
        {"valor": (f"+{_fmt_pct(delta_implantacao)}" if delta_implantacao is not None and delta_implantacao >= 0 else _fmt_pct(delta_implantacao)),
         "rotulo": "Ganho desde a Implantação", "cor": COR_SUCESSO if (delta_implantacao or 0) >= 0 else COR_ERRO},
    ], altura=1.25)

    largura_esquerda = 7.5
    if len(evolucao) >= 2:
        categorias = [_nome_mes(item["mes"])[:3] + "/" + item["mes"][2:4] for item in evolucao]
        valores = [item.get("pct_acuracia") or 0 for item in evolucao]
        _texto(slide, MARGEM_IN, 3.05, largura_esquerda, 0.28, "ACURÁCIA DA RECONCILIAÇÃO — DESDE A IMPLANTAÇÃO", tamanho=11, negrito=True, cor=AZUL_INSTITUCIONAL)
        _grafico_categoria(slide, MARGEM_IN, 3.35, largura_esquerda, 3.35, categorias, "Acurácia", valores, cor_serie=VERDE_AMAZONIA)
    else:
        _caixa_leitura(slide, MARGEM_IN, 3.05, largura_esquerda, 3.65, "Evolução",
                       "Ainda só há um mês de histórico monitorado - a série de evolução aparece a partir do segundo mês de dados.")

    x_direita = MARGEM_IN + largura_esquerda + 0.35
    largura_direita = LARGURA_IN - MARGEM_IN - x_direita
    if primeiro and delta_implantacao is not None:
        if delta_implantacao > 0:
            texto_impacto = (
                f"Desde a implantação do Controle de Movimentados, em {_nome_mes(primeiro['mes'])}, a acurácia da reconciliação "
                f"diária subiu de {_fmt_pct(primeiro['pct_acuracia'])} para {_fmt_pct(resumo['pct_acuracia'])} — um ganho de "
                f"{_fmt_pct(delta_implantacao)}. Esse é o efeito direto de passar a reconciliar o livro-caixa bruto todo dia, em "
                "vez de só no fechamento periódico."
            )
        else:
            texto_impacto = (
                f"Desde a implantação, em {_nome_mes(primeiro['mes'])}, a acurácia da reconciliação diária está em "
                f"{_fmt_pct(resumo['pct_acuracia'])}, ainda sem ganho consistente frente ao ponto de partida "
                f"({_fmt_pct(primeiro['pct_acuracia'])}) — vale olhar os itens com divergência recorrente antes do próximo fechamento."
            )
    else:
        texto_impacto = "Ainda não há dado suficiente pra comparar com o ponto de partida da implantação."
    _caixa_leitura(slide, x_direita, 3.05, largura_direita, 3.65, "Impacto da Implantação", texto_impacto,
                   cor_fundo=OFF_WHITE, tamanho_texto=12)
    return slide


def _slide_fefo(prs: Presentation, mes_label: str, pagina: int, d: dict):
    """FEFO (20/08/2026, suavizado por pedido do usuário): a "quebra de
    FEFO" hoje compara a transferência com o estoque de lote ATIVO NO
    MOMENTO DO CÁLCULO (ver fefo.py: calcular_checagem_fefo lê
    LoteShelfLife.ativo == True "agora"), não com uma leitura de
    disponibilidade tirada na hora exata da transferência - essa medição
    não existe na base hoje. Em vez de apresentar a taxa de quebra como
    fato fechado, o slide mostra só o volume (esse sim confiável) e
    aponta pro dashboard dedicado que a equipe já mantém (Auditoria >
    Outros Dashboards)."""
    slide = _slide_em_branco(prs)
    _fundo(slide, BRANCO)
    _cabecalho(slide, "FEFO", mes_label, pagina, "Volume de transferências entre almoxarifados — leitura de critério em dashboard dedicado")

    transf = d["resumo_transferencias"]
    fefo = d["resumo_fefo"]

    _linha_kpis(slide, 1.55, [
        {"valor": _fmt_num(transf["total_transferencias"]), "rotulo": "Transferências Registradas"},
        {"valor": _fmt_num(transf.get("transferencias_da_fabrica")), "rotulo": "Saídas da Fábrica"},
        {"valor": _fmt_num(fefo.get("total_transferencias_avaliadas")), "rotulo": "Avaliadas p/ Critério FEFO", "cor": COR_INFO},
        {"valor": _fmt_pct(fefo.get("taxa_quebra_pct")), "rotulo": "Taxa de Quebra (referencial)", "cor": COR_INFO},
    ], altura=1.25)

    _caixa_leitura(
        slide, MARGEM_IN, 3.05, LARGURA_IN - 2 * MARGEM_IN, 1.55, "Por que a taxa de quebra não é tratada como fato fechado",
        "O cálculo de quebra de FEFO compara cada transferência que saiu da Fábrica com o lote mais antigo AINDA ATIVO NO "
        "SISTEMA HOJE — não com uma leitura de disponibilidade tirada na hora exata em que a transferência aconteceu (essa "
        "medição não existe na base de dados atual). Por isso o número acima é referencial, não uma meta oficial: uma "
        "leitura mais realista pede uma captura de estoque no momento da transferência, que o Atlas ainda não tem.",
        cor_fundo=OFF_WHITE, cor_rotulo=COR_INFO, tamanho_texto=12,
    )

    _caixa_leitura(
        slide, MARGEM_IN, 4.80, LARGURA_IN - 2 * MARGEM_IN, 1.55, "Onde acompanhar o critério de FEFO de verdade",
        "O dashboard de Controle de FEFO que a equipe já mantém em paralelo ao Atlas está disponível em "
        "Auditoria > Outros Dashboards — suba (ou atualize) o arquivo .html autocontido daquele dashboard lá pra "
        "manter a leitura de FEFO acessível junto com o resto do sistema, sem misturar com este relatório.",
        cor_fundo=AZUL_CLARO, cor_rotulo=AZUL_INSTITUCIONAL, tamanho_texto=12,
    )
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
    _slide_acuracia_ponderada_detalhe(prs, mes_label, 6, dados)
    _slide_mapeamento_passivos(prs, mes_label, 7, dados)
    _slide_passivos_evolucao(prs, mes_label, 8, dados)
    _slide_shelf_life(prs, mes_label, 9, dados)
    _slide_controle_movimentados(prs, mes_label, 10, dados)
    _slide_fefo(prs, mes_label, 11, dados)
    _slide_proximos_passos(prs, mes_label, 12, dados)

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
