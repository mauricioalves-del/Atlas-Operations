"""Extração de dados reais dos dashboards HTML autocontidos que a equipe já
mantém em paralelo ao Atlas (ver app/routers/dashboards_externos_router.py) -
usada pelo MBR pra substituir números calculados pelo próprio Atlas por
números reais desses arquivos (pedido do usuário, 20/08/2026).

Duas famílias de arquivo, por como cada um foi construído:

1. Controle de FEFO e Controle de Testes Industriais - HTML simples com
   Chart.js e um array JS puro embutido (`const RAW=[...]` / `const DATA=[...]`),
   com data/mês por registro -> dá pra filtrar exato pelo mês de referência do
   MBR (`extrair_fefo`, `extrair_testes_industriais`).

2. Farol de Shelf-Life, Dashboard Shelf Life (Recuperação de Shelf) e Dashboard
   Baixas Operacionais - "fotos" estáticas exportadas de um app React/Recharts
   (rodapé de cada arquivo confirma: "Snapshot estático gerado pelo sistema
   Mágio - sem conexão com o banco de dados"). Não têm um "mês" limpo pra
   filtrar (Farol é o estoque agora, sem dimensão de mês nenhuma; os outros
   dois cobrem um período/janela que não é um mês calendário) - por decisão
   do usuário, esses três entram no MBR como retrato datado, com os números
   reais de KPIs e tabelas Top 10 do arquivo, rotulados com a data/período
   real da exportação (não fingem ser do mês específico do relatório). Os
   gráficos de evolução mensal desses três (renderizados como SVG/Recharts,
   sem os números crus em lugar nenhum do HTML) não são extraídos - só o
   conteúdo que já existe como texto/tabela HTML plana, que é a fonte
   confiável (ver `extrair_farol_shelf`, `extrair_recuperacao_shelf`,
   `extrair_baixas_operacionais_externo`).

3. Indicadores dinâmicos (18/08/2026) - qualquer indicador criado pelo admin
   além dos 5 acima (ver dashboards_externos_router.py, POST "") usa
   `extrair_generico`: só tabelas HTML reais + metadados de exportação, sem
   tentar adivinhar KPIs de um layout desconhecido (ver docstring da função).

4. Dispersão de Ficha Técnica ("Dispersão de Lote — Produção", 20/08/2026,
   pedido do usuário: "Adicione Dispersão de Ficha técnica na apresentação
   do MBR") - é um indicador dinâmico (cadastrado em Outros Dashboards >
   Adicionar Indicador), mas ganhou extrator e slide dedicados porque os
   KPIs dele (OPs analisadas, taxa de furo, perda/economia...) são
   renderizados no navegador a partir de um JSON embutido
   (`<script id="dados" type="application/json">`), não como HTML/tabela
   estática - `extrair_generico` não teria nada de confiável pra ler nesse
   arquivo (as tabelas de "Top 10 perda/economia" e "Detalhamento" também
   são preenchidas via JS, ficam vazias no HTML bruto). Tem "mês" limpo por
   registro (campo "mes", "YYYY-MM") - filtra exato pelo mês do MBR, igual
   a Controle de FEFO/Testes Industriais (`extrair_dispersao_ficha_tecnica`).

5. Fase 2 (22/08/2026, pedido do usuário: "Use os HTML anexados no atlas
   para alimentar o MBR igual foi feito aqui... siga com as alterações
   aprovadas") - os 3 gráficos que ficaram pendentes na Fase 1 (Risco de
   Perda por Almoxarifado e Custo Total por Grupo e Status do Farol de
   Shelf-Life; Evolução Mensal da Recuperação de Shelf; Evolução Mensal do
   Baixas Operacionais externo) SÃO extraídos agora, com dois métodos
   diferentes por caso:

   a) "Custo Total por Grupo e Status" não é gráfico SVG - é uma barra
      empilhada feita com <div> comuns, e cada segmento tem um atributo
      `title="Status: XX.XX%"` com o valor exato (ver `_extrair_custo_por_
      grupo_status`). Extração direta de texto, sem risco.

   b) Os outros 3 SÃO SVG puro (Recharts), sem tabela/JSON por trás, mas
      a geometria do SVG não é uma aproximação: o Recharts calcula a
      posição/altura de cada barra a partir do valor real por uma escala
      LINEAR exata, então a extração inverte essa mesma escala calibrando
      pelos próprios ticks do eixo numérico do gráfico (rótulo E posição em
      pixel, ambos no HTML) - ver `_extrair_barras_recharts`. Validado
      batendo a soma reconstruída contra um KPI em texto puro do mesmo
      arquivo (ex.: "Risco por Almoxarifado" bateu exatamente com "Perda
      potencial de R$ 87.224,19" em 3 arquivos reais diferentes - ver
      histórico de validação no MBR). Quando a soma reconstruída não bate
      com um KPI de referência disponível, a função de extração descarta o
      resultado (retorna None pro gráfico) em vez de mostrar um número não
      confiável.
"""
import re
import json
import calendar
from datetime import datetime

from bs4 import BeautifulSoup


def _parse_money_br(s):
    """'R$ 1.234,56' / '1.234,56' -> 1234.56"""
    if s is None:
        return None
    s = str(s).replace("R$", "").replace("\xa0", " ").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _soup_sem_svg(html):
    soup = BeautifulSoup(html, "html.parser")
    for svg in soup.find_all("svg"):
        svg.decompose()
    return soup


def _export_meta(soup):
    meta_el = soup.select_one(".export-meta")
    exportado_em = None
    if meta_el:
        exportado_em = meta_el.get_text(strip=True).replace("Exportado em ", "")
    chips = {}
    for c in soup.select(".export-chip"):
        texto = c.get_text(" ", strip=True)
        if ":" in texto:
            chave, valor = texto.split(":", 1)
            chips[chave.strip()] = valor.strip()
    return exportado_em, chips


# ---------------------------------------------------------------------------
# Fase 2 (22/08/2026) - reconstrução de gráficos SVG/Recharts + leitura da
# barra "Custo por Grupo e Status" (ver item 5 do docstring do módulo).
# ---------------------------------------------------------------------------
def _extrair_custo_por_grupo_status(soup):
    """"Custo Total por Grupo e Status" do Farol de Shelf-Life NÃO é gráfico -
    é uma lista de cartões com <div class="flex justify-between..."> (nome do
    grupo + custo total) seguido de uma barra empilhada feita com <div>s
    comuns, cada um com `title="Status: XX.XX%"` (ex.: title="Perigo: 19.64%")
    - valor exato, direto do atributo, sem depender de geometria de gráfico."""
    resultado = []
    for header in soup.select("div.flex.justify-between.gap-2.text-xs"):
        spans = header.find_all("span", recursive=False)
        if len(spans) != 2:
            continue
        nome_grupo = spans[0].get_text(strip=True)
        total = _parse_money_br(spans[1].get_text(strip=True))
        if not nome_grupo or total is None:
            continue
        barra = header.find_next_sibling("div")
        if not barra:
            continue
        segmentos = barra.select("div[title]")
        if not segmentos:
            continue
        por_status = {}
        for seg in segmentos:
            m = re.match(r"^(.+):\s*([\d.,]+)%$", (seg.get("title") or "").strip())
            if not m:
                continue
            status, pct_texto = m.group(1).strip().capitalize(), m.group(2).replace(",", ".")
            try:
                pct = float(pct_texto)
            except ValueError:
                continue
            por_status[status] = {"pct": pct, "valor": round(total * pct / 100, 2)}
        if por_status:
            resultado.append({"grupo": nome_grupo, "total": round(total, 2), "por_status": por_status})
    return resultado


def _parse_valor_eixo_compacto(texto):
    """Números de eixo Recharts: '0k'/'60k' (milhar sem decimal) ou
    'R$ 20.0Mil'/'R$100.0Mil' (milhar com 1 decimal) - formatador compacto
    que usa PONTO decimal, diferente do formato de dinheiro BR usado no
    resto do export (vírgula decimal, ex. 'R$ 7.742,70') - por isso tem
    parser próprio, não reaproveita `_parse_money_br`. Retorna
    (valor, tolerância) - tolerância é a metade da menor unidade que o
    rótulo consegue exibir (ex.: '60k' só exibe de 1000 em 1000 -> o valor
    real pode diferir do rótulo em até 500)."""
    if texto is None:
        return None
    t = str(texto).replace("R$", "").replace("\xa0", " ").strip()
    if not t:
        return None
    m = re.match(r"^(-?[\d.]+)\s*(mil|k|mi|m)?$", t, re.I)
    if not m:
        return None
    try:
        numero = float(m.group(1))
    except ValueError:
        return None
    sufixo = (m.group(2) or "").lower()
    mult = {"mil": 1000, "k": 1000, "mi": 1_000_000, "m": 1_000_000}.get(sufixo, 1)
    if sufixo and "." in m.group(1):
        tolerancia = mult / 20
    elif sufixo:
        tolerancia = mult / 2
    else:
        tolerancia = 0.5
    return numero * mult, tolerancia


def _calibrar_eixo_linear_recharts(pontos):
    """pontos: [(pixel, valor_rotulo, tolerancia), ...] de UM eixo. O Recharts
    usa escala linear EXATA (valor real -> pixel), mas o texto do tick
    arredonda pro formato compacto - em vez de mínimos-quadrados sobre esse
    texto arredondado (que falsearia a inclinação), calibra pelos 2 ticks
    com maior separação em pixel (menor erro relativo de arredondamento) e
    exige que TODOS os ticks do meio caiam dentro da tolerância de exibição
    de cada um. Se não caírem, o eixo não é linear (ou os rótulos não são
    confiáveis) e retorna None - nunca inventa uma inclinação aproximada."""
    if len(pontos) < 2:
        return None
    pts = sorted(pontos, key=lambda p: p[0])
    (px0, v0, _), (px1, v1, _) = pts[0], pts[-1]
    if px1 == px0:
        return None
    m = (v1 - v0) / (px1 - px0)
    b = v0 - m * px0
    for px, valor_rotulo, tolerancia in pts:
        if abs((m * px + b) - valor_rotulo) > tolerancia + 1e-6:
            return None
    return m, b


def _eixo_ticks_valor_recharts(svg, classe_eixo):
    g = svg.select_one(f"g.{classe_eixo}")
    if not g:
        return []
    pontos = []
    for tick in g.select("g.recharts-cartesian-axis-tick"):
        text_el = tick.find("text", class_="recharts-cartesian-axis-tick-value")
        line_el = tick.find("line")
        if not text_el or not line_el:
            continue
        parsed = _parse_valor_eixo_compacto(text_el.get_text(strip=True))
        if parsed is None:
            continue
        valor, tolerancia = parsed
        pixel = line_el.get("x1") if classe_eixo == "recharts-xAxis" else line_el.get("y1")
        if pixel is None:
            continue
        pontos.append((float(pixel), valor, tolerancia))
    return pontos


def _eixo_ticks_categoria_recharts(svg, classe_eixo):
    g = svg.select_one(f"g.{classe_eixo}")
    if not g:
        return []
    itens = []
    for tick in g.select("g.recharts-cartesian-axis-tick"):
        text_el = tick.find("text", class_="recharts-cartesian-axis-tick-value")
        line_el = tick.find("line")
        if not text_el or not line_el:
            continue
        rotulo = text_el.get_text(strip=True)
        pixel = line_el.get("x1") if classe_eixo == "recharts-xAxis" else line_el.get("y1")
        if pixel is None or not rotulo:
            continue
        itens.append((float(pixel), rotulo))
    return itens


def _e_grafico_recharts_real(svg):
    """Cada item de legenda do Recharts também é um mini <svg
    class="recharts-surface"> (só o quadradinho/bolinha de cor, 14x14) - sem
    filtrar isso, contar "quantos recharts-surface existem" pra saber se
    subiu demais na árvore (função abaixo) contaria ícone de legenda como
    gráfico."""
    return svg.select_one(
        ".recharts-cartesian-grid, .recharts-bar-rectangles, .recharts-line, "
        ".recharts-pie, .recharts-area"
    ) is not None


def _legenda_recharts_do_grafico(svg):
    """Sobe a árvore a partir do <svg> do gráfico até achar o container cujos
    descendentes incluem exatamente 1 gráfico real (o próprio) e ao menos
    1 legenda - evita pegar a legenda de OUTRO gráfico da mesma página
    quando dois cartões usam os mesmos rótulos de série (ex.: "Perda"/
    "Receita Recuperada"/"Saving Recuperado" aparece em mais de um gráfico
    do dashboard de Recuperação de Shelf)."""
    node = svg
    for _ in range(6):
        node = node.parent
        if node is None or getattr(node, "name", None) == "body":
            break
        surfaces = [s for s in node.select(".recharts-surface") if _e_grafico_recharts_real(s)]
        if len(surfaces) > 1:
            break
        itens = node.select(".recharts-legend-item")
        if itens:
            mapa = {}
            for li in itens:
                nome_el = li.select_one(".recharts-legend-item-text")
                icone = li.select_one(".recharts-legend-icon, .recharts-symbols")
                if nome_el and icone and icone.get("fill"):
                    mapa[icone.get("fill")] = nome_el.get_text(strip=True)
            if mapa:
                return mapa
    return {}


def _extrair_barras_recharts(svg):
    """Reconstrói os valores exatos de um gráfico de barras (agrupado ou
    empilhado, vertical ou horizontal) do Recharts a partir da geometria do
    SVG - ver item 5(b) do docstring do módulo pra explicação de por que
    isso NÃO é uma aproximação. Retorna None se não conseguir validar o
    eixo numérico como linear, ou se não achar barra/categoria nenhuma -
    nunca retorna um número em que não confia."""
    tks_x_num = _eixo_ticks_valor_recharts(svg, "recharts-xAxis")
    tks_y_num = _eixo_ticks_valor_recharts(svg, "recharts-yAxis")
    tks_x_cat = _eixo_ticks_categoria_recharts(svg, "recharts-xAxis")
    tks_y_cat = _eixo_ticks_categoria_recharts(svg, "recharts-yAxis")

    if len(tks_x_num) >= 2 and len(tks_x_num) == len(tks_x_cat) and tks_y_cat:
        eixo_valor_pontos, eixo_cat_itens, orientacao = tks_x_num, tks_y_cat, "horizontal"
    elif len(tks_y_num) >= 2 and len(tks_y_num) == len(tks_y_cat) and tks_x_cat:
        eixo_valor_pontos, eixo_cat_itens, orientacao = tks_y_num, tks_x_cat, "vertical"
    else:
        return None

    ajuste = _calibrar_eixo_linear_recharts(eixo_valor_pontos)
    if not ajuste:
        return None
    m, b = ajuste

    legenda = _legenda_recharts_do_grafico(svg)
    categorias_ordenadas = [rotulo for _, rotulo in sorted(eixo_cat_itens, key=lambda t: t[0])]
    posicoes_cat = sorted(p for p, _ in eixo_cat_itens)
    menor_espacamento = min(
        (posicoes_cat[i + 1] - posicoes_cat[i] for i in range(len(posicoes_cat) - 1)), default=1e9
    )
    tolerancia_categoria = menor_espacamento / 2 if menor_espacamento < 1e9 else 1e9

    bars = svg.select(".recharts-bar-rectangle path, .recharts-bar-rectangle rect")
    if not bars:
        return None

    series: dict = {}
    for bar in bars:
        try:
            x, y = float(bar.get("x")), float(bar.get("y"))
            w, h = float(bar.get("width")), float(bar.get("height"))
        except (TypeError, ValueError):
            continue
        if orientacao == "vertical":
            centro_cat, valor = x + w / 2, h * abs(m)
        else:
            centro_cat, valor = y + h / 2, w * abs(m)
        cat_mais_proxima = min(eixo_cat_itens, key=lambda t: abs(t[0] - centro_cat))
        if abs(cat_mais_proxima[0] - centro_cat) > tolerancia_categoria:
            continue  # barra não bateu com nenhuma categoria com confiança - ignora, não adivinha
        rotulo_cat = cat_mais_proxima[1]

        nome_serie = bar.get("name") or legenda.get(bar.get("fill")) or "valor"
        series.setdefault(nome_serie, {})
        series[nome_serie][rotulo_cat] = series[nome_serie].get(rotulo_cat, 0.0) + valor

    totais = {}
    for por_cat in series.values():
        for cat, val in por_cat.items():
            totais[cat] = totais.get(cat, 0.0) + val

    return {
        "categorias": categorias_ordenadas,
        "series": {nome: {c: round(v, 2) for c, v in por_cat.items()} for nome, por_cat in series.items()},
        "totais": {c: round(v, 2) for c, v in totais.items()},
    }


def _achar_grafico_por_categorias(soup, checador_categoria):
    """Acha, entre todos os gráficos Recharts da página, o primeiro cujo
    eixo de categorias bate com `checador_categoria` (ex.: nomes de
    almoxarifado, ou meses) - mais robusto que confiar na ORDEM em que os
    gráficos aparecem no HTML (pode variar entre versões do export)."""
    for svg in soup.find_all("svg"):
        if "recharts-surface" not in (svg.get("class") or []) or not _e_grafico_recharts_real(svg):
            continue
        for classe in ("recharts-xAxis", "recharts-yAxis"):
            cats = _eixo_ticks_categoria_recharts(svg, classe)
            rotulos = [r for _, r in cats]
            if rotulos and checador_categoria(rotulos):
                return svg
    return None


_MESES_PT = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro")


def _parecem_almoxarifados(rotulos):
    return sum(1 for r in rotulos if r.startswith("Alm")) >= max(2, len(rotulos) - 1)


def _parecem_meses_longos(rotulos):
    return sum(1 for r in rotulos if r.strip().lower() in _MESES_PT) >= max(2, len(rotulos) - 1)


def _parecem_meses_abreviados(rotulos):
    return sum(1 for r in rotulos if re.match(r"^[a-zç]{3}/\d{2}$", r.strip(), re.I)) >= max(2, len(rotulos) - 1)


# ---------------------------------------------------------------------------
# 1. Controle de FEFO - const RAW=[...], filtrável por mês (campo "data")
# ---------------------------------------------------------------------------
def extrair_fefo(html_content: str, mes: str) -> dict:
    """mes: 'YYYY-MM'. Cada registro é uma transferência com origem na Fábrica,
    já classificada (categoria: 'ok'/'warn'/'quebra') pela própria equipe a
    partir dos arquivos de auditoria reais - substitui o cálculo do Atlas
    (que comparava contra o estoque de lote ATUAL, não uma leitura no
    momento da transferência)."""
    m = re.search(r"const RAW\s*=\s*(\[.*?\]);", html_content, re.S)
    if not m:
        return None
    dados = json.loads(m.group(1))
    ano, mes_num = (int(x) for x in mes.split("-"))

    do_mes = []
    for d in dados:
        try:
            dt = datetime.strptime(d["data"], "%d/%m/%Y")
        except (KeyError, ValueError):
            continue
        if dt.year == ano and dt.month == mes_num:
            do_mes.append(d)

    if not do_mes:
        return {"tem_dados": False, "mes": mes}

    total = len(do_mes)
    quebras = [d for d in do_mes if d.get("categoria") == "quebra"]
    inconclusivos = [d for d in do_mes if d.get("categoria") == "warn"]

    contagem_produto = {}
    for d in quebras:
        k = d.get("descricao") or "—"
        contagem_produto[k] = contagem_produto.get(k, 0) + 1
    top_produtos = sorted(contagem_produto.items(), key=lambda x: -x[1])[:8]

    dest = {}
    for d in do_mes:
        k = d.get("destino") or "—"
        dest.setdefault(k, {"total": 0, "quebras": 0})
        dest[k]["total"] += 1
        if d.get("categoria") == "quebra":
            dest[k]["quebras"] += 1
    por_destino = [
        {"destino": k, "total": v["total"], "quebras": v["quebras"],
         "taxa_pct": (v["quebras"] / v["total"] * 100 if v["total"] else 0)}
        for k, v in dest.items()
    ]
    por_destino.sort(key=lambda x: -x["quebras"])

    return {
        "tem_dados": True,
        "mes": mes,
        "total_transferencias": total,
        "quebras": len(quebras),
        "inconclusivos": len(inconclusivos),
        "taxa_quebra_pct": (len(quebras) / total * 100) if total else None,
        "top_produtos_quebra": [{"produto": p, "qtd": q} for p, q in top_produtos],
        "por_destino": por_destino[:6],
    }


# ---------------------------------------------------------------------------
# 2. Controle de Testes Industriais - Custo de Inovação (02/09/2026: layout do
#    export mudou - saiu do `const DATA=[...]` original e passou a usar o
#    mesmo padrão de JSON embutido em <script id="dados" type="application/
#    json"> de Dispersão de Ficha Técnica, com o campo de mês chamado
#    "ano_mes" (já em "YYYY-MM", compara direto com o `mes` do MBR - sem
#    conversão). Também trouxe dois campos novos por registro que o formato
#    antigo não tinha: "grupo" (Matéria Prima / Produto em Processo /
#    Embalagem / Sem grupo) e "sem_custo" ("OK" / "Sem custo").
#
#    Decisão do usuário (02/09/2026, respondendo pergunta de esclarecimento
#    sobre a nova lógica de formação do indicador):
#    - itens com sem_custo == "Sem custo" são EXCLUÍDOS do Gasto Total, do
#      Custo Médio por OP e do ranking de matérias-primas (custo zerado/
#      ausente distorceria esses números) - mas o extrator ainda conta
#      quantos foram excluídos (`itens_sem_custo`) pra o slide avisar, em vez
#      de simplesmente sumir com esses itens sem explicação.
#    - Embalagem continua incluída no cálculo normalmente - só sem_custo é
#      motivo de exclusão, nenhum grupo é filtrado.
# ---------------------------------------------------------------------------
def extrair_testes_industriais(html_content: str, mes: str) -> dict:
    """mes: 'YYYY-MM'. Ver decisão de formação do indicador no comentário
    acima do módulo, seção 2."""
    m = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html_content, re.S)
    if not m:
        return None
    try:
        dados = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    linhas = dados.get("linhas") or []

    do_mes = [r for r in linhas if r.get("ano_mes") == mes]
    if not do_mes:
        return {"tem_dados": False, "mes": mes}

    com_custo = [r for r in do_mes if r.get("sem_custo") != "Sem custo"]
    itens_sem_custo = len(do_mes) - len(com_custo)

    gasto_total = sum(r.get("custo", 0) or 0 for r in com_custo)
    ops = sorted(set(r.get("numero_op") for r in com_custo if r.get("numero_op")))

    agg = {}
    for r in com_custo:
        k = r.get("desc_material") or r.get("material") or "—"
        agg.setdefault(k, {"custo": 0.0, "qtd": 0.0, "um": r.get("um")})
        agg[k]["custo"] += r.get("custo", 0) or 0
        agg[k]["qtd"] += r.get("qtd", 0) or 0
    top = sorted(agg.items(), key=lambda x: -x[1]["custo"])[:8]

    return {
        "tem_dados": True,
        "mes": mes,
        "total_itens": len(com_custo),
        "gasto_total": round(gasto_total, 2),
        "ops": len(ops),
        "custo_medio_op": round(gasto_total / len(ops), 2) if ops else 0,
        "top_materias_primas": [
            {"nome": k, "custo": round(v["custo"], 2), "qtd": round(v["qtd"], 4), "um": v["um"]}
            for k, v in top
        ],
        "itens_sem_custo": itens_sem_custo,
    }


# ---------------------------------------------------------------------------
# 8. Constância e Disciplina — Diário de Bordo (02/09/2026, pedido do
#    usuário: "Agora o HTML do diario de bordo passa a alimentar o indicador
#    de performance e cumprimento de rotina") - export estático do Dashboard
#    de Performance da Rotina Master (rotinabusiness.lovable.app), pra
#    substituir a coleta 100% manual que alimentava _DIARIO_BORDO_POR_MES em
#    mbr_generator.py.
#
#    Igual ao item 2 do docstring do módulo (Farol/Recuperação/Baixas): é uma
#    "foto" estática de um app React/Recharts, SEM script/JSON com o dataset
#    cru embutido (confirmado: 0 <script> e 0 <iframe> no arquivo) - só dá
#    pra extrair com segurança o que já está como TEXTO plano no HTML (os 4
#    cartões de KPI no topo). O gráfico "% de atingimento diário das
#    rotinas" É um SVG Recharts (barras por dia), mas diferente dos casos já
#    resolvidos com `_extrair_barras_recharts` (Farol/Recuperação/Baixas),
#    aqui só 16 dos 31 dias do mês têm rótulo no eixo X (Recharts pula tick
#    alternado) - metade das barras cairia perto ou na fronteira de
#    tolerância entre duas datas rotuladas, com risco real de atribuir um
#    valor ao dia errado. Por isso este extrator NÃO tenta reconstruir
#    sequência/lapsos por dia útil nem quebra semanal (campos
#    maior_sequencia_dias_uteis_100/lapsos_dias_uteis/semanas simplesmente
#    não aparecem no retorno) - só os KPIs de topo, que são texto exato, sem
#    geometria envolvida. _slide_diario_bordo trata a ausência desses campos
#    mostrando uma versão mais enxuta do slide (ver lá).
#
#    O período coberto pelo export vem do <meta name="description"> do HTML
#    ("... (DD/MM/AA a DD/MM/AA).") - só usa o dado se esse período for
#    exatamente um mês calendário completo (dia 1 ao último dia, mesmo
#    mês/ano) E esse mês bater com o `mes` pedido; caso contrário devolve
#    "tem_dados": False em vez de arriscar atribuir a um mês errado (mesmo
#    critério de "nunca inventa" usado no resto do módulo).
# ---------------------------------------------------------------------------
def extrair_diario_bordo(html_content: str, mes: str) -> dict:
    """mes: 'YYYY-MM'. Ver decisão de escopo (só KPIs de topo) no comentário
    acima do módulo, seção 8."""
    m_periodo = re.search(
        r'<meta name="description" content="[^"]*\((\d{2})/(\d{2})/(\d{2}) a (\d{2})/(\d{2})/(\d{2})\)',
        html_content,
    )
    if not m_periodo:
        return None
    d1, m1, a1, d2, m2, a2 = m_periodo.groups()
    try:
        inicio = datetime.strptime(f"{d1}/{m1}/{a1}", "%d/%m/%y")
        fim = datetime.strptime(f"{d2}/{m2}/{a2}", "%d/%m/%y")
    except ValueError:
        return None

    m_cumprimento = re.search(
        r'Cumprimento geral</div></div>'
        r'<div class="[^"]*">(\d+(?:[.,]\d+)?)%</div>'
        r'<div class="[^"]*">(\d+)\s+de\s+(\d+)\s+rotinas</div>',
        html_content,
    )
    m_conclusoes = re.search(
        r'Conclusões no período</div></div>.*?'
        r'font-bold text-success">(\d+(?:[.,]\d+)?)%</div>.*?'
        r'font-bold text-destructive">(\d+(?:[.,]\d+)?)%</div>',
        html_content, re.S,
    )
    m_colaboradores = re.search(
        r'Colaboradores no recorte</div></div>'
        r'<div class="[^"]*">(\d+)</div>',
        html_content,
    )
    m_metas = re.search(
        r'Atingimento médio de metas</div></div>'
        r'<div class="[^"]*">(\d+(?:[.,]\d+)?)%</div>',
        html_content,
    )
    if not m_cumprimento:
        return None  # layout inesperado - não tem o KPI principal, não vale a pena tentar montar o resto

    ultimo_dia_mes = calendar.monthrange(inicio.year, inicio.month)[1]
    cobre_mes_calendario_completo = (
        inicio.day == 1 and fim.day == ultimo_dia_mes and inicio.month == fim.month and inicio.year == fim.year
    )
    mes_periodo = f"{inicio.year:04d}-{inicio.month:02d}" if cobre_mes_calendario_completo else None
    if mes_periodo != mes:
        return {"tem_dados": False, "mes": mes}

    resultado = {
        "tem_dados": True,
        "mes": mes,
        "cumprimento_geral_pct": float(m_cumprimento.group(1).replace(",", ".")),
        "rotinas_cumpridas": int(m_cumprimento.group(2)),
        "rotinas_devidas": int(m_cumprimento.group(3)),
        "periodo": f"{d1}/{m1}/{a1} a {d2}/{m2}/{a2}",
    }
    if m_conclusoes:
        resultado["pct_no_prazo"] = float(m_conclusoes.group(1).replace(",", "."))
        resultado["pct_em_atraso"] = float(m_conclusoes.group(2).replace(",", "."))
    if m_colaboradores:
        resultado["colaboradores_no_recorte"] = int(m_colaboradores.group(1))
    if m_metas:
        resultado["atingimento_medio_metas_pct"] = float(m_metas.group(1).replace(",", "."))
    return resultado


# ---------------------------------------------------------------------------
# 3. Farol de Shelf-Life - snapshot estático (sem dimensão de mês)
# ---------------------------------------------------------------------------
def extrair_farol_shelf(html_content: str) -> dict:
    soup = _soup_sem_svg(html_content)
    exportado_em, filtros = _export_meta(soup)
    txt = soup.get_text(" ", strip=True)

    m = re.search(r"Perda potencial de\s*R\$\s*([\d.,]+)\s*·\s*Sendo\s*R\$\s*([\d.,]+)\s*já vencidos", txt)
    perda_potencial_total = _parse_money_br(m.group(1)) if m else None
    perda_ja_vencida = _parse_money_br(m.group(2)) if m else None

    qtd_lotes = {}
    for chave, label in [("vencidos", "Qtd Vencidos"), ("0_30", "Qtd 0-30 dias"),
                          ("31_60", "Qtd 31-60 dias"), ("61_90", "Qtd 61-90 dias")]:
        mm = re.search(r"(\d+)\s*" + re.escape(label), txt)
        qtd_lotes[chave] = int(mm.group(1)) if mm else None

    buckets = []
    for t in soup.find_all("table"):
        titulo_el = t.find_previous(string=re.compile(r"Top 10"))
        titulo = titulo_el.strip() if titulo_el else None
        linhas = []
        total_linha = None
        for r in t.find_all("tr")[1:]:
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if len(cols) < 4:
                continue
            if cols[1].lower().startswith("total"):
                total_linha = {"descricao": cols[1], "custo": _parse_money_br(cols[2])}
                continue
            linhas.append({"rank": cols[0], "descricao": cols[1], "custo": _parse_money_br(cols[2]), "pct": cols[3]})
        buckets.append({"titulo": titulo, "itens": linhas, "total": total_linha})

    # Fase 2 (22/08/2026): "Custo Total por Grupo e Status" é lido do MESMO
    # soup sem svg (é <div> comum, não gráfico) - "Risco de Perda por
    # Almoxarifado" precisa do soup COM svg (é Recharts puro), por isso um
    # parse separado do html original só pra esse gráfico.
    custo_por_grupo_status = _extrair_custo_por_grupo_status(soup) or None

    risco_por_almoxarifado = None
    soup_com_svg = BeautifulSoup(html_content, "html.parser")
    grafico_almox = _achar_grafico_por_categorias(soup_com_svg, _parecem_almoxarifados)
    if grafico_almox is not None:
        extraido = _extrair_barras_recharts(grafico_almox)
        if extraido:
            soma = sum(extraido["totais"].values())
            # valida contra o KPI de texto (mesmo dado, pivotado diferente) -
            # só aceita se bater dentro de uma tolerância pequena; se não
            # bater, descarta em vez de mostrar um número não confiável.
            if perda_potencial_total is None or abs(soma - perda_potencial_total) <= max(1.0, perda_potencial_total * 0.01):
                risco_por_almoxarifado = extraido

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "perda_potencial_total": perda_potencial_total,
        "perda_ja_vencida": perda_ja_vencida,
        "qtd_lotes": qtd_lotes,
        "buckets": buckets,
        "custo_por_grupo_status": custo_por_grupo_status,
        "risco_por_almoxarifado": risco_por_almoxarifado,
    }


# ---------------------------------------------------------------------------
# 4. Dashboard Shelf Life ("Recuperação de Shelf") - snapshot de período
#    (Jan-Ago/26 no exemplo, não um mês calendário isolado)
# ---------------------------------------------------------------------------
def extrair_recuperacao_shelf(html_content: str) -> dict:
    soup = _soup_sem_svg(html_content)
    exportado_em, filtros = _export_meta(soup)
    txt = soup.get_text("|", strip=True)

    kpis = {}
    for chave, label in [
        ("receita_recuperada", "Receita Recuperada"),
        ("perda_evitada", "Perda Evitada"),
        ("perda_real", "Perda Real"),
        ("saving_recuperado", "Saving Recuperado"),
    ]:
        mm = re.search(re.escape(label) + r"\|R\$\s*([\d.,]+)", txt)
        kpis[chave] = _parse_money_br(mm.group(1)) if mm else None
    mm_roi = re.search(r"ROI Operacional\|([\d.,]+)%", txt)
    kpis["roi_operacional_pct"] = float(mm_roi.group(1).replace(",", ".")) if mm_roi else None

    tabelas = {}
    for t in soup.find_all("table"):
        titulo_el = t.find_previous(string=re.compile(r"Top 10"))
        titulo = titulo_el.strip() if titulo_el else f"tabela_{len(tabelas)}"
        cabecalho = [c.get_text(strip=True) for c in t.find_all("tr")[0].find_all(["th", "td"])]
        linhas = []
        for r in t.find_all("tr")[1:]:
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if cols:
                linhas.append(cols)
        tabelas[titulo] = {"cabecalho": cabecalho, "linhas": linhas[:8]}

    # Fase 2 (22/08/2026): gráfico "Evolução Mensal" (Perda × Receita
    # Recuperada × Saving Recuperado por mês) - Recharts puro, precisa do
    # soup COM svg. Valida a série "Perda" (sempre presente em todos os
    # meses no export real) contra o KPI "Perda Real"; "Saving Recuperado"
    # legitimamente pode não bater (o próprio mockup aprovado já destacava
    # esse gráfico "a partir de abril", quando o controle passou a atuar
    # sobre a recuperação - meses antes disso não têm ação de saving, então
    # a soma do gráfico é menor que o total do período por desenho, não por
    # erro de extração).
    evolucao_mensal = None
    soup_com_svg = BeautifulSoup(html_content, "html.parser")
    grafico_evolucao = _achar_grafico_por_categorias(soup_com_svg, _parecem_meses_abreviados)
    if grafico_evolucao is not None:
        extraido = _extrair_barras_recharts(grafico_evolucao)
        if extraido:
            soma_perda = sum(extraido["series"].get("Perda", {}).values())
            perda_real = kpis.get("perda_real")
            if perda_real is None or "Perda" not in extraido["series"] or abs(soma_perda - perda_real) <= max(1.0, perda_real * 0.01):
                evolucao_mensal = extraido

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "kpis": kpis,
        "tabelas": tabelas,
        "evolucao_mensal": evolucao_mensal,
    }


# ---------------------------------------------------------------------------
# 5. Dashboard Baixas Operacionais (externo) - snapshot de janela móvel
#    (últimos ~60 dias no exemplo, controle paralelo ao módulo nativo do Atlas)
# ---------------------------------------------------------------------------
def extrair_baixas_operacionais_externo(html_content: str) -> dict:
    soup = _soup_sem_svg(html_content)
    exportado_em, filtros = _export_meta(soup)
    txt = soup.get_text("|", strip=True)

    m = re.search(
        r"Prejuízo total de\|R\$\s*([\d.,]+)\|no período\.\|([\d.,]+)%\|concentrado em\|([^|]+)\|"
        r"\. Maior impacto no setor:\|([^|]+)\|e grupo:\|([^|]+)",
        txt,
    )
    resumo = None
    if m:
        resumo = {
            "prejuizo_total": _parse_money_br(m.group(1)),
            "pct_concentrado": float(m.group(2).replace(",", ".")),
            "motivo_concentrado": m.group(3).strip(),
            "setor_maior_impacto": m.group(4).strip(),
            "grupo_maior_impacto": m.group(5).strip(),
        }

    tabelas = {}
    for t in soup.find_all("table"):
        titulo_el = t.find_previous(string=re.compile(r"Ranking|Baixas por"))
        titulo = titulo_el.strip() if titulo_el else f"tabela_{len(tabelas)}"
        cabecalho = [c.get_text(strip=True) for c in t.find_all("tr")[0].find_all(["th", "td"])]
        linhas = []
        for r in t.find_all("tr")[1:]:
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if cols:
                linhas.append(cols)
        tabelas[titulo] = {"cabecalho": cabecalho, "linhas": linhas[:8]}

    # Fase 2 (22/08/2026): gráfico "Total de Baixas por Mês" - Recharts puro,
    # precisa do soup COM svg. Cobre o histórico mensal completo do export
    # (ex.: janeiro-agosto), uma janela BEM mais longa que o "Prejuízo Total
    # no Período" do resumo acima (janela móvel curta, ex. últimos ~60 dias)
    # - por desenho os dois números não batem entre si, então não valida um
    # contra o outro (ver nota no slide, pra não parecer inconsistência).
    evolucao_mensal = None
    soup_com_svg = BeautifulSoup(html_content, "html.parser")
    grafico_evolucao = _achar_grafico_por_categorias(soup_com_svg, _parecem_meses_longos)
    if grafico_evolucao is not None:
        evolucao_mensal = _extrair_barras_recharts(grafico_evolucao)

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "resumo": resumo,
        "tabelas": tabelas,
        "evolucao_mensal": evolucao_mensal,
    }


# ---------------------------------------------------------------------------
# 6. Extração genérica - indicadores dinâmicos criados pelo admin (pedido do
#    usuário, 18/08/2026: "adicione a opção de adicionar mais indicadores e
#    adicionar automaticamente na construção do MBR" - ver
#    dashboards_externos_router.py, POST ""). Um indicador novo não tem
#    extrator sob medida como os 5 acima, então usa este: só o que dá pra
#    ler com CONFIANÇA de qualquer HTML, sem depender de classe CSS ou texto
#    específico de um layout de exportação conhecido - as tabelas <table>
#    reais do arquivo (com o heading/negrito mais próximo antes de cada uma
#    como título) e os metadados de exportação (.export-meta/.export-chip),
#    se existirem. NÃO tenta adivinhar "KPIs" a partir de cards/divs
#    estilizados: os 3 exports React/Recharts acima já mostram que o mesmo
#    tipo de card usa classes Tailwind DIFERENTES entre arquivos (farol/
#    recuperação vs. baixas operacionais) - um seletor genérico teria alta
#    chance de não achar nada OU achar um número errado com cara de KPI
#    real, o que é pior do que simplesmente não mostrar nada.
# ---------------------------------------------------------------------------
def extrair_generico(html_content: str) -> dict:
    soup = _soup_sem_svg(html_content)
    exportado_em, filtros = _export_meta(soup)

    titulo = None
    for nivel in ("h1", "h2"):
        el = soup.find(nivel)
        if el and el.get_text(strip=True):
            titulo = el.get_text(strip=True)
            break

    tabelas = []
    for t in soup.find_all("table"):
        linhas_tr = t.find_all("tr")
        if not linhas_tr:
            continue
        cabecalho = [c.get_text(" ", strip=True) for c in linhas_tr[0].find_all(["th", "td"])]
        linhas = []
        for r in linhas_tr[1:]:
            cols = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
            if cols:
                linhas.append(cols)
        if not linhas:
            continue  # tabela sem linha de dado (só cabeçalho, ou vazia) - não vale a pena mostrar
        titulo_el = t.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "b", "strong"])
        titulo_tabela = (titulo_el.get_text(strip=True) if titulo_el else "") or f"Tabela {len(tabelas) + 1}"
        tabelas.append({"titulo": titulo_tabela[:60], "cabecalho": cabecalho, "linhas": linhas[:10]})

    if not tabelas and not titulo and not filtros:
        return None  # nada de confiável pra extrair - vira "erro_extracao" no chamador

    return {
        "titulo": titulo,
        "exportado_em": exportado_em,
        "filtros": filtros,
        # até 4 tabelas por slide - o suficiente sem virar sopa de letra numa
        # única página do MBR.
        "tabelas": tabelas[:4],
    }


# ---------------------------------------------------------------------------
# 7. Dispersão de Ficha Técnica ("Dispersão de Lote — Produção") - Ficha
#    Técnica (BOM) × Consumo real por Ordem de Produção. Todo o conteúdo
#    visível (KPIs, gráficos, tabelas) é renderizado no navegador a partir
#    de um único JSON embutido - reproduz aqui em Python a mesma agregação
#    que o próprio arquivo faz em JS (funções renderKpis/agregarMatriz do
#    export), pra chegar nos mesmos números sem precisar de navegador.
# ---------------------------------------------------------------------------
def extrair_dispersao_ficha_tecnica(html_content: str, mes: str) -> dict:
    """mes: 'YYYY-MM'. Cada registro em `linhas` é um par OP + material
    consumido (com o previsto pela Ficha Técnica, o consumo real, e o
    impacto financeiro já calculado pelo próprio export: positivo = perda,
    negativo = economia). `tem_furo` marca se aquele material daquela OP
    saiu do critério de tolerância do export."""
    m = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html_content, re.S)
    if not m:
        return None
    try:
        dados = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    linhas = dados.get("linhas") or []
    lim_freq = dados.get("limFreq", 5)

    # Tendência Financeira mês a mês (22/08/2026, pedido do usuário: "adicione
    # rótulo de dados no indicador de Dispersão de Ficha Técnica" - a
    # simulação HTML aprovada tinha um gráfico de evolução de Perda/Economia/
    # Impacto Líquido por mês, não só a foto do mês do relatório). Diferente
    # dos outros 3 dashboards externos (Farol/Recuperação/Baixas), este export
    # tem o dataset completo num único JSON embutido (`linhas`, com "mes" por
    # registro) - dá pra agregar por mês em Python com exatidão, sem precisar
    # reconstruir nada a partir de geometria de gráfico SVG. Só até o mês do
    # relatório (nunca vaza mês posterior, mesmo bug de 22/08/2026 corrigido
    # em _truncar_serie_mensal no mbr_generator - aqui filtra na origem porque
    # o "mes" de corte já é um parâmetro desta função).
    por_mes: dict = {}
    for r in linhas:
        mes_r = r.get("mes")
        if not mes_r or mes_r > mes:
            continue
        c = por_mes.setdefault(mes_r, {"perda": 0.0, "economia": 0.0})
        impacto_mes = r.get("impacto") or 0
        if impacto_mes > 0:
            c["perda"] += impacto_mes
        else:
            c["economia"] += -impacto_mes
    evolucao_mensal = [
        {
            "mes": mes_r,
            "perda": round(v["perda"], 2),
            "economia": round(v["economia"], 2),
            "impacto_liquido": round(v["perda"] - v["economia"], 2),
        }
        for mes_r, v in sorted(por_mes.items())
    ]

    do_mes = [r for r in linhas if r.get("mes") == mes]
    if not do_mes:
        return {"tem_dados": False, "mes": mes, "evolucao_mensal": evolucao_mensal}

    ops, ops_com_furo, ops_criticas = set(), set(), set()
    perda, economia = 0.0, 0.0
    for r in do_mes:
        id_op = r.get("id_op")
        ops.add(id_op)
        if r.get("tem_furo"):
            ops_com_furo.add(id_op)
        impacto = r.get("impacto") or 0
        if impacto > 0:
            perda += impacto
        else:
            economia += -impacto
        if r.get("cls") == "CRITICO":
            ops_criticas.add(id_op)

    # Matriz de criticidade por material (só materiais com furo em ao menos
    # uma OP no mês) - mesma base usada pros Top 10 de perda/economia e pra
    # "Concentração Top 20" (quanto do impacto absoluto total está nos 20
    # materiais de maior impacto, positivo ou negativo).
    materiais: dict[str, dict] = {}
    for r in do_mes:
        if not r.get("tem_furo"):
            continue
        chave_material = r.get("material") or "—"
        c = materiais.setdefault(chave_material, {
            "material": chave_material,
            "desc": r.get("desc_material") or chave_material,
            "ops": set(), "liq": 0.0, "abs": 0.0,
        })
        c["ops"].add(r.get("id_op"))
        impacto = r.get("impacto") or 0
        c["liq"] += impacto
        c["abs"] += abs(impacto)

    matriz = [
        {"material": c["material"], "desc": c["desc"], "freq": len(c["ops"]), "liq": c["liq"], "abs": c["abs"]}
        for c in materiais.values()
    ]
    matriz.sort(key=lambda x: -x["abs"])

    total_abs = sum(mm["abs"] for mm in matriz)
    top20_abs = sum(mm["abs"] for mm in matriz[:20])
    materiais_cronicos = sum(1 for mm in matriz if mm["freq"] >= lim_freq)

    top_perda = sorted((mm for mm in matriz if mm["liq"] > 0), key=lambda x: -x["liq"])[:10]
    top_economia = sorted((mm for mm in matriz if mm["liq"] < 0), key=lambda x: x["liq"])[:10]

    return {
        "tem_dados": True,
        "mes": mes,
        "ops_analisadas": len(ops),
        "ops_com_furo": len(ops_com_furo),
        "taxa_furo_pct": (len(ops_com_furo) / len(ops) * 100) if ops else None,
        "perda": round(perda, 2),
        "economia": round(economia, 2),
        "impacto_liquido": round(perda - economia, 2),
        "materiais_cronicos": materiais_cronicos,
        "limiar_freq_ops": lim_freq,
        "ops_criticas": len(ops_criticas),
        "concentracao_top20_pct": (top20_abs / total_abs * 100) if total_abs else None,
        "top_materiais_perda": [
            {"material": mm["material"], "descricao": mm["desc"], "ops": mm["freq"], "impacto": round(mm["liq"], 2)}
            for mm in top_perda
        ],
        "top_materiais_economia": [
            {"material": mm["material"], "descricao": mm["desc"], "ops": mm["freq"], "impacto": round(mm["liq"], 2)}
            for mm in top_economia
        ],
        "evolucao_mensal": evolucao_mensal,
    }
