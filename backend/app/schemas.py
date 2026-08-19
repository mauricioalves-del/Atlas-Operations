from datetime import date, datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class NovaMovimentacao(BaseModel):
    sku: str
    almoxarifado: str
    categoria_produto: Optional[str] = None
    data_movimento: date
    entrada: float = 0
    saida: float = 0
    saldo_sistema: float
    saldo_fisico: float
    unidade: Optional[str] = None


class DivergenciaOut(BaseModel):
    id: int
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: str
    categoria_produto: Optional[str]
    data_deteccao: date
    saldo_sistema: float
    saldo_fisico: float
    divergencia_qtd: float
    valor_estimado: float
    observacao_origem: Optional[str] = None
    hipotese_regras: Optional[str]
    confianca_regras: Optional[float]
    hipotese_ml: Optional[str]
    confianca_ml: Optional[float]
    hipotese_ia: Optional[str]
    confianca_ia: Optional[float]
    evidencias: Optional[Any]
    casos_similares: Optional[Any]
    distribuicao_probabilidades: Optional[Any]
    hipotese_confirmada: Optional[str]
    solucao_aplicada: Optional[str]
    responsavel: Optional[str]
    tempo_resolucao_minutos: Optional[float]
    status: str
    tem_investigacao_pendente: bool = False
    # Resumo por IA GENERATIVA (LLM externo, opcional - ver app/ia_generativa.py).
    # Não confundir com hipotese_ia/confianca_ia acima (regra + modelo estatístico
    # interno, sempre calculado) - isto só existe depois de alguém clicar em
    # "Resumir com IA" na tela de detalhe, e só se o Atlas tiver uma chave configurada.
    ia_gen_resumo: Optional[str] = None
    ia_gen_analisado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConfirmarDivergencia(BaseModel):
    hipotese_confirmada: str
    solucao_aplicada: Optional[str] = None
    responsavel: Optional[str] = None
    tempo_resolucao_minutos: Optional[float] = None


class ResumoImportacao(BaseModel):
    arquivo: str
    linhas_processadas: int
    inseridas_historico: int
    inseridas_divergencias: int
    erros: List[str] = []


class ItemFechamentoOut(BaseModel):
    id: int
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: str
    categoria_produto: Optional[str] = None
    qtd_sistema: float
    qtd_contagem: float
    divergencia_qtd: float
    valor_estimado: float
    percentual_acuracia: Optional[float] = None
    divergente: bool
    resumo_planilha: Optional[str] = None
    observacao_pos_inventario: Optional[str] = None
    observacao_extra: Optional[str] = None
    recorrencias_anteriores: int
    destaque_recorrente: bool
    divergencia_id: Optional[int] = None

    class Config:
        from_attributes = True


class FechamentoOut(BaseModel):
    id: int
    almoxarifado: str
    data_fechamento: date
    arquivo_origem: Optional[str] = None
    criado_por: Optional[str] = None
    total_itens: int
    total_divergentes: int
    valor_total_divergente: float
    status_assinatura: Optional[str] = None
    aprovado_manual: bool = False
    aprovado_manual_por: Optional[str] = None
    aprovado_manual_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcaoPosInventarioOut(BaseModel):
    id: int
    item_fechamento_id: Optional[int] = None
    fechamento_id: Optional[int] = None
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: Optional[str] = None
    acao_descricao: str
    responsavel: Optional[str] = None
    prazo: Optional[date] = None
    status: str
    checklist: Optional[list] = None
    origem_automatica: bool
    observacao_conclusao: Optional[str] = None
    criado_por: Optional[str] = None
    criado_em: datetime
    concluido_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcaoPosInventarioCreate(BaseModel):
    item_fechamento_id: Optional[int] = None
    fechamento_id: Optional[int] = None
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: Optional[str] = None
    acao_descricao: str
    responsavel: Optional[str] = None
    prazo: Optional[date] = None


class AcaoPosInventarioAtualizar(BaseModel):
    acao_descricao: Optional[str] = None
    responsavel: Optional[str] = None
    prazo: Optional[date] = None
    status: Optional[str] = None
    observacao_conclusao: Optional[str] = None
    checklist: Optional[list] = None


class AcoesLoteAtualizar(BaseModel):
    ids: List[int]
    status: str
    observacao_conclusao: Optional[str] = None


class JustificativaAjusteInventarioOut(BaseModel):
    id: int
    ajuste_id: Optional[int] = None
    baixa_operacional_id: Optional[int] = None
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: Optional[str] = None
    id_lote: Optional[str] = None
    qtd_sistema: Optional[float] = None
    qtd_contagem: Optional[float] = None
    divergencia_qtd: Optional[float] = None
    valor_estimado: Optional[float] = None
    justificativa: str
    solucao_aplicada: Optional[str] = None
    responsavel: Optional[str] = None
    prazo: Optional[date] = None
    status: str
    checklist: Optional[list] = None
    criado_por: Optional[str] = None
    criado_em: datetime
    concluido_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class JustificativaAjusteInventarioCreate(BaseModel):
    ajuste_id: Optional[int] = None
    baixa_operacional_id: Optional[int] = None
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado: Optional[str] = None
    id_lote: Optional[str] = None
    qtd_sistema: Optional[float] = None
    qtd_contagem: Optional[float] = None
    divergencia_qtd: Optional[float] = None
    valor_estimado: Optional[float] = None
    justificativa: str
    solucao_aplicada: Optional[str] = None
    responsavel: Optional[str] = None
    prazo: Optional[date] = None


class JustificativaAjusteInventarioAtualizar(BaseModel):
    justificativa: Optional[str] = None
    solucao_aplicada: Optional[str] = None
    responsavel: Optional[str] = None
    prazo: Optional[date] = None
    status: Optional[str] = None
    checklist: Optional[list] = None


class AnexoJustificativaOut(BaseModel):
    id: int
    justificativa_id: int
    nome_arquivo: str
    tipo_conteudo: Optional[str] = None
    tamanho_bytes: Optional[int] = None
    enviado_por: Optional[str] = None
    enviado_em: datetime

    class Config:
        from_attributes = True


class ConciliacaoCienciaCreate(BaseModel):
    observacao: Optional[str] = None
    papel_assinatura: str  # "Diretor_Operacoes", "Coordenador_Financeiro" ou "Responsavel_Departamento"


class AprovacaoManualLoteRequest(BaseModel):
    antes_de: date  # aprova (marcação simples, sem assinatura formal) todo fechamento com data_fechamento < antes_de


class FornecedorOut(BaseModel):
    id: int
    nome: str
    cnpj: Optional[str] = None
    contato: Optional[str] = None
    ativo: bool

    class Config:
        from_attributes = True


class FornecedorCreate(BaseModel):
    nome: str
    cnpj: Optional[str] = None
    contato: Optional[str] = None


class RecebimentoPedidoOut(BaseModel):
    id: int
    pedido_id: int
    data_recebimento: date
    quantidade_recebida: float
    numero_nota_fiscal: Optional[str] = None
    recebido_por: Optional[str] = None
    observacao: Optional[str] = None

    class Config:
        from_attributes = True


class RecebimentoPedidoCreate(BaseModel):
    data_recebimento: date
    quantidade_recebida: float
    numero_nota_fiscal: Optional[str] = None
    recebido_por: Optional[str] = None
    observacao: Optional[str] = None


class PedidoCompraOut(BaseModel):
    id: int
    numero_pedido: Optional[str] = None
    fornecedor_id: Optional[int] = None
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado_destino: str
    quantidade_pedida: float
    unidade: Optional[str] = None
    data_pedido: date
    prazo_entrega_previsto: Optional[date] = None
    status: str
    observacao: Optional[str] = None
    criado_por: Optional[str] = None
    criado_em: datetime
    quantidade_recebida_total: float = 0
    quantidade_pendente: float = 0
    pct_concluido: float = 0
    atrasado: bool = False

    class Config:
        from_attributes = True


class PedidoCompraCreate(BaseModel):
    numero_pedido: Optional[str] = None
    fornecedor_id: Optional[int] = None
    fornecedor_nome: Optional[str] = None  # se vier nome e não existir, cria o fornecedor
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado_destino: str
    quantidade_pedida: float
    unidade: Optional[str] = None
    data_pedido: date
    prazo_entrega_previsto: Optional[date] = None
    observacao: Optional[str] = None


class PedidoCompraAtualizar(BaseModel):
    status: Optional[str] = None
    prazo_entrega_previsto: Optional[date] = None
    observacao: Optional[str] = None


class ConciliacaoCienciaOut(BaseModel):
    id: int
    fechamento_id: int
    gestor_username: str
    gestor_nome: Optional[str] = None
    papel_assinatura: Optional[str] = None
    data_assinatura: datetime
    observacao: Optional[str] = None
    total_itens_divergentes: int
    valor_total_divergente: float

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    senha: str


class LoginResponse(BaseModel):
    access_token: str
    username: str
    nome_exibicao: Optional[str] = None
    papel: str


class UsuarioOut(BaseModel):
    id: int
    username: str
    nome_exibicao: Optional[str] = None
    papel: str
    ativo: bool
    almoxarifados_permitidos: Optional[List[str]] = None

    class Config:
        from_attributes = True


class UsuarioCreate(BaseModel):
    username: str
    senha: str
    nome_exibicao: Optional[str] = None
    papel: str = "leitura"
    almoxarifados_permitidos: Optional[List[str]] = None


class UsuarioAtualizar(BaseModel):
    nome_exibicao: Optional[str] = None
    papel: Optional[str] = None
    ativo: Optional[bool] = None
    nova_senha: Optional[str] = None
    # None = não tocar no campo (padrão do PATCH); [] = remove a restrição explicitamente
    # e passa a ver tudo; lista não-vazia = define o novo conjunto de almoxarifados
    # permitidos. Distinguir "não veio no payload" de "veio uma lista vazia de propósito"
    # é por isso que o router usa `"almoxarifados_permitidos" in payload.model_fields_set`
    # em vez de só checar `is not None`.
    almoxarifados_permitidos: Optional[List[str]] = None


class ProdutoOut(BaseModel):
    sku: str
    descricao: Optional[str] = None
    categoria_produto: Optional[str] = None
    unidade: Optional[str] = None
    custo_unitario: Optional[float] = None
    ativo: bool = True

    class Config:
        from_attributes = True


class ProdutoCreate(BaseModel):
    sku: str
    descricao: Optional[str] = None
    categoria_produto: Optional[str] = None
    unidade: Optional[str] = None
    custo_unitario: Optional[float] = None


class ProdutoAtualizar(BaseModel):
    descricao: Optional[str] = None
    categoria_produto: Optional[str] = None
    unidade: Optional[str] = None
    custo_unitario: Optional[float] = None
    ativo: Optional[bool] = None


class AlmoxarifadoOut(BaseModel):
    codigo: str
    nome_exibicao: Optional[str] = None
    ativo: bool = True
    participa_contagem_diaria: bool = True

    class Config:
        from_attributes = True


class AlmoxarifadoCreate(BaseModel):
    codigo: str
    nome_exibicao: Optional[str] = None


class AlmoxarifadoAtualizar(BaseModel):
    nome_exibicao: Optional[str] = None
    ativo: Optional[bool] = None
    participa_contagem_diaria: Optional[bool] = None


class HipoteseOut(BaseModel):
    codigo: str
    nome: Optional[str] = None
    descricao: Optional[str] = None
    peso_padrao: float = 20.0
    ativo: bool = True

    class Config:
        from_attributes = True


class HipoteseCreate(BaseModel):
    codigo: str
    nome: str
    descricao: Optional[str] = None
    peso_padrao: float = 20.0


class HipoteseAtualizar(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    peso_padrao: Optional[float] = None
    ativo: Optional[bool] = None


class RotinaOut(BaseModel):
    id: int
    nome: str
    descricao: Optional[str] = None
    setor: Optional[str] = None
    frequencia: str
    responsavel_padrao: Optional[str] = None
    ativo: bool

    class Config:
        from_attributes = True


class RotinaCreate(BaseModel):
    nome: str
    descricao: Optional[str] = None
    setor: Optional[str] = None
    frequencia: str = "diaria"
    responsavel_padrao: Optional[str] = None


class RotinaAtualizar(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    setor: Optional[str] = None
    frequencia: Optional[str] = None
    responsavel_padrao: Optional[str] = None
    ativo: Optional[bool] = None


class ExecucaoRotinaOut(BaseModel):
    id: Optional[int] = None  # None = ainda não persistida (linha virtual "Pendente"/"Atrasada" - ver listar_execucoes)
    rotina_id: int
    rotina_nome: Optional[str] = None
    rotina_setor: Optional[str] = None
    data_referencia: date
    status: str
    concluido_em: Optional[datetime] = None
    concluido_por: Optional[str] = None
    observacao: Optional[str] = None

    class Config:
        from_attributes = True


class ExecucaoRotinaAtualizar(BaseModel):
    status: str  # Concluida | Atrasada | Nao_Aplicavel | Pendente
    observacao: Optional[str] = None


class ChecagemFefoOut(BaseModel):
    id: int
    transferencia_id: int
    sku: str
    descricao_produto: Optional[str] = None
    almoxarifado_origem: str
    almoxarifado_destino: Optional[str] = None
    data_saida: Optional[date] = None
    quantidade_transferida: Optional[float] = None
    lote_mais_antigo_sku: Optional[str] = None
    validade_lote_mais_antigo: Optional[date] = None
    quantidade_remanescente_lote_antigo: Optional[float] = None
    dias_uteis_em_aberto: Optional[int] = None
    resultado: str

    class Config:
        from_attributes = True
