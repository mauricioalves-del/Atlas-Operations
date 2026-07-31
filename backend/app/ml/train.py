"""
Treino do modelo estatístico do Atlas.

Correção principal aplicada aqui (pedida explicitamente antes de construir):
o dataset anterior (`lovable_casos_ml_seed.csv`) excluía silenciosamente
52% dos 1368 casos históricos rotulados - incluindo a categoria MAIS
frequente, "Sem divergência real (falso positivo)" (494 casos, 36%).
O modelo treinado com esse seed era estruturalmente incapaz de prever
"não há divergência real".

Aqui o treino parte direto do arquivo bruto categorizado
(atlas_casos_historicos_categorizados.csv) e usa o de-para completo e
auditável de app/hipoteses_config.py, que cobre TODAS as 16 categorias
brutas originais - nenhuma é descartada. Categoria bruta não mapeada faz
o script falhar alto (em vez de sumir silenciosamente do treino).

Segunda correção (fechando o loop de aprendizado): por padrão, o treino
agora também busca os casos confirmados pela equipe (tabela
CasoMLFeedback, alimentada sempre que alguém confirma uma divergência) e
incorpora eles junto do histórico bruto. Antes essa tabela só acumulava
dados sem uso real - o script tinha o parâmetro pra receber isso, mas
nada chamava. Use --sem-feedback se quiser treinar só com o histórico
bruto, sem os casos confirmados.

Uso:
    python -m app.ml.train --historico caminho/para/atlas_casos_historicos_categorizados.csv
    python -m app.ml.train --historico caminho/... --sem-feedback
"""
import argparse
import os
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from app.hipoteses_config import MAPA_CATEGORIA_BRUTA_PARA_CODIGO

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.joblib")

FEATURE_COLS = ["almoxarifado", "categoria_produto", "divergencia_qtd", "valor", "dia_semana"]


def carregar_e_mapear(caminho_csv: str) -> pd.DataFrame:
    df = pd.read_csv(caminho_csv, dtype={"Id_Produto": str})
    df = df.rename(columns={
        "Almoxarifado_Origem_Arquivo": "almoxarifado",
        "Grupo": "categoria_produto",
        "Divergencia_Qtd": "divergencia_qtd",
        "Valor": "valor",
        "Hipotese_Sugerida": "categoria_bruta",
        "Data": "data",
    })

    categoria_bruta = df["categoria_bruta"].astype(str).str.strip()
    nao_mapeadas = sorted(set(categoria_bruta) - set(MAPA_CATEGORIA_BRUTA_PARA_CODIGO))
    if nao_mapeadas:
        raise ValueError(
            "Categorias brutas sem mapeamento em hipoteses_config.py "
            f"(adicione-as antes de treinar): {nao_mapeadas}"
        )

    df["hipotese_confirmada"] = categoria_bruta.map(MAPA_CATEGORIA_BRUTA_PARA_CODIGO)
    df["dia_semana"] = pd.to_datetime(df["data"], errors="coerce").dt.dayofweek.fillna(-1)
    df["divergencia_qtd"] = pd.to_numeric(df["divergencia_qtd"], errors="coerce").fillna(0)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0)
    df["almoxarifado"] = df["almoxarifado"].fillna("Desconhecido")
    df["categoria_produto"] = df["categoria_produto"].fillna("Desconhecido")
    return df


def carregar_casos_feedback() -> pd.DataFrame:
    """Busca os casos que a equipe já confirmou (tabela CasoMLFeedback) e
    devolve no mesmo formato de FEATURE_COLS + hipotese_confirmada, pronto
    pra entrar no treino junto do histórico bruto."""
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        casos = db.query(models.CasoMLFeedback).all()
        if not casos:
            return pd.DataFrame(columns=FEATURE_COLS + ["hipotese_confirmada"])
        linhas = []
        for c in casos:
            dia_semana = pd.to_datetime(str(c.data_deteccao)).dayofweek if c.data_deteccao else -1
            linhas.append({
                "almoxarifado": c.almoxarifado or "Desconhecido",
                "categoria_produto": c.categoria_produto or "Desconhecido",
                "divergencia_qtd": c.divergencia_qtd or 0,
                "valor": c.valor_estimado or 0,
                "dia_semana": dia_semana,
                "hipotese_confirmada": c.hipotese_confirmada,
            })
        return pd.DataFrame(linhas)
    finally:
        db.close()


def _codigos_hipotese_validos() -> set:
    """Lê o catálogo de hipóteses direto do banco (não da lista fixa do
    código) - assim hipóteses criadas depois, pela tela de Cadastros,
    também são aceitas no treino."""
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        return {h.codigo for h in db.query(models.Hipotese).all()}
    finally:
        db.close()


def treinar(caminho_csv: str, casos_extra: pd.DataFrame = None, incluir_feedback: bool = True, salvar_em: str = MODEL_PATH):
    df = carregar_e_mapear(caminho_csv)
    df = df[FEATURE_COLS + ["hipotese_confirmada"]]

    partes = [df]
    if casos_extra is None and incluir_feedback:
        casos_extra = carregar_casos_feedback()

    if casos_extra is not None and len(casos_extra) > 0:
        casos_extra = casos_extra.copy()
        codigos_validos = _codigos_hipotese_validos()
        desconhecidos = set(casos_extra["hipotese_confirmada"]) - codigos_validos
        if desconhecidos:
            raise ValueError(f"Feedback com hipótese fora do catálogo cadastrado: {desconhecidos}")
        partes.append(casos_extra[FEATURE_COLS + ["hipotese_confirmada"]])
        print(f"Incluindo {len(casos_extra)} caso(s) confirmado(s) pela equipe (CasoMLFeedback) no treino.")

    df = pd.concat(partes, ignore_index=True)

    X = df[FEATURE_COLS]
    y = df["hipotese_confirmada"]

    print("Distribuição de classes usada no treino:")
    print(y.value_counts())

    try:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    except ValueError:
        print("Aviso: pelo menos uma hipótese tem poucos casos pra dividir treino/teste de forma estratificada - usando divisão aleatória simples.")
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), ["almoxarifado", "categoria_produto"])],
        remainder="passthrough",
    )
    modelo = Pipeline([
        ("pre", pre),
        ("rf", RandomForestClassifier(n_estimators=300, class_weight="balanced", max_depth=12, random_state=42)),
    ])
    modelo.fit(X_train, y_train)

    print("\nRelatório de avaliação (holdout 20%):")
    print(classification_report(y_test, modelo.predict(X_test), zero_division=0))

    joblib.dump(modelo, salvar_em)
    print(f"\nModelo salvo em {salvar_em}. Total de casos usados: {len(df)}")
    return modelo


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--historico", required=True)
    parser.add_argument("--sem-feedback", action="store_true", help="Não incluir os casos confirmados pela equipe (CasoMLFeedback) - treina só com o histórico bruto.")
    args = parser.parse_args()
    treinar(args.historico, incluir_feedback=not args.sem_feedback)
