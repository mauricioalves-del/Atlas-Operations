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


EXCLUIDOS_DA_CONTAGEM_DIARIA_PADRAO = [
    "Almox_SP_Loja", "Almox_Box_2", "Almox_Box", "Almox_SP_Degustacao", "Almox_SP_Ativacao",
]


def seed_catalogo(db: Session):
    """Hipóteses e almoxarifados - não dependem de CSV, sempre roda."""
    for codigo, nome, descricao in HIPOTESES:
        if not db.query(models.Hipotese).filter_by(codigo=codigo).first():
            db.add(models.Hipotese(codigo=codigo, nome=nome, descricao=descricao, peso_padrao=20.0))
    for codigo, nome in ALMOXARIFADOS_PADRAO:
        if not db.query(models.Almoxarifado).filter_by(codigo=codigo).first():
            db.add(models.Almoxarifado(codigo=codigo, nome_exibicao=nome, participa_contagem_diaria=codigo not in EXCLUIDOS_DA_CONTAGEM_DIARIA_PADRAO))
    db.commit()


def reprocessar_almoxarifados_nao_mapeados(db: Session):
    """Corrige em massa fechamentos JÁ importados que ficaram com o
    almoxarifado gravado como "NAO_MAPEADO__<valor original>" (ver
    hipoteses_config.normalizar_almoxarifado).

    Por que isso é necessário e por que editar a tela Cadastros >
    Almoxarifados não resolve sozinho (30/09/2026, caso real: "Pátio
    Paulista" aparecia como NAO_MAPEADO__ mesmo depois de cadastrar o
    código lá): a normalização só roda NO MOMENTO DA IMPORTAÇÃO da
    planilha de fechamento (ver fechamento_router.importar_fechamento) -
    o resultado fica gravado como texto direto em várias tabelas
    (FechamentoInventario, ItemFechamento, AcaoPosInventario, Divergencia,
    MovimentacaoHistorico), sem nenhuma referência viva ao cadastro de
    Almoxarifado. Cadastrar um código novo em Cadastros só afeta
    IMPORTAÇÕES FUTURAS - não reprocessa o que já foi importado antes. Da
    mesma forma, adicionar uma palavra-chave nova em
    ALMOXARIFADO_DE_PARA_PREFIXOS (hipoteses_config.py) só resolve o
    problema pra frente, a menos que os registros antigos sejam
    reprocessados manualmente - é isso que esta função faz, sozinha, a
    cada boot do backend: para cada valor ainda marcado NAO_MAPEADO__,
    tenta normalizar de novo o valor original (a parte depois do prefixo)
    com as regras ATUAIS de ALMOXARIFADO_DE_PARA_PREFIXOS: se agora
    resolve pra um código oficial (por causa de uma palavra-chave
    adicionada depois da importação original), atualiza todas as tabelas
    acima que guardam essa cópia. Idempotente e seguro de rodar sempre:
    se não sobrar nenhum NAO_MAPEADO__ que hoje já resolveria, não faz
    nada; nunca derruba o boot do servidor se algo der errado."""
    from .hipoteses_config import normalizar_almoxarifado

    tabelas = [
        models.FechamentoInventario, models.ItemFechamento, models.AcaoPosInventario,
        models.Divergencia, models.MovimentacaoHistorico,
    ]
    try:
        valores_antigos = set()
        for tabela in tabelas:
            for (v,) in db.query(tabela.almoxarifado).distinct().all():
                if v and v.startswith("NAO_MAPEADO__"):
                    valores_antigos.add(v)

        total_corrigidos = 0
        for valor_antigo in valores_antigos:
            bruto = valor_antigo[len("NAO_MAPEADO__"):]
            novo_codigo = normalizar_almoxarifado(bruto)
            if novo_codigo == valor_antigo or novo_codigo.startswith("NAO_MAPEADO__"):
                continue  # ainda não bate com nenhuma palavra-chave conhecida hoje
            for tabela in tabelas:
                n = (
                    db.query(tabela)
                    .filter(tabela.almoxarifado == valor_antigo)
                    .update({"almoxarifado": novo_codigo}, synchronize_session=False)
                )
                total_corrigidos += n
            print(f"Atlas: reprocessado almoxarifado '{valor_antigo}' -> '{novo_codigo}' ({total_corrigidos} registro(s) corrigido(s) até agora).")

        if total_corrigidos:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Atlas: falha ao reprocessar almoxarifados NAO_MAPEADO__ ({type(e).__name__}: {e}) - siga normalmente, tenta de novo no próximo boot.")


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
        # Existe um arquivo, mas pode ter sido treinado com outra versão
        # do scikit-learn (ex: no computador local do usuário, com um
        # pip diferente do ambiente de nuvem) - carregar um modelo assim
        # quebra a previsão em tempo de execução, não no boot, o que é
        # bem mais difícil de diagnosticar. Testa aqui, no boot, e
        # descarta/retreina se estiver incompatível.
        import joblib
        try:
            joblib.load(MODEL_PATH)
            return  # carregou normalmente, nada a fazer
        except Exception as e:
            print(f"Atlas: model.joblib existente está incompatível com o ambiente atual ({type(e).__name__}: {e}) - descartando e retreinando do zero.")
            os.remove(MODEL_PATH)

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
        reprocessar_almoxarifados_nao_mapeados(db)
        seed_dados_historicos(db)
    finally:
        db.close()
    treinar_modelo_se_ausente()
