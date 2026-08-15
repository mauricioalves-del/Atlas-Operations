"""
Outros Dashboards (20/08/2026) - dashboards HTML autocontidos que a equipe já
mantém em paralelo ao Atlas, fora dos módulos nativos do sistema. Nasceu da
conversa sobre o slide de FEFO do MBR: a "quebra de FEFO" que o Atlas calcula
a partir da data da transferência não reflete disponibilidade real medida no
momento (ver docstring de ../fefo.py) - em vez de forçar essa métrica dentro
do relatório, o admin sobe aqui o HTML já pronto de cada dashboard que já
existe por fora, e ele fica acessível dentro do Atlas, embutido via iframe.

5 slots fixos - a lista abaixo é a única fonte de verdade de quais existem;
pra adicionar um sexto, basta acrescentar uma linha aqui (o front lê a lista
via GET "" e monta a tela sozinho, não tem nada mais hard-coded no HTML).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import requer_papel
from ..audit import registrar_log

router = APIRouter(prefix="/dashboards-externos", tags=["dashboards_externos"])

SLOTS = [
    ("controle_fefo", "Controle de FEFO"),
    ("farol_shelf_life", "Farol de Shelf-Life"),
    ("recuperacao_shelf", "Recuperação de Shelf"),
    ("testes_industriais", "Testes Industriais"),
    ("baixas_operacionais", "Dashboard Baixas Operacionais"),
]
NOME_POR_CHAVE = dict(SLOTS)
CHAVES_VALIDAS = set(NOME_POR_CHAVE)


@router.get("")
def listar_dashboards_externos(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Status dos 5 slots fixos - não devolve o HTML em si (pode ser grande
    demais pra uma listagem), só quem/quando enviou. O conteúdo é buscado sob
    demanda em GET /{chave}/conteudo, quando a pessoa clica em "Abrir"."""
    existentes = {d.chave: d for d in db.query(models.DashboardExterno).all()}
    return [
        {
            "chave": chave,
            "nome_exibicao": nome,
            "enviado": chave in existentes,
            "enviado_por": existentes[chave].enviado_por if chave in existentes else None,
            "enviado_em": existentes[chave].enviado_em.isoformat() if chave in existentes else None,
            "nome_arquivo_original": existentes[chave].nome_arquivo_original if chave in existentes else None,
        }
        for chave, nome in SLOTS
    ]


@router.post("/{chave}/upload")
async def enviar_dashboard_externo(
    chave: str,
    arquivo: UploadFile = File(...),
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Recebe um .html autocontido (CSS/JS já embutidos - nada de referência
    a arquivo externo, já que o Atlas só guarda esse único arquivo) e
    substitui o conteúdo anterior do mesmo slot, se houver (upsert por
    chave)."""
    if chave not in CHAVES_VALIDAS:
        raise HTTPException(404, f"Slot de dashboard desconhecido: '{chave}'. Slots válidos: {sorted(CHAVES_VALIDAS)}")
    if not arquivo.filename or not arquivo.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(400, "Envie um arquivo .html (autocontido - CSS e JS já embutidos no próprio arquivo).")

    conteudo_bruto = await arquivo.read()
    try:
        html = conteudo_bruto.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Não consegui ler o arquivo como texto UTF-8. Salve o .html com essa codificação e tente de novo.")

    existente = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if existente:
        existente.html_content = html
        existente.nome_arquivo_original = arquivo.filename
        existente.enviado_por = usuario.username
        existente.enviado_em = datetime.utcnow()
    else:
        db.add(models.DashboardExterno(
            chave=chave, nome_exibicao=NOME_POR_CHAVE[chave], html_content=html,
            nome_arquivo_original=arquivo.filename, enviado_por=usuario.username,
        ))

    registrar_log(
        db, usuario.username, "enviar_dashboard_externo", entidade="dashboard_externo", entidade_id=chave,
        detalhes={"arquivo": arquivo.filename, "tamanho_bytes": len(conteudo_bruto)},
    )
    db.commit()
    return {"ok": True, "chave": chave}


@router.get("/{chave}/conteudo")
def conteudo_dashboard_externo(chave: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """HTML bruto do dashboard, pra ser embutido via iframe (srcdoc) no
    front-end. Devolvido por um fetch autenticado, não por navegação direta
    do navegador - uma tag <iframe src="..."> comum não manda o cabeçalho de
    autorização, então o front busca aqui com o token e injeta o resultado
    no iframe via srcdoc."""
    if chave not in CHAVES_VALIDAS:
        raise HTTPException(404, f"Slot de dashboard desconhecido: '{chave}'.")
    d = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if not d:
        raise HTTPException(404, "Esse dashboard ainda não teve nenhum arquivo enviado.")
    return Response(content=d.html_content, media_type="text/html")


@router.delete("/{chave}")
def remover_dashboard_externo(chave: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    if chave not in CHAVES_VALIDAS:
        raise HTTPException(404, f"Slot de dashboard desconhecido: '{chave}'.")
    d = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if not d:
        raise HTTPException(404, "Esse dashboard ainda não teve nenhum arquivo enviado.")
    db.delete(d)
    registrar_log(db, usuario.username, "remover_dashboard_externo", entidade="dashboard_externo", entidade_id=chave)
    db.commit()
    return {"ok": True}
