from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
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
