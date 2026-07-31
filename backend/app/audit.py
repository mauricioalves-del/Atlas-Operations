from sqlalchemy.orm import Session
from . import models


def registrar_log(db: Session, username: str, acao: str, entidade: str = None, entidade_id=None, detalhes: dict = None):
    """Grava uma linha de auditoria. Não faz commit - quem chamar decide
    quando commitar (geralmente junto com a mudança que está sendo
    registrada, na mesma transação)."""
    db.add(models.LogAuditoria(
        username=username, acao=acao, entidade=entidade,
        entidade_id=str(entidade_id) if entidade_id is not None else None,
        detalhes=detalhes,
    ))
