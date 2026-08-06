from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .auth import decodificar_token, TokenInvalido

PAPEIS_VALIDOS = ("admin", "analista", "leitura")


def obter_usuario_atual(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> models.Usuario:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado - faça login novamente.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decodificar_token(token)
    except TokenInvalido as e:
        raise HTTPException(401, f"Sessão inválida ou expirada: {e}")

    usuario = db.query(models.Usuario).filter_by(username=payload["sub"]).first()
    if not usuario or not usuario.ativo:
        raise HTTPException(401, "Usuário não encontrado ou desativado.")
    return usuario


def requer_papel(*papeis_permitidos: str):
    """Uso: Depends(requer_papel("admin", "analista")) numa rota - só
    deixa passar se o usuário logado tiver um desses papéis."""

    def verificador(usuario: models.Usuario = Depends(obter_usuario_atual)) -> models.Usuario:
        if usuario.papel not in papeis_permitidos:
            raise HTTPException(403, f"Ação restrita a: {', '.join(papeis_permitidos)}. Seu papel atual: {usuario.papel}.")
        return usuario

    return verificador
