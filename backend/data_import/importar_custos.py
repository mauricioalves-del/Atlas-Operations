"""
Atualiza o custo unitário dos produtos a partir de um CSV com colunas
sku, custo_unitario.

Uso: python -m data_import.importar_custos --arquivo caminho/custos.csv
"""
import argparse
import pandas as pd
from app.database import SessionLocal
from app import models
from app.csv_utils import parse_sku, parse_decimal

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arquivo", required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.arquivo, dtype=str)
    db = SessionLocal()
    atualizados, ignorados = 0, []
    for _, row in df.iterrows():
        sku = parse_sku(row["sku"])
        custo = parse_decimal(row["custo_unitario"])
        produto = db.query(models.Produto).filter_by(sku=sku).first()
        if not produto:
            ignorados.append(sku)
            continue
        produto.custo_unitario = custo
        atualizados += 1
    db.commit()
    db.close()
    print(f"Produtos atualizados: {atualizados}")
    if ignorados:
        print(f"SKUs não encontrados no cadastro (ignorados): {ignorados}")
