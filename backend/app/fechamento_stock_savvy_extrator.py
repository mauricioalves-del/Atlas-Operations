"""
Fechamento mensal do Stock Savvy (09/09/2026, pedido do usuário: "adicionar
ao MBR um modelo criado na outra ferramenta de controle contemplando as
principais ações e resultados do período [...] para substituir o resultado
da análise [...] para números reais obtidos e mapeados através da
implementação").

Extrai do .pptx nativo que o Stock Savvy exporta no fechamento de cada mês
(capa + Resumo Executivo do Período + Resultado Financeiro — Shelf Life +
5 rankings Top 10 por módulo + Mapeamento por Módulo + Destaques de Risco)
o que o MBR precisa pro resumo executivo que substitui a antiga análise
genérica "Atlas + Stock Savvy" (ver mbr_generator._slide_fechamento_stock_
savvy_panorama/_acoes): os KPIs do Resumo Executivo, o ponto de atenção
do mês, os KPIs financeiros de Shelf Life (com seus sublabels de
contexto), e as 5 maiores ações de cada categoria (Top 10 por módulo -
10/09/2026, pedido do usuário: o resumo só de KPIs "não conta a história
das atividades realizadas no período"). O Mapeamento por Módulo e
Destaques de Risco continuam fora desta extração - ficam disponíveis pra
uma extração futura se o formato do MBR mudar.

Ao contrário dos dashboards HTML (dashboards_externos_extrator.py, que lêem
texto RENDERIZADO via BeautifulSoup), este é um .pptx nativo - lido direto
por shape com python-pptx.

Extração por GEOMETRIA (15/09/2026, achado comparando os arquivos de
fechamento de agosto/2026 v7 e v8: o Stock Savvy renomeou os 4 rótulos do
slide financeiro entre um export e outro da MESMA ferramenta, na MESMA
semana - "Custo estimado de perda/Valor recuperado real/Lucro operacional/
ROI operacional" virou "Perda estimada/Perda real/Valor recuperado/Saving
recuperado", com a frase de contexto do slide também mudando. Casar por
TEXTO de rótulo fixo (como a versão anterior deste módulo fazia) quebra
toda vez que o Stock Savvy mexporta com um rótulo novo, mesmo que os dados
continuem lá). Em vez de casar por rótulo, agrupamos os shapes "estreitos"
(cartão de KPI, não título/subtítulo de largura cheia) em colunas por
proximidade horizontal (`left`, com tolerância) - o layout em grade de
colunas é estável mesmo quando o texto dos rótulos muda. Dentro de cada
coluna, o shape numérico é o "valor"; dos textos não numéricos restantes,
o mais próximo do valor é o "rótulo" e o segundo mais próximo (quando
existe) é o "contexto" - isso funciona tanto pro Resumo Executivo (rótulo
ACIMA do valor, sem contexto) quanto pro Resultado Financeiro (valor ACIMA
do rótulo, com contexto embaixo), sem precisar saber a ordem nem o texto
de nenhum rótulo. Cada card devolvido carrega o rótulo e o valor
EXATAMENTE como o Stock Savvy escreveu naquele mês - "traga exatamente os
mesmos dados do relatório gerado" (pedido do usuário, 15/09/2026).
"""
import io
import re

from pptx import Presentation

_TOLERANCIA_COLUNA_EMU = 50_000  # ~0.05in de folga pra considerar "mesma coluna"
_LARGURA_MAXIMA_CARTAO_EMU = 3_000_000  # ~3.28in - separa cartões de KPI (estreitos)
                                          # de títulos/subtítulos de largura cheia

_RE_TEM_DIGITO = re.compile(r"\d")
_RE_PERIODO = re.compile(r"^\d{2}/\d{2} a \d{2}/\d{2}/\d{4}$")


def _slide_por_titulo(prs, *candidatos):
    """Acha o primeiro slide cujo texto de algum shape bate (exato, após
    strip) com um dos títulos candidatos - não assume índice fixo de slide,
    só depende do título existir em algum lugar do template do Stock Savvy."""
    alvo = {c.strip() for c in candidatos}
    for slide in prs.slides:
        for shp in slide.shapes:
            if shp.has_text_frame and shp.text_frame.text.strip() in alvo:
                return slide
    return None


def _shapes_com_texto(slide):
    return [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]


def _parece_numerico(texto: str) -> bool:
    """True pra "361", "98,46%", "R$ 2.474,96", "0,96%" - False pra texto
    livre (rótulo, sublabel) mesmo que tenha algum dígito solto no meio."""
    t = texto.strip()
    if not t or not _RE_TEM_DIGITO.search(t):
        return False
    sobra = re.sub(r"[R$%\d.,\s \-–−]", "", t)
    return len(sobra) <= 2


def _colunas_de_shapes(shapes, tolerancia=_TOLERANCIA_COLUNA_EMU):
    """Agrupa shapes em colunas por proximidade horizontal (mesmo `left`,
    com tolerância) - independe de rótulo/texto, só da geometria do
    template do Stock Savvy (estável mês a mês, ao contrário do texto dos
    rótulos - ver docstring do módulo)."""
    ordenados = sorted(shapes, key=lambda s: s.left)
    colunas = []
    for s in ordenados:
        for coluna in colunas:
            if abs(coluna[0].left - s.left) <= tolerancia:
                coluna.append(s)
                break
        else:
            colunas.append([s])
    return colunas


def _cartao_da_coluna(coluna):
    """Acha o valor (numérico) e, entre os textos não numéricos, o mais
    próximo do valor vira rótulo e o segundo mais próximo vira contexto -
    funciona tanto pro padrão rótulo-acima-valor (Resumo) quanto
    valor-acima-rótulo-acima-contexto (Financeiro), sem depender do texto
    exato de nenhum rótulo. Devolve None se a coluna não tem nenhum valor
    numérico (não é um cartão de KPI de verdade)."""
    numericos = [s for s in coluna if _parece_numerico(s.text_frame.text)]
    if not numericos:
        return None
    valor_shape = numericos[0]
    nao_numericos = sorted(
        (s for s in coluna if s is not valor_shape and not _parece_numerico(s.text_frame.text)),
        key=lambda s: abs(s.top - valor_shape.top),
    )
    rotulo = nao_numericos[0].text_frame.text.strip() if nao_numericos else None
    contexto = nao_numericos[1].text_frame.text.strip() if len(nao_numericos) > 1 else None
    return {"rotulo": rotulo, "valor": valor_shape.text_frame.text.strip(), "contexto": contexto}


def _extrair_linha_cartoes(slide):
    """[{"rotulo","valor","contexto"}, ...] pra cada coluna de KPI
    encontrada no slide, na ordem esquerda->direita - substitui a extração
    por rótulo fixo: o layout em colunas do Stock Savvy é estável, mas o
    TEXTO dos rótulos já mudou de um mês pro outro (achado em 15/09/2026,
    comparando fechamento_2026-08_7.pptx vs _8.pptx). Shapes de largura
    cheia (título, subtítulo, caixa de atenção) são descartados antes de
    agrupar em colunas - só cartões de KPI (estreitos) entram."""
    if slide is None:
        return []
    shapes = [s for s in _shapes_com_texto(slide) if s.width <= _LARGURA_MAXIMA_CARTAO_EMU]
    colunas = _colunas_de_shapes(shapes)
    cartoes = []
    for coluna in colunas:
        cartao = _cartao_da_coluna(coluna)
        if cartao:
            cartoes.append(cartao)
    return cartoes


def _subtitulo(slide):
    """Frase de contexto de largura cheia logo abaixo do título (ex.: "33
    ações abertas no período — do risco estimado ao que foi realmente
    recuperado") - largura cheia (>_LARGURA_MAXIMA_CARTAO_EMU) e SEM dígito
    algum, pra não pegar o título em si nem confundir com um cartão. Só
    existe no slide financeiro hoje, mas a busca é genérica."""
    if slide is None:
        return None
    candidatos = [
        s for s in _shapes_com_texto(slide)
        if s.width > _LARGURA_MAXIMA_CARTAO_EMU and not _RE_TEM_DIGITO.search(s.text_frame.text)
    ]
    if not candidatos:
        return None
    # a mais próxima do topo, mas não a primeira (título) - pega a 2ª mais alta
    candidatos.sort(key=lambda s: s.top)
    return candidatos[1].text_frame.text.strip() if len(candidatos) > 1 else None


def _ponto_atencao(slide):
    if slide is None:
        return None
    for shp in _shapes_com_texto(slide):
        texto = shp.text_frame.text
        if texto.strip().startswith("Ponto de atenção do mês"):
            resto = texto.split("Ponto de atenção do mês", 1)[1].strip()
            return resto or None
    return None


def _periodo(prs):
    for slide in prs.slides:
        for shp in _shapes_com_texto(slide):
            if _RE_PERIODO.match(shp.text_frame.text.strip()):
                return shp.text_frame.text.strip()
    return None


# ---------------------------------------------------------------------------
# Top 5 ações por categoria (10/09/2026, pedido do usuário: o resumo
# compacto original (só os 8 KPIs) "está muito pobre... não conta a história
# das atividades realizadas no período" - adicionado por cima do resumo
# compacto, sem remover nada dele. Cada categoria do Stock Savvy exporta seu
# próprio slide "Top 10 — <categoria>" com uma tabela nativa (não HTML, não
# precisa de heurística de posição como os KPIs acima) - aqui só pegamos as
# 5 primeiras linhas de dado de cada tabela (o próprio Stock Savvy já as
# ordena por maior impacto - "ordenados por saving recuperado" etc - não
# reordenamos aqui).
#
# 15/09/2026, 2º rebuild (feedback do usuário sobre a 1ª versão, que reduzia
# cada categoria a 4 colunas genéricas #/Ação/Detalhe/Valor: "reenquadre as
# tabelas e traga todos os dados de colunas presentes no relatório. Bem
# detalhado"): a extração agora devolve a tabela INTEIRA de cada categoria
# (cabeçalho + linhas, com TODAS as colunas nativas, verbatim) em vez de
# reduzir/combinar colunas - o número de colunas varia por categoria (8 em
# Ações de Lote, 6 em Baixas Operacionais/Mapeamento de Testes, 4 em
# Dispersão de Lote/FEFO); cabe ao MBR (mbr_generator.py) desenhar cada
# tabela com a largura que ela precisar, não mais a esta extração decidir o
# que "conta a história" e o que é ruído.
# ---------------------------------------------------------------------------
# Ordem de exibição preferida (categorias com mais impacto/volume primeiro,
# pra contar a história do período do mais relevante pro menos) - qualquer
# categoria nova que o Stock Savvy vier a exportar no futuro (título "Top
# 10 — X" fora desta lista) ainda aparece, só que depois destas.
_ORDEM_CATEGORIAS_ACOES = [
    "Baixas Operacionais",
    "Dispersão de Lote (identificadas)",
    "Ações de Lote (Shelf Life)",
    "Mapeamento de Testes Operacionais",
    "Controle de FEFO",
]


def _tabela_do_slide(slide):
    for shp in slide.shapes:
        if shp.has_table:
            return shp.table
    return None


def _slides_top_acoes(prs):
    """[(categoria, slide), ...] pra cada slide "Top 10 — <categoria>"
    encontrado, na ordem em que aparecem no arquivo."""
    resultado = []
    for slide in prs.slides:
        for shp in _shapes_com_texto(slide):
            texto = shp.text_frame.text.strip()
            if texto.startswith("Top 10"):
                separador = "—" if "—" in texto else "-"
                categoria = texto.split(separador, 1)[1].strip() if separador in texto else texto
                resultado.append((categoria, slide))
                break
    return resultado


def _extrair_top5_categoria_completa(slide, maximo=5):
    """{"cabecalho": [...], "linhas": [[...], ...]} com TODAS as colunas
    nativas da tabela "Top 10" dessa categoria, verbatim - só as 5
    primeiras linhas de DADO de verdade (pula a linha "Total", que
    Mapeamento de Testes Operacionais tem, e qualquer linha malformada; uma
    linha de dado de verdade sempre começa com o número do ranking). None
    se a categoria não tiver tabela ou nenhuma linha válida."""
    tabela = _tabela_do_slide(slide)
    if tabela is None or len(tabela.rows) < 2:
        return None
    linhas_cruas = [[c.text.strip() for c in row.cells] for row in tabela.rows]
    cabecalho, linhas_dado = linhas_cruas[0], linhas_cruas[1:]
    linhas = []
    for linha in linhas_dado:
        if len(linhas) >= maximo:
            break
        if not linha or not linha[0].strip().isdigit():
            continue
        linhas.append(linha)
    if not linhas:
        return None
    return {"cabecalho": cabecalho, "linhas": linhas}


def _extrair_top_acoes(prs):
    """[{"categoria": str, "cabecalho": [...], "linhas": [[...], ...até 5]}, ...]
    só com categorias que realmente tinham pelo menos 1 linha de dado válida
    (uma categoria "Sem movimento" no período - ex.: Dispersão de Lote (ações
    corretivas) no arquivo de exemplo - nem gera o slide "Top 10", então já
    fica de fora naturalmente)."""
    encontrados = {}
    for categoria, slide in _slides_top_acoes(prs):
        tabela = _extrair_top5_categoria_completa(slide)
        if tabela:
            encontrados[categoria] = tabela
    resultado = []
    vistos = set()
    for categoria in _ORDEM_CATEGORIAS_ACOES:
        if categoria in encontrados:
            resultado.append({"categoria": categoria, **encontrados[categoria]})
            vistos.add(categoria)
    for categoria, tabela in encontrados.items():
        if categoria not in vistos:
            resultado.append({"categoria": categoria, **tabela})
    return resultado


# ---------------------------------------------------------------------------
# Mapeamento por Módulo (15/09/2026, pedido do usuário depois de ver a
# própria tela "Fechamento Mensal" do Stock Savvy - "o relatório anexado no
# atlas já tem os dados requisitados"): o gráfico "Concluídas x em aberto
# por módulo" (nativo, embutido no slide "Resumo executivo do período") e a
# tabela "Mapeamento por módulo" (slide próprio, 1 tabela nativa com
# Módulo/Criadas/Concluídas/Em Aberto/Valor-Qtd./Status) já vêm prontos no
# .pptx do Stock Savvy - a docstring do módulo já previa essa extração
# futura ("ficam disponíveis pra uma extração futura se o formato do MBR
# mudar"). Diferente dos cartões de KPI (texto solto por shape), o gráfico é
# um objeto CHART nativo do python-pptx (categorias + séries já
# estruturadas, sem heurística de posição) e a tabela é lida do mesmo jeito
# que as tabelas de Top 10 (_tabela_do_slide).
# ---------------------------------------------------------------------------
def _grafico_do_slide(slide):
    if slide is None:
        return None
    for shp in slide.shapes:
        if shp.has_chart:
            return shp.chart
    return None


def _extrair_grafico_modulo(prs):
    """{"categorias": [...], "series": {nome: [valores]}} a partir do
    PRIMEIRO gráfico nativo encontrado no arquivo (o Stock Savvy só embute
    um gráfico no .pptx de fechamento, no slide de Resumo Executivo) - {}
    se nenhum slide tiver um gráfico embutido (export mais antigo, sem esse
    recurso)."""
    for slide in prs.slides:
        chart = _grafico_do_slide(slide)
        if chart is None:
            continue
        try:
            plot = chart.plots[0]
            categorias = [str(c) for c in plot.categories]
            series = {serie.name: list(serie.values) for serie in plot.series}
        except Exception:
            return {}
        return {"categorias": categorias, "series": series}
    return {}


def _extrair_tabela_modulo(prs):
    """{"cabecalho": [...], "linhas": [[...], ...]} da tabela nativa do
    slide "Mapeamento por módulo" - None se o slide não existir (export
    mais antigo) ou não tiver tabela."""
    slide = _slide_por_titulo(prs, "Mapeamento por módulo", "Mapeamento por Módulo")
    if slide is None:
        return None
    tabela = _tabela_do_slide(slide)
    if tabela is None or len(tabela.rows) < 2:
        return None
    linhas_cruas = [[c.text.strip() for c in row.cells] for row in tabela.rows]
    return {"cabecalho": linhas_cruas[0], "linhas": linhas_cruas[1:]}


def _extrair_mapeamento_modulo(prs):
    grafico = _extrair_grafico_modulo(prs)
    tabela = _extrair_tabela_modulo(prs)
    if not grafico and not tabela:
        return None
    return {
        "categorias": grafico.get("categorias", []),
        "series": grafico.get("series", {}),
        "tabela": tabela,
    }


def extrair_fechamento_stock_savvy(pptx_bytes: bytes) -> dict:
    """Devolve None se o arquivo não é um .pptx válido (corrompido/formato
    inesperado - tratado pelo chamador como erro de extração) ou se NENHUM
    cartão de KPI foi encontrado em nenhum dos dois slides (layout
    completamente diferente - provavelmente não é um export do Stock
    Savvy). `resumo` e `financeiro_shelf_life` são listas de cartões (na
    ordem em que aparecem no slide, esquerda->direita) com o rótulo e o
    valor EXATAMENTE como o Stock Savvy escreveu naquele mês - não há mais
    chaves fixas (ex.: "acoes_criadas"), porque o texto dos rótulos já
    mudou de um export pro outro (15/09/2026)."""
    try:
        prs = Presentation(io.BytesIO(pptx_bytes))
    except Exception:
        return None

    slide_resumo = _slide_por_titulo(prs, "Resumo executivo do período")
    slide_financeiro = _slide_por_titulo(
        prs, "Resultado Financeiro — Shelf Life", "Resultado Financeiro - Shelf Life",
    )

    resumo = _extrair_linha_cartoes(slide_resumo)
    financeiro = _extrair_linha_cartoes(slide_financeiro)
    subtitulo_financeiro = _subtitulo(slide_financeiro)
    ponto_atencao = _ponto_atencao(slide_resumo)
    periodo = _periodo(prs)
    top_acoes = _extrair_top_acoes(prs)
    mapeamento_modulo = _extrair_mapeamento_modulo(prs)

    if not resumo and not financeiro:
        return None

    return {
        "periodo": periodo,
        "resumo": resumo,
        "financeiro_shelf_life": financeiro,
        "financeiro_subtitulo": subtitulo_financeiro,
        "ponto_atencao": ponto_atencao,
        "top_acoes": top_acoes,
        "mapeamento_modulo": mapeamento_modulo,
    }
