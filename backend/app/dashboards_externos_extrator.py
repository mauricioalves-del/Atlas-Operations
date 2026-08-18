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
"""
import re
import json
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
# 2. Controle de Testes Industriais - const DATA=[...], campo "mes" (YYYYMM)
# ---------------------------------------------------------------------------
def extrair_testes_industriais(html_content: str, mes: str) -> dict:
    """mes: 'YYYY-MM'."""
    m = re.search(r"const DATA\s*=\s*(\[.*?\]);", html_content, re.S)
    if not m:
        return None
    dados = json.loads(m.group(1))
    mes_chave = mes.replace("-", "")

    do_mes = [d for d in dados if d.get("mes") == mes_chave]
    if not do_mes:
        return {"tem_dados": False, "mes": mes}

    gasto_total = sum(d.get("custo", 0) or 0 for d in do_mes)
    ops = sorted(set(d.get("op") for d in do_mes if d.get("op")))

    agg = {}
    for d in do_mes:
        k = d.get("descMat") or d.get("material") or "—"
        agg.setdefault(k, {"custo": 0.0, "qtd": 0.0, "um": d.get("um")})
        agg[k]["custo"] += d.get("custo", 0) or 0
        agg[k]["qtd"] += d.get("qtd", 0) or 0
    top = sorted(agg.items(), key=lambda x: -x[1]["custo"])[:8]

    return {
        "tem_dados": True,
        "mes": mes,
        "total_itens": len(do_mes),
        "gasto_total": round(gasto_total, 2),
        "ops": len(ops),
        "custo_medio_op": round(gasto_total / len(ops), 2) if ops else 0,
        "top_materias_primas": [
            {"nome": k, "custo": round(v["custo"], 2), "qtd": round(v["qtd"], 4), "um": v["um"]}
            for k, v in top
        ],
    }


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

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "perda_potencial_total": perda_potencial_total,
        "perda_ja_vencida": perda_ja_vencida,
        "qtd_lotes": qtd_lotes,
        "buckets": buckets,
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

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "kpis": kpis,
        "tabelas": tabelas,
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

    return {
        "exportado_em": exportado_em,
        "filtros": filtros,
        "resumo": resumo,
        "tabelas": tabelas,
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
