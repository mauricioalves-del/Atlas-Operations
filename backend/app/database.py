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

    # IMPORTANTE (bug corrigido em 19/08/2026, causou falha de deploy em produção):
    # os blocos de ALTER TABLE de baixas_operacionais/divergencias (colunas ia_gen_*
    # - ver app/ia_generativa.py) precisam rodar AQUI NO TOPO, antes de QUALQUER
    # outro código desta função que faça uma consulta ORM de entidade inteira
    # (ex: _remover_duplicatas_status_baixa_operacional() mais abaixo, que faz
    # `db.query(models.BaixaOperacional).order_by(...).all()`). Um SELECT desses
    # sempre inclui TODAS as colunas que o modelo Python declara, mesmo antes do
    # ALTER TABLE ter rodado - se o bloco de ALTER TABLE vier depois dessa consulta
    # no arquivo, a consulta quebra com "no such column"/"column does not exist"
    # porque a coluna ainda não existe na tabela real quando ela é executada. Novas
    # colunas em BaixaOperacional/Divergencia devem sempre ser adicionadas aqui no
    # topo por esse motivo - não misturar com os blocos de baixo.
    colunas_divergencias = {c["name"] for c in inspecao.get_columns("divergencias")}
    if "ia_gen_resumo" not in colunas_divergencias:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE divergencias ADD COLUMN ia_gen_resumo TEXT"))
            conn.execute(text("ALTER TABLE divergencias ADD COLUMN ia_gen_analisado_em TIMESTAMP"))
            conn.commit()
    if inspecao.has_table("baixas_operacionais"):
        colunas_baixas = {c["name"] for c in inspecao.get_columns("baixas_operacionais")}
        if "ia_gen_categoria" not in colunas_baixas:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE baixas_operacionais ADD COLUMN ia_gen_categoria VARCHAR"))
                conn.execute(text("ALTER TABLE baixas_operacionais ADD COLUMN ia_gen_prioridade VARCHAR"))
                conn.execute(text("ALTER TABLE baixas_operacionais ADD COLUMN ia_gen_resumo TEXT"))
                conn.execute(text("ALTER TABLE baixas_operacionais ADD COLUMN ia_gen_analisado_em TIMESTAMP"))
                conn.commit()

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
            conn.execute(text("ALTER TABLE produtos ADD COLUMN ativo BOOLEAN DEFAULT TRUE"))
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
            conn.execute(text("ALTER TABLE almoxarifados ADD COLUMN ativo BOOLEAN DEFAULT TRUE"))
            conn.commit()
    if "participa_contagem_diaria" not in colunas_almox:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE almoxarifados ADD COLUMN participa_contagem_diaria BOOLEAN DEFAULT TRUE"))
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
                conn.execute(text("UPDATE almoxarifados SET participa_contagem_diaria = FALSE WHERE codigo = :codigo"), {"codigo": codigo})
            conn.commit()

    colunas_hipoteses = {c["name"] for c in inspecao.get_columns("hipoteses")}
    if "ativo" not in colunas_hipoteses:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE hipoteses ADD COLUMN ativo BOOLEAN DEFAULT TRUE"))
            conn.commit()

    colunas_usuarios = {c["name"] for c in inspecao.get_columns("usuarios")}
    if "tentativas_falhas" not in colunas_usuarios:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN tentativas_falhas INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN bloqueado_ate TIMESTAMP"))
            conn.commit()
    if "almoxarifados_permitidos" not in colunas_usuarios:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN almoxarifados_permitidos JSON"))
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
        _remover_duplicatas_cruzadas_ajuste_inventario()

    if inspecao.has_table("baixas_operacionais"):
        _remover_duplicatas_status_baixa_operacional()

    # justificativas_ajuste_inventario existia só pra ajustes de inventário -
    # 13/08/2026, passou a cobrir também linhas de Passivo (Top 10 Maiores
    # Movimentações do Mapeamento de Passivos), então precisa de uma segunda
    # referência opcional pra baixa_operacional (ver models.py).
    if inspecao.has_table("justificativas_ajuste_inventario"):
        colunas_justificativas = {c["name"] for c in inspecao.get_columns("justificativas_ajuste_inventario")}
        if "baixa_operacional_id" not in colunas_justificativas:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE justificativas_ajuste_inventario ADD COLUMN baixa_operacional_id INTEGER"))
                conn.commit()

    if inspecao.has_table("fechamentos_inventario"):
        colunas_fechamentos = {c["name"] for c in inspecao.get_columns("fechamentos_inventario")}
        if "aprovado_manual" not in colunas_fechamentos:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE fechamentos_inventario ADD COLUMN aprovado_manual BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE fechamentos_inventario ADD COLUMN aprovado_manual_por VARCHAR"))
                conn.execute(text("ALTER TABLE fechamentos_inventario ADD COLUMN aprovado_manual_em TIMESTAMP"))
                conn.commit()

    # grupo_produto (20/08/2026) - a aba Lote_Sistema passou a trazer a coluna
    # "Grupo" (Produto Acabado, Embalagem, Ativo Imobilizado...), o que permite
    # excluir Embalagens e Ativos Imobilizados do indicador de Shelf Life de forma
    # confiável (ver models.LoteShelfLife e shelf_life.py).
    if inspecao.has_table("lotes_shelf_life"):
        colunas_shelf_life = {c["name"] for c in inspecao.get_columns("lotes_shelf_life")}
        if "grupo_produto" not in colunas_shelf_life:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE lotes_shelf_life ADD COLUMN grupo_produto VARCHAR"))
                conn.commit()

    # (as colunas ia_gen_* de baixas_operacionais/divergencias foram movidas pro
    # topo desta função em 19/08/2026 - ver o comentário lá explicando por quê)


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


def _remover_duplicatas_cruzadas_ajuste_inventario():
    """O dedup feito no momento da importação (ver
    ajustes_inventario_router.py) só compara linhas DENTRO do mesmo
    arquivo - uma planilha corrigida reenviada depois, que ainda traga de
    volta linhas de um período já conciliado num lote anterior, passava
    batido (reportado pelo Maurício: "duplicando os dados novos" na segunda
    importação). Aqui a limpeza é retroativa, em duas passadas sobre TODAS
    as linhas já no banco:

    1) Duplicata 100% idêntica (todas as colunas físicas iguais, custo
       incluso) - mantém a ocorrência mais antiga (menor id), remove as
       demais.

    2) Mesmo lançamento (SKU+Status+Id_Invent+Data+Almoxarifado+Lote+
       Qtd_Sistema+Qtd_Contagem+Ajuste iguais) com Custo/Valor DIFERENTE -
       não é um evento novo, é o custo daquele movimento tendo sido
       recalculado depois no sistema de origem (achado ao investigar por
       que julho/2026 ainda ficava ~R$930 maior que o arquivo mais recente,
       mesmo já sem duplicata exata). Confirmado com o Maurício: a
       importação mais recente vale - mantém a ocorrência mais antiga (pra
       preservar eventuais Justificativas já linkadas a ela via ajuste_id),
       mas atualiza seu Custo/Valor pro da ocorrência mais recente (maior
       id), e remove a mais recente.

    Em nenhum dos dois casos a chave NATURAL (Id_Produto+Id_Invent+Id_Lote)
    isolada é usada pra decidir duplicata - ela pode legitimamente repetir
    com valores diferentes por ser um lançamento distinto (verificado com
    dados reais); só entra aqui quando Qtd_Sistema/Qtd_Contagem/Ajuste TAMBÉM
    batem, sobrando só custo pra explicar a diferença.

    Recalcula os contadores do(s) lote(s) afetados, pra "Importações
    anteriores" continuar batendo com o que está de fato no banco. Roda em
    todo startup; barato quando não há nada pra corrigir."""
    from . import models  # import local: evita ciclo (models importa Base deste módulo)
    db = SessionLocal()
    try:
        linhas = db.query(models.AjusteInventarioOficial).order_by(models.AjusteInventarioOficial.id.asc()).all()
        lotes_afetados = set()
        removidos = 0
        custos_corrigidos = 0

        # Passada 1: duplicata exata
        vistas = set()
        sobreviventes = []
        for registro in linhas:
            chave = (
                registro.sku, registro.status, registro.id_invent, registro.dt_invent,
                registro.almoxarifado_origem, registro.id_lote, registro.qtd_sistema,
                registro.qtd_contagem, registro.ajuste_qtd, registro.custo_unitario, registro.valor_total,
            )
            if chave in vistas:
                if registro.lote_id:
                    lotes_afetados.add(registro.lote_id)
                db.delete(registro)
                removidos += 1
            else:
                vistas.add(chave)
                sobreviventes.append(registro)

        # Passada 2: mesmo movimento, custo diferente - agrupa os
        # sobreviventes da passada 1 pela assinatura SEM custo/valor.
        por_movimento = defaultdict(list)
        for registro in sobreviventes:
            chave_sem_custo = (
                registro.sku, registro.status, registro.id_invent, registro.dt_invent,
                registro.almoxarifado_origem, registro.id_lote, registro.qtd_sistema,
                registro.qtd_contagem, registro.ajuste_qtd,
            )
            por_movimento[chave_sem_custo].append(registro)
        for grupo in por_movimento.values():
            if len(grupo) <= 1:
                continue
            grupo.sort(key=lambda r: r.id)
            mantido = grupo[0]  # mais antigo - preserva id (e Justificativas já linkadas a ele)
            mais_recente = grupo[-1]
            if mantido.custo_unitario != mais_recente.custo_unitario or mantido.valor_total != mais_recente.valor_total:
                mantido.custo_unitario = mais_recente.custo_unitario
                mantido.valor_total = mais_recente.valor_total
                mantido.arquivo_origem = mais_recente.arquivo_origem
                custos_corrigidos += 1
            if mantido.lote_id:
                lotes_afetados.add(mantido.lote_id)
            for extra in grupo[1:]:
                if extra.lote_id:
                    lotes_afetados.add(extra.lote_id)
                db.delete(extra)
                removidos += 1

        if not removidos and not custos_corrigidos:
            return
        db.flush()
        for lote_id in lotes_afetados:
            lote = db.query(models.LoteAjusteInventario).get(lote_id)
            if not lote:
                continue
            restantes = db.query(models.AjusteInventarioOficial).filter_by(lote_id=lote_id).all()
            lote.importadas = len(restantes)
            lote.contadas_como_ajuste_inventario = sum(1 for r in restantes if r.conta_como_ajuste_inventario)
            lote.ignoradas_flag_nao = sum(
                1 for r in restantes
                if not r.conta_como_ajuste_inventario and str(r.inventario_flag_bruto or "").strip().lower() == "não"
            )
            lote.ignoradas_legado_pre_separacao = sum(
                1 for r in restantes
                if not r.conta_como_ajuste_inventario and str(r.inventario_flag_bruto or "").strip().lower() != "não"
            )
            lote.valor_total_ajustes_contados = round(sum(r.valor_total or 0 for r in restantes if r.conta_como_ajuste_inventario), 2)
        db.commit()
        print(
            f"Atlas: removidas {removidos} linha(s) duplicada(s) e corrigido custo de {custos_corrigidos} "
            f"lançamento(s) entre importações de ajuste de inventário (ajustado(s) {len(lotes_afetados)} lote(s))."
        )
    finally:
        db.close()


def _remover_duplicatas_status_baixa_operacional():
    """Limpeza retroativa de um bug encontrado em produção em 12/08/2026: a
    primeira versão de importar_planilha_historico_lovable (ver
    baixas_operacionais.py) casava linhas da planilha "Baixar relatório
    completo" contra o que já existia no Atlas usando uma assinatura que
    incluía o Status (Pendente/Aprovada/Reprovada). Toda baixa nasce
    Pendente e muda de status quando é decidida - então qualquer baixa cujo
    status mudou entre a sincronização original (webhook) e a exportação da
    planilha deixava de "casar" e era inserida de novo como se fosse um
    evento novo. Rodado uma vez contra produção real (Maurício, tela
    Relatório de Baixa): 638 baixas -> 865, sendo pelo menos 11 pares
    confirmados como a MESMA baixa duplicada só por causa da mudança de
    status.

    A função já foi corrigida pra casar por uma chave ESTÁVEL (sem Status) e
    atualizar o status no lugar em vez de inserir - mas isso não desfaz as
    duplicatas que a versão antiga já criou. Esta limpeza roda em todo
    startup (idempotente, barata quando não há nada pra corrigir) e refaz
    retroativamente o que a versão corrigida teria feito:

    Agrupa TODAS as linhas de baixas_operacionais pela mesma chave estável
    (SKU + Almoxarifado + Hipótese + Quantidade + Valor + Data). Dentro de
    cada grupo, separa as que vieram do backfill por planilha
    (payload_bruto._fonte == "backfill_planilha_historico") das que já
    existiam antes (webhook, colar lote, ou backfill de uma rodada
    anterior). Casa 1-a-1, na ordem do id (mais antiga primeiro): pra cada
    par, se o status diferir, atualiza o status da linha MAIS ANTIGA pro da
    mais nova (preserva o id mais antigo, e qualquer divergência já
    vinculada a ele) e tenta resolver divergência automaticamente se acabou
    de virar Aprovada; a linha do backfill do par é removida. Se um grupo
    tem mais linhas de backfill do que linhas antigas, o excedente fica -
    são ocorrências genuinamente novas (a lacuna real que a planilha vinha
    pra fechar), não duplicata."""
    from . import models  # import local: evita ciclo (models importa Base deste módulo)
    from .baixas_operacionais import buscar_divergencia_compativel, resolver_divergencia_automaticamente, STATUS_FLUXO_APROVADO
    db = SessionLocal()
    try:
        linhas = db.query(models.BaixaOperacional).order_by(models.BaixaOperacional.id.asc()).all()
        grupos = defaultdict(list)
        for r in linhas:
            chave = (r.sku, r.almoxarifado, r.hipotese_aplicada, r.quantidade, r.valor_total, r.data_baixa)
            grupos[chave].append(r)

        removidos = 0
        status_corrigidos = 0
        resolvidas = 0

        def _e_backfill(registro):
            return bool(registro.payload_bruto) and registro.payload_bruto.get("_fonte") == "backfill_planilha_historico"

        for grupo in grupos.values():
            if len(grupo) <= 1:
                continue
            antigas = [r for r in grupo if not _e_backfill(r)]
            novas_backfill = [r for r in grupo if _e_backfill(r)]
            if not antigas or not novas_backfill:
                continue  # sem par antiga+backfill nesse grupo - nada a mesclar
            for mantida, duplicata in zip(antigas, novas_backfill):
                if mantida.status_fluxo != duplicata.status_fluxo:
                    mantida.status_fluxo = duplicata.status_fluxo
                    if duplicata.solicitante_nome:
                        mantida.solicitante_nome = duplicata.solicitante_nome
                    status_corrigidos += 1
                    if mantida.status_fluxo == STATUS_FLUXO_APROVADO and not mantida.divergencia_vinculada_id:
                        almoxarifado = mantida.almoxarifado or ""
                        if mantida.data_baixa and not almoxarifado.startswith("NAO_MAPEADO__"):
                            div = buscar_divergencia_compativel(db, mantida.sku, almoxarifado, mantida.data_baixa)
                            if div:
                                resolver_divergencia_automaticamente(db, div, mantida)
                                resolvidas += 1
                db.delete(duplicata)
                removidos += 1

        if not removidos and not status_corrigidos:
            return
        db.commit()
        print(
            f"Atlas: mesclada(s) {removidos} baixa(s) operacional(is) duplicada(s) por mudança de status "
            f"(status corrigido em {status_corrigidos}, {resolvidas} divergência(s) resolvida(s) automaticamente na mesclagem)."
        )
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
