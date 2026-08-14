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


def verificar_chave_integracao(x_atlas_chave: str | None = Header(None, alias="X-Atlas-Chave")):
    """Autenticação por chave fixa pra endpoints chamados por SISTEMAS
    externos (ex: webhook do Supabase do Lovable), não por uma pessoa
    logada - ver integracoes_router.py. Defina ATLAS_INTEGRACAO_CHAVE no
    ambiente do servidor (Render) e configure o mesmo valor no header
    'X-Atlas-Chave' do lado de quem chama (ex: no cabeçalho customizado do
    Database Webhook do Supabase)."""
    chave_esperada = os.environ.get("ATLAS_INTEGRACAO_CHAVE")
    if not chave_esperada:
        raise HTTPException(
            500,
            "ATLAS_INTEGRACAO_CHAVE não configurada no servidor - defina essa variável de "
            "ambiente antes de habilitar integrações externas (ver integracoes_router.py).",
        )
    if not x_atlas_chave or x_atlas_chave != chave_esperada:
        raise HTTPException(401, "Chave de integração inválida ou ausente (header X-Atlas-Chave).")


def filtrar_por_almoxarifado_permitido(query, coluna_almoxarifado, usuario: models.Usuario, almoxarifado_solicitado: str | None):
    """Aplica o "parâmetro de visualização" por almoxarifado (18/08/2026) - a
    restrição em si vive em Usuario.almoxarifados_permitidos (lista de códigos,
    JSON; None/[] = sem restrição, continua vendo tudo como sempre viu). Ponto
    único de aplicação pra não repetir essa lógica em cada endpoint que filtra
    por almoxarifado - troca a chamada de
        if almoxarifado: query = query.filter(Coluna == almoxarifado)
    por
        query = filtrar_por_almoxarifado_permitido(query, Coluna, usuario, almoxarifado)
    e cobre os dois casos: usuário pediu um almoxarifado específico (intersecta
    com o que ele pode ver - fora da lista permitida vira filtro impossível, sem
    lançar erro) e usuário não pediu nenhum, ou seja "quero ver tudo" (se tem
    restrição, "tudo" passa a significar "tudo que eu posso ver", não o banco
    inteiro)."""
    permitidos = getattr(usuario, "almoxarifados_permitidos", None) or None
    if not permitidos:
        if almoxarifado_solicitado:
            query = query.filter(coluna_almoxarifado == almoxarifado_solicitado)
        return query
    if almoxarifado_solicitado:
        if almoxarifado_solicitado in permitidos:
            return query.filter(coluna_almoxarifado == almoxarifado_solicitado)
        return query.filter(coluna_almoxarifado.in_([]))  # pediu um fora do escopo - devolve vazio, sem erro
    return query.filter(coluna_almoxarifado.in_(permitidos))


def requer_papel(*papeis_permitidos: str):
    """Uso: Depends(requer_papel("admin", "analista")) numa rota - só
    deixa passar se o usuário logado tiver um desses papéis."""

    def verificador(usuario: models.Usuario = Depends(obter_usuario_atual)) -> models.Usuario:
        if usuario.papel not in papeis_permitidos:
            raise HTTPException(403, f"Ação restrita a: {', '.join(papeis_permitidos)}. Seu papel atual: {usuario.papel}.")
        return usuario

    return verificador
