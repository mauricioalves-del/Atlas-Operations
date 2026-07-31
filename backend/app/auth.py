"""
Autenticação e autorização do Atlas.

Decisão de projeto: tudo aqui usa só a biblioteca padrão do Python
(hashlib, hmac, secrets) - nada de bcrypt/passlib/PyJWT. Isso é
deliberado: seu ambiente já teve problema pra instalar pandas por falta
de wheel pronta pra versão do Python instalada, e bibliotecas de auth
frequentemente têm extensões nativas (bcrypt, sobretudo). Hash de senha
com PBKDF2-HMAC-SHA256 e token assinado com HMAC são criptograficamente
adequados para este cenário (uso interno da empresa) e não dependem de
nenhuma compilação.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
import base64

ARQUIVO_SEGREDO = os.path.join(os.path.dirname(__file__), "..", ".secret_key")
ITERACOES_PBKDF2 = 260_000
VALIDADE_TOKEN_HORAS = 12


def _obter_segredo() -> bytes:
    """Chave usada para assinar os tokens de sessão. Gerada uma vez e
    persistida em disco - se você preferir, pode sobrepor via variável de
    ambiente ATLAS_SECRET_KEY (recomendado se for rodar múltiplas
    instâncias atrás de um load balancer)."""
    env = os.environ.get("ATLAS_SECRET_KEY")
    if env:
        return env.encode()
    if os.path.exists(ARQUIVO_SEGREDO):
        with open(ARQUIVO_SEGREDO, "r") as f:
            return f.read().strip().encode()
    novo = secrets.token_hex(32)
    with open(ARQUIVO_SEGREDO, "w") as f:
        f.write(novo)
    return novo.encode()


def hash_senha(senha_plana: str) -> str:
    sal = secrets.token_hex(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha_plana.encode(), sal.encode(), ITERACOES_PBKDF2)
    return f"{sal}${derivado.hex()}"


def verificar_senha(senha_plana: str, hash_armazenado: str) -> bool:
    try:
        sal, derivado_hex = hash_armazenado.split("$")
    except ValueError:
        return False
    derivado = hashlib.pbkdf2_hmac("sha256", senha_plana.encode(), sal.encode(), ITERACOES_PBKDF2)
    return hmac.compare_digest(derivado.hex(), derivado_hex)


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def criar_token(username: str, papel: str, validade_horas: float = VALIDADE_TOKEN_HORAS) -> str:
    payload = {"sub": username, "papel": papel, "exp": time.time() + validade_horas * 3600}
    payload_bytes = json.dumps(payload).encode()
    payload_b64 = _b64url(payload_bytes)
    assinatura = hmac.new(_obter_segredo(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{assinatura}"


class TokenInvalido(Exception):
    pass


def decodificar_token(token: str) -> dict:
    try:
        payload_b64, assinatura = token.split(".")
    except (ValueError, AttributeError):
        raise TokenInvalido("formato de token inválido")

    assinatura_esperada = hmac.new(_obter_segredo(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, assinatura_esperada):
        raise TokenInvalido("assinatura inválida")

    payload = json.loads(_b64url_decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise TokenInvalido("token expirado")
    return payload
