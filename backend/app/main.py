import secrets
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from .database import engine, Base, garantir_colunas_novas, SessionLocal
from .routers import (
    import_router, divergencias_router, dashboard_router, auth_router,
    usuarios_router, auditoria_router, cadastros_router, fechamento_router,
    backup_router, ml_router, compras_router, voz_router,
    baixas_operacionais_router, integracoes_router, shelf_life_router,
    ajustes_inventario_router, producao_router, movimentados_router,
    fefo_router,
)
from . import models
from .auth import hash_senha
from .bootstrap import rodar_bootstrap_completo

backup_router.fazer_backup_automatico()  # ANTES de qualquer migração/bootstrap tocar no banco

Base.metadata.create_all(bind=engine)
garantir_colunas_novas()
rodar_bootstrap_completo(SessionLocal)

# Garante que hipóteses novas do catálogo (ex: adicionadas numa atualização)
# entrem mesmo em bancos que já existiam antes dela - idempotente (só
# insere o que ainda não existe), não afeta pesos já ajustados pelo uso.
from .hipoteses_config import HIPOTESES as _HIPOTESES_CATALOGO
with SessionLocal() as _db_seed:
    for _codigo, _nome, _descricao in _HIPOTESES_CATALOGO:
        if not _db_seed.query(models.Hipotese).filter_by(codigo=_codigo).first():
            _db_seed.add(models.Hipotese(codigo=_codigo, nome=_nome, descricao=_descricao, peso_padrao=20.0))
    _db_seed.commit()

from . import scheduler
scheduler.iniciar_agendador()


def _bootstrap_admin_inicial():
    """Se o banco não tem nenhum usuário ainda (primeira vez rodando esta
    versão com autenticação), cria um admin com senha aleatória e imprime
    no console - só dessa vez. Sem isso ninguém conseguiria fazer o
    primeiro login."""
    db = SessionLocal()
    try:
        if db.query(models.Usuario).count() > 0:
            return
        senha_gerada = secrets.token_urlsafe(9)
        admin = models.Usuario(
            username="admin", nome_exibicao="Administrador",
            senha_hash=hash_senha(senha_gerada), papel="admin", ativo=True,
        )
        db.add(admin)
        db.commit()
        print("\n" + "=" * 60)
        print("ATLAS - usuário administrador criado automaticamente:")
        print(f"   username: admin")
        print(f"   senha:    {senha_gerada}")
        print("   Troque essa senha depois de logar (tela Usuários).")
        print("=" * 60 + "\n")
    finally:
        db.close()


_bootstrap_admin_inicial()

if not os.environ.get("ATLAS_SECRET_KEY") and not os.environ.get("DATABASE_URL", "sqlite:///./atlas.db").startswith("sqlite"):
    print(
        "\nATLAS - AVISO: você está usando um banco externo (provavelmente deploy em nuvem) "
        "mas não definiu ATLAS_SECRET_KEY. Se o disco for reiniciado, a chave de sessão muda e "
        "todo mundo é deslogado. Defina ATLAS_SECRET_KEY como variável de ambiente fixa no seu provedor.\n"
    )

app = FastAPI(title="Atlas - Inteligência de Estoque", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ATLAS_ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(usuarios_router.router, prefix="/api")
app.include_router(auditoria_router.router, prefix="/api")
app.include_router(cadastros_router.router, prefix="/api")
app.include_router(fechamento_router.router, prefix="/api")
app.include_router(backup_router.router, prefix="/api")
app.include_router(ml_router.router, prefix="/api")
app.include_router(import_router.router, prefix="/api")
app.include_router(divergencias_router.router, prefix="/api")
app.include_router(dashboard_router.router, prefix="/api")
app.include_router(compras_router.router, prefix="/api")
app.include_router(voz_router.router, prefix="/api")
app.include_router(baixas_operacionais_router.router, prefix="/api")
app.include_router(integracoes_router.router, prefix="/api")
app.include_router(shelf_life_router.router, prefix="/api")
app.include_router(ajustes_inventario_router.router, prefix="/api")
app.include_router(producao_router.router, prefix="/api")
app.include_router(movimentados_router.router, prefix="/api")
app.include_router(fefo_router.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# O mount de arquivos estáticos tem que ser o ÚLTIMO registrado: um Mount em
# "/" intercepta qualquer caminho que ainda não tenha sido resolvido acima.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
