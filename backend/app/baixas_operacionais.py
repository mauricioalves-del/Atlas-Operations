"""
Integração automática com o sistema de baixas operacionais (Avaria,
Vencimento, Descarte, Degustação, Cortesia, Perda/Furto, Uso e Consumo,
Envio/Laboratório, Sensorial/Inovações) construído no Lovable, tabela
`baixa_operacional` no banco Supabase/Lovable Cloud daquele projeto.

Schema real da tabela de origem (checado direto no SQL editor do Lovable
em 2026-08-07 - ver conversa): id (uuid), codigo_produto (text),
id_local (text), motivo_baixa_id (uuid, FK pra tabela motivo_baixa),
quantidade (numeric), status_fluxo (text: PENDENTE | APROVADA |
REPROVADA), data_solicitacao/data_aprovacao/data_execucao (timestamps),
data_ocorrencia (date, nem sempre preenchida).

Três detalhes importantes que só apareceram ao inspecionar os dados de
verdade (por isso este módulo não usa nomes de coluna "genéricos" tipo
"sku"/"tipo" como uma primeira versão fazia):

1) `motivo_baixa_id` é um UUID (chave estrangeira), não um texto livre
   tipo "avaria" - o webhook de INSERT/UPDATE do Supabase manda só as
   colunas da própria linha, sem fazer join com motivo_baixa. Por isso o
   mapeamento aqui é por UUID fixo (ver MOTIVO_ID_PARA_HIPOTESE), tirado
   direto da tabela motivo_baixa no momento da integração.
2) O código de almoxarifado (`id_local`) usa prefixo "Alm_" (ex:
   "Alm_SP_Loja"), enquanto o Atlas usa "Almox_" (ex: "Almox_SP_Loja") -
   são quase iguais mas NÃO idênticos. Um "mesmo código" ingênuo nunca
   bateria. Ver ALMOXARIFADO_LOVABLE_PARA_ATLAS.
3) A baixa só é real depois de aprovada: `status_fluxo` passa por
   PENDENTE -> APROVADA (ou REPROVADA). Processar no INSERT (que
   acontece em PENDENTE) resolveria divergências com baixas que podem
   ainda ser rejeitadas. Por isso só processamos quando status_fluxo é
   'APROVADA' - seja já nascendo assim, seja numa atualização que
   transiciona pra esse estado (nesse caso o endpoint compara
   record/old_record do envelope do Supabase).

Fluxo de casamento (a ordem de chegada entre a baixa e a divergência
pode ser qualquer uma das duas):
  1) Webhook chega primeiro: a baixa é gravada e tentamos casar contra
     divergências ABERTAS já existentes (ver processar_baixa_recebida).
  2) Divergência é criada primeiro: o motor de investigação
     (investigation.py) procura baixas recebidas que ainda não foram
     vinculadas a nenhuma divergência (ver buscar_baixa_compativel).

Nenhum commit acontece aqui dentro - quem chama decide quando persistir
(mesmo padrão do resto do projeto: investigar() nunca comita).
"""
import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Session

from . import models

# Janela de tolerância entre a data da baixa e a data de detecção da
# divergência. Baixas costumam ser aprovadas em lote bem depois de
# ocorrerem (ex: aprovação em bloco às sextas) - por isso a "data da
# baixa" usada aqui é data_ocorrencia (ou data_solicitacao como
# fallback), nunca data_aprovacao, que só reflete quando o lote foi
# processado, não quando o evento aconteceu.
JANELA_DIAS_ANTES = 1
JANELA_DIAS_DEPOIS = 4

# Mesmos valores usados no loop de aprendizado do endpoint /confirmar em
# divergencias_router.py - duplicado aqui de propósito, pra este módulo
# não precisar importar um router (que traria muito mais coisa junto).
PESO_MIN, PESO_MAX = 5.0, 60.0
INCREMENTO_ACERTO = 2.0

RESPONSAVEL_AUTOMATICO = "Integração Lovable (automático)"

STATUS_FLUXO_APROVADO = "APROVADA"

# De-para tirado direto da tabela `motivo_baixa` do projeto Lovable
# (consulta feita em 2026-08-07). Se um motivo novo for cadastrado lá no
# futuro, uma baixa com esse motivo cai em MOTIVO_ID_PARA_HIPOTESE.get(...)
# = None e processar_baixa_recebida recusa com erro claro (400), em vez
# de adivinhar - é só adicionar a linha correspondente aqui.
MOTIVO_ID_PARA_HIPOTESE = {
    "9717e486-c7a0-4b3d-9515-272f28adbebd": "Avaria_Perda",              # Avaria
    "4ec6b21a-0744-44c7-a435-fba22872112d": "Cortesia_Amostra",          # Cortesia
    "11a201ee-9bd3-4eb9-80a7-cd7727d358b6": "Degustacao_Amostra",        # Degustação
    "55187d01-d362-4a9f-9a5f-ad8b5cf9925f": "Descarte_Operacional",      # Descarte/Qualidade
    "e5e043a9-20a5-43ea-9cc5-80de2e903bfd": "Envio_Laboratorio_Analise", # Envio/Laboratório
    "2490f52b-9f3b-4045-9eb0-f65ce33788b7": "Perda_Furto_Registrado",    # Perda/Furto
    "94fae356-5f30-4d9d-a273-bcd552a396f4": "Uso_Consumo_Interno",       # Uso e Consumo
    "de203fd3-dd2b-4662-bbdc-633c7412d48b": "Vencimento_Produto",        # Vencimento
    "484912e6-d10e-48fe-8d73-987fe0b53dd0": "Amostra_Sensorial_Inovacao",# Sensorial/Inovações
}

# Só pra deixar o texto de auditoria (solucao_aplicada) legível - o rótulo
# original que aparece na tela do Lovable, não o código oficial do Atlas.
MOTIVO_ID_PARA_DESCRICAO = {
    "9717e486-c7a0-4b3d-9515-272f28adbebd": "Avaria",
    "4ec6b21a-0744-44c7-a435-fba22872112d": "Cortesia",
    "11a201ee-9bd3-4eb9-80a7-cd7727d358b6": "Degustação",
    "55187d01-d362-4a9f-9a5f-ad8b5cf9925f": "Descarte/Qualidade",
    "e5e043a9-20a5-43ea-9cc5-80de2e903bfd": "Envio/Laboratório",
    "2490f52b-9f3b-4045-9eb0-f65ce33788b7": "Perda/Furto",
    "94fae356-5f30-4d9d-a273-bcd552a396f4": "Uso e Consumo",
    "de203fd3-dd2b-4662-bbdc-633c7412d48b": "Vencimento",
    "484912e6-d10e-48fe-8d73-987fe0b53dd0": "Sensorial/Inovações",
}

# De-para tirado direto dos valores reais de `id_local` observados na
# tabela baixa_operacional (consulta feita em 2026-08-07), contra a
# lista oficial de almoxarifados do Atlas (ALMOXARIFADOS_PADRAO em
# hipoteses_config.py). "Alm_Paulista" ficou de fora de propósito - não
# tem um almoxarifado do Atlas claramente correspondente ainda
# (pergunta em aberto pro Mauricio confirmar) - fica sem mapear, o que
# significa que baixas desse local nunca vão casar com uma divergência
# (não é erro, só fica incompleto até confirmar).
ALMOXARIFADO_LOVABLE_PARA_ATLAS = {
    "Alm_SP_Processo": "Almox_SP_Processo",
    "Alm_SP_Loja": "Almox_SP_Loja",
    "Alm_SP_Fabrica": "Almox_SP_Fabrica",
    "Alm_PDV_Ativacao": "Almox_SP_Ativacao",
    "Alm_SP_Qualidade": "Almox_SP_Qualidade",
    "Alm_Degustacao": "Almox_SP_Degustacao",
    "Alm_Para": "Almox_PA_Para",
    # "Alm_Paulista": ainda sem correspondência confirmada no Atlas.
}


# Inverso de MOTIVO_ID_PARA_DESCRICAO - usado só pela reconciliação por
# planilha (ver importar_planilha_historico_lovable), que recebe o rótulo
# legível ("Descarte/Qualidade") em vez do uuid de motivo_baixa_id (o
# export "Baixar relatório completo" da tela Baixas Operacionais não traz
# o uuid). Reconstrói o mesmo motivo_baixa_id pra reusar exatamente a
# mesma regra de MOTIVO_ID_PARA_HIPOTESE, sem duplicar o de-para.
DESCRICAO_PARA_MOTIVO_ID = {descricao: uuid for uuid, descricao in MOTIVO_ID_PARA_DESCRICAO.items()}


class BaixaInvalida(Exception):
    """Payload recebido no webhook não tem os campos mínimos (sku,
    id_local, motivo_baixa_id reconhecido) - erro de configuração do
    webhook/dado de origem, não do Atlas."""


def _normalizar_data(data_bruta) -> date:
    if not data_bruta:
        return date.today()
    if isinstance(data_bruta, date):
        return data_bruta
    # Timestamps ISO do Supabase vêm tipo "2026-08-06T14:23:00+00:00" ou só
    # "2026-08-06" - os 10 primeiros caracteres sempre dão a data pura.
    return date.fromisoformat(str(data_bruta)[:10])


def _dentro_da_janela(data_baixa: date, data_deteccao: date) -> bool:
    if not data_deteccao:
        return False
    diferenca = (data_deteccao - data_baixa).days
    return -JANELA_DIAS_DEPOIS <= diferenca <= JANELA_DIAS_ANTES


def buscar_divergencia_compativel(db: Session, sku: str, almoxarifado: str, data_baixa: date) -> Optional[models.Divergencia]:
    """Usado quando a BAIXA chega primeiro: procura entre as divergências
    ainda abertas desse SKU+almoxarifado a que estiver mais perto da data
    da baixa, dentro da janela de tolerância."""
    candidatas = (
        db.query(models.Divergencia)
        .filter(
            models.Divergencia.status == "Aberta",
            models.Divergencia.sku == sku,
            models.Divergencia.almoxarifado == almoxarifado,
        )
        .all()
    )
    compativeis = [d for d in candidatas if _dentro_da_janela(data_baixa, d.data_deteccao)]
    if not compativeis:
        return None
    compativeis.sort(key=lambda d: abs((d.data_deteccao - data_baixa).days))
    return compativeis[0]


def buscar_baixa_compativel(db: Session, sku: str, almoxarifado: str, data_deteccao: date) -> Optional[models.BaixaOperacional]:
    """Usado quando a DIVERGÊNCIA é criada primeiro (chamado de dentro de
    investigation.py): procura baixas já recebidas que ainda não foram
    vinculadas a nenhuma divergência."""
    candidatas = (
        db.query(models.BaixaOperacional)
        .filter(
            models.BaixaOperacional.divergencia_vinculada_id.is_(None),
            models.BaixaOperacional.sku == sku,
            models.BaixaOperacional.almoxarifado == almoxarifado,
        )
        .all()
    )
    compativeis = [b for b in candidatas if _dentro_da_janela(b.data_baixa, data_deteccao)]
    if not compativeis:
        return None
    compativeis.sort(key=lambda b: abs((data_deteccao - b.data_baixa).days))
    return compativeis[0]


# Diferença relativa máxima entre a soma das baixas PENDENTES e a magnitude
# da divergência para ainda considerar que "correlaciona" (ver
# calcular_correlacao_baixas_pendentes) - acima disso, mesmo existindo uma
# baixa pendente do mesmo SKU+Almoxarifado, ela é tratada como não
# relacionada a ESTA divergência específica (ex: baixa pendente de 4 un.
# não deveria "explicar" uma falta de 400 un.) - fica em silêncio em vez de
# sugerir uma correlação que não se sustenta.
TOLERANCIA_CORRELACAO_QUANTIDADE = 0.5
TOLERANCIA_CORRELACAO_QUANTIDADE_PESO_CHEIO = 0.2


def calcular_correlacao_baixas_pendentes(db: Session, sku: str, almoxarifado: str, divergencia_qtd: float) -> Optional[dict]:
    """Concilia a divergência com o Relatório de Baixa (a pedido do
    Maurício, 20/08/2026): soma TODAS as baixas ainda com status_fluxo
    'PENDENTE' (nunca Aprovada - essa já tem tratamento próprio e resolve
    a divergência automaticamente, ver resolver_divergencia_automaticamente
    - nem Reprovada, que nunca deveria influenciar nada) do mesmo SKU +
    Almoxarifado, e verifica se essa soma tem correlação de QUANTIDADE com
    a magnitude da divergência.

    Deliberadamente SEM janela de data: uma baixa "semanal" ou aprovada em
    lote pode ser solicitada bem depois do dia em que a diferença foi
    detectada - o que importa aqui é Almoxarifado x Item x Quantidade, não
    coincidência de datas (essa é a diferença chave em relação a
    buscar_baixa_compativel, que é usada só no caminho de resolução
    automática por baixa APROVADA, onde a precisão de data importa mais).

    Só se aplica a FALTAS (divergencia_qtd < 0) - uma baixa é sempre uma
    saída de estoque, então nunca explica uma SOBRA.

    Devolve None quando não há nenhuma baixa pendente pra esse SKU+
    Almoxarifado, OU quando a soma encontrada está tão distante da
    magnitude da divergência (> TOLERANCIA_CORRELACAO_QUANTIDADE) que
    apontar uma "correlação" seria mais enganoso do que útil."""
    if not divergencia_qtd or divergencia_qtd >= 0:
        return None

    pendentes = (
        db.query(models.BaixaOperacional)
        .filter(
            models.BaixaOperacional.status_fluxo == "PENDENTE",
            models.BaixaOperacional.sku == sku,
            models.BaixaOperacional.almoxarifado == almoxarifado,
        )
        .all()
    )
    if not pendentes:
        return None

    soma_pendente = sum(b.quantidade or 0 for b in pendentes)
    falta = abs(divergencia_qtd)
    maior = max(falta, soma_pendente)
    diferenca_relativa = abs(falta - soma_pendente) / maior if maior else 1.0

    if diferenca_relativa > TOLERANCIA_CORRELACAO_QUANTIDADE:
        return None  # baixa(s) pendente(s) existe(m), mas a quantidade não sustenta a correlação

    return {
        "baixas": pendentes,
        "soma_quantidade_pendente": soma_pendente,
        "divergencia_qtd_absoluta": falta,
        "diferenca_relativa": round(diferenca_relativa, 4),
        "correlaciona_bem": diferenca_relativa <= TOLERANCIA_CORRELACAO_QUANTIDADE_PESO_CHEIO,
    }


def resolver_divergencia_automaticamente(db: Session, div: models.Divergencia, baixa: models.BaixaOperacional):
    """Aplica em `div` o mesmo efeito que o endpoint /confirmar aplicaria
    se um analista confirmasse manualmente essa hipótese - só que
    disparado pela baixa aprovada no Lovable, sem intervenção humana."""
    hipotese_codigo = baixa.hipotese_aplicada
    div.hipotese_confirmada = hipotese_codigo
    div.solucao_aplicada = f"Baixa de '{baixa.motivo_baixa_bruto}' aprovada no sistema operacional (Lovable), casada automaticamente."
    div.responsavel = RESPONSAVEL_AUTOMATICO
    div.status = "Resolvida"
    div.resolvido_em = datetime.utcnow()

    if div.hipotese_regras:
        h = db.query(models.Hipotese).filter_by(codigo=div.hipotese_regras).first()
        if h:
            if div.hipotese_regras == hipotese_codigo:
                h.peso_padrao = min(PESO_MAX, h.peso_padrao + INCREMENTO_ACERTO)
            else:
                h.peso_padrao = max(PESO_MIN, h.peso_padrao - INCREMENTO_ACERTO)

    db.add(models.CasoMLFeedback(
        divergencia_id=div.id, sku=div.sku, almoxarifado=div.almoxarifado,
        categoria_produto=div.categoria_produto, divergencia_qtd=div.divergencia_qtd,
        valor_estimado=div.valor_estimado, data_deteccao=div.data_deteccao,
        hipotese_confirmada=hipotese_codigo,
    ))

    baixa.divergencia_vinculada_id = div.id


def processar_baixa_recebida(db: Session, record: dict) -> dict:
    """Ponto de entrada chamado pelo endpoint de webhook (e pela
    importação/backfill em lote - ver importar_lote). Recebe o `record`
    (dicionário com as colunas da linha de baixa_operacional no
    Supabase), grava/atualiza a baixa no Atlas - de QUALQUER status
    (PENDENTE, APROVADA, REPROVADA), pra aparecer no relatório de baixa -
    e só tenta casar com uma divergência aberta quando status_fluxo for
    'APROVADA'. Não comita - o endpoint/rotina que chama decide o
    commit.

    Upsert por origem_id: uma baixa que nasce PENDENTE e depois é
    aprovada/reprovada no Lovable ATUALIZA a mesma linha aqui (não
    duplica) - por isso um evento de update com a baixa já vinculada a
    uma divergência não tenta vincular de novo."""
    sku = record.get("codigo_produto")
    id_local_bruto = record.get("id_local")
    motivo_id = record.get("motivo_baixa_id")
    status_fluxo = record.get("status_fluxo")
    hipotese_codigo = MOTIVO_ID_PARA_HIPOTESE.get(str(motivo_id)) if motivo_id else None

    if not sku or not id_local_bruto or not hipotese_codigo:
        raise BaixaInvalida(
            f"Payload incompleto ou motivo_baixa_id não reconhecido - "
            f"codigo_produto={sku!r}, id_local={id_local_bruto!r}, motivo_baixa_id={motivo_id!r}. "
            f"Se este é um motivo novo cadastrado no Lovable, adicione o UUID em "
            f"MOTIVO_ID_PARA_HIPOTESE (backend/app/baixas_operacionais.py)."
        )

    almoxarifado = ALMOXARIFADO_LOVABLE_PARA_ATLAS.get(id_local_bruto)
    if not almoxarifado:
        # Sem correspondência conhecida no Atlas - guardamos mesmo assim
        # (fica no bruto, nunca vai casar com nenhuma divergência até
        # alguém adicionar o de-para), em vez de descartar a baixa.
        almoxarifado = f"NAO_MAPEADO__{id_local_bruto}"

    data_baixa = _normalizar_data(record.get("data_ocorrencia") or record.get("data_solicitacao"))
    quantidade_bruta = record.get("quantidade")
    try:
        quantidade = float(quantidade_bruta) if quantidade_bruta is not None else None
    except (TypeError, ValueError):
        quantidade = None
    valor_total_bruto = record.get("valor_total")
    try:
        valor_total = float(valor_total_bruto) if valor_total_bruto is not None else None
    except (TypeError, ValueError):
        valor_total = None

    origem_id = record.get("id")
    origem_id = str(origem_id) if origem_id is not None else None

    baixa = db.query(models.BaixaOperacional).filter_by(origem_id=origem_id).first() if origem_id else None
    baixa_e_nova = baixa is None
    if baixa is None:
        baixa = models.BaixaOperacional(origem_id=origem_id)
        db.add(baixa)

    baixa.sku = str(sku)
    baixa.almoxarifado_origem = id_local_bruto
    baixa.almoxarifado = almoxarifado
    baixa.motivo_baixa_bruto = MOTIVO_ID_PARA_DESCRICAO.get(str(motivo_id), str(motivo_id))
    baixa.hipotese_aplicada = hipotese_codigo
    baixa.quantidade = quantidade
    baixa.valor_total = valor_total
    baixa.status_fluxo = status_fluxo
    baixa.solicitante_nome = record.get("responsavel_nome")
    baixa.data_baixa = data_baixa
    baixa.payload_bruto = record
    db.flush()  # garante baixa.id antes de eventualmente vincular

    if status_fluxo != STATUS_FLUXO_APROVADO:
        # PENDENTE ou REPROVADA - fica registrada pro relatório, mas não
        # tenta casar com divergência nenhuma ainda (pode virar APROVADA
        # depois, numa próxima atualização, ou nunca).
        return {
            "status": "importada_sem_resolver", "status_fluxo": status_fluxo,
            "baixa_id": baixa.id, "nova": baixa_e_nova, "divergencia_vinculada_id": baixa.divergencia_vinculada_id,
        }

    if baixa.divergencia_vinculada_id:
        # Já tinha sido casada antes (ex: update posterior só mudando um
        # campo qualquer) - não tenta casar de novo.
        return {"status": "ja_resolvida", "baixa_id": baixa.id, "divergencia_vinculada_id": baixa.divergencia_vinculada_id}

    if almoxarifado.startswith("NAO_MAPEADO__"):
        return {"status": "aguardando_de_para_almoxarifado", "baixa_id": baixa.id, "divergencia_vinculada_id": None}

    div = buscar_divergencia_compativel(db, str(sku), almoxarifado, data_baixa)
    if div:
        resolver_divergencia_automaticamente(db, div, baixa)
        return {"status": "resolvida_automaticamente", "baixa_id": baixa.id, "divergencia_vinculada_id": div.id}

    return {"status": "aguardando_divergencia", "baixa_id": baixa.id, "divergencia_vinculada_id": None}


def buscar_avisos_baixa_pendente(db: Session, divergencias: list) -> None:
    """Preenche o atributo transiente `aviso_baixa_pendente` em cada
    Divergencia recebida (não é coluna do banco - só existe em memória
    depois desta função rodar, no mesmo padrão de
    `tem_investigacao_pendente` em divergencias_router.py - por isso não
    precisou de nenhuma migração pra existir).

    Conciliação com o Relatório de Baixa (reformulada em 20/08/2026, a
    pedido do Maurício): não é mais "existe qualquer baixa pendente do
    mesmo SKU+Almoxarifado dentro de uma janela de datas" (isso gerava
    tanto falsos negativos - baixa pendente real, mas fora da janela de
    poucos dias - quanto o risco de apontar uma baixa pendente que não
    tem nada a ver com a magnitude desta divergência específica). Agora
    usa `calcular_correlacao_baixas_pendentes`: Almoxarifado x Item x
    Quantidade, somando todas as baixas PENDENTES desse SKU+Almoxarifado
    e comparando a soma com o tamanho da falta - SEM olhar pra data, e
    IGNORANDO Aprovadas/Reprovadas nesta análise (Aprovada já resolve a
    divergência automaticamente em outro lugar - ver
    resolver_divergencia_automaticamente -, Reprovada nunca deveria
    influenciar nada).

    Continua SEM resolver a divergência sozinha - uma baixa PENDENTE
    ainda pode ser reprovada. Só quando ela for de fato aprovada é que
    resolver_divergencia_automaticamente entra em ação (ver
    processar_baixa_recebida e o passo 0b de investigation.py)."""
    if not divergencias:
        return
    for d in divergencias:
        d.aviso_baixa_pendente = None

    abertas = [d for d in divergencias if d.status != "Resolvida"]
    for d in abertas:
        correlacao = calcular_correlacao_baixas_pendentes(db, d.sku, d.almoxarifado, d.divergencia_qtd)
        if not correlacao:
            continue
        baixas = correlacao["baixas"]
        motivos = ", ".join(sorted({b.motivo_baixa_bruto for b in baixas if b.motivo_baixa_bruto}))
        solicitantes = ", ".join(sorted({b.solicitante_nome for b in baixas if b.solicitante_nome})) or "não informado"
        qualificador = "compatível" if correlacao["correlaciona_bem"] else "parcialmente compatível"
        plural = "s" if len(baixas) > 1 else ""
        d.aviso_baixa_pendente = (
            f"Há {len(baixas)} baixa{plural} pendente{plural} de aprovação no Relatório de Baixa "
            f"('{motivos}', solicitada{plural} por {solicitantes}), somando "
            f"{correlacao['soma_quantidade_pendente']:g} unidade(s) - quantidade {qualificador} com esta "
            f"divergência ({correlacao['divergencia_qtd_absoluta']:g} un.). Ainda não foi(ram) aprovada(s) - "
            f"se aprovada(s), a divergência será resolvida automaticamente."
        )


def importar_lote(db: Session, registros: list) -> dict:
    """Importa várias baixas de uma vez (usado pelo endpoint de
    backfill/sincronização em lote, ou pra importar manualmente um
    export da tabela baixa_operacional do Lovable). Cada registro passa
    por processar_baixa_recebida - erros em um registro não travam o
    lote inteiro, ficam listados em `erros`. Também não comita - quem
    chama decide (normalmente um commit só no final do lote)."""
    contagem = {"importada_sem_resolver": 0, "resolvida_automaticamente": 0, "aguardando_divergencia": 0,
                "aguardando_de_para_almoxarifado": 0, "ja_resolvida": 0}
    erros = []
    for registro in registros:
        try:
            resultado = processar_baixa_recebida(db, registro)
            contagem[resultado["status"]] = contagem.get(resultado["status"], 0) + 1
        except BaixaInvalida as e:
            erros.append({"origem_id": registro.get("id"), "erro": str(e)})
    return {"total_recebido": len(registros), "contagem": contagem, "erros": erros}


# Colunas de baixa_operacional que processar_baixa_recebida sabe ler - é
# exatamente o que a rota /api/public/atlas-exportar-baixas do Lovable
# devolve (a paginação/seleção de colunas agora é feita do lado de lá,
# não mais montada aqui como query string do PostgREST). Deixado aqui só
# como documentação do que este código depende.
_COLUNAS_BAIXA_OPERACIONAL = (
    "id,codigo_produto,id_local,motivo_baixa_id,quantidade,valor_total,"
    "status_fluxo,data_ocorrencia,data_solicitacao,responsavel_nome"
)


class SincronizacaoIndisponivel(Exception):
    """LOVABLE_SYNC_URL/LOVABLE_SYNC_SECRET não configuradas, ou a
    chamada à rota de exportação do app do Lovable falhou (rede,
    autenticação, etc.)."""


def buscar_baixas_lovable_agora() -> list[dict]:
    """Busca AGORA o estado atual completo da tabela `baixa_operacional`
    (de qualquer status_fluxo), via uma rota própria publicada no app do
    Lovable (`/api/public/atlas-exportar-baixas`) - não mais direto no
    REST do Supabase (ver DECISOES.md, 12/08/2026).

    Por que não mais PostgREST direto: `baixa_operacional` tem RLS que só
    libera leitura pra gestor/auditor/o próprio solicitante (ver
    conferência via SQL editor do Lovable), e essa chamada é
    servidor-a-servidor, sem sessão de usuário - nem a chave anônima nem
    uma eventual chave legada bypassavam isso. A rota
    `/api/public/atlas-exportar-baixas` (código-fonte no repositório do
    Lovable) resolve isso do lado de lá: valida um segredo compartilhado
    (header `x-atlas-sync-secret` contra o secret `ATLAS_SYNC_SECRET` do
    Lovable Cloud) e, só depois de validar, consulta a tabela com a
    service role (que ignora RLS) - a service role key nunca trafega até
    aqui, fica só do lado do Lovable. A rota já pagina internamente e
    devolve todas as linhas de uma vez, num array JSON só, com exatamente
    as colunas que este módulo sabe processar (_COLUNAS_BAIXA_OPERACIONAL).

    Não grava nada no Atlas - só busca e devolve a lista de dicts, no
    mesmo formato que importar_lote espera em `registros`. Quem chama
    decide o que fazer com o resultado (ver sincronizar_com_lovable)."""
    base_url = os.environ.get("LOVABLE_SYNC_URL")
    secret = os.environ.get("LOVABLE_SYNC_SECRET")
    if not base_url or not secret:
        raise SincronizacaoIndisponivel(
            "Sincronização com o Lovable não configurada: defina LOVABLE_SYNC_URL "
            "(a URL do app do Lovable, ex: https://stockswift-sync-75.lovable.app) e "
            "LOVABLE_SYNC_SECRET (o mesmo valor do secret ATLAS_SYNC_SECRET cadastrado "
            "em Lovable Cloud > Secrets) no ambiente do servidor (Render)."
        )
    base_url = base_url.rstrip("/")

    url = f"{base_url}/api/public/atlas-exportar-baixas"
    requisicao = urllib.request.Request(url, method="GET")
    requisicao.add_header("x-atlas-sync-secret", secret)
    # O app do Lovable é servido atrás de uma CDN (Cloudflare) com proteção
    # anti-bot, que bloqueia requisições sem um User-Agent de navegador (o
    # padrão do urllib, "Python-urllib/x.y", já foi bloqueado com
    # HTTP 403 "error code: 1010" - ban de "autonomous software agent",
    # nada a ver com o secret estar errado). Um User-Agent/Accept comuns
    # de navegador resolvem isso sem precisar de nenhuma credencial nova.
    requisicao.add_header("User-Agent", "Mozilla/5.0 (compatible; Atlas-Sync/1.0)")
    requisicao.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(requisicao, timeout=60) as resposta:
            registros = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")
        dica_extra = (
            " (esse 'error code: 1010' é bloqueio anti-bot da Cloudflare na frente do "
            "app do Lovable, não tem relação com o secret - se persistir, pode ser "
            "necessário liberar o IP do Render nas configurações de segurança do Lovable)"
            if "1010" in corpo else ""
        )
        raise SincronizacaoIndisponivel(
            f"O app do Lovable respondeu {e.code} ao buscar baixa_operacional: {corpo}.{dica_extra} "
            f"Confira se LOVABLE_SYNC_URL/LOVABLE_SYNC_SECRET estão corretos e se o secret "
            f"bate com ATLAS_SYNC_SECRET cadastrado em Lovable Cloud > Secrets."
        ) from e
    except urllib.error.URLError as e:
        raise SincronizacaoIndisponivel(f"Não consegui alcançar o app do Lovable: {e.reason}") from e

    if not isinstance(registros, list):
        raise SincronizacaoIndisponivel(
            f"Resposta inesperada do Lovable ao buscar baixa_operacional (esperava uma lista, "
            f"recebi {type(registros).__name__}): {json.dumps(registros)[:500]}"
        )
    return registros


def sincronizar_com_lovable(db: Session) -> dict:
    """Busca o estado atual da tabela baixa_operacional no Lovable e
    reimporta tudo pro Atlas de uma vez (usado pelo botão "Sincronizar
    agora" da tela Relatório de Baixa). importar_lote faz upsert por
    origem_id, então isso também ATUALIZA baixas que estavam Pendente e
    foram aprovadas/reprovadas no Lovable desde a última sincronização -
    não duplica nada, e é seguro clicar de novo quantas vezes quiser.
    Não comita - quem chama decide (ver baixas_operacionais_router)."""
    registros = buscar_baixas_lovable_agora()
    resultado = importar_lote(db, registros)
    resultado["total_na_origem"] = len(registros)
    return resultado


def _normalizar_data_planilha(valor) -> Optional[date]:
    """Aceita tanto o formato DD/MM/AAAA usado no export "Baixar relatório
    completo" da tela Baixas Operacionais quanto uma data/datetime já
    processada pelo openpyxl (algumas planilhas trazem a coluna Data como
    tipo data real, não como texto)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return date.fromisoformat(s[:10])


def importar_planilha_historico_lovable(db: Session, linhas: list[dict]) -> dict:
    """Reconcilia o export "Baixar relatório completo" da tela Baixas
    Operacionais (Lovable) contra o que já está no Atlas - fallback pra usar
    quando o botão "Sincronizar agora" (pull ao vivo do Supabase) não está
    disponível (ex: credencial não configurada) ou dá erro de conexão. Vive
    no módulo Importar, não mais na tela Relatório de Baixa - ver
    importar_router.py.

    Diferente de importar_lote/processar_baixa_recebida, essa planilha NÃO
    tem o `id` (uuid) real da linha no Supabase - não tem como fazer upsert
    por origem_id, então cada linha da planilha é casada com o que já existe
    no Atlas por uma CHAVE ESTÁVEL (SKU + Almoxarifado já mapeado + Hipótese
    + Quantidade + Valor + Data) - **sem o Status**.

    Por que sem o Status: descoberto em produção (11/08/2026, ver
    DECISOES.md) que toda baixa nasce Pendente e muda de status quando é
    decidida (Aprovada/Reprovada) - se o Status entra na chave de casamento,
    toda baixa cujo status mudou desde a última sincronização deixa de
    "casar" com a linha já existente e é inserida de novo como se fosse um
    evento novo, duplicando (rodado uma vez contra produção real: 638 baixas
    -> 865, sendo pelo menos 11 pares confirmados como a MESMA baixa
    duplicada só porque tinha virado Aprovada/Reprovada nesse meio tempo -
    ver _remover_duplicatas_status_baixa_operacional em database.py pra
    limpeza retroativa desse lote). Com a chave estável, uma baixa que já
    existe e só teve o status decidido é ATUALIZADA no lugar (e, se acabou
    de virar Aprovada, tenta casar com divergência igual já faz o fluxo
    normal) em vez de criar uma linha nova.

    Ainda usa CONTAGEM (multiset), não presença simples - baixas genuinamente
    distintas podem ter a mesma chave estável por coincidência (mesmo
    produto, motivo, quantidade e valor lançados mais de uma vez, em datas
    diferentes ou até no mesmo dia - achados 22 grupos assim, 79 linhas, num
    lote real de 750). Cada linha da planilha consome, na ordem, a ocorrência
    já existente mais antiga ainda não usada com a mesma chave; quando não
    sobra nenhuma, insere uma linha nova."""
    existentes = db.query(models.BaixaOperacional).order_by(models.BaixaOperacional.id.asc()).all()
    existentes_por_chave = defaultdict(list)
    for b in existentes:
        chave = (b.sku, b.almoxarifado, b.hipotese_aplicada, b.quantidade, b.valor_total, b.data_baixa)
        existentes_por_chave[chave].append(b)

    total = 0
    erros = []
    ja_existentes = 0
    atualizadas_status = 0
    novas_importadas = 0
    resolvidas_automaticamente = 0
    aguardando_divergencia = 0
    aguardando_de_para_almoxarifado = 0

    for i, linha in enumerate(linhas, start=2):
        sku_bruto = linha.get("Código")
        if sku_bruto is None or str(sku_bruto).strip() == "":
            continue
        total += 1
        sku = str(sku_bruto).strip()
        try:
            motivo_texto = str(linha.get("Motivo") or "").strip()
            motivo_id = DESCRICAO_PARA_MOTIVO_ID.get(motivo_texto)
            hipotese_codigo = MOTIVO_ID_PARA_HIPOTESE.get(motivo_id) if motivo_id else None
            if not hipotese_codigo:
                erros.append(f"Linha {i} (Código {sku}): motivo '{motivo_texto}' não reconhecido - adicione em MOTIVO_ID_PARA_DESCRICAO/MOTIVO_ID_PARA_HIPOTESE se for um motivo novo.")
                continue

            id_local_bruto = str(linha.get("Almoxarifado") or "").strip()
            almoxarifado = ALMOXARIFADO_LOVABLE_PARA_ATLAS.get(id_local_bruto) or f"NAO_MAPEADO__{id_local_bruto or '(vazio)'}"

            data_baixa = _normalizar_data_planilha(linha.get("Data"))

            quantidade_bruta = linha.get("Quantidade")
            quantidade = float(quantidade_bruta) if quantidade_bruta not in (None, "") else None
            valor_total_bruto = linha.get("Valor Total")
            valor_total = float(valor_total_bruto) if valor_total_bruto not in (None, "") else None

            status_fluxo = str(linha.get("Status") or "").strip().upper()
            solicitante_nome = (str(linha.get("Solicitante")).strip() or None) if linha.get("Solicitante") else None
            motivo_baixa_bruto = MOTIVO_ID_PARA_DESCRICAO.get(motivo_id, motivo_texto)
            payload_bruto = {k: (str(v) if v is not None else None) for k, v in linha.items()} | {"_fonte": "backfill_planilha_historico"}

            chave_estavel = (sku, almoxarifado, hipotese_codigo, quantidade, valor_total, data_baixa)
            fila = existentes_por_chave.get(chave_estavel)
            baixa_para_resolver = None

            if fila:
                existente = fila.pop(0)
                if existente.status_fluxo == status_fluxo:
                    ja_existentes += 1
                else:
                    existente.status_fluxo = status_fluxo
                    if solicitante_nome:
                        existente.solicitante_nome = solicitante_nome
                    atualizadas_status += 1
                    baixa_para_resolver = existente
            else:
                baixa = models.BaixaOperacional(
                    origem_id=None, sku=sku, almoxarifado_origem=id_local_bruto or None, almoxarifado=almoxarifado,
                    motivo_baixa_bruto=motivo_baixa_bruto, hipotese_aplicada=hipotese_codigo,
                    quantidade=quantidade, valor_total=valor_total, status_fluxo=status_fluxo,
                    solicitante_nome=solicitante_nome, data_baixa=data_baixa, payload_bruto=payload_bruto,
                )
                db.add(baixa)
                db.flush()
                novas_importadas += 1
                baixa_para_resolver = baixa

            if baixa_para_resolver is None or status_fluxo != STATUS_FLUXO_APROVADO:
                continue
            if baixa_para_resolver.divergencia_vinculada_id:
                continue  # já resolvida antes - não tenta de novo
            if almoxarifado.startswith("NAO_MAPEADO__"):
                aguardando_de_para_almoxarifado += 1
                continue
            div = buscar_divergencia_compativel(db, sku, almoxarifado, data_baixa) if data_baixa else None
            if div:
                resolver_divergencia_automaticamente(db, div, baixa_para_resolver)
                resolvidas_automaticamente += 1
            else:
                aguardando_divergencia += 1
        except Exception as e:
            erros.append(f"Linha {i} (Código {sku}): {e}")

    return {
        "total_planilha": total, "ja_existentes": ja_existentes, "atualizadas_status": atualizadas_status,
        "novas_importadas": novas_importadas, "resolvidas_automaticamente": resolvidas_automaticamente,
        "aguardando_divergencia": aguardando_divergencia,
        "aguardando_de_para_almoxarifado": aguardando_de_para_almoxarifado, "erros": erros,
    }
