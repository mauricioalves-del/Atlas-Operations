import os
import shutil
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db, DATABASE_URL
from ..deps import requer_papel
from ..audit import registrar_log

router = APIRouter(prefix="/backup", tags=["backup"])

CAMINHO_DB_LOCAL = os.path.join(os.path.dirname(__file__), "..", "..", "atlas.db")
PASTA_BACKUPS = os.path.join(os.path.dirname(__file__), "..", "..", "backups")
MAX_BACKUPS_AUTOMATICOS = 15


def _eh_sqlite_local() -> bool:
    return DATABASE_URL.startswith("sqlite") and os.path.exists(CAMINHO_DB_LOCAL)


@router.get("/status")
def status(usuario: models.Usuario = Depends(requer_papel("admin"))):
    if not _eh_sqlite_local():
        return {
            "tipo_banco": "externo (Postgres ou outro)",
            "mensagem": "Backup por aqui só funciona pra SQLite local. Um banco Postgres/gerenciado deve ser "
                        "protegido pelas ferramentas de backup do próprio provedor (ex: snapshots automáticos do Render).",
            "backups_automaticos": [],
        }
    arquivos = sorted(os.listdir(PASTA_BACKUPS), reverse=True) if os.path.isdir(PASTA_BACKUPS) else []
    return {
        "tipo_banco": "sqlite local",
        "tamanho_atual_mb": round(os.path.getsize(CAMINHO_DB_LOCAL) / (1024 * 1024), 2),
        "backups_automaticos": arquivos[:MAX_BACKUPS_AUTOMATICOS],
    }


@router.get("/download")
def download(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Baixa uma cópia do banco atual agora mesmo - guarde esse arquivo
    fora do projeto antes de qualquer atualização de código."""
    if not _eh_sqlite_local():
        raise HTTPException(400, "Esse endpoint só funciona com SQLite local. Veja /backup/status para orientação sobre bancos externos.")
    nome = f"atlas_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    registrar_log(db, usuario.username, "download_backup")
    db.commit()
    return FileResponse(CAMINHO_DB_LOCAL, filename=nome, media_type="application/octet-stream")


@router.post("/restaurar")
async def restaurar(
    arquivo: UploadFile = File(...),
    confirmar: bool = False,
    usuario: models.Usuario = Depends(requer_papel("admin")),
):
    """Substitui o banco atual por um arquivo de backup enviado. É
    DESTRUTIVO - exige ?confirmar=true explicitamente. O banco atual é
    salvo automaticamente em backups/ antes de ser sobrescrito, então dá
    pra desfazer se restaurar o arquivo errado."""
    if not _eh_sqlite_local():
        raise HTTPException(400, "Restauração automática só funciona com SQLite local.")
    if not confirmar:
        raise HTTPException(400, "Isso substitui todos os dados atuais. Marque a confirmação na tela para continuar.")

    os.makedirs(PASTA_BACKUPS, exist_ok=True)
    pre_restauro = os.path.join(PASTA_BACKUPS, f"antes_de_restaurar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    shutil.copy2(CAMINHO_DB_LOCAL, pre_restauro)

    conteudo = await arquivo.read()
    with open(CAMINHO_DB_LOCAL, "wb") as f:
        f.write(conteudo)

    return {
        "ok": True,
        "mensagem": "Banco restaurado. Reinicie o servidor (Ctrl+C e suba de novo) para carregar os dados restaurados.",
        "backup_do_estado_anterior": os.path.basename(pre_restauro),
    }


def fazer_backup_automatico():
    """Chamado no startup do servidor - guarda uma cópia do banco atual
    ANTES de qualquer migração/bootstrap rodar. Mantém só os últimos
    MAX_BACKUPS_AUTOMATICOS arquivos, apaga os mais antigos."""
    if not _eh_sqlite_local():
        return
    try:
        os.makedirs(PASTA_BACKUPS, exist_ok=True)
        nome = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(CAMINHO_DB_LOCAL, os.path.join(PASTA_BACKUPS, nome))

        arquivos = sorted(
            [f for f in os.listdir(PASTA_BACKUPS) if f.startswith("auto_")],
            reverse=True,
        )
        for antigo in arquivos[MAX_BACKUPS_AUTOMATICOS:]:
            os.remove(os.path.join(PASTA_BACKUPS, antigo))
        print(f"Atlas: backup automático salvo em backups/{nome}")
    except Exception as e:
        print(f"Atlas: falha ao fazer backup automático ({type(e).__name__}: {e}) - o servidor continua normalmente.")
