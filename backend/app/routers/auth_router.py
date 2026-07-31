from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import verificar_senha, criar_token
from ..deps import obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/auth", tags=["autenticacao"])

MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter_by(username=payload.username).first()

    if usuario and usuario.bloqueado_ate and usuario.bloqueado_ate > datetime.utcnow():
        minutos_restantes = int((usuario.bloqueado_ate - datetime.utcnow()).total_seconds() / 60) + 1
        raise HTTPException(429, f"Muitas tentativas erradas. Tente de novo em {minutos_restantes} min.")

    senha_ok = usuario and usuario.ativo and verificar_senha(payload.senha, usuario.senha_hash)

    if not senha_ok:
        if usuario:
            usuario.tentativas_falhas = (usuario.tentativas_falhas or 0) + 1
            if usuario.tentativas_falhas >= MAX_TENTATIVAS:
                usuario.bloqueado_ate = datetime.utcnow() + timedelta(minutes=BLOQUEIO_MINUTOS)
            db.commit()
        registrar_log(db, payload.username, "login_falha")
        db.commit()
        raise HTTPException(401, "Usuário ou senha incorretos.")

    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    registrar_log(db, usuario.username, "login_sucesso")
    db.commit()

    token = criar_token(usuario.username, usuario.papel)
    return {
        "access_token": token,
        "username": usuario.username,
        "nome_exibicao": usuario.nome_exibicao,
        "papel": usuario.papel,
    }


@router.get("/me", response_model=schemas.UsuarioOut)
def me(usuario: models.Usuario = Depends(obter_usuario_atual)):
    return usuario
