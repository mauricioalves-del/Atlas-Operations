"""
Configuração de conexão com o banco de dados.

Por padrão usa SQLite em arquivo (zero-config, roda em qualquer máquina sem
instalar nada). Em produção, basta setar a variável de ambiente DATABASE_URL
apontando para um Postgres (ex: postgresql+psycopg2://user:pass@host/atlas)
que o SQLAlchemy troca de banco sem precisar mudar nenhuma linha de código
do resto do projeto.
"""
import os
from collections import defaultdict
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./atlas.db")
# Alguns provedores (Render, Heroku) entregam a connection string como
# "postgres://..." mas o SQLAlchemy 2.x exige "postgresql://...".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def garantir_colunas_novas():
    """Auto-migração leve: se o banco já existia de uma versão anterior do
    Atlas e uma coluna nova foi adicionada a um modelo, isso a acrescenta
    via ALTER TABLE em vez de exigir recriar o banco do zero (só funciona
    para adicionar colunas, não para renomear/remover - suficiente para o
    estágio atual do projeto)."""
    inspecao = inspect(engine)
    if not inspecao.has_table("divergencias"):
        return  # banco novo - Base.metadata.create_all já cria certo
    colunas_existentes = {c["name"] for c in inspecao.get_columns("divergencias")}
    if "observacao_origem" not in colunas_existentes:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE divergencias ADD COLUMN observacao_origem VARCHAR"))
            conn.commit()

    colunas_produtos = {c["name"] for c in inspecao.get_columns("produtos")}
    if "custo_unitario" not in colunas_produtos:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE produtos ADD COLUMN custo_unitario FLOAT"))
            conn.commit()
    if "ativo" not in colunas_produtos:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE produtos ADD COLUMN ativo BOOLEAN DEFAULT 1"))
            conn.commit()

    if inspecao.has_table("conciliacoes_ciencia"):
        colunas_ciencia = {c["name"] for c in inspecao.get_columns("conciliacoes_ciencia")}
        if "papel_assinatura" not in colunas_ciencia:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE conciliacoes_ciencia ADD COLUMN papel_assinatura VARCHAR"))
                conn.commit()

    colunas_almox = {c["name"] for c in inspecao.get_columns("almoxarifados")}
    if "ativo" not in colunas_almox:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE almoxarifados ADD COLUMN ativo BOOLEAN DEFAULT 1"))
            conn.commit()
    if "participa_contagem_diaria" not in colunas_almox:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE almoxarifados ADD COLUMN participa_contagem_diaria BOOLEAN DEFAULT 1"))
            conn.commit()
        # ajuste inicial pedido explicitamente: esses almoxarifados não
        # fazem parte da contagem diária no planejamento atual. Fica
        # gravado como um dado comum (não é regra fixa no código) -
        # ajustável a qualquer momento pela tela Cadastros > Almoxarifados
        # se o planejamento interno mudar, sem precisar de outra atualização.
        excluidos_da_contagem_diaria = [
            "Almox_SP_Loja", "Almox_Box_2", "Almox_Box", "Almox_SP_Degustacao", "Almox_SP_Ativacao",
        ]
        with engine.connect() as conn:
            for codigo in excluidos_da_contagem_diaria:
                conn.execute(text("UPDATE almoxarifados SET participa_contagem_diaria = 0 WHERE codigo = :codigo"), {"codigo": codigo})
            conn.commit()

    colunas_hipoteses = {c["name"] for c in inspecao.get_columns("hipoteses")}
    if "ativo" not in colunas_hipoteses:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE hipoteses ADD COLUMN ativo BOOLEAN DEFAULT 1"))
            conn.commit()

    colunas_usuarios = {c["name"] for c in inspecao.get_columns("usuarios")}
    if "tentativas_falhas" not in colunas_usuarios:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN tentativas_falhas INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN bloqueado_ate TIMESTAMP"))
            conn.commit()

    # log_auditoria é uma tabela nova - Base.metadata.create_all já cria
    # se ainda não existir, sem precisar de ALTER TABLE aqui.

    if inspecao.has_table("itens_fechamento"):
        colunas_itens_fechamento = {c["name"] for c in inspecao.get_columns("itens_fechamento")}
        if "percentual_acuracia" not in colunas_itens_fechamento:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE itens_fechamento ADD COLUMN percentual_acuracia FLOAT"))
                conn.commit()
        if "movimentacao_historico_id" not in colunas_itens_fechamento:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE itens_fechamento ADD COLUMN movimentacao_historico_id INTEGER"))
                conn.commit()
    # acoes_pos_inventario é tabela nova - create_all cuida sozinho.
    if inspecao.has_table("acoes_pos_inventario"):
        colunas_acoes = {c["name"] for c in inspecao.get_columns("acoes_pos_inventario")}
        if "checklist" not in colunas_acoes:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE acoes_pos_inventario ADD COLUMN checklist JSON"))
                conn.commit()

    if inspecao.has_table("ficha_tecnica_bom"):
        colunas_bom = {c["name"] for c in inspecao.get_columns("ficha_tecnica_bom")}
        novas_colunas_bom = {
            "sku_subconjunto": "VARCHAR", "subconjunto": "VARCHAR", "custo": "FLOAT",
            "tem_filho": "BOOLEAN", "gera_oc": "BOOLEAN", "categoria": "VARCHAR", "linha_producao": "VARCHAR",
        }
        with engine.connect() as conn:
            for coluna, tipo in novas_colunas_bom.items():
                if coluna not in colunas_bom:
                    conn.execute(text(f"ALTER TABLE ficha_tecnica_bom ADD COLUMN {coluna} {tipo}"))
            conn.commit()

    if "origem" not in colunas_existentes:  # colunas_existentes = colunas de "divergencias"
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE divergencias ADD COLUMN origem VARCHAR DEFAULT 'movimentacao'"))
            conn.execute(text("UPDATE divergencias SET origem = 'movimentacao' WHERE origem IS NULL"))
            conn.commit()

    colunas_historico = {c["name"] for c in inspecao.get_columns("movimentacoes_historico")}
    if "origem" not in colunas_historico:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE movimentacoes_historico ADD COLUMN origem VARCHAR DEFAULT 'movimentacao'"))
            conn.execute(text("UPDATE movimentacoes_historico SET origem = 'movimentacao' WHERE origem IS NULL"))
            conn.commit()

    # Correção retroativa: fechamentos já importados antes desta versão
    # marcaram seus itens como origem 'movimentacao' por engano (o campo
    # não existia ainda) - reclassifica pelos vínculos já salvos.
    if inspecao.has_table("itens_fechamento") and inspecao.has_table("fechamentos_inventario"):
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE divergencias SET origem = 'fechamento_inventario'
                WHERE id IN (SELECT divergencia_id FROM itens_fechamento WHERE divergencia_id IS NOT NULL)
            """))
            conn.execute(text("""
                UPDATE movimentacoes_historico SET origem = 'fechamento_inventario'
                WHERE id IN (SELECT movimentacao_historico_id FROM itens_fechamento WHERE movimentacao_historico_id IS NOT NULL)
            """))
            conn.commit()

    # lotes_importacao é tabela nova - create_all cuida sozinho.
    if "lote_importacao_id" not in colunas_existentes:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE divergencias ADD COLUMN lote_importacao_id INTEGER"))
            conn.commit()
    if "lote_importacao_id" not in colunas_historico:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE movimentacoes_historico ADD COLUMN lote_importacao_id INTEGER"))
            conn.commit()

    # ajustes_inventario_oficial já existia (com dados reais importados, ver
    # ajustes_inventario_router.py) antes do conceito de "lote"
    # (LoteAjusteInventario) existir - create_all não altera tabela já
    # existente, então sem isso a coluna lote_id nunca apareceria em produção
    # e toda query no modelo quebraria com "no such column". Além de
    # adicionar a coluna, agrupa linhas legadas (lote_id NULL) por
    # arquivo_origem em lotes retroativos (ver
    # _backfill_lotes_ajuste_inventario_legado) - sem isso, a importação
    # original fica "invisível" na tela Importar > Importações anteriores,
    # mesmo contando certinho nos painéis (foi reportado assim: "não tem o
    # primeiro arquivo na tabela"). O backfill roda em TODO startup, não só
    # quando a coluna é criada agora - se um deploy anterior já rodou o ALTER
    # sem o backfill (ele foi adicionado depois), a próxima subida ainda
    # precisa agrupar as linhas órfãs; a função em si é barata/idempotente
    # quando não sobra nenhuma linha com lote_id NULL.
    if inspecao.has_table("ajustes_inventario_oficial"):
        colunas_ajustes = {c["name"] for c in inspecao.get_columns("ajustes_inventario_oficial")}
        if "lote_id" not in colunas_ajustes:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE ajustes_inventario_oficial ADD COLUMN lote_id INTEGER"))
                conn.commit()
        _backfill_lotes_ajuste_inventario_legado()


def _backfill_lotes_ajuste_inventario_legado():
    """Roda uma única vez, imediatamente depois da migração que criou a
    coluna lote_id: agrupa as linhas de AjusteInventarioOficial importadas
    ANTES do conceito de "lote" existir (lote_id NULL) por arquivo_origem, e
    cria um LoteAjusteInventario retroativo pra cada grupo, linkando as
    linhas a ele. Sem isso, a importação real que o Maurício já tinha feito
    em produção some da lista "Importações anteriores" (não tem lote), mesmo
    continuando a contar certinho nos painéis - ele reportou isso como "dado
    inconsistente" ao testar, e de fato é uma lacuna, não só um detalhe
    cosmético: sem aparecer na lista, não tem como excluir/substituir aquela
    importação específica pela tela."""
    from . import models  # import local: evita ciclo (models importa Base deste módulo)
    db = SessionLocal()
    try:
        orfaos = db.query(models.AjusteInventarioOficial).filter(models.AjusteInventarioOficial.lote_id.is_(None)).all()
        if not orfaos:
            return
        grupos = defaultdict(list)
        for r in orfaos:
            grupos[r.arquivo_origem or "Importação legada (arquivo não registrado)"].append(r)
        for arquivo, linhas in grupos.items():
            contadas = sum(1 for l in linhas if l.conta_como_ajuste_inventario)
            ignoradas_nao = sum(
                1 for l in linhas
                if not l.conta_como_ajuste_inventario and str(l.inventario_flag_bruto or "").strip().lower() == "não"
            )
            ignoradas_legado = len(linhas) - contadas - ignoradas_nao
            valor_contadas = round(sum(l.valor_total or 0 for l in linhas if l.conta_como_ajuste_inventario), 2)
            datas_criacao = [l.criado_em for l in linhas if l.criado_em]
            criado_por = next((l.criado_por for l in linhas if l.criado_por), None)
            lote_kwargs = dict(
                arquivo_origem=arquivo, aba_usada="Estoque", criado_por=criado_por,
                total_linhas=len(linhas), importadas=len(linhas),
                contadas_como_ajuste_inventario=contadas, ignoradas_flag_nao=ignoradas_nao,
                ignoradas_legado_pre_separacao=ignoradas_legado, valor_total_ajustes_contados=valor_contadas,
            )
            if datas_criacao:
                lote_kwargs["criado_em"] = min(datas_criacao)  # senão usa o default (agora) do próprio modelo
            lote = models.LoteAjusteInventario(**lote_kwargs)
            db.add(lote)
            db.flush()
            for l in linhas:
                l.lote_id = lote.id
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
