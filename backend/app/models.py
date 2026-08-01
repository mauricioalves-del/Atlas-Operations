"""
Modelos de banco de dados do Atlas.

Regras de tipo aplicadas em TODO o schema (corrigindo os problemas
encontrados nas versões no-code anteriores):
  - Qualquer campo de código de produto/lote/nota/OP é sempre String,
    nunca Integer — zero à esquerda é significativo.
  - Qualquer campo de data usa sqlalchemy.Date (data pura, sem hora).
  - Qualquer campo numérico usa Float (Python/SQLAlchemy já tratam com
    ponto decimal nativamente — o problema de "vírgula brasileira" era um
    bug de importação, não de schema, e é resolvido no parser de CSV).
"""
from sqlalchemy import (
    Column, String, Float, Date, DateTime, Boolean, Integer,
    ForeignKey, UniqueConstraint, JSON, Text
)
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True, nullable=False)
    nome_exibicao = Column(String, nullable=True)
    senha_hash = Column(String, nullable=False)
    papel = Column(String, nullable=False, default="leitura")  # admin | analista | leitura
    ativo = Column(Boolean, default=True)
    tentativas_falhas = Column(Integer, default=0)
    bloqueado_ate = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class LogAuditoria(Base):
    """Trilha de auditoria: quem fez o quê, quando. Cobre as ações
    sensíveis (login, importação, confirmação, edição de cadastros,
    gestão de usuários) - não é um log técnico, é um log de negócio."""
    __tablename__ = "log_auditoria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, index=True)
    acao = Column(String, index=True)  # ex: "login_sucesso", "confirmar_divergencia", "criar_produto"
    entidade = Column(String, nullable=True)  # ex: "divergencia", "produto"
    entidade_id = Column(String, nullable=True)
    detalhes = Column(JSON, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, index=True)


class Produto(Base):
    __tablename__ = "produtos"
    sku = Column(String, primary_key=True)
    descricao = Column(String)
    categoria_produto = Column(String)
    unidade = Column(String)
    custo_unitario = Column(Float, nullable=True)
    ativo = Column(Boolean, default=True)


class Almoxarifado(Base):
    __tablename__ = "almoxarifados"
    codigo = Column(String, primary_key=True)
    nome_exibicao = Column(String)
    ativo = Column(Boolean, default=True)


class Hipotese(Base):
    __tablename__ = "hipoteses"
    codigo = Column(String, primary_key=True)
    nome = Column(String)
    descricao = Column(String)
    peso_padrao = Column(Float, default=20.0)
    ativo = Column(Boolean, default=True)


class LoteImportacao(Base):
    """Um lote de importação de movimentação (CSV ou Excel) - permite
    desfazer uma importação inteira sem precisar apagar linha por linha."""
    __tablename__ = "lotes_importacao"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String)  # movimentacao_csv | movimentacao_excel
    arquivo_origem = Column(String, nullable=True)
    almoxarifado = Column(String, nullable=True)
    usuario = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    linhas_processadas = Column(Integer, default=0)
    divergencias_criadas = Column(Integer, default=0)
    historico_criado = Column(Integer, default=0)


class MovimentacaoHistorico(Base):
    """Dados históricos já resolvidos - nunca geram divergência nova,
    servem como base de conhecimento e base de treino do ML."""
    __tablename__ = "movimentacoes_historico"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    almoxarifado = Column(String, index=True)
    categoria_produto = Column(String, index=True)
    data_movimento = Column(Date, index=True)
    entrada = Column(Float, default=0)
    saida = Column(Float, default=0)
    saldo_sistema = Column(Float)
    saldo_fisico = Column(Float)
    divergencia = Column(Float, default=0)
    valor_divergencia = Column(Float, default=0)
    unidade = Column(String)
    observacao_original = Column(String)
    prejuizo_confirmado = Column(Boolean, default=False)
    hipotese_confirmada = Column(String, ForeignKey("hipoteses.codigo"), nullable=True)
    status = Column(String, default="Historico_Resolvido")
    origem = Column(String, default="movimentacao", index=True)  # movimentacao | fechamento_inventario
    lote_importacao_id = Column(Integer, ForeignKey("lotes_importacao.id"), nullable=True)


class Divergencia(Base):
    """Divergências detectadas a partir de hoje. Nunca recebe dados
    históricos - só o motor de investigação escreve aqui."""
    __tablename__ = "divergencias"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    almoxarifado = Column(String, index=True)
    categoria_produto = Column(String, index=True)
    data_deteccao = Column(Date, index=True)
    saldo_sistema = Column(Float)
    saldo_fisico = Column(Float)
    divergencia_qtd = Column(Float)
    valor_estimado = Column(Float, default=0)

    # saída do motor de regras (investigation.py)
    hipotese_regras = Column(String, nullable=True)
    confianca_regras = Column(Float, nullable=True)
    evidencias = Column(JSON, nullable=True)
    casos_similares = Column(JSON, nullable=True)

    # saída do modelo estatístico (ml/predict.py)
    hipotese_ml = Column(String, nullable=True)
    confianca_ml = Column(Float, nullable=True)
    distribuicao_probabilidades = Column(JSON, nullable=True)

    # hipótese final reconciliada (regras + ML) - ver investigation.py
    hipotese_ia = Column(String, nullable=True)
    confianca_ia = Column(Float, nullable=True)

    hipotese_confirmada = Column(String, nullable=True)
    observacao_origem = Column(String, nullable=True)
    solucao_aplicada = Column(String, nullable=True)
    responsavel = Column(String, nullable=True)
    tempo_resolucao_minutos = Column(Float, nullable=True)
    status = Column(String, default="Aberta")  # Aberta, Em_Investigacao, Resolvida
    origem = Column(String, default="movimentacao", index=True)  # movimentacao | fechamento_inventario
    lote_importacao_id = Column(Integer, ForeignKey("lotes_importacao.id"), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    resolvido_em = Column(DateTime, nullable=True)


class Transferencia(Base):
    __tablename__ = "transferencias"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    descricao = Column(String)
    data_saida = Column(Date)
    data_entrada = Column(Date, nullable=True)
    documento = Column(String)
    almoxarifado_origem = Column(String, index=True)
    almoxarifado_destino = Column(String, index=True)
    quantidade = Column(Float)
    lote = Column(String)


class OrdemProducao(Base):
    __tablename__ = "ordens_producao"
    numero_op = Column(String, primary_key=True)
    sku_produto_final = Column(String, index=True)
    descricao_produto = Column(String)
    data_registro = Column(Date)
    data_producao = Column(Date)
    status = Column(String)
    qtd_prevista = Column(Float)
    qtd_produzida = Column(Float)
    qtd_saldo = Column(Float)


class ConsumoOP(Base):
    __tablename__ = "consumo_op"
    id = Column(Integer, primary_key=True, autoincrement=True)
    numero_op = Column(String, index=True)  # referência solta a ordens_producao.numero_op, sem FK rígida -
    # mesmo padrão usado em todo o resto do sistema (sku nunca é FK de Produto): dado de consumo pode
    # legitimamente existir sem a OP correspondente já ter sido importada, sem travar a importação por isso.
    sku_produto_final = Column(String, index=True)
    sku_material = Column(String, index=True)
    descricao_material = Column(String)
    qtd_consumo = Column(Float)
    qtd_previsto = Column(Float)
    qtd_diferenca = Column(Float)
    data_registro = Column(Date)
    data_producao = Column(Date)
    status = Column(String)


class FichaTecnicaBOM(Base):
    __tablename__ = "ficha_tecnica_bom"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku_produto_final = Column(String, index=True)
    produto_final = Column(String)
    sku_subconjunto = Column(String, nullable=True, index=True)  # nível intermediário da receita (novo - planilha rica)
    subconjunto = Column(String, nullable=True)
    sku_item = Column(String, index=True)
    descricao_item = Column(String)
    qtd_padrao = Column(Float)
    unidade = Column(String)
    custo = Column(Float, nullable=True)  # custo do item nessa linha da receita (novo)
    tem_filho = Column(Boolean, nullable=True)  # esse item é ele mesmo um subconjunto com receita própria (novo)
    gera_oc = Column(Boolean, nullable=True)  # esse item é comprado de fornecedor, não produzido internamente (novo -
    # liga direto com o módulo de Controle de Compras: item com gera_oc=True é candidato a ter Pedido de Compra)
    categoria = Column(String, nullable=True)  # "Grupo" da planilha (novo)
    linha_producao = Column(String, nullable=True)  # "Linha" da planilha (novo)


class Faturamento(Base):
    __tablename__ = "faturamento"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    origem = Column(String)
    data_faturamento = Column(Date)
    quantidade = Column(Float)
    descricao = Column(String)


class FechamentoInventario(Base):
    """Um ciclo de fechamento de inventário (ex: conciliação contábil x
    físico mensal de um almoxarifado). Cada importação de planilha de
    fechamento cria um registro aqui, com os itens em ItemFechamento."""
    __tablename__ = "fechamentos_inventario"
    id = Column(Integer, primary_key=True, autoincrement=True)
    almoxarifado = Column(String, index=True)
    data_fechamento = Column(Date, index=True)
    arquivo_origem = Column(String, nullable=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    total_itens = Column(Integer, default=0)
    total_divergentes = Column(Integer, default=0)
    valor_total_divergente = Column(Float, default=0)


class ItemFechamento(Base):
    """Um item (SKU x almoxarifado) dentro de um fechamento de inventário.
    Se divergente, fica linkado a uma Divergencia normal (mesma
    investigação de regras+ML+texto que o resto do sistema usa) - este
    registro guarda o que é específico do CONTEXTO de fechamento:
    recorrência em fechamentos anteriores e destaque visual."""
    __tablename__ = "itens_fechamento"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fechamento_id = Column(Integer, ForeignKey("fechamentos_inventario.id"), index=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    almoxarifado = Column(String, index=True)
    categoria_produto = Column(String, nullable=True)
    qtd_sistema = Column(Float, default=0)
    qtd_contagem = Column(Float, default=0)
    divergencia_qtd = Column(Float, default=0)
    valor_estimado = Column(Float, default=0)
    percentual_acuracia = Column(Float, nullable=True)  # 0.0-1.0, vem da coluna "%" da planilha (Contagem/Sistema)
    divergente = Column(Boolean, default=False, index=True)
    resumo_planilha = Column(String, nullable=True)
    observacao_pos_inventario = Column(String, nullable=True)
    observacao_extra = Column(String, nullable=True)
    recorrencias_anteriores = Column(Integer, default=0)
    destaque_recorrente = Column(Boolean, default=False)
    divergencia_id = Column(Integer, ForeignKey("divergencias.id"), nullable=True)
    movimentacao_historico_id = Column(Integer, ForeignKey("movimentacoes_historico.id"), nullable=True)


class AcaoPosInventario(Base):
    """Ação de acompanhamento pós-inventário - o 'próximo passo' de um
    item divergente detectado num fechamento (ex: 'ajustar sistema',
    'solicitar recontagem'). Paralelo ao fluxo de Divergencia, mas focado
    em responsabilidade e prazo, não em diagnóstico de causa."""
    __tablename__ = "acoes_pos_inventario"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_fechamento_id = Column(Integer, ForeignKey("itens_fechamento.id"), index=True)
    fechamento_id = Column(Integer, ForeignKey("fechamentos_inventario.id"), index=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    almoxarifado = Column(String, nullable=True)
    acao_descricao = Column(String)
    responsavel = Column(String, nullable=True)
    prazo = Column(Date, nullable=True)
    status = Column(String, default="Pendente", index=True)  # Pendente | Em_Andamento | Concluida | Cancelada
    checklist = Column(JSON, nullable=True)  # [{"descricao": str, "concluido": bool}, ...]
    origem_automatica = Column(Boolean, default=False)  # criada sozinha a partir da "obs pós inv" da planilha
    observacao_conclusao = Column(String, nullable=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    concluido_em = Column(DateTime, nullable=True)


class EstadoTreinoML(Base):
    """Registro único (singleton, id=1) do estado do retreino automático -
    quando foi o último retreino e quantos casos de feedback existiam
    naquele momento, pra saber quando vale a pena retreinar de novo."""
    __tablename__ = "estado_treino_ml"
    id = Column(Integer, primary_key=True)
    ultimo_retreino_em = Column(DateTime, nullable=True)
    casos_feedback_no_ultimo_retreino = Column(Integer, default=0)
    origem_ultimo_retreino = Column(String, nullable=True)  # manual | automatico


class ConciliacaoCiencia(Base):
    """Registro de ciência/validação de um fechamento por um gestor -
    não é uma assinatura manuscrita, é a confirmação autenticada (usuário
    logado + timestamp) de que alguém com responsabilidade revisou a
    conciliação. Guarda uma FOTO congelada dos itens divergentes no
    momento da assinatura (itens_divergentes_snapshot) - o PDF gerado a
    partir daqui sempre reflete o que foi assinado, mesmo que os dados
    mudem depois (item seja corrigido, reconciliado, etc)."""
    __tablename__ = "conciliacoes_ciencia"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fechamento_id = Column(Integer, ForeignKey("fechamentos_inventario.id"), index=True)
    gestor_username = Column(String)
    gestor_nome = Column(String, nullable=True)
    data_assinatura = Column(DateTime, default=datetime.utcnow)
    observacao = Column(String, nullable=True)
    itens_divergentes_snapshot = Column(JSON)
    total_itens_divergentes = Column(Integer, default=0)
    valor_total_divergente = Column(Float, default=0)


class Fornecedor(Base):
    """Cadastro leve de fornecedor - o suficiente pra rastrear pedidos e,
    no futuro, medir desempenho (atraso médio, % de pedidos fracionados)
    sem precisar de um módulo de compras completo."""
    __tablename__ = "fornecedores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String, unique=True)
    cnpj = Column(String, nullable=True)
    contato = Column(String, nullable=True)
    ativo = Column(Boolean, default=True)


class PedidoCompra(Base):
    """Controle de estoque externo: o Atlas não é o sistema de compras -
    ele registra o pedido e os recebimentos parciais só o suficiente pra
    que o motor de investigação (investigation.py) saiba explicar uma
    'falta' na contagem como 'ainda não chegou tudo do fornecedor' em vez
    de tratar como perda real. Isso vale tanto pra Movimentados quanto
    pra Fechamento de Inventário, porque os dois chamam a mesma função
    investigar()."""
    __tablename__ = "pedidos_compra"
    id = Column(Integer, primary_key=True, autoincrement=True)
    numero_pedido = Column(String, nullable=True)  # referência externa (nº do PO/nota do fornecedor)
    fornecedor_id = Column(Integer, ForeignKey("fornecedores.id"), nullable=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    almoxarifado_destino = Column(String, index=True)
    quantidade_pedida = Column(Float)
    unidade = Column(String, nullable=True)
    data_pedido = Column(Date)
    prazo_entrega_previsto = Column(Date, nullable=True)
    status = Column(String, default="Aberto", index=True)  # Aberto | Parcialmente_Recebido | Concluido | Cancelado
    observacao = Column(String, nullable=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class RecebimentoPedido(Base):
    """Cada entrega parcial de um pedido - é a soma desses registros que
    diz quanto já chegou de fato, versus quanto ainda está pendente."""
    __tablename__ = "recebimentos_pedido"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_compra.id"), index=True)
    data_recebimento = Column(Date)
    quantidade_recebida = Column(Float)
    numero_nota_fiscal = Column(String, nullable=True)
    recebido_por = Column(String, nullable=True)
    observacao = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class CasoMLFeedback(Base):
    """Casos confirmados que alimentam o retreino do modelo. Persistido
    no MESMO banco do resto do app (Postgres/SQLite via DATABASE_URL) -
    ao contrário da versão anterior, que usava um SQLite separado dentro
    do próprio serviço de ML e perdia dados a cada deploy."""
    __tablename__ = "casos_ml_feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    divergencia_id = Column(Integer, ForeignKey("divergencias.id"), nullable=True)
    sku = Column(String)
    almoxarifado = Column(String)
    categoria_produto = Column(String)
    divergencia_qtd = Column(Float)
    valor_estimado = Column(Float)
    data_deteccao = Column(Date)
    hipotese_confirmada = Column(String)
    criado_em = Column(DateTime, default=datetime.utcnow)
