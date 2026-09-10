"""
Fechamento mensal do Stock Savvy (09/09/2026, pedido do usuário: "adicionar
ao MBR um modelo criado na outra ferramenta de controle contemplando as
principais ações e resultados do período [...] para substituir o resultado
da análise [...] para números reais obtidos e mapeados através da
implementação").

Extrai do .pptx nativo que o Stock Savvy exporta no fechamento de cada mês
(capa + Resumo Executivo do Período + Resultado Financeiro — Shelf Life +
5 rankings Top 10 por módulo + Mapeamento por Módulo + Destaques de Risco)
só o que o MBR precisa pro resumo executivo compacto que substitui a antiga
análise genérica "Atlas + Stock Savvy" (ver
mbr_generator._slide_fechamento_stock_savvy): os 4 KPIs do Resumo Executivo,
o ponto de atenção do mês, e os 4 KPIs financeiros de Shelf Life (com seus
sublabels de contexto). As tabelas Top 10 e o Mapeamento por Módulo não
entram nesta extração (usuário optou por resumo compacto, não pelo
relatório completo, em 09/09/2026) - ficam disponíveis pra uma extração
futura se o formato do MBR mudar.

Ao contrário dos dashboards HTML (dashboards_externos_extrator.py, que lêem
texto RENDERIZADO via BeautifulSoup), este é um .pptx nativo - lido direto
por shape com python-pptx.

Extração por CASAMENTO DE RÓTULO + shape numérico na mesma coluna (mesmo
`left`, com tolerância), não por índice fixo de shape: no próprio arquivo
de exemplo, a ordem já muda entre os dois slides (Resumo Executivo tem
rótulo ACIMA do valor; Resultado Financeiro tem valor ACIMA do rótulo, com
um sublabel de contexto embaixo) - fixar "valor = rótulo + 1 shape" quebraria
um dos dois. O casamento por coluna+proximidade é resistente a essa
diferença de ordem, mas ainda depende dos rótulos exatos que o Stock Savvy
usa hoje (_ROTULOS_* abaixo); se o Stock Savvy renomear um rótulo, aquele
card específico volta None (tratado no MBR como "—", sem quebrar os
outros nem a extração inteira).
"""
import io
import re

from pptx import Presentation

_TOLERANCIA_COLUNA_EMU = 50_000  # ~0.05in de folga pra considerar "mesma coluna"

_ROTULOS_RESUMO = [
    ("acoes_criadas", "AÇÕES CRIADAS"),
    ("concluidas", "CONCLUÍDAS"),
    ("em_aberto", "EM ABERTO"),
    ("aderencia_fefo", "ADERÊNCIA FEFO"),
]
_ROTULOS_FINANCEIRO_SHELF = [
    ("custo_estimado_perda", "Custo estimado de perda"),
    ("valor_recuperado_real", "Valor recuperado real"),
    ("lucro_operacional", "Lucro operacional"),
    ("roi_operacional", "ROI operacional"),
]

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


def _valor_na_coluna(shapes, rotulo_shape):
    candidatos = [
        s for s in shapes
        if s is not rotulo_shape
        and abs(s.left - rotulo_shape.left) <= _TOLERANCIA_COLUNA_EMU
        and _parece_numerico(s.text_frame.text)
    ]
    if not candidatos:
        return None
    return min(candidatos, key=lambda s: abs(s.top - rotulo_shape.top))


def _sublabel_na_coluna(shapes, rotulo_shape, valor_shape):
    """Sublabel/contexto (ex.: "Valor em risco nas ações") - texto NÃO
    numérico na mesma coluna, diferente do rótulo e do valor, mais perto do
    valor (no exemplo real, fica colado nele - acima ou abaixo, dependendo
    do slide)."""
    ancora = valor_shape or rotulo_shape
    candidatos = [
        s for s in shapes
        if s is not rotulo_shape and s is not valor_shape
        and abs(s.left - rotulo_shape.left) <= _TOLERANCIA_COLUNA_EMU
        and not _parece_numerico(s.text_frame.text)
    ]
    if not candidatos:
        return None
    return min(candidatos, key=lambda s: abs(s.top - ancora.top)).text_frame.text.strip()


def _extrair_cards(slide, rotulos, com_contexto: bool):
    """rotulos: lista de (chave, texto_do_rótulo). Devolve
    {chave: {"valor": str|None, "contexto": str|None}}.

    `com_contexto` liga a busca de sublabel só pros cards que REALMENTE têm
    uma 3ª linha no template de origem (Resultado Financeiro) - nos cards
    do Resumo Executivo (só rótulo + valor, sem 3ª linha), a busca por
    "texto não-numérico mais próximo na mesma coluna" pegava por engano o
    título do gráfico logo abaixo ("Concluídas x em aberto por módulo",
    mesma coluna x do 1º card) como se fosse contexto do card - achado ao
    testar contra o arquivo real de exemplo (09/09/2026)."""
    if slide is None:
        return {chave: {"valor": None, "contexto": None} for chave, _ in rotulos}
    shapes = _shapes_com_texto(slide)
    por_texto = {}
    for s in shapes:
        por_texto.setdefault(s.text_frame.text.strip(), s)
    resultado = {}
    for chave, texto_rotulo in rotulos:
        rotulo_shape = por_texto.get(texto_rotulo)
        if rotulo_shape is None:
            resultado[chave] = {"valor": None, "contexto": None}
            continue
        valor_shape = _valor_na_coluna(shapes, rotulo_shape)
        valor = valor_shape.text_frame.text.strip() if valor_shape else None
        contexto = _sublabel_na_coluna(shapes, rotulo_shape, valor_shape) if com_contexto else None
        resultado[chave] = {"valor": valor, "contexto": contexto}
    return resultado


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


def extrair_fechamento_stock_savvy(pptx_bytes: bytes) -> dict:
    """Devolve None se o arquivo não é um .pptx válido (corrompido/formato
    inesperado - tratado pelo chamador como erro de extração) ou se NENHUM
    dos 8 KPIs esperados foi encontrado (rótulos completamente diferentes -
    provavelmente não é um export do Stock Savvy). Um resultado parcial
    (alguns KPIs None, outros preenchidos) é devolvido normalmente - cada
    card mostra "—" individualmente no slide, sem invalidar o resto."""
    try:
        prs = Presentation(io.BytesIO(pptx_bytes))
    except Exception:
        return None

    slide_resumo = _slide_por_titulo(prs, "Resumo executivo do período")
    slide_financeiro = _slide_por_titulo(
        prs, "Resultado Financeiro — Shelf Life", "Resultado Financeiro - Shelf Life",
    )

    resumo = _extrair_cards(slide_resumo, _ROTULOS_RESUMO, com_contexto=False)
    financeiro = _extrair_cards(slide_financeiro, _ROTULOS_FINANCEIRO_SHELF, com_contexto=True)
    ponto_atencao = _ponto_atencao(slide_resumo)
    periodo = _periodo(prs)

    tem_algum_dado = any(v["valor"] for v in resumo.values()) or any(v["valor"] for v in financeiro.values())
    if not tem_algum_dado:
        return None

    return {
        "periodo": periodo,
        "resumo": resumo,
        "financeiro_shelf_life": financeiro,
        "ponto_atencao": ponto_atencao,
    }
