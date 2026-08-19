"""
Perguntas padrão do Assistente Atlas (19/08/2026 - pedido do Maurício, a
partir de um caso real: perguntou "Qual almoxarifado representa um risco"
e o assistente respondeu corretamente que não tinha esse dado quebrado por
almoxarifado no retrato genérico, mas isso deixava a resposta menos útil
do que podia ser).

O problema que este módulo resolve: `assistente_ia.montar_contexto()`
monta um retrato só com números AGREGADOS (Atlas inteiro) pra risco de
obsolescência/Shelf Life/FEFO - sem quebra por almoxarifado, SKU etc. Uma
pergunta genérica ("resumo do dia") não precisa de mais que isso, mas uma
pergunta mais específica ("qual almoxarifado...") merece um detalhamento
mais preciso, senão a IA só pode admitir a limitação em vez de responder
de verdade.

Como funciona - "pré-validação" simples, sem gastar outra chamada de IA
generativa pra classificar a pergunta (mantém o custo em 1 chamada por
pergunta, igual já era):

1. `identificar_pergunta_padrao(pergunta)` compara o texto digitado/falado
   contra os `gatilhos` de cada entrada do catálogo `PERGUNTAS_PADRAO`
   (comparação simples de substring, sem acento/maiúscula).
2. Quando bate com uma entrada que tem `contexto_extra_fn`,
   `assistente_ia.montar_contexto()` chama essa função e anexa o
   resultado ao retrato numa chave dedicada (`detalhamento_para_esta_pergunta`)
   - só pra ESSA pergunta, sem inflar o retrato de todas as outras (que
   continuam recebendo só os blocos genéricos, mais rápidos de calcular).
3. `assistente_ia.responder_pergunta_assistente()` inclui a
   `instrucao_extra` da entrada no prompt, dando um "norte" de onde focar
   a resposta.

Pra adicionar uma pergunta padrão nova (e o botão correspondente na tela
Início - ver GET /assistente/perguntas-padrao, que lê direto deste
catálogo): só acrescentar uma entrada em PERGUNTAS_PADRAO. Se ela precisar
de dados mais específicos que o retrato genérico já cobre, escreva uma
função `_contexto_de_algo(db, usuario)` e aponte em `contexto_extra_fn` -
senão deixe `None` (a pergunta ainda é reconhecida e ganha a
`instrucao_extra`, só não ganha um bloco de dados extra).

Módulo de configuração (09/08/2026 - pedido do Maurício): além deste
catálogo fixo (que só muda com uma alteração de código, feita numa sessão
como esta), administradores podem criar/editar/excluir perguntas padrão
PELO PRÓPRIO APP, sem depender de uma nova versão - ver
`models.PerguntaPadraoPersonalizada`, os endpoints em
`routers/assistente_router.py` (`POST/PUT/DELETE /assistente/perguntas-padrao`,
restritos a admin via `requer_papel("admin")`) e o painel "⚙️ Configurar
perguntas padrão" no frontend. `listar_perguntas_padrao(db)` e
`identificar_pergunta_padrao(pergunta, db)` combinam as duas fontes: o
catálogo fixo é checado primeiro (preserva a ordem/comportamento de antes
pra quem já dependia disso), depois as personalizadas ativas. Uma entrada
personalizada nunca tem `contexto_extra_fn` (é uma função Python, não dá
pra guardar em banco) - só gatilhos + instrução textual pra IA, igual às
entradas do catálogo fixo que também não têm detalhamento extra."""
import re
import unicodedata
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, shelf_life, fefo
from .deps import filtrar_por_almoxarifado_permitido
from .routers.dashboard_router import _calcular_risco_obsolescencia


def _normalizar(txt: str) -> str:
    txt = (txt or "").lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def _top_por_almoxarifado_valor(itens: list, chave_valor: str, top: int = 5) -> list:
    """Agrupa uma lista de itens (que já tem uma chave "almoxarifado" e uma
    chave de valor) somando quantidade e valor por almoxarifado, e devolve
    só os `top` almoxarifados com maior valor acumulado - usado tanto pro
    risco de validade quanto pro de obsolescência abaixo, que têm o mesmo
    formato de item (ver shelf_life.py / dashboard_router.py)."""
    acumulado = {}
    for it in itens:
        almox = it.get("almoxarifado") or "Não informado"
        bloco = acumulado.setdefault(almox, {"quantidade": 0, "valor": 0.0})
        bloco["quantidade"] += 1
        bloco["valor"] += it.get(chave_valor) or 0
    linhas = [{"almoxarifado": a, "quantidade": v["quantidade"], "valor": round(v["valor"], 2)} for a, v in acumulado.items()]
    linhas.sort(key=lambda x: x["valor"], reverse=True)
    return linhas[:top]


def _contexto_risco_por_almoxarifado(db: Session, usuario) -> dict:
    """Detalhamento específico pra perguntas do tipo "qual almoxarifado
    representa risco" - quebra por almoxarifado os MESMOS sinais que o
    retrato genérico só mostra agregados (Atlas inteiro). De propósito NÃO
    combina os quatro blocos numa única "pontuação de risco por
    almoxarifado": inventar um peso entre divergência/validade/
    obsolescência/FEFO seria dado fabricado, não calculado - a IA sintetiza
    a partir dos números separados (ver instrucao_extra em
    PERGUNTAS_PADRAO), sem que o Atlas decida por ela qual pesa mais.
    Cada bloco é isolado (mesmo padrão de montar_contexto): 1 falhar não
    derruba os outros."""
    contexto = {}

    try:
        base = db.query(
            models.Divergencia.almoxarifado, func.count(models.Divergencia.id).label("qtd")
        ).filter(models.Divergencia.status == "Aberta")
        base = filtrar_por_almoxarifado_permitido(base, models.Divergencia.almoxarifado, usuario, None)
        linhas = base.group_by(models.Divergencia.almoxarifado).order_by(func.count(models.Divergencia.id).desc()).limit(5).all()
        contexto["divergencias_abertas_por_almoxarifado"] = [{"almoxarifado": a or "Não informado", "quantidade": q} for a, q in linhas]
    except Exception as erro:
        contexto["divergencias_abertas_por_almoxarifado"] = {"indisponivel": erro.__class__.__name__}

    try:
        shelf = shelf_life.calcular_resumo_shelf_life(db, incluir_itens=True, limite_itens=2000)
        contexto["risco_de_validade_por_almoxarifado"] = _top_por_almoxarifado_valor(shelf["itens"], "valor_estimado")
    except Exception as erro:
        contexto["risco_de_validade_por_almoxarifado"] = {"indisponivel": erro.__class__.__name__}

    try:
        obsolescencia = _calcular_risco_obsolescencia(db)
        contexto["obsolescencia_por_almoxarifado"] = _top_por_almoxarifado_valor(obsolescencia["itens"], "valor_estimado")
    except Exception as erro:
        contexto["obsolescencia_por_almoxarifado"] = {"indisponivel": erro.__class__.__name__}

    try:
        fefo_resumo = fefo.calcular_resumo_checagem_fefo_movimento(db)
        contexto["quebras_de_fefo_por_almoxarifado_destino"] = fefo_resumo.get("top_destinos_com_quebra", [])
    except Exception as erro:
        contexto["quebras_de_fefo_por_almoxarifado_destino"] = {"indisponivel": erro.__class__.__name__}

    return contexto


# Catálogo único de perguntas padrão - fonte de verdade tanto pro roteamento
# (identificar_pergunta_padrao) quanto pros botões de pergunta rápida da tela
# Início (GET /assistente/perguntas-padrao lê direto daqui, ver
# assistente_router.py e carregarPerguntasPadraoAssistente() em app.js).
PERGUNTAS_PADRAO = [
    {
        "chave": "resumo_do_dia",
        "rotulo": "Resumo do dia",
        "pergunta": "Resumo do dia",
        "gatilhos": ["resumo do dia", "resumo de hoje", "resumo hoje", "o que aconteceu hoje", "o que foi feito hoje"],
        "instrucao_extra": (
            "Essa pergunta é sobre o dia de hoje - foque no que já foi feito (divergências detectadas/"
            "resolvidas, baixas aprovadas, fechamentos criados) e no que está pendente/planejado (ações "
            "pós-inventário). Não é necessário repetir números de risco de longo prazo aqui."
        ),
        "contexto_extra_fn": None,
    },
    {
        "chave": "motivos_recorrentes_divergencia",
        "rotulo": "Motivos mais recorrentes de divergência",
        "pergunta": "Quais são os motivos mais recorrentes de divergência?",
        "gatilhos": [
            "motivo mais recorrente", "motivos mais recorrentes", "causa mais comum", "causas mais comuns",
            "motivo de divergencia", "motivos de divergencia", "motivo das divergencias",
        ],
        "instrucao_extra": (
            "A resposta já está pronta na chave motivos_de_divergencia_mais_recorrentes_ultimos_90_dias "
            "do retrato (já ordenada do mais pro menos recorrente) - baseie a resposta diretamente nela."
        ),
        "contexto_extra_fn": None,
    },
    {
        # Fica ANTES de "riscos_negocio" de propósito: uma pergunta como "qual
        # almoxarifado tem mais risco pro negócio?" bate nos gatilhos de AMBAS
        # as entradas ("almoxarifado tem mais risco" e "risco pro negocio"), e
        # identificar_pergunta_padrao() fica com a primeira que bater - a
        # pergunta menciona almoxarifado explicitamente, então merece a
        # resposta mais específica (quebrada por almoxarifado), não a
        # genérica. Ver teste em test_perguntas_padrao.py que cobre esse caso.
        "chave": "risco_por_almoxarifado",
        "rotulo": "Qual almoxarifado representa mais risco?",
        "pergunta": "Qual almoxarifado representa mais risco pro negócio?",
        "gatilhos": [
            "qual almoxarifado", "almoxarifado representa", "almoxarifado com mais risco",
            "almoxarifado tem mais risco", "qual local representa risco", "qual unidade tem mais risco",
        ],
        "instrucao_extra": (
            "Use o bloco detalhamento_para_esta_pergunta - ele quebra divergências abertas, risco de validade "
            "e obsolescência POR ALMOXARIFADO, além das quebras de FEFO por destino. Aponte o(s) almoxarifado(s) "
            "que aparecem repetidamente no topo de mais de um desses blocos - isso é o sinal mais forte de risco "
            "concentrado. Não invente uma pontuação combinada entre os blocos - se nenhum almoxarifado se repetir, "
            "diga isso e cite o topo de cada bloco separadamente."
        ),
        "contexto_extra_fn": _contexto_risco_por_almoxarifado,
    },
    {
        "chave": "riscos_negocio",
        "rotulo": "Riscos pro negócio",
        "pergunta": "Quais são os principais riscos pro negócio agora?",
        "gatilhos": ["risco pro negocio", "riscos pro negocio", "principal risco", "principais riscos", "riscos do negocio"],
        "instrucao_extra": (
            "Cruze passivo_de_baixas_pendentes, risco_de_obsolescencia_baixo_giro, risco_de_validade_shelf_life "
            "e fefo_transferencias - aponte qual desses te parece mais crítico agora e por quê, em termos de "
            "valor financeiro em risco."
        ),
        "contexto_extra_fn": None,
    },
]


def _entradas_personalizadas_ativas(db: Session) -> list:
    """Busca as perguntas personalizadas (ver models.PerguntaPadraoPersonalizada)
    e devolve no MESMO formato de dict das entradas fixas de PERGUNTAS_PADRAO,
    pra poderem ser tratadas de forma idêntica pelo resto deste módulo e por
    assistente_ia.py. `contexto_extra_fn` é sempre None aqui - ver docstring
    do módulo."""
    if db is None:
        return []
    linhas = db.query(models.PerguntaPadraoPersonalizada).filter_by(ativo=True).order_by(
        models.PerguntaPadraoPersonalizada.criado_em
    ).all()
    return [
        {
            "chave": linha.chave,
            "rotulo": linha.rotulo,
            "pergunta": linha.pergunta,
            "gatilhos": linha.gatilhos or [],
            "instrucao_extra": linha.instrucao_extra,
            "contexto_extra_fn": None,
            "personalizada": True,
        }
        for linha in linhas
    ]


def identificar_pergunta_padrao(pergunta: str, db: Session | None = None) -> dict | None:
    """Compara a pergunta contra os gatilhos de cada entrada - primeiro o
    catálogo FIXO (PERGUNTAS_PADRAO, primeira que bater ganha - preserva o
    comportamento de antes desta função existir), depois as personalizadas
    criadas via app (ver _entradas_personalizadas_ativas). `db` é opcional
    só pra não quebrar quem já chamava esta função sem banco (nesse caso,
    simplesmente não considera as personalizadas)."""
    alvo = _normalizar(pergunta)
    for entrada in PERGUNTAS_PADRAO:
        for gatilho in entrada["gatilhos"]:
            if _normalizar(gatilho) in alvo:
                return entrada
    for entrada in _entradas_personalizadas_ativas(db):
        for gatilho in entrada["gatilhos"]:
            if _normalizar(gatilho) in alvo:
                return entrada
    return None


def listar_perguntas_padrao(db: Session | None = None) -> list:
    """Formato seguro pra expor via API (sem a função contexto_extra_fn,
    que não é serializável) - usado pelo endpoint GET /assistente/perguntas-padrao.
    Junta o catálogo fixo (sempre `personalizada: False`, não editável por
    aqui) com as perguntas personalizadas ativas (`personalizada: True`,
    admin pode editar/excluir - ver routers/assistente_router.py)."""
    fixas = [{"chave": e["chave"], "rotulo": e["rotulo"], "pergunta": e["pergunta"], "personalizada": False} for e in PERGUNTAS_PADRAO]
    personalizadas = [
        {"chave": e["chave"], "rotulo": e["rotulo"], "pergunta": e["pergunta"], "personalizada": True}
        for e in _entradas_personalizadas_ativas(db)
    ]
    return fixas + personalizadas


CHAVES_FIXAS = {e["chave"] for e in PERGUNTAS_PADRAO}


def _gerar_chave_unica(db: Session, rotulo: str) -> str:
    """Deriva uma chave (slug) a partir do rótulo digitado pelo admin,
    garantindo que não colide nem com o catálogo fixo nem com outra
    pergunta personalizada já existente - acrescenta um sufixo numérico se
    precisar."""
    base = _normalizar(rotulo)
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "pergunta_personalizada"
    chave = base
    sufixo = 2
    while chave in CHAVES_FIXAS or db.query(models.PerguntaPadraoPersonalizada).filter_by(chave=chave).first():
        chave = f"{base}_{sufixo}"
        sufixo += 1
    return chave


def criar_pergunta_personalizada(db: Session, usuario, rotulo: str, pergunta: str, gatilhos: list, instrucao_extra: str | None) -> models.PerguntaPadraoPersonalizada:
    rotulo = (rotulo or "").strip()
    pergunta = (pergunta or "").strip()
    gatilhos_limpos = [g.strip() for g in (gatilhos or []) if g and g.strip()]
    if not rotulo or not pergunta:
        raise ValueError("Rótulo e pergunta são obrigatórios.")
    if not gatilhos_limpos:
        raise ValueError("Informe pelo menos uma frase-gatilho (o que a pessoa precisa dizer/digitar pra acionar esta pergunta).")
    linha = models.PerguntaPadraoPersonalizada(
        chave=_gerar_chave_unica(db, rotulo),
        rotulo=rotulo,
        pergunta=pergunta,
        gatilhos=gatilhos_limpos,
        instrucao_extra=(instrucao_extra or "").strip() or None,
        ativo=True,
        criado_por=getattr(usuario, "username", None),
    )
    db.add(linha)
    db.commit()
    db.refresh(linha)
    return linha


def atualizar_pergunta_personalizada(db: Session, chave: str, rotulo: str, pergunta: str, gatilhos: list, instrucao_extra: str | None) -> models.PerguntaPadraoPersonalizada:
    if chave in CHAVES_FIXAS:
        raise ValueError("Essa pergunta faz parte do catálogo padrão do sistema e não pode ser editada por aqui.")
    linha = db.query(models.PerguntaPadraoPersonalizada).filter_by(chave=chave).first()
    if not linha:
        raise ValueError("Pergunta personalizada não encontrada.")
    gatilhos_limpos = [g.strip() for g in (gatilhos or []) if g and g.strip()]
    if not (rotulo or "").strip() or not (pergunta or "").strip():
        raise ValueError("Rótulo e pergunta são obrigatórios.")
    if not gatilhos_limpos:
        raise ValueError("Informe pelo menos uma frase-gatilho.")
    linha.rotulo = rotulo.strip()
    linha.pergunta = pergunta.strip()
    linha.gatilhos = gatilhos_limpos
    linha.instrucao_extra = (instrucao_extra or "").strip() or None
    db.commit()
    db.refresh(linha)
    return linha


def excluir_pergunta_personalizada(db: Session, chave: str) -> None:
    if chave in CHAVES_FIXAS:
        raise ValueError("Essa pergunta faz parte do catálogo padrão do sistema e não pode ser excluída por aqui.")
    linha = db.query(models.PerguntaPadraoPersonalizada).filter_by(chave=chave).first()
    if not linha:
        raise ValueError("Pergunta personalizada não encontrada.")
    db.delete(linha)
    db.commit()
