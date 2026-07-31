import time
from app.auth import hash_senha, verificar_senha, criar_token, decodificar_token, TokenInvalido
import pytest


def test_hash_e_verificacao_de_senha():
    h = hash_senha("MinhaSenh@123")
    assert verificar_senha("MinhaSenh@123", h) is True
    assert verificar_senha("SenhaErrada", h) is False


def test_hashes_sao_diferentes_para_mesma_senha():
    # sal aleatório - dois hashes da mesma senha não devem ser iguais
    assert hash_senha("abc") != hash_senha("abc")


def test_criar_e_decodificar_token():
    token = criar_token("joao", "analista", validade_horas=1)
    payload = decodificar_token(token)
    assert payload["sub"] == "joao"
    assert payload["papel"] == "analista"


def test_token_expirado_falha():
    token = criar_token("joao", "analista", validade_horas=-1)  # já expirado
    with pytest.raises(TokenInvalido):
        decodificar_token(token)


def test_token_adulterado_falha():
    token = criar_token("joao", "analista")
    token_adulterado = token[:-2] + "xx"
    with pytest.raises(TokenInvalido):
        decodificar_token(token_adulterado)
