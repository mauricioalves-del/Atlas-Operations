from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models
from ..audit import registrar_log
from ..database import get_db
from ..deps import requer_papel

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get("")
def listar(
    pagina: int = 1,
    tamanho_pagina: int = 50,
    username: Optional[str] = None,
    acao: Optional[str] = None,
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    q = db.query(models.LogAuditoria)
    if username:
        q = q.filter(models.LogAuditoria.username == username)
    if acao:
        q = q.filter(models.LogAuditoria.acao == acao)
    total = q.count()
    q = q.order_by(models.LogAuditoria.criado_em.desc())
    itens = q.offset((pagina - 1) * tamanho_pagina).limit(tamanho_pagina).all()
    return {
        "itens": [
            {
                "id": i.id, "username": i.username, "acao": i.acao, "entidade": i.entidade,
                "entidade_id": i.entidade_id, "detalhes": i.detalhes, "criado_em": i.criado_em.isoformat(),
            }
            for i in itens
        ],
        "total": total,
        "pagina": pagina,
        "paginas": max(1, -(-total // tamanho_pagina)),
    }


@router.post("/gerar-mbr")
def gerar_mbr(
    mes: str = Query(..., description='Mês no formato "AAAA-MM" - escolhido pelo usuário na tela (decisão explícita: sem cálculo automático de "mês fechado").'),
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Gera o MBR (Monthly Business Review) em PPTX com DADOS REAIS lidos
    diretamente das funções de negócio do Atlas (ver app/mbr_generator.py,
    reescrito em 20/08/2026) - não abre mais navegador nenhum (versão
    anterior usava Playwright/Chromium para printar as telas; trocado por
    pedido do usuário por um relatório no estilo do MBR do gestor dele, com
    a identidade visual da Mágio e narrativa executiva por módulo). Restrito
    a admin. Só cobre os módulos que já têm tela própria no Atlas (decisão do
    usuário, 19/08/2026) - Testes de Inovação e o antigo "Controle de
    Movimentados" (itens analisados/divergência) ficam de fora por enquanto."""
    from ..mbr_generator import montar_pptx_mbr

    try:
        pptx_bytes = montar_pptx_mbr(db=db, usuario=usuario, mes=mes)
    except Exception as e:
        raise HTTPException(500, f"Não foi possível gerar o MBR: {e}")

    registrar_log(db, usuario.username, "gerar_mbr", detalhes={"mes": mes})
    db.commit()

    nome_arquivo = f"MBR_Atlas_{mes}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
