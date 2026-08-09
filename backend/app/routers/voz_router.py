from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..audit import registrar_log
from ..database import get_db
from ..deps import obter_usuario_atual

router = APIRouter(prefix="/voz", tags=["voz"])


class ComandoDeVozEntrada(BaseModel):
    transcricao: str
    view_destino: Optional[str] = None
    reconhecido: bool = False


@router.post("/comando")
def registrar_comando_de_voz(
    corpo: ComandoDeVozEntrada,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Grava na auditoria cada comando de voz dado no hub do Atlas -
    reconhecido (abriu algum módulo) ou não - pra manter rastreabilidade
    de como o pessoal está navegando por comando de voz (ex: "Atlas,
    cadastro")."""
    registrar_log(
        db, usuario.username, "comando_voz",
        entidade="modulo", entidade_id=corpo.view_destino,
        detalhes={"transcricao": corpo.transcricao, "reconhecido": corpo.reconhecido},
    )
    db.commit()
    return {"status": "ok"}
