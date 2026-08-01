"""
Importa as tabelas de apoio usadas pelo motor de investigação.
Uso:
    python -m data_import.importar_operacionais --pasta /caminho/para/csvs
Espera os arquivos: transferencias_import.csv, ordens_producao_import.csv,
consumo_op_import.csv, ficha_tecnica_bom_import.csv, faturamento_import.csv
"""
import argparse
import os
import pandas as pd
from app.database import SessionLocal
from app import models
from app.csv_utils import parse_sku, parse_decimal
from app.hipoteses_config import normalizar_almoxarifado


def _data(v):
    if pd.isna(v) or str(v).strip() == "":
        return None
    return pd.to_datetime(str(v).split(" ")[0]).date()


# bulk_save_objects (lista de objetos de uma vez) em vez de db.add() um a
# um - testado e confirmado durante a preparação do deploy em nuvem:
# inserir centenas/milhares de linhas via db.add()+commit dispara um bug
# real de desalinhamento de colunas no Postgres (recurso
# "insertmanyvalues" do SQLAlchemy 2.x, que usa RETURNING com um contador
# sentinela pra manter a ordem - com muitas linhas de uma vez, o valor de
# uma coluna pode ir pra outra). Em SQLite isso nunca aparecia.


def importar_transferencias(db, caminho):
    df = pd.read_csv(caminho, dtype=str)
    objetos = [
        models.Transferencia(
            sku=parse_sku(r["sku"]), descricao=r.get("descricao"),
            data_saida=_data(r["data_saida"]), data_entrada=_data(r.get("data_entrada")),
            documento=r.get("documento"),
            almoxarifado_origem=normalizar_almoxarifado(r["almoxarifado_origem"]) if r.get("almoxarifado_origem") else None,
            almoxarifado_destino=normalizar_almoxarifado(r["almoxarifado_destino"]) if r.get("almoxarifado_destino") else None,
            quantidade=parse_decimal(r["quantidade"]), lote=r.get("lote"),
        )
        for _, r in df.iterrows()
    ]
    db.bulk_save_objects(objetos)
    db.commit()
    print(f"transferencias: {len(objetos)} importados")


def importar_ordens_producao(db, caminho):
    df = pd.read_csv(caminho, dtype=str)
    existentes = {o.numero_op for o in db.query(models.OrdemProducao.numero_op).all()}
    objetos, ignorados, sem_numero = [], 0, 0
    for _, r in df.iterrows():
        numero_op = r.get("numero_op")
        if pd.isna(numero_op) or str(numero_op).strip() == "":
            sem_numero += 1
            continue
        numero_op = str(numero_op).strip()
        if numero_op in existentes:
            ignorados += 1
            continue
        objetos.append(models.OrdemProducao(
            numero_op=numero_op, sku_produto_final=parse_sku(r["sku_produto_final"]),
            descricao_produto=r.get("descricao_produto"),
            data_registro=_data(r["data_registro"]), data_producao=_data(r["data_producao"]),
            status=r.get("status"),
            qtd_prevista=parse_decimal(r["qtd_prevista"]), qtd_produzida=parse_decimal(r["qtd_produzida"]),
            qtd_saldo=parse_decimal(r["qtd_saldo"]),
        ))
    db.bulk_save_objects(objetos)
    db.commit()
    print(f"ordens_producao: {len(objetos)} importados, {ignorados} ignorados (numero_op duplicado), {sem_numero} ignorados (numero_op vazio)")


def importar_consumo_op(db, caminho):
    df = pd.read_csv(caminho, dtype=str)
    objetos, ignorados = [], 0
    for _, r in df.iterrows():
        numero_op = r.get("numero_op")
        if pd.isna(numero_op) or str(numero_op).strip() == "":
            ignorados += 1
            continue
        objetos.append(models.ConsumoOP(
            numero_op=str(numero_op).strip(), sku_produto_final=parse_sku(r["sku_produto_final"]),
            sku_material=parse_sku(r["sku_material"]), descricao_material=r.get("descricao_material"),
            qtd_consumo=parse_decimal(r["qtd_consumo"]), qtd_previsto=parse_decimal(r["qtd_previsto"]),
            qtd_diferenca=parse_decimal(r["qtd_diferenca"]),
            data_registro=_data(r["data_registro"]), data_producao=_data(r["data_producao"]),
            status=r.get("status"),
        ))
    db.bulk_save_objects(objetos)
    db.commit()
    print(f"consumo_op: {len(objetos)} importados, {ignorados} ignorados (numero_op vazio/ausente)")


def importar_ficha_tecnica(db, caminho):
    df = pd.read_csv(caminho, dtype=str)
    objetos = [
        models.FichaTecnicaBOM(
            sku_produto_final=parse_sku(r["sku_produto_final"]), produto_final=r.get("produto_final"),
            sku_item=parse_sku(r["sku_item"]), descricao_item=r.get("descricao_item"),
            qtd_padrao=parse_decimal(r["qtd_padrao"]), unidade=r.get("unidade"),
        )
        for _, r in df.iterrows()
    ]
    db.bulk_save_objects(objetos)
    db.commit()
    print(f"ficha_tecnica_bom: {len(objetos)} importados")


def importar_faturamento(db, caminho):
    df = pd.read_csv(caminho, dtype=str)
    objetos = [
        models.Faturamento(
            sku=parse_sku(r["sku"]), origem=r.get("origem"),
            data_faturamento=_data(r["data_faturamento"]), quantidade=parse_decimal(r["quantidade"]),
            descricao=r.get("descricao"),
        )
        for _, r in df.iterrows()
    ]
    db.bulk_save_objects(objetos)
    db.commit()
    print(f"faturamento: {len(objetos)} importados")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pasta", required=True)
    args = parser.parse_args()
    db = SessionLocal()

    arquivos = {
        "transferencias_import.csv": importar_transferencias,
        "ordens_producao_import.csv": importar_ordens_producao,
        "consumo_op_import.csv": importar_consumo_op,
        "ficha_tecnica_bom_import.csv": importar_ficha_tecnica,
        "faturamento_import.csv": importar_faturamento,
    }
    for nome, fn in arquivos.items():
        caminho = os.path.join(args.pasta, nome)
        if os.path.exists(caminho):
            fn(db, caminho)
        else:
            print(f"(pulado - não encontrado: {nome})")
    db.close()
