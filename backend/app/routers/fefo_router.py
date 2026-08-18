"""
Módulo FEFO (First-Expired-First-Out) - detecção de quebras na
movimentação de saída da Fábrica (18/08/2026). Ver app/fefo.py pra regra
de cálculo (documentada lá, com a suposição sinalizada pra validação do
usuário) e models.ChecagemFefo pro formato do resultado guardado.
"""
import io
from collections import Counter
from datetime import date
from typing import Optional
import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import obter_usuario_atual, requer_papel
from ..audit import registrar_log
from .. import fefo
from ..fefo import recalcular_checagens_fefo

router = APIRouter(prefix="/fefo", tags=["fefo"])


@router.post("/recalcular")
def recalcular(usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    """Roda a checagem de FEFO pra toda transferência elegível (origem =
    Fábrica) e atualiza o resultado guardado - chamar depois de reimportar
    a planilha de lotes (Lote_Sistema) ou o livro-caixa bruto/
    transferências, pra refletir o estado mais recente."""
    resultado = recalcular_checagens_fefo(db)
    registrar_log(db, usuario.username, "recalcular_fefo", detalhes=resultado)
    db.commit()
    return resultado


@router.get("/checagens", response_model=list[schemas.ChecagemFefoOut])
def listar_checagens(
    resultado: Optional[str] = Query(None, description="Quebra_Fefo | Dentro_Do_Criterio | Sem_Dado_Suficiente"),
    sku: Optional[str] = None,
    almoxarifado_destino: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.ChecagemFefo)
    if resultado:
        q = q.filter(models.ChecagemFefo.resultado == resultado)
    if sku:
        q = q.filter(models.ChecagemFefo.sku == sku)
    if almoxarifado_destino:
        q = q.filter(models.ChecagemFefo.almoxarifado_destino == almoxarifado_destino)
    return q.order_by(models.ChecagemFefo.data_saida.desc()).all()


@router.get("/dashboard/resumo")
def dashboard_resumo(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    """Total de transferências avaliadas (saídas da Fábrica com checagem
    já calculada), quantas quebraram o critério de FEFO, taxa de quebra,
    e os SKUs/destinos mais frequentes nas quebras - pro indicador do
    MBR. Rodar POST /fefo/recalcular antes se os dados de transferência ou
    de lotes tiverem mudado desde a última checagem."""
    checagens = db.query(models.ChecagemFefo).all()
    total = len(checagens)
    quebras = [c for c in checagens if c.resultado == "Quebra_Fefo"]
    sem_dado = [c for c in checagens if c.resultado == "Sem_Dado_Suficiente"]

    top_skus = Counter(c.sku for c in quebras).most_common(10)
    top_destinos = Counter(c.almoxarifado_destino for c in quebras if c.almoxarifado_destino).most_common(10)

    avaliaveis = total - len(sem_dado)  # taxa de quebra só faz sentido sobre o que pôde ser avaliado

    return {
        "total_transferencias_avaliadas": total,
        "total_quebras_fefo": len(quebras),
        "total_dentro_do_criterio": total - len(quebras) - len(sem_dado),
        "total_sem_dado_suficiente": len(sem_dado),
        "taxa_quebra_pct": round(len(quebras) / avaliaveis * 100, 2) if avaliaveis else None,
        "top_skus_com_quebra": [{"sku": sku, "quebras": qtd} for sku, qtd in top_skus],
        "top_destinos_com_quebra": [{"almoxarifado_destino": destino, "quebras": qtd} for destino, qtd in top_destinos],
    }


# ═════════════════════════════════════════════════════════════════════════
# Auditoria FEFO importada (20/08/2026) - ver docstring de
# models.AuditoriaFefo e da seção equivalente em app/fefo.py.
# ═════════════════════════════════════════════════════════════════════════

@router.post("/auditoria/importar")
async def importar_auditoria_fefo(
    arquivos: list[UploadFile] = File(...),
    usuario: models.Usuario = Depends(requer_papel("admin", "analista")),
    db: Session = Depends(get_db),
):
    """Importa um ou mais Excels de auditoria FEFO diária (o arquivo que o
    processo do estagiário já gera todo dia - ver Auditar_FEFO.ipynb dele),
    lendo a aba 'Todas as Movimentações'. Pode subir vários arquivos de uma
    vez (ex: pra consolidar o histórico acumulado). Cada arquivo é um dia -
    reimportar o mesmo dia substitui as linhas daquele dia, não duplica."""
    resultados = []
    for arquivo in arquivos:
        conteudo = await arquivo.read()
        try:
            wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
        except Exception as e:
            resultados.append({"arquivo": arquivo.filename, "erro": f"Não consegui abrir o Excel: {e}"})
            continue
        if fefo.ABA_AUDITORIA_FEFO_DIARIA not in wb.sheetnames:
            resultados.append({
                "arquivo": arquivo.filename,
                "erro": f"Aba '{fefo.ABA_AUDITORIA_FEFO_DIARIA}' não encontrada. Abas disponíveis: {wb.sheetnames}",
            })
            continue
        ws = wb[fefo.ABA_AUDITORIA_FEFO_DIARIA]
        linhas_brutas = list(ws.iter_rows(values_only=True))
        if not linhas_brutas:
            resultados.append({"arquivo": arquivo.filename, "erro": "Aba vazia."})
            continue
        cabecalho = [str(c).strip() if c is not None else "" for c in linhas_brutas[0]]
        faltando = [c for c in fefo.COLUNAS_AUDITORIA_FEFO_DIARIA if c not in cabecalho]
        if faltando:
            resultados.append({
                "arquivo": arquivo.filename,
                "erro": f"Colunas obrigatórias não encontradas: {faltando}. Cabeçalho encontrado: {cabecalho}",
            })
            continue
        linhas = [dict(zip(cabecalho, linha)) for linha in linhas_brutas[1:] if any(v is not None for v in linha)]
        resultado = fefo.importar_auditoria_fefo_diaria(db, linhas, arquivo.filename, usuario.username)
        resultados.append({"arquivo": arquivo.filename, **resultado})

    db.commit()
    registrar_log(db, usuario.username, "importar_auditoria_fefo", detalhes={"arquivos": [r["arquivo"] for r in resultados]})
    total_importadas = sum(r.get("linhas_importadas", 0) for r in resultados)
    total_quebras = sum(r.get("quebras_no_arquivo", 0) for r in resultados)
    total_erros = sum(1 for r in resultados if "erro" in r)
    return {"arquivos_processados": len(resultados), "arquivos_com_erro": total_erros,
            "linhas_importadas": total_importadas, "quebras_importadas": total_quebras, "detalhe": resultados}


@router.post("/auditoria/importar-consolidado")
async def importar_auditoria_fefo_consolidado(
    arquivo: UploadFile = File(...),
    usuario: models.Usuario = Depends(requer_papel("admin", "analista")),
    db: Session = Depends(get_db),
):
    """Importa o dashboard HTML consolidado que o estagiário já mantinha
    (Controle - FEFO.html, gerado pelo DashBoard_FEFO.ipynb dele) - só pra
    estender o histórico a dias sem o Excel de auditoria diária bruto. Ver
    fefo.importar_auditoria_fefo_consolidada pra regra de "dia já cobrido
    pela auditoria diária não é sobrescrito"."""
    conteudo = await arquivo.read()
    try:
        registros = fefo.extrair_registros_dashboard_consolidado(conteudo.decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"Não consegui ler o dashboard consolidado: {e}")

    resultado = fefo.importar_auditoria_fefo_consolidada(db, registros, arquivo.filename, usuario.username)
    registrar_log(db, usuario.username, "importar_auditoria_fefo_consolidado",
                  detalhes={"arquivo": arquivo.filename, **resultado})
    db.commit()
    return {"arquivo": arquivo.filename, **resultado}


@router.get("/auditoria/resumo")
def resumo_auditoria_fefo(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Agregados do histórico de auditoria FEFO importado (ver
    fefo.calcular_resumo_auditoria_fefo) - alimenta o painel nativo na tela
    FEFO, com o histórico real consolidado do processo do estagiário."""
    return fefo.calcular_resumo_auditoria_fefo(db, data_inicio, data_fim)


@router.get("/auditoria/registros")
def listar_auditoria_fefo(
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    apenas_quebras: bool = False,
    produto: Optional[str] = Query(None, description="Busca por SKU ou descrição (contém, case-insensitive)"),
    limite: int = Query(200, le=2000),
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Lista os movimentos importados, mais recentes primeiro - pra tabela
    de detalhamento da tela FEFO. Exclui 'Destino (não auditado)' por
    padrão (não é útil olhar individualmente), a menos que se queira tudo
    via outro filtro no futuro."""
    q = db.query(models.AuditoriaFefo).filter(models.AuditoriaFefo.status != fefo.STATUS_DESTINO_NAO_AUDITADO)
    if data_inicio:
        q = q.filter(models.AuditoriaFefo.data >= data_inicio)
    if data_fim:
        q = q.filter(models.AuditoriaFefo.data <= data_fim)
    if apenas_quebras:
        q = q.filter(models.AuditoriaFefo.quebra_fefo.is_(True))
    if produto:
        termo = f"%{produto}%"
        q = q.filter((models.AuditoriaFefo.sku.ilike(termo)) | (models.AuditoriaFefo.descricao_produto.ilike(termo)))
    registros = q.order_by(models.AuditoriaFefo.data.desc(), models.AuditoriaFefo.id.desc()).limit(limite).all()
    return [
        {
            "id": r.id, "data": str(r.data), "sku": r.sku, "descricao_produto": r.descricao_produto,
            "movimento": r.movimento, "almoxarifado": r.almoxarifado, "lote_movimentado": r.lote_movimentado,
            "qtd_lote_movimentado": r.qtd_lote_movimentado,
            "validade_lote_movimentado": str(r.validade_lote_movimentado) if r.validade_lote_movimentado else None,
            "quebra_fefo": r.quebra_fefo, "status": r.status,
            "lote_mais_antigo_disponivel": r.lote_mais_antigo_disponivel,
            "qtd_lote_mais_antigo_disponivel": r.qtd_lote_mais_antigo_disponivel,
            "validade_mais_antiga_disponivel": str(r.validade_mais_antiga_disponivel) if r.validade_mais_antiga_disponivel else None,
            "fonte": r.fonte,
        }
        for r in registros
    ]
