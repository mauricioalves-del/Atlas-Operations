"""Popula as tabelas de referência: hipoteses, almoxarifados, produtos.
Uso: python -m data_import.seed_referencias --produtos caminho/produtos_import.csv
"""
import argparse
import pandas as pd
from app.database import SessionLocal, Base, engine
from app import models

Base.metadata.create_all(bind=engine)
from app.hipoteses_config import HIPOTESES, ALMOXARIFADOS_PADRAO
from app.csv_utils import parse_sku


def seed_hipoteses(db):
    for codigo, nome, descricao in HIPOTESES:
        if not db.query(models.Hipotese).filter_by(codigo=codigo).first():
            db.add(models.Hipotese(codigo=codigo, nome=nome, descricao=descricao, peso_padrao=20.0))
    db.commit()
    print(f"hipoteses: {db.query(models.Hipotese).count()} registros")


EXCLUIDOS_DA_CONTAGEM_DIARIA_PADRAO = [
    "Almox_SP_Loja", "Almox_Box_2", "Almox_Box", "Almox_SP_Degustacao", "Almox_SP_Ativacao",
]


def seed_almoxarifados(db):
    for codigo, nome in ALMOXARIFADOS_PADRAO:
        if not db.query(models.Almoxarifado).filter_by(codigo=codigo).first():
            db.add(models.Almoxarifado(codigo=codigo, nome_exibicao=nome, participa_contagem_diaria=codigo not in EXCLUIDOS_DA_CONTAGEM_DIARIA_PADRAO))
    db.commit()
    print(f"almoxarifados: {db.query(models.Almoxarifado).count()} registros")


def importar_produtos(db, caminho_csv):
    df = pd.read_csv(caminho_csv, dtype=str)
    inseridos, ignorados = 0, 0
    for _, row in df.iterrows():
        sku = parse_sku(row["sku"])
        if db.query(models.Produto).filter_by(sku=sku).first():
            ignorados += 1
            continue
        db.add(models.Produto(
            sku=sku,
            descricao=row.get("descricao"),
            categoria_produto=row.get("categoria_produto"),
            unidade=row.get("unidade"),
        ))
        inseridos += 1
    db.commit()
    print(f"produtos: {inseridos} inseridos, {ignorados} ignorados (sku já existia)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--produtos", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    seed_hipoteses(db)
    seed_almoxarifados(db)
    importar_produtos(db, args.produtos)
    db.close()
