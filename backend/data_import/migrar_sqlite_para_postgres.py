"""
Migra os dados do seu atlas.db local (SQLite) para o Postgres na nuvem -
pra você não perder nada do que já construiu (fechamentos, custos, ações
de acompanhamento, pedidos de compra etc.) ao migrar pra nuvem.

Uso:
    1. Rode o Atlas na nuvem pelo menos uma vez (pra criar as tabelas vazias).
    2. No seu computador, com o atlas.db local intacto, rode:

       cd backend
       python -m data_import.migrar_sqlite_para_postgres --destino "postgresql://usuario:senha@host/banco" --origem atlas.db

    O --destino é a "External Database URL" que o Render mostra na tela
    do banco Postgres (Dashboard > seu banco > Connections).

    3. Depois de migrar, gere uma senha nova pra cada usuário na nuvem
       (a senha continua igual à local, então funciona - mas é boa
       prática trocar depois do primeiro acesso).

Importante: use bulk_save_objects (não db.add() um a um) - inserir muitas
linhas de uma vez via SQLAlchemy no Postgres tem um bug real de
desalinhamento de colunas com o recurso "insertmanyvalues" (testado e
corrigido nos importadores nesta mesma atualização). bulk_save_objects
evita esse caminho de código.
"""
import argparse
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base

# Ordem importa: tabelas "pai" primeiro, senão as referências soltas
# (não são FK rígidas na maioria dos casos, mas é mais seguro migrar
# assim mesmo pra manter os dados coerentes)
ORDEM_MODELOS = [
    models.Usuario,
    models.Hipotese,
    models.Almoxarifado,
    models.Produto,
    models.Fornecedor,
    models.LoteImportacao,           # referenciado por MovimentacaoHistorico e Divergencia
    models.MovimentacaoHistorico,    # depende de Hipotese e LoteImportacao
    models.Divergencia,              # depende de LoteImportacao
    models.FechamentoInventario,
    models.ItemFechamento,           # depende de FechamentoInventario, Divergencia e MovimentacaoHistorico
    models.AcaoPosInventario,        # depende de ItemFechamento e FechamentoInventario
    models.ConciliacaoCiencia,       # depende de FechamentoInventario
    models.PedidoCompra,             # depende de Fornecedor
    models.RecebimentoPedido,        # depende de PedidoCompra
    models.CasoMLFeedback,           # depende de Divergencia
    models.EstadoTreinoML,
    models.Transferencia,
    models.OrdemProducao,
    models.ConsumoOP,
    models.FichaTecnicaBOM,
    models.Faturamento,
    models.LogAuditoria,
]


def limpar_destino(engine_destino):
    """Apaga os dados de todas as tabelas no destino, na ordem inversa
    (filhas antes das pais) - usado quando você já migrou antes e quer
    substituir tudo por uma versão mais atual, sem duplicar linhas."""
    SessaoDestino = sessionmaker(bind=engine_destino)
    db = SessaoDestino()
    for modelo in reversed(ORDEM_MODELOS):
        n = db.query(modelo).delete()
        if n:
            print(f"{modelo.__tablename__}: {n} linhas removidas (limpeza antes de migrar de novo)")
    db.commit()
    db.close()


def migrar(origem: str, destino: str, limpar: bool = False):
    engine_origem = create_engine(f"sqlite:///{origem}")
    engine_destino = create_engine(destino)

    Base.metadata.create_all(bind=engine_destino)  # garante que as tabelas existem no destino

    if limpar:
        limpar_destino(engine_destino)
        print()

    SessaoOrigem = sessionmaker(bind=engine_origem)
    SessaoDestino = sessionmaker(bind=engine_destino)
    db_origem = SessaoOrigem()
    db_destino = SessaoDestino()

    insp_origem = inspect(engine_origem)
    tabelas_origem = set(insp_origem.get_table_names())
    insp_destino = inspect(engine_destino)

    for modelo in ORDEM_MODELOS:
        if modelo.__tablename__ not in tabelas_origem:
            print(f"{modelo.__tablename__}: tabela não existe na origem (módulo mais novo que essa versão do banco local - normal, pulando)")
            continue

        linhas = db_origem.query(modelo).all()
        if not linhas:
            print(f"{modelo.__tablename__}: 0 linhas (vazio, pulando)")
            continue

        colunas = [c["name"] for c in insp_destino.get_columns(modelo.__tablename__)]
        objetos = []
        for linha in linhas:
            dados = {c: getattr(linha, c) for c in colunas if hasattr(linha, c)}
            objetos.append(modelo(**dados))

        db_destino.bulk_save_objects(objetos)
        db_destino.commit()
        print(f"{modelo.__tablename__}: {len(objetos)} linhas migradas")

    db_origem.close()
    db_destino.close()
    print("\nMigração concluída.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--origem", default="atlas.db", help="Caminho do atlas.db local")
    parser.add_argument("--destino", required=True, help="Connection string do Postgres na nuvem (postgresql://...)")
    parser.add_argument("--limpar-destino", action="store_true",
                         help="Apaga os dados já existentes no destino antes de migrar - use isso se já migrou antes "
                              "e quer substituir tudo por uma versão mais atual (evita duplicar linhas).")
    args = parser.parse_args()
    destino = args.destino
    if destino.startswith("postgres://"):
        destino = destino.replace("postgres://", "postgresql://", 1)
    migrar(args.origem, destino, limpar=args.limpar_destino)
