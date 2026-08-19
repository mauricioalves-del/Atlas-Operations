"""Cotações de dólar/cacau pra saudação personalizada da tela Início (ver
app/cotacoes.py). Qualquer usuário autenticado pode consultar - não é
informação sensível, só dado público de mercado."""
from fastapi import APIRouter, Depends

from .. import models, cotacoes
from ..deps import obter_usuario_atual

router = APIRouter(prefix="/cotacoes", tags=["cotacoes"])


@router.get("/atuais")
def cotacoes_atuais(usuario: models.Usuario = Depends(obter_usuario_atual)):
    return cotacoes.obter_cotacoes_atuais()
