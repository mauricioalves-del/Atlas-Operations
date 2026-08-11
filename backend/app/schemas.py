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


class ConciliacaoCienciaCreate(BaseModel):
    observacao: Optional[str] = None
    papel_assinatura: str  # "Diretor_Operacoes" ou "Coordenador_Financeiro"


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

    class Config:
        from_attributes = True


class UsuarioCreate(BaseModel):
    username: str
    senha: str
    nome_exibicao: Optional[str] = None
    papel: str = "leitura"


class UsuarioAtualizar(BaseModel):
    nome_exibicao: Optional[str] = None
    papel: Optional[str] = None
    ativo: Optional[bool] = None
    nova_senha: Optional[str] = None


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
