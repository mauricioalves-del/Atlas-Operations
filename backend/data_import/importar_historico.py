"""
Importa atlas_casos_historicos_categorizados.csv para movimentacoes_historico,
já com: SKU como texto, almoxarifado normalizado (de-para com correção do bug
de encoding), e hipotese_confirmada mapeada pelo dicionário auditável de
app/hipoteses_config.py (nenhuma categoria é descartada - ver comentário lá).

Uso: python -m data_import.importar_historico --arquivo caminho/atlas_casos_historicos_categorizados.csv
"""
import argparse
import pandas as pd
from app.database import SessionLocal
from app import models
from app.csv_utils import parse_sku, parse_decimal
from app.hipoteses_config import MAPA_CATEGORIA_BRUTA_PARA_CODIGO, normalizar_almoxarifado


def importar(caminho_csv: str):
    df = pd.read_csv(caminho_csv, dtype={"Id_Produto": str})

    categoria_bruta = df["Hipotese_Sugerida"].astype(str).str.strip()
    nao_mapeadas = sorted(set(categoria_bruta) - set(MAPA_CATEGORIA_BRUTA_PARA_CODIGO))
    if nao_mapeadas:
        raise ValueError(f"Categorias sem mapeamento - adicione em hipoteses_config.py: {nao_mapeadas}")

    db = SessionLocal()
    inseridos, ignorados_sem_data = 0, 0
    objetos = []

    for _, row in df.iterrows():
        data_str = str(row["Data"]).split(" ")[0]  # descarta timestamp 00:00:00
        try:
            data_mov = pd.to_datetime(data_str).date()
        except Exception:
            ignorados_sem_data += 1
            continue

        sku = parse_sku(row["Id_Produto"])
        almoxarifado = normalizar_almoxarifado(row["Almoxarifado_Origem_Arquivo"])
        divergencia_qtd = parse_decimal(row["Divergencia_Qtd"])
        valor = parse_decimal(row["Valor"])
        hipotese = MAPA_CATEGORIA_BRUTA_PARA_CODIGO[str(row["Hipotese_Sugerida"]).strip()]

        objetos.append(models.MovimentacaoHistorico(
            sku=sku,
            almoxarifado=almoxarifado,
            categoria_produto=row.get("Grupo"),
            data_movimento=data_mov,
            entrada=0, saida=0,
            saldo_sistema=parse_decimal(row.get("Sistema", 0)),
            saldo_fisico=parse_decimal(row.get("Contagem", 0)),
            divergencia=divergencia_qtd,
            valor_divergencia=valor,
            observacao_original=row.get("Obs"),
            prejuizo_confirmado=str(row.get("Prejuizo", "")).strip().lower() == "sim",
            hipotese_confirmada=hipotese,
            status="Historico_Resolvido",
        ))
        inseridos += 1

    # bulk_save_objects em vez de várias chamadas de db.add() - testado e
    # confirmado durante a preparação do deploy em nuvem: inserir centenas
    # de linhas via db.add()+commit dispara um bug real de desalinhamento
    # de colunas no Postgres (recurso "insertmanyvalues" do SQLAlchemy
    # 2.x, que usa RETURNING com um contador sentinela pra manter a ordem -
    # com muitas linhas de uma vez, o valor de uma coluna pode ir pra
    # outra). Em SQLite isso nunca aparecia, por isso passou despercebido.
    db.bulk_save_objects(objetos)
    db.commit()
    total = db.query(models.MovimentacaoHistorico).count()
    nao_mapeados_almox = db.query(models.MovimentacaoHistorico).filter(
        models.MovimentacaoHistorico.almoxarifado.like("NAO_MAPEADO__%")
    ).count()
    db.close()

    print(f"Inseridos: {inseridos} | ignorados por data inválida: {ignorados_sem_data}")
    print(f"Total em movimentacoes_historico agora: {total}")
    if nao_mapeados_almox:
        print(f"ATENÇÃO: {nao_mapeados_almox} registros com almoxarifado NAO_MAPEADO - revisar manualmente.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arquivo", required=True)
    args = parser.parse_args()
    importar(args.arquivo)
