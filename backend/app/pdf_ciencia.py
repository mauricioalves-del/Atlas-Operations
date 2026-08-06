"""
Geração do documento de ciência - o PDF que registra que um gestor
revisou uma conciliação de inventário, com a lista de itens divergentes
congelada no momento da confirmação (não muda depois, mesmo que os dados
do fechamento sejam corrigidos/reconciliados posteriormente).

Usa fpdf2 - biblioteca pura Python, sem dependência nativa (mesma lógica
de escolha do resto do projeto: evitar bibliotecas que exigem compilação
em ambientes Windows problemáticos).
"""
from fpdf import FPDF
from datetime import datetime


def _sanitizar(txt) -> str:
    """As fontes core do fpdf2 (Helvetica, sem TTF Unicode carregado) só
    suportam Latin-1. Dados de planilha real frequentemente têm
    caracteres 'inteligentes' (en-dash –, aspas curvas etc) que quebram
    a geração do PDF - normaliza os mais comuns e, por segurança, troca
    qualquer coisa remanescente fora do Latin-1 por '?' em vez de deixar
    o documento inteiro falhar por um caractere isolado."""
    if txt is None:
        return ""
    txt = str(txt)
    substituicoes = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "..."}
    for antigo, novo in substituicoes.items():
        txt = txt.replace(antigo, novo)
    return txt.encode("latin-1", errors="replace").decode("latin-1")


def gerar_pdf_ciencia(ciencia, fechamento) -> bytes:
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Atlas - Documento de Ciência de Conciliação", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, "Confirmação de revisão de fechamento de inventário", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Dados do fechamento", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _sanitizar(f"Almoxarifado: {fechamento.almoxarifado}"), ln=True)
    pdf.cell(0, 6, f"Data do fechamento: {fechamento.data_fechamento}", ln=True)
    pdf.cell(0, 6, f"Itens avaliados: {fechamento.total_itens} | Divergentes: {ciencia.total_itens_divergentes}", ln=True)
    pdf.cell(0, 6, f"Valor total divergente: R$ {ciencia.valor_total_divergente:,.2f}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Confirmação de ciência", ln=True)
    pdf.set_font("Helvetica", "", 10)
    ROTULOS_PAPEL = {"Diretor_Operacoes": "Diretor de Operações", "Coordenador_Financeiro": "Coordenador Financeiro"}
    if getattr(ciencia, "papel_assinatura", None):
        pdf.cell(0, 6, _sanitizar(f"Assinando como: {ROTULOS_PAPEL.get(ciencia.papel_assinatura, ciencia.papel_assinatura)}"), ln=True)
    pdf.cell(0, 6, _sanitizar(f"Gestor responsavel: {ciencia.gestor_nome or ciencia.gestor_username} ({ciencia.gestor_username})"), ln=True)
    pdf.cell(0, 6, f"Data/hora da confirmação: {ciencia.data_assinatura.strftime('%d/%m/%Y %H:%M:%S')}", ln=True)
    if ciencia.observacao:
        pdf.multi_cell(0, 6, _sanitizar(f"Observacao: {ciencia.observacao}"))
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"Itens divergentes a serem ajustados ({len(ciencia.itens_divergentes_snapshot)})", ln=True)
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    larguras = [25, 65, 25, 22, 22, 30]
    cabecalho = ["SKU", "Descrição", "Almoxarifado", "Qtd. Sist.", "Qtd. Cont.", "Valor (R$)"]
    for w, titulo in zip(larguras, cabecalho):
        pdf.cell(w, 7, _sanitizar(titulo), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for item in ciencia.itens_divergentes_snapshot:
        pdf.cell(larguras[0], 6, _sanitizar(str(item.get("sku", "")))[:14], border=1)
        pdf.cell(larguras[1], 6, _sanitizar(str(item.get("descricao", "") or ""))[:38], border=1)
        pdf.cell(larguras[2], 6, _sanitizar(str(item.get("almoxarifado", "")))[:16], border=1)
        pdf.cell(larguras[3], 6, str(item.get("qtd_sistema", "")), border=1, align="R")
        pdf.cell(larguras[4], 6, str(item.get("qtd_contagem", "")), border=1, align="R")
        pdf.cell(larguras[5], 6, f"{item.get('valor_estimado', 0):,.2f}", border=1, align="R")
        pdf.ln()

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, f"Documento gerado automaticamente pelo Atlas em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}. "
                          "Este registro reflete o estado dos itens divergentes no momento exato da confirmação de ciência "
                          "e não é alterado por reconciliações ou correções feitas posteriormente no sistema.")

    return bytes(pdf.output())
