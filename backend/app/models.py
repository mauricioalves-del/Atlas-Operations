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
    ForeignKey, UniqueConstraint, JSON, Text, LargeBinary
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
    # "Parâmetro de visualização" (18/08/2026): lista de códigos de Almoxarifado que este
    # usuário pode ver - None/[] = sem restrição (continua vendo tudo, comportamento de
    # sempre). Ver deps.filtrar_por_almoxarifado_permitido pra como isso é aplicado nas
    # queries. Guardado como JSON (lista de strings) em vez de tabela de associação
    # separada porque é só uma lista simples de códigos, sem atributo próprio por vínculo.
    almoxarifados_permitidos = Column(JSON, nullable=True)
    ativo = Column(Boolean, default=True)
    tentativas_falhas = Column(Integer, default=0)
    bloqueado_ate = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)

    # Integrações pessoais (19/08/2026 - pedido do Maurício): Gmail e Slack via
    # OAuth, uma conexão POR USUÁRIO (cada pessoa conecta a própria conta - ver
    # app/integracoes_pessoais.py e routers/integracoes_pessoais_router.py).
    # Guardado aqui, não numa tabela separada, pelo mesmo motivo de
    # almoxarifados_permitidos acima: é 1 conexão por serviço por usuário, sem
    # atributo próprio que justifique uma tabela de associação.
    google_conectado_email = Column(String, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    slack_conectado_user_id = Column(String, nullable=True)
    slack_conectado_team_id = Column(String, nullable=True)
    slack_user_token = Column(Text, nullable=True)


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
    participa_contagem_diaria = Column(Boolean, default=True)  # parametrizável - se muda o planejamento
    # interno, ajusta aqui (tela Cadastros) em vez de excluir na mão sempre que rodar Cobertura de Conferência


class DiaOperacional(Base):
    """Um dia em que houve QUALQUER movimentação de sistema registrada
    pra um almoxarifado (não só conferência) - vem do livro-caixa bruto
    do sistema. É a base pra saber quais dias realmente precisavam de
    conferência: um dia sem nenhuma operação (fim de semana, feriado, ou
    o almoxarifado simplesmente não rodou nada) não deveria contar como
    "furo" no controle - não tinha nada pra conferir."""
    __tablename__ = "dias_operacionais"
    id = Column(Integer, primary_key=True, autoincrement=True)
    almoxarifado = Column(String, index=True)
    data = Column(Date, index=True)


class Hipotese(Base):
    __tablename__ = "hipoteses"
    codigo = Column(String, primary_key=True)
    nome = Column(String)
    descricao = Column(String)
    peso_padrao = Column(Float, default=20.0)
    ativo = Column(Boolean, default=True)


class PerguntaPadraoPersonalizada(Base):
    """Módulo de configuração de perguntas padrão do Assistente Atlas
    (09/08/2026 - pedido do Maurício). O catálogo ORIGINAL de perguntas
    padrão (ver app/assistente_perguntas_padrao.py, PERGUNTAS_PADRAO) é
    fixo no código - pra adicionar uma pergunta nova ali, era preciso pedir
    uma alteração de código. Esta tabela guarda perguntas padrão CRIADAS
    PELO PRÓPRIO USUÁRIO (administradores, ver requer_papel("admin") em
    routers/assistente_router.py), sem precisar de uma nova versão do
    Atlas. As duas fontes (catálogo fixo + esta tabela) são combinadas em
    listar_perguntas_padrao()/identificar_pergunta_padrao() - ver esse
    arquivo pra entender a junção.

    Diferença deliberada em relação ao catálogo fixo: uma entrada aqui
    NUNCA tem um "contexto_extra_fn" (aquilo é uma função Python, não dá
    pra guardar num campo de banco) - só gatilhos + uma instrução textual
    pra IA generativa focar a resposta. Ainda é reconhecida e melhora a
    resposta (mesmo texto de "instrucao_extra" usado no catálogo fixo),
    só não ganha um bloco de dados extra pré-calculado como
    "risco_por_almoxarifado" ganha.
    """
    __tablename__ = "perguntas_padrao_personalizadas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chave = Column(String, unique=True, nullable=False, index=True)
    rotulo = Column(String, nullable=False)  # texto do botão de atalho na tela Início
    pergunta = Column(String, nullable=False)  # pergunta "oficial" enviada quando clicam no botão
    gatilhos = Column(JSON, nullable=False)  # lista de strings - frases que disparam esta pergunta por voz/texto
    instrucao_extra = Column(Text, nullable=True)
    ativo = Column(Boolean, default=True)
    criado_por = Column(String, nullable=True)  # username de quem criou (auditoria simples)
    criado_em = Column(DateTime, default=datetime.utcnow)


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

    # Resumo por IA GENERATIVA (LLM externo, 25/08/2026 - ver app/ia_generativa.py).
    # Propositalmente com prefixo `ia_gen_` bem diferente de hipotese_ia/confianca_ia
    # acima - aqueles são a hipótese final reconciliada por regras + modelo estatístico
    # treinado no próprio Atlas (investigation.py/ml/predict.py), calculados sempre.
    # ia_gen_resumo é opcional, só existe quando alguém pede ("Resumir com IA" na tela de
    # detalhe) e uma chave de IA generativa está configurada - nunca substitui nem
    # recalcula a hipótese, só traduz os sinais já existentes numa leitura corrida.
    ia_gen_resumo = Column(Text, nullable=True)
    ia_gen_analisado_em = Column(DateTime, nullable=True)


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
    # Marcação simples de "revisado/aprovado" pra fechamentos antigos que nunca vão
    # passar pelo fluxo formal de assinatura (Diretor de Operações/Coordenador
    # Financeiro/Responsável pelo Departamento) - não conta como nenhuma das
    # assinaturas obrigatórias, não gera PDF, é só um jeito de tirar o fechamento
    # da fila de "em aberto" sem fabricar uma ciência que ninguém de fato assinou
    # (17/08/2026 - decisão explícita do Maurício ao pedir aprovação em massa dos
    # fechamentos anteriores a uma certa data).
    aprovado_manual = Column(Boolean, default=False)
    aprovado_manual_por = Column(String, nullable=True)
    aprovado_manual_em = Column(DateTime, nullable=True)


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
    papel_assinatura = Column(String, nullable=True)  # "Diretor_Operacoes" ou "Coordenador_Financeiro" -
    # papel ORGANIZACIONAL de quem está assinando, distinto do papel técnico de permissão do usuário (admin/analista/leitura)
    data_assinatura = Column(DateTime, default=datetime.utcnow)
    observacao = Column(String, nullable=True)
    itens_divergentes_snapshot = Column(JSON)
    total_itens_divergentes = Column(Integer, default=0)
    valor_total_divergente = Column(Float, default=0)


class ConferenciaRealizada(Base):
    """Marca um dia em que uma conferência de estoque de verdade
    aconteceu num almoxarifado - vem de operações de ajuste de
    inventário no livro-caixa bruto do sistema ("Inventario (+)/(-)"),
    não de uma divergência propriamente dita. Alimenta só o indicador de
    Cobertura de Conferência (dias conferidos x pendentes) - não
    interfere em nenhuma outra lógica de investigação."""
    __tablename__ = "conferencias_realizadas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    almoxarifado = Column(String, index=True)
    data = Column(Date, index=True)
    sku = Column(String, nullable=True)
    quantidade_ajustada = Column(Float, nullable=True)
    origem = Column(String, default="ajuste_inventario_sistema")


class MovimentacaoBruta(Base):
    """Cada linha do livro-caixa bruto do sistema, guardada de verdade
    (não só os sinais derivados como Transferencia/ConferenciaRealizada) -
    necessária pra reconstruir "o que se moveu nesse dia, nesse
    almoxarifado" no detalhe da Cobertura de Conferência."""
    __tablename__ = "movimentacoes_brutas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    almoxarifado = Column(String, index=True)
    sku = Column(String, index=True)
    descricao = Column(String, nullable=True)
    data = Column(Date, index=True)
    operacao = Column(String, nullable=True)
    id_doc = Column(String, nullable=True)
    doc = Column(String, nullable=True)
    qtd_sai = Column(Float, default=0)
    qtd_ent = Column(Float, default=0)
    saldo = Column(Float, nullable=True)


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


class BaixaOperacional(Base):
    """Baixa operacional (Avaria, Vencimento, Descarte, Degustação, etc.)
    importada do sistema construído no Lovable - ver
    backend/app/baixas_operacionais.py pra entender o mapeamento e o
    casamento automático com Divergencia. Guarda QUALQUER status_fluxo
    (Pendente/Aprovada/Reprovada) pra alimentar a tela de Relatório de
    Baixa - só é usada pra resolver uma divergência quando Aprovada."""
    __tablename__ = "baixas_operacionais"
    id = Column(Integer, primary_key=True, autoincrement=True)
    origem_id = Column(String, unique=True, index=True, nullable=True)  # id (uuid) da linha no Lovable - chave do upsert
    sku = Column(String, index=True)
    almoxarifado = Column(String, index=True, nullable=True)  # já traduzido pro código do Atlas (Almox_...)
    almoxarifado_origem = Column(String, nullable=True)  # id_local bruto do Lovable (Alm_...), guardado pra auditoria
    motivo_baixa_bruto = Column(String, nullable=True)  # rótulo legível (Avaria, Vencimento, ...)
    hipotese_aplicada = Column(String, nullable=True)  # código de Hipotese correspondente
    quantidade = Column(Float, nullable=True)
    valor_total = Column(Float, nullable=True)
    status_fluxo = Column(String, index=True, nullable=True)  # PENDENTE | APROVADA | REPROVADA
    solicitante_nome = Column(String, nullable=True)
    data_baixa = Column(Date, index=True, nullable=True)
    payload_bruto = Column(JSON, nullable=True)  # linha crua recebida do Lovable, pra depuração
    divergencia_vinculada_id = Column(Integer, ForeignKey("divergencias.id"), nullable=True, index=True)
    recebido_em = Column(DateTime, default=datetime.utcnow)

    # Classificação/resumo por IA GENERATIVA (LLM externo, 25/08/2026 - pedido do
    # Maurício, ver app/ia_generativa.py). Sugestão opcional e revisável - só existe
    # depois que alguém pede ("Analisar com IA") e uma chave está configurada
    # (ATLAS_IA_GENERATIVA_API_KEY). Nunca roda sozinho nem sobrescreve
    # hipotese_aplicada (o de-para determinístico feito a partir do motivo bruto).
    ia_gen_categoria = Column(String, nullable=True)  # um código do catálogo de Hipotese (hipoteses_config.py)
    ia_gen_prioridade = Column(String, nullable=True)  # Alta | Média | Baixa
    ia_gen_resumo = Column(Text, nullable=True)
    ia_gen_analisado_em = Column(DateTime, nullable=True)


class LoteAjusteInventario(Base):
    """Um "lote" = uma importação da planilha oficial de ajustes de
    inventário ("Ace4"/aba "Estoque"). Cada upload cria um lote novo com
    seu próprio resumo (linhas importadas, contadas, ignoradas) - "cada
    importação é uma coisa", separada, com histórico visível na tela
    Importar e opção de excluir (e as linhas dela junto - ver
    AjusteInventarioOficial.lote_id) se algum upload foi feito errado ou
    duplicado."""
    __tablename__ = "lotes_ajuste_inventario"
    id = Column(Integer, primary_key=True, autoincrement=True)
    arquivo_origem = Column(String, nullable=True)
    aba_usada = Column(String, nullable=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    total_linhas = Column(Integer, default=0)
    importadas = Column(Integer, default=0)
    contadas_como_ajuste_inventario = Column(Integer, default=0)
    ignoradas_flag_nao = Column(Integer, default=0)
    ignoradas_legado_pre_separacao = Column(Integer, default=0)
    valor_total_ajustes_contados = Column(Float, default=0)


class AjusteInventarioOficial(Base):
    """Linha da tabela OFICIAL de ajustes de inventário ("Ace4") - a
    conciliação real feita pela operação, importada da planilha
    Inventários (aba "Estoque"). Diferente do ItemFechamento (que vem do
    fechamento bruto e inclui itens que a operação sinalizou como
    divergentes mas NUNCA chegou a ajustar de fato, por problema de
    processo), esta tabela é a fonte de verdade de Entradas/Saídas de
    inventário porque só tem o que foi de fato processado e conciliado.

    A coluna "Inventário" da planilha de origem diz se aquela linha é um
    ajuste de inventário (Sim) ou uma baixa de passivo que só passou por
    ali mas já é contabilizada em outro lugar - BaixaOperacional (Não).
    Até o meio de 2026 as duas coisas se misturavam no mesmo módulo; a
    partir de PADRONIZACAO_NOTA_FISCAL_DESDE (jul/2026), toda baixa de
    passivo passou a vir só por nota fiscal, então qualquer lançamento de
    inventário a partir daí já é ajuste de inventário automaticamente,
    mesmo sem a coluna preenchida - ver conta_como_ajuste_inventario.
    Colunas como Grupo/Ano/Obs/Inventário são OPCIONAIS na planilha de
    origem (a partir de jul/2026 a própria coluna "Inventário" deixa de
    existir, já que não tem mais baixa de passivo se misturando no
    módulo) - por isso todas são nullable e o importador não quebra se
    alguma faltar (ver ajustes_inventario_router.py)."""
    __tablename__ = "ajustes_inventario_oficial"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lote_id = Column(Integer, ForeignKey("lotes_ajuste_inventario.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    status = Column(String, nullable=True)
    id_invent = Column(Integer, index=True, nullable=True)  # número do evento de inventário na planilha de origem
    dt_invent = Column(Date, index=True, nullable=True)
    almoxarifado = Column(String, index=True, nullable=True)  # já traduzido pro código do Atlas (Almox_...)
    almoxarifado_origem = Column(String, nullable=True)  # valor bruto da planilha ("Almox - SP Fabrica"), pra auditoria
    descricao_produto = Column(String, nullable=True)
    id_lote = Column(String, nullable=True)
    qtd_sistema = Column(Float, default=0)  # coluna "Qtd" da planilha
    qtd_contagem = Column(Float, default=0)  # coluna "Cont1" da planilha
    ajuste_qtd = Column(Float, default=0)  # coluna "Ajuste" (Cont1 - Qtd) - positivo=sobra/entrada, negativo=falta/saída
    custo_unitario = Column(Float, default=0)
    valor_total = Column(Float, default=0)  # coluna "Vlr_Total" (Ajuste * Custo) - mesmo sinal do ajuste_qtd
    categoria_produto = Column(String, nullable=True)  # coluna "Grupo"
    observacao = Column(String, nullable=True)
    inventario_flag_bruto = Column(String, nullable=True)  # valor bruto da coluna "Inventário": "Sim" | "Não" | ano legado (ex: "2025")
    conta_como_ajuste_inventario = Column(Boolean, default=False, index=True)  # regra derivada - ver _conta_como_ajuste_inventario no router
    arquivo_origem = Column(String, nullable=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class JustificativaAjusteInventario(Base):
    """Justificativa de um ajuste de inventário OU de uma baixa operacional
    (passivo) específica - por que aquilo aconteceu e qual solução foi
    aplicada. Espelha AcaoPosInventario (mesma ideia de responsável/prazo/
    status/checklist). Exatamente um entre ajuste_id/baixa_operacional_id é
    preenchido, dependendo de onde a justificativa foi aberta (linha do
    Fluxo de Inventário ou linha de Passivo, ambos hoje reunidos no Top 10
    Maiores Movimentações do Mapeamento de Passivos - 13/08/2026). Guarda
    os dados do item "congelados" no momento da criação (sku, qtd_sistema,
    qtd_contagem etc.) pra continuar fazendo sentido mesmo se o lote/baixa
    de origem for excluído depois - é registro de uma decisão já tomada,
    não deveria desaparecer junto com o dado bruto."""
    __tablename__ = "justificativas_ajuste_inventario"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ajuste_id = Column(Integer, ForeignKey("ajustes_inventario_oficial.id"), nullable=True, index=True)
    baixa_operacional_id = Column(Integer, ForeignKey("baixas_operacionais.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    almoxarifado = Column(String, nullable=True)
    id_lote = Column(String, nullable=True)
    qtd_sistema = Column(Float, nullable=True)
    qtd_contagem = Column(Float, nullable=True)
    divergencia_qtd = Column(Float, nullable=True)
    valor_estimado = Column(Float, nullable=True)
    justificativa = Column(String)  # por que esse ajuste aconteceu
    solucao_aplicada = Column(String, nullable=True)  # o que foi feito pra resolver/evitar de novo
    responsavel = Column(String, nullable=True)
    prazo = Column(Date, nullable=True)
    status = Column(String, default="Pendente", index=True)  # Pendente | Em_Andamento | Concluida | Cancelada
    checklist = Column(JSON, nullable=True)  # [{"descricao": str, "concluido": bool}, ...]
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    concluido_em = Column(DateTime, nullable=True)


class AnexoJustificativa(Base):
    """Arquivo anexado a uma justificativa (ex: foto do produto avariado,
    laudo, nota fiscal) - evidência de apoio pra quem revisar depois
    (14/08/2026). Guardado como BLOB direto no banco (não em disco): assim
    funciona igual rodando local (SQLite, o caso de uso principal hoje) ou
    num Postgres gerenciado na nuvem, sem depender de um volume de disco
    persistente separado que teria que ser configurado à parte."""
    __tablename__ = "anexos_justificativa"
    id = Column(Integer, primary_key=True, autoincrement=True)
    justificativa_id = Column(Integer, ForeignKey("justificativas_ajuste_inventario.id"), nullable=False, index=True)
    nome_arquivo = Column(String, nullable=False)
    tipo_conteudo = Column(String, nullable=True)
    tamanho_bytes = Column(Integer, nullable=True)
    conteudo = Column(LargeBinary, nullable=False)
    enviado_por = Column(String, nullable=True)
    enviado_em = Column(DateTime, default=datetime.utcnow)


class LoteShelfLife(Base):
    """Lote físico (com validade) para controle de risco de shelf life -
    alimenta a tela dedicada 'Shelf Life' e o bloco de Shelf Life do Mapa
    de Demandas (tela Início). Duas origens possíveis: importação da
    planilha do sistema interno (aba 'Lote_Sistema' de Lote_Sistema.xlsx -
    ver shelf_life.py) ou cadastro manual direto na tela. Isso substitui a
    dependência do módulo Shelf Life do Lovable (sem acesso de leitura
    direta - só a tela, sem SQL editor) por uma fonte de dados que o
    próprio Atlas controla e recalcula a qualquer momento.

    Natural key (sku, lote, almoxarifado) faz a reimportação da planilha
    ser um upsert (atualiza quantidade/validade do lote já visto) em vez
    de duplicar - mas ao contrário de outras importações do Atlas
    (Faturamento, BOM...), NÃO é 'substituição completa': lotes
    cadastrados manualmente ou vindos de uma importação anterior que não
    aparecem na planilha nova são mantidos, porque a planilha é uma fonte
    de dados entre outras, não a única."""
    __tablename__ = "lotes_shelf_life"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    tipo_material = Column(String, nullable=True)  # MateriaPrima | Produto | SubConjunto | Diversos
    # Grupo de produto (ex: "Produto Acabado", "Embalagem", "Ativo Imobilizado",
    # "Materia Prima"...) - coluna nova "Grupo" que passou a vir na aba Lote_Sistema
    # a partir do arquivo enviado em 20/08/2026 (antes, a planilha não trazia essa
    # informação, e a exclusão de embalagens só podia ser feita por palavra-chave na
    # descrição - ver PALAVRAS_CHAVE_EMBALAGEM em shelf_life.py, mantida como
    # fallback pra lote sem Grupo preenchido). None em lotes importados de uma
    # planilha antiga ou cadastrados manualmente sem essa informação.
    grupo_produto = Column(String, nullable=True, index=True)
    almoxarifado = Column(String, index=True, nullable=True)  # já normalizado (Almox_...) - ou NAO_MAPEADO__<valor>
    almoxarifado_origem = Column(String, nullable=True)  # valor bruto da planilha de origem, guardado pra auditoria
    lote = Column(String, index=True, nullable=True)
    quantidade = Column(Float, nullable=True)
    unidade = Column(String, nullable=True)
    data_validade = Column(Date, nullable=True, index=True)  # None = sem validade cadastrada (material não rastreado)
    peso_kg = Column(Float, nullable=True)
    custo_unitario = Column(Float, nullable=True)
    ativo = Column(Boolean, default=True)
    origem_cadastro = Column(String, default="manual")  # manual | importacao_planilha
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


class Rotina(Base):
    """Diário de Bordo (18/08/2026): cadastro de uma rotina recorrente de
    gestão (ex: "Conferência de câmara fria", "Checklist de abertura") -
    a definição em si, não as execuções. Cada Rotina gera uma
    ExecucaoRotina esperada por dia (ou pela frequência configurada), e o
    % de cumprimento do MBR ("395 de 485 rotinas, 81%") é a razão entre
    ExecucaoRotina concluídas no prazo e o total esperado no período.
    Módulo novo - não existia nenhum controle estruturado disso antes
    (confirmado com o usuário), então o histórico começa do zero a partir
    de quando isso for cadastrado."""
    __tablename__ = "rotinas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String, nullable=False)
    descricao = Column(String, nullable=True)
    setor = Column(String, index=True, nullable=True)  # ex: Geral, Qualidade, Fábrica, Loja - agrupa o % por setor
    frequencia = Column(String, default="diaria")  # diaria | semanal | mensal
    responsavel_padrao = Column(String, nullable=True)
    ativo = Column(Boolean, default=True)
    criado_por = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class ExecucaoRotina(Base):
    """Um registro concreto de execução (ou falta de execução) de uma
    Rotina numa data específica - a unidade que alimenta o % de
    cumprimento. `status` distingue "ainda não chegou o prazo"
    (Pendente) de "passou do prazo sem ser concluída" (Atrasada), pra o
    % de cumprimento não contar um dia ainda em andamento como se já
    tivesse falhado."""
    __tablename__ = "execucoes_rotina"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rotina_id = Column(Integer, ForeignKey("rotinas.id"), nullable=False, index=True)
    data_referencia = Column(Date, nullable=False, index=True)  # o dia (ou período) que essa execução cobre
    status = Column(String, default="Pendente")  # Pendente | Concluida | Atrasada | Nao_Aplicavel
    concluido_em = Column(DateTime, nullable=True)
    concluido_por = Column(String, nullable=True)
    observacao = Column(String, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("rotina_id", "data_referencia", name="uq_execucao_rotina_dia"),)


class ChecagemFefo(Base):
    """Resultado calculado (não importado) de uma checagem de FEFO
    (First-Expired-First-Out) sobre uma Transferencia que saiu do
    almoxarifado de Fábrica pra outro almoxarifado (18/08/2026).

    DESATIVADA em 20/08/2026 - a tela "FEFO — Quebras na Movimentação" não
    escreve/lê mais esta tabela (ver ChecagemFefoMovimento abaixo). Motivo:
    o cálculo abaixo nunca comparou de fato o lote que saiu contra o lote
    mais antigo - só checava "já passaram 5 dias úteis desde a data da
    transferência (não importa se foi ontem ou há 8 meses) E existe algum
    lote desse SKU com estoque na Fábrica hoje", o que classificava quase
    toda transferência antiga como quebra (89,85% no relatório que o
    usuário mostrou, contra ~4,6% da Auditoria FEFO importada, que usa
    dado real de lote). Causa raiz e decisão documentadas no Atlas
    Operations (claude/checagens-fefo-heuristica-quebrada.md). Classe e
    tabela mantidas só pra não quebrar quem eventualmente já tenha linhas
    históricas gravadas aqui - não é mais escrita.

    Regra ORIGINAL (mantida no código só como registro histórico): pra
    cada Transferencia com origem = Fábrica, olha em LoteShelfLife todos os
    lotes do mesmo SKU que estavam na Fábrica com data_validade ANTERIOR
    à do lote mais provável de ter sido movido (não é possível saber com
    certeza QUAL lote fisicamente saiu, porque a importação diária de
    Movimentados não registra o lote da transferência - só
    sku/quantidade/origem/destino/data). Se existe um lote mais antigo
    (validade menor) do mesmo SKU que ainda aparece com quantidade > 0 na
    Fábrica depois da transferência, e essa situação persiste por mais
    de 5 dias úteis (a janela operacional mencionada pelo usuário), isso
    é registrado como quebra."""
    __tablename__ = "checagens_fefo"
    id = Column(Integer, primary_key=True, autoincrement=True)
    transferencia_id = Column(Integer, ForeignKey("transferencias.id"), nullable=False, index=True)
    sku = Column(String, index=True)
    descricao_produto = Column(String, nullable=True)
    almoxarifado_origem = Column(String, index=True)
    almoxarifado_destino = Column(String, index=True)
    data_saida = Column(Date, index=True)
    quantidade_transferida = Column(Float, nullable=True)
    lote_mais_antigo_sku = Column(String, nullable=True)  # o lote que deveria ter saído primeiro, se houve quebra
    validade_lote_mais_antigo = Column(Date, nullable=True)
    quantidade_remanescente_lote_antigo = Column(Float, nullable=True)
    dias_uteis_em_aberto = Column(Integer, nullable=True)  # dias úteis que o lote mais antigo ficou parado após a transferência
    resultado = Column(String, index=True)  # Dentro_Do_Criterio | Quebra_Fefo | Sem_Dado_Suficiente
    calculado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("transferencia_id", name="uq_checagem_fefo_transferencia"),)


class MovimentacaoLoteDiaria(Base):
    """Movimentação bruta POR LOTE (20/08/2026) - a mesma exportação
    "Movimentação - Lt.xlsx" que o estagiário (André) já usa no próprio
    processo de auditoria (ver Auditar_FEFO.ipynb, função
    ler_movimentacao()). Diferente de Transferencia/MovimentacaoBruta (o
    resto do Atlas), essa planilha registra QUAL lote se moveu
    (id_lote), não só SKU/quantidade - é o dado bruto que falta pro Atlas
    conseguir comparar de fato "o lote que saiu" contra "o lote que
    deveria ter saído primeiro", em vez de adivinhar (ver
    fefo.calcular_quebra_fefo_nativa e o histórico do porquê isso
    substituiu ChecagemFefo em claude/checagens-fefo-heuristica-quebrada.md
    no Atlas Operations).

    Um arquivo pode trazer vários dias de uma vez (é assim que o sistema de
    origem exporta). Reimportar substitui só os dias presentes no arquivo
    novo (escopo por data, igual à Auditoria FEFO importada) - não apaga
    outros dias já importados antes."""
    __tablename__ = "movimentacoes_lote_diaria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(Date, index=True, nullable=False)
    sku = Column(String, index=True, nullable=True)
    descricao_produto = Column(String, nullable=True)
    documento = Column(String, nullable=True)
    movimento = Column(String, nullable=True)  # texto bruto "Origem -> Destino" (desc_movimento)
    almoxarifado_raw = Column(String, nullable=True)  # desc_almox bruto da planilha de origem
    quantidade = Column(Float, nullable=True)
    lote_movimentado = Column(String, index=True, nullable=True)  # id_lote - o dado que faltava em Transferencia
    arquivo_origem = Column(String, nullable=True)
    importado_por = Column(String, nullable=True)
    importado_em = Column(DateTime, default=datetime.utcnow)


class ChecagemFefoMovimento(Base):
    """Resultado do motor NATIVO de checagem de FEFO (20/08/2026) -
    substitui ChecagemFefo/calcular_checagem_fefo (ver docstring de
    ChecagemFefo pro porquê). Pra cada movimento de saída da Fábrica em
    MovimentacaoLoteDiaria, compara o lote que de fato saiu
    (lote_movimentado) contra os lotes do mesmo SKU que continuam na
    Fábrica com validade MAIS ANTIGA e estoque positivo (LoteShelfLife) -
    se existir um lote assim que não seja o que saiu, é quebra de FEFO.
    Mesma lógica que Auditar_FEFO.ipynb do André usa (analisar_fefo) -
    ver fefo.py pro detalhamento e pra a taxonomia de status.

    Recalculado automaticamente a cada importação nova de
    MovimentacaoLoteDiaria, e uma vez por dia em background (ver
    scheduler.py) - reflete sempre o LoteShelfLife mais recente, então
    reimportar Lote_Sistema.xlsx muda o resultado de checagens já
    calculadas (ao contrário do ChecagemFefo antigo, que congelava o
    resultado - aqui o resultado É o estado atual, recalculado, não um
    histórico congelado). Escopo de substituição por DIA, igual à
    MovimentacaoLoteDiaria."""
    __tablename__ = "checagens_fefo_movimento"
    id = Column(Integer, primary_key=True, autoincrement=True)
    movimentacao_lote_diaria_id = Column(Integer, ForeignKey("movimentacoes_lote_diaria.id"), nullable=False, index=True)
    data = Column(Date, index=True, nullable=False)
    sku = Column(String, index=True, nullable=True)
    descricao_produto = Column(String, nullable=True)
    movimento = Column(String, nullable=True)
    almoxarifado_destino = Column(String, nullable=True)
    lote_movimentado = Column(String, nullable=True)
    qtd_lote_movimentado = Column(Float, nullable=True)
    validade_lote_movimentado = Column(Date, nullable=True)
    quebra_fefo = Column(Boolean, default=False, index=True)
    status = Column(String, nullable=True, index=True)  # mesma taxonomia da Auditoria FEFO importada
    lote_mais_antigo_disponivel = Column(String, nullable=True)
    qtd_lote_mais_antigo_disponivel = Column(Float, nullable=True)
    validade_mais_antiga_disponivel = Column(Date, nullable=True)
    calculado_em = Column(DateTime, default=datetime.utcnow)


class ResumoMovimentacaoMensal(Base):
    """Snapshot mensal (persistido) dos indicadores de 'Controle de
    Movimentados' - itens analisados / sem divergência / com divergência,
    por mês e por almoxarifado (almoxarifado = None é o total geral do
    mês) (19/08/2026).

    Existe como tabela separada, em vez do dashboard consultar
    MovimentacaoHistorico/Divergencia direto a cada carregamento, porque
    essas duas tabelas não são uma fonte estável no longo prazo: o
    livro-caixa bruto (de onde a investigação parte) é SUBSTITUÍDO por
    completo a cada reimportação de um almoxarifado (ver
    import_router.py - delete-then-reinsert por almoxarifado). Sem esse
    snapshot, o gráfico de "Evolução Mensal" perderia meses antigos
    silenciosamente assim que a planilha fosse reimportada.

    Esta tabela é atualizada (upsert por mês+almoxarifado) a cada
    carregamento do dashboard - o valor mais recente calculado pra um mês
    fica guardado aqui pra sempre, mesmo que o dado bruto de origem depois
    mude ou seja substituído (idêntico em espírito ao ChecagemFefo:
    resultado calculado e guardado, não recalculado on-the-fly)."""
    __tablename__ = "resumos_movimentacao_mensal"
    id = Column(Integer, primary_key=True, autoincrement=True)
    mes = Column(String, index=True)  # "YYYY-MM"
    almoxarifado = Column(String, nullable=True, index=True)  # None = total geral do mês (todos os almoxarifados)
    itens_analisados = Column(Integer, default=0)
    itens_sem_divergencia = Column(Integer, default=0)
    itens_com_divergencia = Column(Integer, default=0)
    pct_acuracia = Column(Float, nullable=True)
    valor_total_divergencias = Column(Float, default=0)
    atualizado_em = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("mes", "almoxarifado", name="uq_resumo_mov_mensal_mes_almox"),)


class ResumoTransferenciasMensal(Base):
    """Snapshot mensal (persistido) de Transferências entre almoxarifados,
    já cruzado com a checagem de FEFO nas que saem da Fábrica (19/08/2026)
    - alimenta o Dashboard de Acompanhamento (o usuário definiu
    "movimentação" == Transferências, com o critério de que toda saída da
    Fábrica precisa respeitar FEFO).

    Guardado à parte de Transferencia/ChecagemFefo porque a importação
    manual da planilha de Transferências ('Transferências.xlsx') APAGA e
    recria TODAS as linhas de Transferencia a cada envio (ver
    import_router.py: 'db.query(models.Transferencia).delete()') - sem
    esse snapshot, o histórico mensal de volume e de quebra de FEFO se
    perderia justamente nesse momento. Atualizado (upsert por mês) a cada
    carregamento do dashboard."""
    __tablename__ = "resumos_transferencias_mensal"
    id = Column(Integer, primary_key=True, autoincrement=True)
    mes = Column(String, index=True, unique=True)  # "YYYY-MM" - baseado em Transferencia.data_saida
    total_transferencias = Column(Integer, default=0)
    quantidade_total = Column(Float, default=0)
    transferencias_fabrica_avaliadas = Column(Integer, default=0)  # saíram da Fábrica E têm checagem de FEFO calculada (exclui Sem_Dado_Suficiente)
    quebras_fefo = Column(Integer, default=0)
    taxa_quebra_fefo_pct = Column(Float, nullable=True)
    atualizado_em = Column(DateTime, default=datetime.utcnow)


class DashboardExterno(Base):
    """Dashboards HTML autocontidos (CSS/JS já embutidos no próprio arquivo),
    construídos fora do Atlas e mantidos em paralelo a ele - pedido do usuário
    (20/08/2026) depois de esclarecer que a "quebra de FEFO" calculada a
    partir da data de transferência não reflete disponibilidade real medida
    no momento (não há hoje uma leitura de estoque do lote concorrente
    tirada exatamente na hora da transferência - ver docstring de fefo.py).
    Em vez de forçar dentro do MBR uma métrica que a base de dados atual não
    sustenta com confiança, o admin sobe aqui o HTML já pronto de cada
    dashboard que a equipe já mantém por fora, e ele fica acessível dentro do
    Atlas (Auditoria > Outros Dashboards), embutido via iframe - sem
    recalcular nada, só exibir o que já existe.

    5 slots fixos (ver CHAVES_VALIDAS em dashboards_externos_router.py):
    Controle de FEFO, Farol de Shelf-Life, Recuperação de Shelf, Testes
    Industriais, Dashboard Baixas Operacionais - mais quaisquer indicadores
    dinâmicos criados pelo admin (18/08/2026, POST /dashboards-externos),
    identificados por não terem a chave em CHAVES_VALIDAS. Um upload novo
    substitui o conteúdo anterior do mesmo slot (upsert por chave).
    html_content="" (string vazia, não NULL) é o estado "criado, ainda sem
    arquivo enviado" de um indicador dinâmico."""
    __tablename__ = "dashboards_externos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chave = Column(String, unique=True, index=True, nullable=False)
    nome_exibicao = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    nome_arquivo_original = Column(String, nullable=True)
    enviado_por = Column(String, nullable=True)
    enviado_em = Column(DateTime, default=datetime.utcnow)


class AuditoriaFefo(Base):
    """Histórico de auditoria de FEFO (First-Expired-First-Out) importado do
    processo que a equipe de Controle já roda por fora do Atlas (planilha
    "Controle de lote" + exportação de "Movimentação", comparadas dia a dia
    por um notebook Python do estagiário - ver fefo.py) - pedido do usuário
    (20/08/2026): "consolide o histórico e suba pro Atlas [...] baseado nas
    ferramentas de importação que já existem, consolide o relatório dentro
    do Atlas". O Atlas NÃO recalcula a comparação de lotes aqui - só
    consolida o resultado já apurado pelo processo do estagiário (isso é
    diferente de ChecagemFefo, que é a checagem própria do Atlas, calculada
    a partir de LoteShelfLife/Transferencia e sabidamente menos precisa por
    não ter uma leitura de estoque no momento exato da transferência - ver
    docstring de ChecagemFefo).

    Cada linha é UM movimento (normalmente saída da Fábrica) já avaliado
    pelo processo do estagiário. Dois níveis de fidelidade, marcados em
    `fonte`:
      - "auditoria_diaria": importado direto do Excel de auditoria de UM
        dia (aba "Todas as Movimentações", gerada pelo notebook
        Auditar_FEFO.ipynb dele) - todos os campos preenchidos, incluindo
        qual seria o lote mais antigo disponível, sua validade e
        quantidade.
      - "dashboard_consolidado": recuperado do dashboard HTML que ele já
        consolidava localmente (DashBoard_FEFO.ipynb, "Controle - FEFO.html")
        - usado só pra estender o histórico a um período (Maio/Jun-2026)
        de que não temos mais o Excel bruto de cada dia. Tem BEM menos
        detalhe (sem SKU, sem número de lote, sem o lote mais antigo
        disponível) porque o próprio dashboard dele já tinha descartado
        essas colunas antes de exportar. Dias em que os dois níveis
        existiriam ao mesmo tempo usam só "auditoria_diaria" (mais
        confiável) - o importador do consolidado pula esses dias de
        propósito (ver fefo.importar_auditoria_fefo_consolidada).

    Reimportar o mesmo dia (mesma `data`, mesma `fonte`) substitui as linhas
    daquele dia por completo (upsert por dia, não por linha - não há um ID
    de movimento único no arquivo de origem pra upsert por linha).

    Nem toda linha é uma "quebra em potencial" avaliável: quando o processo
    do estagiário não confirma que a origem do movimento é a Fábrica, ele
    marca como "Destino (não auditado)" e não avalia - guardado aqui do
    mesmo jeito (fidelidade ao dado de origem, só existe em linhas
    "auditoria_diaria" - o dashboard consolidado já descartava essas antes
    de exportar), mas os relatórios do Atlas excluem esse status das
    métricas de taxa de quebra (ver fefo.calcular_resumo_auditoria_fefo)."""
    __tablename__ = "auditorias_fefo"
    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(Date, index=True, nullable=False)
    sku = Column(String, index=True, nullable=True)
    descricao_produto = Column(String, nullable=True)
    movimento = Column(String, nullable=True)
    almoxarifado = Column(String, index=True, nullable=True)
    lote_movimentado = Column(String, nullable=True)
    qtd_lote_movimentado = Column(Float, nullable=True)
    validade_lote_movimentado = Column(Date, nullable=True)
    quebra_fefo = Column(Boolean, default=False, index=True)
    status = Column(String, nullable=True)
    lote_mais_antigo_disponivel = Column(String, nullable=True)
    qtd_lote_mais_antigo_disponivel = Column(Float, nullable=True)
    validade_mais_antiga_disponivel = Column(Date, nullable=True)
    fonte = Column(String, index=True, nullable=False, default="auditoria_diaria")
    arquivo_origem = Column(String, nullable=True)
    importado_por = Column(String, nullable=True)
    importado_em = Column(DateTime, default=datetime.utcnow)
