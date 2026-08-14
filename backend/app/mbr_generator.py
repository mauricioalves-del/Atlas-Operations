"""
Geração automática do MBR (Monthly Business Review) em PPTX (19/08/2026) -
usa capturas de tela REAIS das telas do Atlas (decisão explícita do
usuário: "prints reais das telas do Atlas", não gráficos nativos do
PowerPoint nem dados recriados à parte) - a mesma tela que a equipe já vê
no dia a dia, printada direto do servidor via Playwright (Chromium
headless).

IMPORTANTE - risco de infraestrutura documentado: isso exige Playwright +
o navegador Chromium instalados no ambiente que roda o backend (tanto
localmente quanto no Render/nuvem) - ver requirements.txt e
ATUALIZANDO.md pro passo extra de setup. É mais pesado (memória/disco)
que o resto do sistema. Se isso não couber no plano de hospedagem atual,
os sintomas mais prováveis são o deploy demorar muito mais tempo, ou o
próprio Chromium falhar ao abrir (nesse caso o endpoint devolve um erro
claro, sem derrubar o resto do Atlas).

IMPORTANTE - suposição documentada sobre o conteúdo: o MBR gerado aqui
tem os prints de tela + título/mês de cada seção, mas NÃO tenta escrever
o texto analítico (a prosa explicando "por que" os números vieram assim)
que uma pessoa escreve à mão no MBR de verdade - isso exige leitura e
julgamento humano dos números, não é algo que dê pra automatizar de
forma confiável. O usuário decide se quer complementar o PPTX gerado à
mão depois, ou se pede pra eu tentar automatizar isso também (com outro
grau de confiança) numa próxima rodada.
"""
import os
from datetime import datetime
from io import BytesIO
from typing import Optional

from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# Cada seção: chave = data-view do Atlas (o mesmo valor usado em
# mostrarView() no frontend), título do slide, e o id do <select> de
# filtro de mês quando a tela tiver um (None = tela não tem recorte por
# mês, é sempre "estado atual"). Só entram aqui telas que JÁ EXISTEM no
# Atlas (decisão do usuário) - Testes de Inovação e o "Controle de
# Movimentados" original (itens analisados/divergência) ainda não têm
# tela própria, então não aparecem no MBR ainda.
SECOES_MBR = [
    {"chave": "fechamento-dashboard", "titulo": "Painel de Inventário", "filtro_mes_id": "fd-filtro-mes"},
    {"chave": "acuracia-ponderada", "titulo": "Acurácia Ponderada", "filtro_mes_id": "ap-filtro-mes"},
    {"chave": "mapeamento-passivos", "titulo": "Mapeamento de Passivos", "filtro_mes_id": None},
    {"chave": "shelf-life", "titulo": "Shelf Life — Risco de Validade", "filtro_mes_id": None},
    {"chave": "movimentados", "titulo": "Controle de Movimentados (Transferências + FEFO)", "filtro_mes_id": None},
    {"chave": "fefo", "titulo": "FEFO — Quebras na Movimentação", "filtro_mes_id": None},
]

COR_AZUL_ATLAS = RGBColor(0x5B, 0x75, 0xAC)
COR_CINZA_TEXTO = RGBColor(0x55, 0x55, 0x55)


def _base_url() -> str:
    """URL interna pra o próprio servidor - o Chromium headless roda no
    mesmo processo/container do backend, então acessa via loopback (nunca
    precisa do domínio público nem de HTTPS, e continua funcionando
    mesmo se o serviço não tiver saída de rede externa)."""
    porta = os.environ.get("PORT", "8000")
    return os.environ.get("ATLAS_MBR_BASE_URL", f"http://127.0.0.1:{porta}")


async def _capturar_com_retentativa(elemento, titulo: str):
    """Tira o print de uma seção com tolerância a instabilidade de layout -
    o plano "free" do Render (0.1 CPU/512MB) é lento o bastante pra
    gráficos/tabelas ainda estarem se ajustando quando o Playwright tenta
    tirar o print, e o "element is not stable" do Playwright fica tentando
    de novo até estourar o timeout padrão (30s). "animations=disabled"
    resolve a causa mais comum (transição CSS/animação de gráfico que nunca
    "para" de vez); o timeout maior (45s, com uma segunda tentativa até 75s)
    cobre o resto. Se mesmo assim não der, NÃO derruba o MBR inteiro - essa
    seção entra como "não disponível" (ver _adicionar_slide_secao) e as
    outras 5 seções continuam normalmente."""
    for tentativa, timeout_ms in enumerate((45000, 75000), start=1):
        try:
            return await elemento.screenshot(timeout=timeout_ms, animations="disabled")
        except Exception as e:
            print(f"Atlas MBR: falha ao capturar '{titulo}' (tentativa {tentativa}): {e}")
    return None


async def capturar_telas_mbr(token: str, mes: Optional[str] = None) -> list[dict]:
    """Abre um Chromium headless, autentica reaproveitando o MESMO token
    de quem pediu a geração (lido do header Authorization da requisição -
    não gera nem guarda nenhuma credencial nova), navega por cada seção de
    SECOES_MBR aplicando o filtro de mês quando existir, e tira um print
    de cada uma. Retorna [{titulo, png_bytes}] (png_bytes pode vir None se
    aquela seção específica não deu tempo de capturar - ver
    _capturar_com_retentativa). Faz import do Playwright dentro da função
    (não no topo do módulo) de propósito: se o Chromium não estiver
    instalado nesse ambiente, o erro só aparece quando alguém realmente
    tenta gerar um MBR, não impede o resto do Atlas de subir."""
    from playwright.async_api import async_playwright

    base_url = _base_url()
    resultados = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})
            # Timeouts padrão mais folgados que o default do Playwright (30s) -
            # o plano "free" do Render pode levar 50s+ só pra acordar de um
            # spin-down por inatividade (aviso do próprio Render), fora o
            # tempo de fato processando os dashboards com 0.1 CPU.
            page.set_default_timeout(45000)
            page.set_default_navigation_timeout(60000)

            # primeira navegação só pra existir um "origin" válido -
            # localStorage não pode ser setado antes de a página carregar
            # ao menos uma vez nesse domínio.
            await page.goto(base_url, wait_until="networkidle")
            await page.evaluate(
                "(token) => { localStorage.setItem('atlas_token', token); localStorage.setItem('atlas_user', '{}'); }",
                token,
            )
            await page.reload(wait_until="networkidle")
            await page.wait_for_selector("#shell-app:not(.hidden)", timeout=30000)

            for secao in SECOES_MBR:
                await page.evaluate("(v) => mostrarView(v)", secao["chave"])
                await page.wait_for_timeout(1200)  # tempo pro fetch inicial da view carregar - mais folga
                # que no sandbox de teste porque o plano "free" do Render roda com só 0.1 CPU/512MB,
                # bem mais lento que qualquer ambiente de desenvolvimento pra abrir gráficos/tabelas.

                if secao["filtro_mes_id"] and mes:
                    seletor = f"#{secao['filtro_mes_id']}"
                    if await page.locator(seletor).count():
                        valores = await page.eval_on_selector_all(f"{seletor} option", "opts => opts.map(o => o.value)")
                        if mes in valores:
                            await page.select_option(seletor, mes)
                            await page.wait_for_timeout(1500)  # tempo pro dashboard recarregar com o filtro novo

                await page.wait_for_timeout(1000)
                elemento = page.locator(f"#view-{secao['chave']}")
                png_bytes = await _capturar_com_retentativa(elemento, secao["titulo"])
                if png_bytes is not None:
                    resultados.append({"titulo": secao["titulo"], "png_bytes": png_bytes})
                else:
                    resultados.append({"titulo": secao["titulo"], "png_bytes": None})
        finally:
            await browser.close()

    return resultados


def _adicionar_slide_titulo(prs: Presentation, mes: str):
    layout_branco = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout_branco)

    caixa = slide.shapes.add_textbox(Inches(1), Inches(2.7), Inches(11.3), Inches(2))
    tf = caixa.text_frame
    tf.word_wrap = True
    p1 = tf.paragraphs[0]
    p1.text = "MBR — Controle de Estoque"
    p1.font.size = Pt(40)
    p1.font.bold = True
    p1.font.color.rgb = COR_AZUL_ATLAS

    p2 = tf.add_paragraph()
    p2.text = f"{mes} · Gerado automaticamente pelo Atlas em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    p2.font.size = Pt(16)
    p2.font.color.rgb = COR_CINZA_TEXTO


def _adicionar_slide_secao(prs: Presentation, titulo: str, png_bytes: Optional[bytes]):
    layout_branco = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout_branco)

    titulo_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.25), Inches(12.3), Inches(0.6))
    p = titulo_box.text_frame.paragraphs[0]
    p.text = titulo
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = COR_AZUL_ATLAS

    # Essa seção específica não deu tempo de capturar (ver
    # _capturar_com_retentativa) - em vez de derrubar o MBR inteiro, entra
    # um aviso no lugar do print e o restante do PPTX segue normal.
    if png_bytes is None:
        aviso_box = slide.shapes.add_textbox(Inches(0.5), Inches(3.2), Inches(12.3), Inches(1.5))
        p_aviso = aviso_box.text_frame.paragraphs[0]
        p_aviso.text = "Não foi possível capturar esta tela a tempo (servidor lento no momento da geração). Tente gerar o MBR de novo."
        p_aviso.font.size = Pt(18)
        p_aviso.font.color.rgb = COR_CINZA_TEXTO
        p_aviso.alignment = PP_ALIGN.CENTER
        return

    img_stream = BytesIO(png_bytes)
    img = Image.open(img_stream)
    largura_img, altura_img = img.size
    img_stream.seek(0)

    largura_disponivel = Inches(12.3)
    altura_disponivel = Inches(6.3)
    proporcao_img = largura_img / altura_img
    proporcao_area = largura_disponivel / altura_disponivel

    if proporcao_img > proporcao_area:
        largura = largura_disponivel
        altura = int(largura / proporcao_img)
    else:
        altura = altura_disponivel
        largura = int(altura * proporcao_img)

    left = Inches(0.5) + int((largura_disponivel - largura) / 2)
    top = Inches(1.05) + int((altura_disponivel - altura) / 2)
    slide.shapes.add_picture(img_stream, left, top, width=largura, height=altura)


def montar_pptx_mbr(secoes: list[dict], mes: str) -> bytes:
    """Monta o .pptx a partir das capturas de tela já feitas
    (capturar_telas_mbr) - função pura, sem I/O de rede, fácil de testar
    separado da parte de Playwright."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    _adicionar_slide_titulo(prs, mes)
    for secao in secoes:
        _adicionar_slide_secao(prs, secao["titulo"], secao["png_bytes"])

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
