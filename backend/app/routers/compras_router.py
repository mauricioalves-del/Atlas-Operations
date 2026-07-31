"""
Controle de Estoque Externo - pedidos de compra e recebimentos parciais.

Contexto de negócio: fornecedores entregam pedidos fracionados (ex:
compra de embalagens chega em várias remessas ao longo do tempo). Sem
rastrear isso, toda contagem física feita antes da entrega completa
parece uma "falta" real de estoque - quando na verdade é só mercadoria
ainda em trânsito com o fornecedor.

O Atlas não é o sistema de compras da empresa - este módulo registra só
o suficiente (pedido + recebimentos) pra alimentar o motor de
investigação (investigation.py), que consulta isso pra explicar
divergências como "Pedido de Compra Pendente" em vez de perda real. Como
Movimentados e Fechamento de Inventário chamam a mesma função investigar(),
o efeito vale pros dois fluxos automaticamente.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import obter_usuario_atual, requer_papel
from ..audit import registrar_log

router = APIRouter(prefix="/compras", tags=["controle_estoque_externo"])


def _enriquecer_pedido(db: Session, pedido: models.PedidoCompra) -> models.PedidoCompra:
    """Anexa campos calculados (transientes, não colunas) - recebido
    total, pendente, % concluído e se está atrasado."""
    recebido = sum(
        r.quantidade_recebida for r in db.query(models.RecebimentoPedido).filter_by(pedido_id=pedido.id).all()
    )
    pedido.quantidade_recebida_total = round(recebido, 3)
    pedido.quantidade_pendente = round(max(0, pedido.quantidade_pedida - recebido), 3)
    pedido.pct_concluido = round(min(100, recebido / pedido.quantidade_pedida * 100), 1) if pedido.quantidade_pedida else 0
    pedido.atrasado = bool(
        pedido.status not in ("Concluido", "Cancelado")
        and pedido.prazo_entrega_previsto
        and pedido.prazo_entrega_previsto < datetime.utcnow().date()
    )
    return pedido


def _atualizar_status_pedido(db: Session, pedido: models.PedidoCompra):
    recebido = sum(
        r.quantidade_recebida for r in db.query(models.RecebimentoPedido).filter_by(pedido_id=pedido.id).all()
    )
    if pedido.status == "Cancelado":
        return
    if recebido <= 0:
        pedido.status = "Aberto"
    elif recebido < pedido.quantidade_pedida:
        pedido.status = "Parcialmente_Recebido"
    else:
        pedido.status = "Concluido"


# ==================== Fornecedores ====================

@router.get("/fornecedores", response_model=list[schemas.FornecedorOut])
def listar_fornecedores(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    return db.query(models.Fornecedor).order_by(models.Fornecedor.nome).all()


@router.post("/fornecedores", response_model=schemas.FornecedorOut)
def criar_fornecedor(payload: schemas.FornecedorCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    if db.query(models.Fornecedor).filter_by(nome=payload.nome).first():
        raise HTTPException(400, "Já existe um fornecedor com esse nome.")
    fornecedor = models.Fornecedor(**payload.model_dump())
    db.add(fornecedor)
    registrar_log(db, usuario.username, "criar_fornecedor", entidade="fornecedor", entidade_id=payload.nome)
    db.commit()
    db.refresh(fornecedor)
    return fornecedor


# ==================== Pedidos de compra ====================

@router.get("/pedidos/dashboard/kpis")
def dashboard_kpis_pedidos(usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    pedidos = db.query(models.PedidoCompra).all()
    pedidos = [_enriquecer_pedido(db, p) for p in pedidos]
    abertos = [p for p in pedidos if p.status in ("Aberto", "Parcialmente_Recebido")]
    atrasados = [p for p in abertos if p.atrasado]
    return {
        "total_pedidos": len(pedidos),
        "pedidos_abertos": len(abertos),
        "pedidos_atrasados": len(atrasados),
        "itens_pendentes_qtd": round(sum(p.quantidade_pendente for p in abertos), 2),
    }


@router.get("/pedidos", response_model=list[schemas.PedidoCompraOut])
def listar_pedidos(
    status: str | None = None,
    sku: str | None = None,
    almoxarifado: str | None = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    q = db.query(models.PedidoCompra)
    if status:
        q = q.filter_by(status=status)
    if sku:
        q = q.filter_by(sku=sku)
    if almoxarifado:
        q = q.filter_by(almoxarifado_destino=almoxarifado)
    pedidos = q.order_by(models.PedidoCompra.data_pedido.desc()).all()
    return [_enriquecer_pedido(db, p) for p in pedidos]


@router.post("/pedidos", response_model=schemas.PedidoCompraOut)
def criar_pedido(payload: schemas.PedidoCompraCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    dados = payload.model_dump()
    nome_fornecedor = dados.pop("fornecedor_nome", None)
    if nome_fornecedor and not dados.get("fornecedor_id"):
        fornecedor = db.query(models.Fornecedor).filter_by(nome=nome_fornecedor).first()
        if not fornecedor:
            fornecedor = models.Fornecedor(nome=nome_fornecedor)
            db.add(fornecedor)
            db.flush()
        dados["fornecedor_id"] = fornecedor.id

    pedido = models.PedidoCompra(**dados, status="Aberto", criado_por=usuario.username)
    db.add(pedido)
    registrar_log(db, usuario.username, "criar_pedido_compra", entidade="pedido_compra", entidade_id=payload.sku,
                  detalhes={"quantidade_pedida": payload.quantidade_pedida, "almoxarifado": payload.almoxarifado_destino})
    db.commit()
    db.refresh(pedido)
    return _enriquecer_pedido(db, pedido)


@router.get("/pedidos/{pedido_id}", response_model=schemas.PedidoCompraOut)
def detalhar_pedido(pedido_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoCompra).get(pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado.")
    return _enriquecer_pedido(db, pedido)


@router.patch("/pedidos/{pedido_id}", response_model=schemas.PedidoCompraOut)
def atualizar_pedido(pedido_id: int, payload: schemas.PedidoCompraAtualizar, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoCompra).get(pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado.")
    dados = payload.model_dump(exclude_unset=True)
    for campo, valor in dados.items():
        setattr(pedido, campo, valor)
    registrar_log(db, usuario.username, "atualizar_pedido_compra", entidade="pedido_compra", entidade_id=pedido_id, detalhes=dados)
    db.commit()
    db.refresh(pedido)
    return _enriquecer_pedido(db, pedido)


@router.delete("/pedidos/{pedido_id}")
def excluir_pedido(pedido_id: int, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoCompra).get(pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado.")
    db.query(models.RecebimentoPedido).filter_by(pedido_id=pedido_id).delete()
    registrar_log(db, usuario.username, "excluir_pedido_compra", entidade="pedido_compra", entidade_id=pedido_id)
    db.delete(pedido)
    db.commit()
    return {"ok": True}


# ==================== Recebimentos (entregas parciais) ====================

@router.get("/pedidos/{pedido_id}/recebimentos", response_model=list[schemas.RecebimentoPedidoOut])
def listar_recebimentos(pedido_id: int, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    return db.query(models.RecebimentoPedido).filter_by(pedido_id=pedido_id).order_by(models.RecebimentoPedido.data_recebimento).all()


@router.post("/pedidos/{pedido_id}/recebimentos", response_model=schemas.PedidoCompraOut)
def registrar_recebimento(pedido_id: int, payload: schemas.RecebimentoPedidoCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoCompra).get(pedido_id)
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado.")
    if pedido.status == "Cancelado":
        raise HTTPException(400, "Pedido cancelado não aceita novos recebimentos.")
    if payload.quantidade_recebida <= 0:
        raise HTTPException(400, "Quantidade recebida deve ser maior que zero.")

    recebimento = models.RecebimentoPedido(pedido_id=pedido_id, recebido_por=payload.recebido_por or usuario.username, **payload.model_dump(exclude={"recebido_por"}))
    db.add(recebimento)
    db.flush()
    _atualizar_status_pedido(db, pedido)

    registrar_log(db, usuario.username, "registrar_recebimento_pedido", entidade="pedido_compra", entidade_id=pedido_id,
                  detalhes={"quantidade_recebida": payload.quantidade_recebida, "novo_status": pedido.status})
    db.commit()
    db.refresh(pedido)
    return _enriquecer_pedido(db, pedido)


@router.delete("/recebimentos/{recebimento_id}")
def excluir_recebimento(recebimento_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    recebimento = db.query(models.RecebimentoPedido).get(recebimento_id)
    if not recebimento:
        raise HTTPException(404, "Recebimento não encontrado.")
    pedido = db.query(models.PedidoCompra).get(recebimento.pedido_id)
    db.delete(recebimento)
    db.flush()
    if pedido:
        _atualizar_status_pedido(db, pedido)
    registrar_log(db, usuario.username, "excluir_recebimento_pedido", entidade="recebimento_pedido", entidade_id=recebimento_id)
    db.commit()
    return {"ok": True}
