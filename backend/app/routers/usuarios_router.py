from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import hash_senha
from ..deps import requer_papel, obter_usuario_atual, PAPEIS_VALIDOS
from ..audit import registrar_log

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("", response_model=list[schemas.UsuarioOut])
def listar(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    return db.query(models.Usuario).order_by(models.Usuario.username).all()


@router.post("", response_model=schemas.UsuarioOut)
def criar(payload: schemas.UsuarioCreate, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    if payload.papel not in PAPEIS_VALIDOS:
        raise HTTPException(400, f"Papel inválido. Use um de: {PAPEIS_VALIDOS}")
    if db.query(models.Usuario).filter_by(username=payload.username).first():
        raise HTTPException(400, "Já existe um usuário com esse username.")
    novo = models.Usuario(
        username=payload.username, nome_exibicao=payload.nome_exibicao,
        senha_hash=hash_senha(payload.senha), papel=payload.papel, ativo=True,
    )
    db.add(novo)
    registrar_log(db, usuario.username, "criar_usuario", entidade="usuario", entidade_id=payload.username, detalhes={"papel": payload.papel})
    db.commit()
    db.refresh(novo)
    return novo


@router.patch("/{usuario_id}", response_model=schemas.UsuarioOut)
def atualizar(usuario_id: int, payload: schemas.UsuarioAtualizar, usuario_logado: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    alvo = db.query(models.Usuario).get(usuario_id)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if payload.papel is not None:
        if payload.papel not in PAPEIS_VALIDOS:
            raise HTTPException(400, f"Papel inválido. Use um de: {PAPEIS_VALIDOS}")
        alvo.papel = payload.papel
    if payload.nome_exibicao is not None:
        alvo.nome_exibicao = payload.nome_exibicao
    if payload.ativo is not None:
        if alvo.username == usuario_logado.username and payload.ativo is False:
            raise HTTPException(400, "Você não pode desativar o próprio usuário.")
        alvo.ativo = payload.ativo
        if payload.ativo:
            alvo.tentativas_falhas = 0
            alvo.bloqueado_ate = None
    if payload.nova_senha:
        alvo.senha_hash = hash_senha(payload.nova_senha)
    registrar_log(db, usuario_logado.username, "atualizar_usuario", entidade="usuario", entidade_id=alvo.username, detalhes=payload.model_dump(exclude={"nova_senha"}))
    db.commit()
    db.refresh(alvo)
    return alvo


@router.delete("/{usuario_id}")
def excluir(usuario_id: int, usuario_logado: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    alvo = db.query(models.Usuario).get(usuario_id)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if alvo.username == usuario_logado.username:
        raise HTTPException(400, "Você não pode excluir o próprio usuário.")
    if alvo.papel == "admin" and db.query(models.Usuario).filter_by(papel="admin", ativo=True).count() <= 1:
        raise HTTPException(400, "Não é possível excluir o último administrador ativo.")
    registrar_log(db, usuario_logado.username, "excluir_usuario", entidade="usuario", entidade_id=alvo.username)
    db.delete(alvo)
    db.commit()
    return {"ok": True}
