"""
Inicialização automática de dados no primeiro boot contra um banco vazio.

Por que isso existe: localmente você roda os scripts de data_import à
mão, no seu terminal. Num deploy em nuvem (Render, Railway etc.) muitas
vezes não há terminal disponível sem pagar por isso - então o próprio
servidor, ao subir, detecta que o banco está vazio e importa os dados de
exemplo que vêm junto no deploy (pasta seed_data/). Cada etapa é
independente e não derruba o servidor se falhar - só loga o problema e
segue (o dashboard sobe de qualquer forma, só que sem aqueles dados).

Se você não quiser isso (por exemplo, já tem dados reais e não quer que
nada de exemplo seja importado), apague a pasta seed_data/ antes de
fazer deploy - com a pasta ausente, este módulo não faz nada.
"""
import os
from sqlalchemy.orm import Session

from . import models
from .hipoteses_config import HIPOTESES, ALMOXARIFADOS_PADRAO

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "seed_data")


def seed_catalogo(db: Session):
    """Hipóteses e almoxarifados - não dependem de CSV, sempre roda."""
    for codigo, nome, descricao in HIPOTESES:
        if not db.query(models.Hipotese).filter_by(codigo=codigo).first():
            db.add(models.Hipotese(codigo=codigo, nome=nome, descricao=descricao, peso_padrao=20.0))
    for codigo, nome in ALMOXARIFADOS_PADRAO:
        if not db.query(models.Almoxarifado).filter_by(codigo=codigo).first():
            db.add(models.Almoxarifado(codigo=codigo, nome_exibicao=nome))
    db.commit()


def seed_dados_historicos(db: Session):
    """Só roda se a tabela de histórico ainda estiver vazia e os CSVs de
    seed_data/ existirem no deploy."""
    if db.query(models.MovimentacaoHistorico).count() > 0:
        return
    if not os.path.isdir(SEED_DIR):
        print("Atlas: pasta seed_data/ não encontrada - pulando import automático de dados de exemplo.")
        return

    try:
        from data_import.seed_referencias import importar_produtos
        from data_import.importar_historico import importar as importar_historico_csv
        from data_import.importar_operacionais import (
            importar_transferencias, importar_ordens_producao, importar_consumo_op,
            importar_ficha_tecnica, importar_faturamento,
        )

        caminho_produtos = os.path.join(SEED_DIR, "produtos_import.csv")
        if os.path.exists(caminho_produtos):
            importar_produtos(db, caminho_produtos)
            db.commit()

        caminho_historico = os.path.join(SEED_DIR, "atlas_casos_historicos_categorizados.csv")
        if os.path.exists(caminho_historico):
            importar_historico_csv(caminho_historico)  # abre sua própria sessão internamente

        arquivos_operacionais = {
            "transferencias_import.csv": importar_transferencias,
            "ordens_producao_import.csv": importar_ordens_producao,
            "consumo_op_import.csv": importar_consumo_op,
            "ficha_tecnica_bom_import.csv": importar_ficha_tecnica,
            "faturamento_import.csv": importar_faturamento,
        }
        for nome_arquivo, fn in arquivos_operacionais.items():
            caminho = os.path.join(SEED_DIR, nome_arquivo)
            if os.path.exists(caminho):
                fn(db, caminho)
                db.commit()

        print("Atlas: dados de exemplo (histórico + operacionais) importados automaticamente no primeiro boot.")
    except Exception as e:
        print(f"Atlas: falha ao importar dados de exemplo automaticamente ({type(e).__name__}: {e}) - siga sem eles, ou importe manualmente depois.")


def treinar_modelo_se_ausente():
    from .ml.predict import MODEL_PATH
    if os.path.exists(MODEL_PATH):
        return
    caminho_historico = os.path.join(SEED_DIR, "atlas_casos_historicos_categorizados.csv")
    if not os.path.exists(caminho_historico):
        print("Atlas: sem modelo de ML treinado e sem CSV de treino em seed_data/ - o motor de regras funciona normalmente, só sem o sinal estatístico extra.")
        return
    try:
        from .ml.train import treinar
        treinar(caminho_historico)
        print("Atlas: modelo de ML treinado automaticamente no primeiro boot.")
    except Exception as e:
        print(f"Atlas: falha ao treinar modelo de ML automaticamente ({type(e).__name__}: {e}).")


def rodar_bootstrap_completo(SessionLocal):
    db = SessionLocal()
    try:
        seed_catalogo(db)
        seed_dados_historicos(db)
    finally:
        db.close()
    treinar_modelo_se_ausente()
