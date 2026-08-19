"""
Assistente Atlas por voz/texto (25/08/2026 - pedido do Maurício): reaproveita
o comando de voz que já existe no hub ("Atlas, [módulo]" - ver
configurarComandoDeVoz() em app.js) pra também responder perguntas abertas,
tipo "Atlas, resumo do dia", "quais os motivos mais recorrentes de
divergência" ou "onde encontro os pedidos de compra atrasados".

Como funciona, em 2 passos:
1. `montar_contexto()` reúne um "retrato" do estado atual do Atlas -
   reaproveitando as MESMAS funções que já alimentam a tela Início (Mapa de
   Demandas) e os dashboards de FEFO/Shelf Life, mais contagens de HOJE
   (divergências detectadas/resolvidas, baixas aprovadas, fechamentos
   importados) e os motivos de divergência mais recorrentes dos últimos 90
   dias.
2. `responder_pergunta_assistente()` manda esse retrato + a pergunta pro
   provedor de IA generativa já configurado em app/ia_generativa.py (Google
   Gemini) e pede uma resposta curta, em português falado.

Importante: a IA generativa NUNCA consulta o banco direto - só vê o
retrato que este módulo monta. Isso significa que ela não pode "inventar"
um número que não esteja aqui, mas também significa que uma pergunta sobre
algo fora deste retrato (ex: um SKU específico) não vai ter resposta
precisa - nesses casos o prompt pede pra IA admitir isso e indicar em qual
módulo a pessoa provavelmente encontra a resposta, em vez de arriscar um
palpite.

Sobre restrição por almoxarifado (Usuario.almoxarifados_permitidos): os
blocos escritos aqui (divergências/baixas de hoje, motivos recorrentes)
respeitam essa restrição, do mesmo jeito que o resto do Atlas. Os blocos
reaproveitados do Mapa de Demandas (passivo pendente, obsolescência,
Shelf Life, FEFO) NÃO filtram por almoxarifado - mesma lacuna que já existe
hoje no próprio endpoint /dashboard/mapa-demandas (não é uma regressão
introduzida aqui; corrigir isso é uma mudança maior, em vários módulos, que
não foi pedida agora).
"""
from datetime import date, timedelta
import json as _json

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, shelf_life, fefo, ia_generativa
from .hipoteses_config import HIPOTESES as _HIPOTESES_CATALOGO
from .deps import filtrar_por_almoxarifado_permitido
from .routers.dashboard_router import _calcular_baixas_pendentes, _calcular_risco_obsolescencia

_NOMES_HIPOTESES = {codigo: nome for codigo, nome, _descricao in _HIPOTESES_CATALOGO}

# Descrição curta de cada módulo, pra IA orientar "onde encontro X" - mantido
# em prosa simples de propósito (é isso que entra no prompt, não um menu de
# navegação real; não precisa ficar 100% sincronizado com HUB_PALAVRAS_CHAVE_POR_VIEW
# do frontend, mas vale revisar os dois juntos se um módulo novo for adicionado).
MAPA_MODULOS = [
    {"modulo": "Início", "conteudo": "Visão geral: passivo de baixas pendentes, risco de obsolescência (baixo giro) e risco de Shelf Life/validade."},
    {"modulo": "Painel de Divergências", "conteudo": "Divergências abertas, por status e por almoxarifado."},
    {"modulo": "Lista de Divergências", "conteudo": "Lista detalhada de cada divergência, com filtros; clicar numa linha abre o diagnóstico completo (hipóteses, evidências, casos similares)."},
    {"modulo": "Cobertura de Conferência", "conteudo": "Quais dias/almoxarifados tiveram (ou não) conferência de Movimentados ou fechamento no período."},
    {"modulo": "Importar", "conteudo": "Upload de planilhas: movimentação, fechamento de inventário, auditoria FEFO, ajustes de inventário, baixas operacionais."},
    {"modulo": "Painel de Inventário", "conteudo": "Acurácia e evolução dos fechamentos de inventário mensal, por almoxarifado."},
    {"modulo": "Acurácia Ponderada", "conteudo": "Acurácia ponderada por valor financeiro (IAP), além da acurácia item a item (IAQ)."},
    {"modulo": "Controle de Compras", "conteudo": "Pedidos de compra em aberto, atrasados, e itens pendentes de recebimento."},
    {"modulo": "Fechamento de Inventário", "conteudo": "Histórico de fechamentos por almoxarifado, ciência/assinatura dupla e geração de PDF."},
    {"modulo": "Pós-Inventário", "conteudo": "Ações de acompanhamento ('próximo passo') abertas a partir de itens divergentes de um fechamento - responsável e prazo."},
    {"modulo": "Cadastros", "conteudo": "Cadastro de produtos, almoxarifados e catálogo de hipóteses de causa-raiz."},
    {"modulo": "Auditoria", "conteudo": "Log de todas as ações realizadas no Atlas, por usuário e data."},
    {"modulo": "Usuários", "conteudo": "Gestão de contas e papéis de acesso (admin/analista/leitura)."},
    {"modulo": "Relatório de Baixa / Mapeamento de Passivos", "conteudo": "Todas as baixas operacionais (Avaria, Vencimento, Descarte...), mapeamento de origem (inventário mensal vs. movimentação diária), resumo executivo, e a análise por IA generativa (categoria/prioridade/resumo sugeridos)."},
    {"modulo": "Controle de Movimentados", "conteudo": "Transferências entre almoxarifados e checagem do critério FEFO nas saídas da Fábrica."},
]


def _contar_divergencias_hoje(db: Session, usuario) -> dict:
    hoje = date.today()
    base = db.query(models.Divergencia)
    base = filtrar_por_almoxarifado_permitido(base, models.Divergencia.almoxarifado, usuario, None)
    return {
        "abertas_total": base.filter(models.Divergencia.status == "Aberta").count(),
        "em_investigacao": base.filter(models.Divergencia.status == "Em_Investigacao").count(),
        "detectadas_hoje": base.filter(models.Divergencia.data_deteccao == hoje).count(),
        "resolvidas_hoje": base.filter(
            models.Divergencia.status == "Resolvida", func.date(models.Divergencia.resolvido_em) == hoje
        ).count(),
    }


def _contar_baixas_hoje(db: Session, usuario) -> dict:
    hoje = date.today()
    base = db.query(models.BaixaOperacional).filter(models.BaixaOperacional.status_fluxo == "APROVADA")
    base = filtrar_por_almoxarifado_permitido(base, models.BaixaOperacional.almoxarifado, usuario, None)
    aprovadas_hoje = base.filter(models.BaixaOperacional.data_baixa == hoje).all()
    return {
        "aprovadas_hoje_qtd": len(aprovadas_hoje),
        "aprovadas_hoje_valor": round(sum(b.valor_total or 0 for b in aprovadas_hoje), 2),
    }


def _contar_fechamentos_hoje(db: Session) -> int:
    hoje = date.today()
    return db.query(models.FechamentoInventario).filter(func.date(models.FechamentoInventario.criado_em) == hoje).count()


def _acoes_pos_inventario_resumo(db: Session) -> dict:
    hoje = date.today()
    acoes = db.query(models.AcaoPosInventario).all()
    pendentes = [a for a in acoes if a.status in ("Pendente", "Em_Andamento")]
    atrasadas = [a for a in pendentes if a.prazo and a.prazo < hoje]
    concluidas_hoje = [a for a in acoes if a.concluido_em and a.concluido_em.date() == hoje]
    return {
        "pendentes_total": len(pendentes),
        "atrasadas_total": len(atrasadas),
        "concluidas_hoje": len(concluidas_hoje),
        "exemplos_atrasadas": [
            {"sku": a.sku, "acao": a.acao_descricao, "responsavel": a.responsavel, "prazo": str(a.prazo)}
            for a in sorted(atrasadas, key=lambda a: a.prazo)[:5]
        ],
    }


def _top_motivos_divergencia(db: Session, usuario, dias: int = 90, top: int = 5) -> list:
    desde = date.today() - timedelta(days=dias)
    base = db.query(models.Divergencia.hipotese_ia, func.count(models.Divergencia.id).label("qtd")).filter(
        models.Divergencia.data_deteccao >= desde, models.Divergencia.hipotese_ia.isnot(None),
    )
    base = filtrar_por_almoxarifado_permitido(base, models.Divergencia.almoxarifado, usuario, None)
    linhas = (
        base.group_by(models.Divergencia.hipotese_ia)
        .order_by(func.count(models.Divergencia.id).desc())
        .limit(top)
        .all()
    )
    return [{"hipotese": codigo, "nome": _NOMES_HIPOTESES.get(codigo, codigo), "quantidade": qtd} for codigo, qtd in linhas]


def _resumo_baixas_pendentes(db: Session) -> dict:
    r = _calcular_baixas_pendentes(db)
    return {"total": r["total"], "valor_total": r["valor_total"], "por_motivo": r["por_motivo"][:5]}


def _resumo_obsolescencia(db: Session) -> dict:
    return {"resumo": _calcular_risco_obsolescencia(db)["resumo"]}


def montar_contexto(db: Session, usuario, pergunta_padrao: dict | None = None) -> dict:
    """Reúne tudo num "retrato" só do estado atual do Atlas. Cada bloco é
    isolado num try/except pra um problema num indicador (ex: banco muito
    novo, tabela vazia) não impedir os outros de aparecer nem derrubar o
    assistente inteiro - melhor responder com o que dá do que falhar tudo
    por causa de 1 número.

    `pergunta_padrao` (opcional) é uma entrada do catálogo em
    app/assistente_perguntas_padrao.py, já identificada pelo endpoint via
    identificar_pergunta_padrao(pergunta) - ver módulo de pré-validação.
    Quando ela tem um `contexto_extra_fn`, o resultado entra numa chave
    dedicada (`detalhamento_para_esta_pergunta`), só pra essa pergunta - as
    outras continuam recebendo só os blocos genéricos abaixo, sem o custo
    extra de calcular um detalhamento que não vão usar."""
    contexto = {"data_hoje": str(date.today())}

    def _seguro(chave, calculo):
        try:
            contexto[chave] = calculo()
        except Exception as erro:
            contexto[chave] = {"indisponivel": f"{erro.__class__.__name__}: não foi possível calcular agora"}

    _seguro("divergencias", lambda: _contar_divergencias_hoje(db, usuario))
    _seguro("baixas_operacionais", lambda: _contar_baixas_hoje(db, usuario))
    _seguro("fechamentos_de_inventario_criados_hoje", lambda: _contar_fechamentos_hoje(db))
    _seguro("acoes_pos_inventario", lambda: _acoes_pos_inventario_resumo(db))
    _seguro("motivos_de_divergencia_mais_recorrentes_ultimos_90_dias", lambda: _top_motivos_divergencia(db, usuario))
    _seguro("passivo_de_baixas_pendentes", lambda: _resumo_baixas_pendentes(db))
    _seguro("risco_de_obsolescencia_baixo_giro", lambda: _resumo_obsolescencia(db))
    _seguro("risco_de_validade_shelf_life", lambda: shelf_life.calcular_resumo_shelf_life(db, incluir_itens=False))
    _seguro("fefo_transferencias", lambda: fefo.calcular_resumo_checagem_fefo_movimento(db))

    if pergunta_padrao and pergunta_padrao.get("contexto_extra_fn"):
        _seguro("detalhamento_para_esta_pergunta", lambda: pergunta_padrao["contexto_extra_fn"](db, usuario))

    return contexto


def responder_pergunta_assistente(pergunta: str, contexto: dict, pergunta_padrao: dict | None = None) -> str:
    """Manda a pergunta + o retrato atual do Atlas (montar_contexto) pro
    provedor de IA generativa, pedindo uma resposta curta, em português
    falado (sem markdown, sem listas com marcadores) - a resposta é lida em
    voz alta pelo navegador (ver falarResumoModulo em app.js), então texto
    corrido e direto funciona muito melhor que um formato de "relatório".
    Levanta ia_generativa.IAGenerativaIndisponivel se a IA não estiver
    configurada ou a chamada falhar - o endpoint trata isso como 503.

    `pergunta_padrao` (opcional, ver app/assistente_perguntas_padrao.py) dá
    um "norte" extra pro prompt - a instrucao_extra da entrada do catálogo
    que bateu com essa pergunta, indicando pra IA onde focar/qual bloco do
    retrato usar. Sem isso, a IA depende só do bom senso pra achar o que
    interessa dentro do retrato inteiro."""
    modulos_txt = "\n".join(f"- {m['modulo']}: {m['conteudo']}" for m in MAPA_MODULOS)
    instrucao_padrao_txt = ""
    if pergunta_padrao and pergunta_padrao.get("instrucao_extra"):
        instrucao_padrao_txt = (
            f"\nEssa pergunta foi reconhecida como uma pergunta padrão do tipo "
            f"\"{pergunta_padrao['rotulo']}\" - siga esta orientação específica pra responder: "
            f"{pergunta_padrao['instrucao_extra']}\n"
        )
    prompt = f"""Você é o assistente de voz do Atlas, o sistema de inteligência de estoque da Magio Chocolates.
Alguém acabou de te fazer esta pergunta, falando em voz alta: "{pergunta}"

Responda em português do Brasil, em texto corrido (SEM markdown, SEM listas com
marcadores, SEM emojis, SEM títulos) - a resposta vai ser lida em voz alta por um
sintetizador de fala, então frases curtas e diretas funcionam muito melhor que
parágrafos longos. No máximo 5 frases.

Use SOMENTE os números do retrato abaixo - nunca invente um dado que não esteja
aqui. Se a pergunta pedir algo que não está neste retrato (ex: um SKU específico,
ou um período diferente de hoje), diga isso claramente e indique em qual módulo da
lista abaixo a pessoa provavelmente encontra essa informação, em vez de arriscar
um palpite.
{instrucao_padrao_txt}
Retrato atual do Atlas (hoje é {contexto.get('data_hoje')}):
{_json.dumps(contexto, ensure_ascii=False, indent=2, default=str)}

Módulos disponíveis no Atlas (use pra orientar perguntas do tipo "onde encontro X"):
{modulos_txt}"""

    resposta = ia_generativa._chamar_gemini(prompt, esperar_json=False, temperatura=0.3)
    return resposta.strip()
