from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import requer_papel, obter_usuario_atual
from ..audit import registrar_log
from ..ml import predict as ml_predict

router = APIRouter(tags=["cadastros"])


# ---------------- Produtos ----------------

@router.get("/produtos", response_model=list[schemas.ProdutoOut])
def listar_produtos(incluir_inativos: bool = False, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    q = db.query(models.Produto)
    if not incluir_inativos:
        q = q.filter(models.Produto.ativo.is_(True))
    return q.order_by(models.Produto.sku).all()


@router.post("/produtos", response_model=schemas.ProdutoOut)
def criar_produto(payload: schemas.ProdutoCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    if db.query(models.Produto).filter_by(sku=payload.sku).first():
        raise HTTPException(400, "Já existe um produto com esse SKU.")
    novo = models.Produto(**payload.model_dump(), ativo=True)
    db.add(novo)
    registrar_log(db, usuario.username, "criar_produto", entidade="produto", entidade_id=payload.sku)
    db.commit()
    db.refresh(novo)
    return novo


@router.patch("/produtos/{sku}", response_model=schemas.ProdutoOut)
def atualizar_produto(sku: str, payload: schemas.ProdutoAtualizar, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter_by(sku=sku).first()
    if not produto:
        raise HTTPException(404, "Produto não encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(produto, campo, valor)
    registrar_log(db, usuario.username, "atualizar_produto", entidade="produto", entidade_id=sku, detalhes=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(produto)
    return produto


def _contar_usos_sku(db: Session, sku: str) -> int:
    total = 0
    total += db.query(models.Divergencia).filter_by(sku=sku).count()
    total += db.query(models.MovimentacaoHistorico).filter_by(sku=sku).count()
    total += db.query(models.Transferencia).filter_by(sku=sku).count()
    total += db.query(models.OrdemProducao).filter_by(sku_produto_final=sku).count()
    total += db.query(models.ConsumoOP).filter_by(sku_material=sku).count()
    total += db.query(models.Faturamento).filter_by(sku=sku).count()
    return total


@router.delete("/produtos/{sku}")
def excluir_produto(sku: str, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter_by(sku=sku).first()
    if not produto:
        raise HTTPException(404, "Produto não encontrado.")
    usos = _contar_usos_sku(db, sku)
    if usos > 0:
        raise HTTPException(400, f"Esse SKU aparece em {usos} registro(s) (movimentações, divergências, OPs...). Use 'desativar' em vez de excluir, pra não perder o histórico.")
    registrar_log(db, usuario.username, "excluir_produto", entidade="produto", entidade_id=sku)
    db.delete(produto)
    db.commit()
    return {"ok": True}


# ---------------- Almoxarifados ----------------

@router.get("/almoxarifados-cadastro", response_model=list[schemas.AlmoxarifadoOut])
def listar_almoxarifados_cadastro(incluir_inativos: bool = False, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    q = db.query(models.Almoxarifado)
    if not incluir_inativos:
        q = q.filter(models.Almoxarifado.ativo.is_(True))
    return q.order_by(models.Almoxarifado.codigo).all()


@router.post("/almoxarifados-cadastro", response_model=schemas.AlmoxarifadoOut)
def criar_almoxarifado(payload: schemas.AlmoxarifadoCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    if db.query(models.Almoxarifado).filter_by(codigo=payload.codigo).first():
        raise HTTPException(400, "Já existe um almoxarifado com esse código.")
    novo = models.Almoxarifado(**payload.model_dump(), ativo=True)
    db.add(novo)
    registrar_log(db, usuario.username, "criar_almoxarifado", entidade="almoxarifado", entidade_id=payload.codigo)
    db.commit()
    db.refresh(novo)
    return novo


@router.patch("/almoxarifados-cadastro/{codigo}", response_model=schemas.AlmoxarifadoOut)
def atualizar_almoxarifado(codigo: str, payload: schemas.AlmoxarifadoAtualizar, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    almox = db.query(models.Almoxarifado).filter_by(codigo=codigo).first()
    if not almox:
        raise HTTPException(404, "Almoxarifado não encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(almox, campo, valor)
    registrar_log(db, usuario.username, "atualizar_almoxarifado", entidade="almoxarifado", entidade_id=codigo, detalhes=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(almox)
    return almox


@router.delete("/almoxarifados-cadastro/{codigo}")
def excluir_almoxarifado(codigo: str, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    almox = db.query(models.Almoxarifado).filter_by(codigo=codigo).first()
    if not almox:
        raise HTTPException(404, "Almoxarifado não encontrado.")
    usos = (
        db.query(models.Divergencia).filter_by(almoxarifado=codigo).count()
        + db.query(models.MovimentacaoHistorico).filter_by(almoxarifado=codigo).count()
    )
    if usos > 0:
        raise HTTPException(400, f"Esse almoxarifado aparece em {usos} registro(s). Use 'desativar' em vez de excluir.")
    registrar_log(db, usuario.username, "excluir_almoxarifado", entidade="almoxarifado", entidade_id=codigo)
    db.delete(almox)
    db.commit()
    return {"ok": True}


# ---------------- Hipóteses ----------------

@router.get("/hipoteses-cadastro", response_model=list[schemas.HipoteseOut])
def listar_hipoteses_cadastro(incluir_inativos: bool = False, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    q = db.query(models.Hipotese)
    if not incluir_inativos:
        q = q.filter(models.Hipotese.ativo.is_(True))
    return q.order_by(models.Hipotese.codigo).all()


@router.post("/hipoteses-cadastro", response_model=schemas.HipoteseOut)
def criar_hipotese(payload: schemas.HipoteseCreate, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    if db.query(models.Hipotese).filter_by(codigo=payload.codigo).first():
        raise HTTPException(400, "Já existe uma hipótese com esse código.")
    novo = models.Hipotese(**payload.model_dump(), ativo=True)
    db.add(novo)
    registrar_log(db, usuario.username, "criar_hipotese", entidade="hipotese", entidade_id=payload.codigo)
    db.commit()
    db.refresh(novo)
    return novo


@router.patch("/hipoteses-cadastro/{codigo}", response_model=schemas.HipoteseOut)
def atualizar_hipotese(codigo: str, payload: schemas.HipoteseAtualizar, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    hip = db.query(models.Hipotese).filter_by(codigo=codigo).first()
    if not hip:
        raise HTTPException(404, "Hipótese não encontrada.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(hip, campo, valor)
    registrar_log(db, usuario.username, "atualizar_hipotese", entidade="hipotese", entidade_id=codigo, detalhes=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(hip)
    ml_predict.invalidar_cache()
    return hip


@router.delete("/hipoteses-cadastro/{codigo}")
def excluir_hipotese(codigo: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    hip = db.query(models.Hipotese).filter_by(codigo=codigo).first()
    if not hip:
        raise HTTPException(404, "Hipótese não encontrada.")
    usos = (
        db.query(models.MovimentacaoHistorico).filter_by(hipotese_confirmada=codigo).count()
        + db.query(models.Divergencia).filter_by(hipotese_confirmada=codigo).count()
        + db.query(models.CasoMLFeedback).filter_by(hipotese_confirmada=codigo).count()
    )
    if usos > 0:
        raise HTTPException(400, f"Essa hipótese aparece em {usos} registro(s) de casos já confirmados. Não pode ser excluída (o histórico de aprendizado depende dela) - use 'desativar'.")
    registrar_log(db, usuario.username, "excluir_hipotese", entidade="hipotese", entidade_id=codigo)
    db.delete(hip)
    db.commit()
    return {"ok": True}
