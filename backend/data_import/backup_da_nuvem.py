"""
Baixa uma cópia completa do banco da nuvem (Postgres) pro seu
computador, num arquivo .db comum (SQLite) - pra ter uma rede de
segurança ANTES de subir qualquer atualização de código.

Uso:
    cd backend
    python -m data_import.backup_da_nuvem --origem "URL_EXTERNA_DO_POSTGRES"

Gera um arquivo como `backup_nuvem_2026-08-03_1610.db` na pasta atual.
Se algo der errado depois de um deploy, você restaura de volta com:

    python -m data_import.migrar_sqlite_para_postgres --origem backup_nuvem_2026-08-03_1610.db --destino "URL_EXTERNA_DO_POSTGRES" --limpar-destino

Recomendação: rode este backup toda vez, antes de clicar em
atualizar.ps1 - leva poucos segundos e evita ter que repreencher tudo
de novo caso algo dê errado no deploy.
"""
import argparse
from datetime import datetime
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base

# Mesma ordem usada na migração (SQLite -> Postgres) - aqui a ordem não
# afeta a gravação em si (SQLite não força a integridade referencial por
# padrão), mas mantém os dois scripts consistentes e fáceis de comparar.
ORDEM_MODELOS = [
    models.Usuario, models.Hipotese, models.Almoxarifado, models.Produto, models.Fornecedor,
    models.LoteImportacao, models.MovimentacaoHistorico, models.Divergencia, models.FechamentoInventario,
    models.ItemFechamento, models.AcaoPosInventario, models.ConciliacaoCiencia, models.PedidoCompra,
    models.RecebimentoPedido, models.CasoMLFeedback, models.EstadoTreinoML, models.Transferencia,
    models.OrdemProducao, models.ConsumoOP, models.FichaTecnicaBOM, models.Faturamento, models.LogAuditoria,
]


def fazer_backup(origem: str, destino: str):
    engine_origem = create_engine(origem)
    engine_destino = create_engine(f"sqlite:///{destino}")
    Base.metadata.create_all(bind=engine_destino)

    SessaoOrigem = sessionmaker(bind=engine_origem)
    SessaoDestino = sessionmaker(bind=engine_destino)
    db_origem = SessaoOrigem()
    db_destino = SessaoDestino()

    insp_origem = inspect(engine_origem)
    tabelas_origem = set(insp_origem.get_table_names())
    insp_destino = inspect(engine_destino)

    total_geral = 0
    for modelo in ORDEM_MODELOS:
        if modelo.__tablename__ not in tabelas_origem:
            continue
        linhas = db_origem.query(modelo).all()
        if not linhas:
            continue
        colunas = [c["name"] for c in insp_destino.get_columns(modelo.__tablename__)]
        objetos = []
        for linha in linhas:
            dados = {c: getattr(linha, c) for c in colunas if hasattr(linha, c)}
            objetos.append(modelo(**dados))
        db_destino.bulk_save_objects(objetos)
        db_destino.commit()
        total_geral += len(objetos)
        print(f"{modelo.__tablename__}: {len(objetos)} linhas salvas")

    db_origem.close()
    db_destino.close()
    print(f"\nBackup concluído: {destino} ({total_geral} linhas no total)")
    print("Guarde esse arquivo num lugar seguro - ele é o seu ponto de restauração.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--origem", required=True, help="Connection string do Postgres na nuvem (postgresql://...)")
    parser.add_argument("--destino", default=None, help="Nome do arquivo de backup (padrão: backup_nuvem_DATA_HORA.db)")
    args = parser.parse_args()

    origem = args.origem
    if origem.startswith("postgres://"):
        origem = origem.replace("postgres://", "postgresql://", 1)

    destino = args.destino or f"backup_nuvem_{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"
    fazer_backup(origem, destino)
