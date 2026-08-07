import os

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


def verificar_chave_integracao(x_atlas_integration_key: str | None = Header(None)) -> None:
    """Autenticação para chamadas máquina-a-máquina (webhooks de sistemas
    externos, ex: baixas operacionais do Lovable) - não usa login/JWT
    porque não há um usuário humano na ponta, só uma chave fixa
    compartilhada, enviada no header 'X-Atlas-Integration-Key'.

    A chave é lida da variável de ambiente ATLAS_INTEGRATION_API_KEY (
    configurar no Render, igual ATLAS_SECRET_KEY). Sem essa variável
    definida, o endpoint fica bloqueado por padrão em vez de aceitar
    qualquer coisa."""
    chave_esperada = os.environ.get("ATLAS_INTEGRATION_API_KEY")
    if not chave_esperada:
        raise HTTPException(500, "Integração não configurada: defina ATLAS_INTEGRATION_API_KEY no ambiente do servidor.")
    if not x_atlas_integration_key or x_atlas_integration_key != chave_esperada:
        raise HTTPException(401, "Chave de integração ausente ou inválida (header X-Atlas-Integration-Key).")
