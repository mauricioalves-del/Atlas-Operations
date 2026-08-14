from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
async def gerar_mbr(
    mes: str = Query(..., description='Mês no formato "AAAA-MM" - escolhido pelo usuário na tela (decisão explícita: sem cálculo automático de "mês fechado").'),
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Gera o MBR (Monthly Business Review) em PPTX com capturas de tela REAIS
    das telas do Atlas (ver app/mbr_generator.py) - restrito a admin porque
    abre um navegador Chromium headless dentro do próprio processo do
    servidor, reaproveitando o token de quem pediu (nunca gera nem guarda
    credencial nova). Só cobre os módulos que já têm tela própria no Atlas
    (decisão do usuário, 19/08/2026) - Testes de Inovação e o antigo
    "Controle de Movimentados" (itens analisados/divergência) ficam de fora
    por enquanto."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sessão inválida ou expirada - faça login de novo antes de gerar o MBR.")
    token = authorization.removeprefix("Bearer ").strip()

    from ..mbr_generator import capturar_telas_mbr, montar_pptx_mbr

    try:
        secoes = await capturar_telas_mbr(token, mes)
    except Exception as e:
        raise HTTPException(
            500,
            "Não foi possível gerar o MBR: falha ao capturar as telas do Atlas "
            f"(Playwright/Chromium). Detalhe técnico: {e}",
        )

    pptx_bytes = montar_pptx_mbr(secoes, mes)

    registrar_log(db, usuario.username, "gerar_mbr", detalhes={"mes": mes})
    db.commit()

    nome_arquivo = f"MBR_Atlas_{mes}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
