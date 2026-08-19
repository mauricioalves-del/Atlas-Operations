"""
Integração com IA GENERATIVA externa (LLM), para classificação e resumo
automático de baixas operacionais e divergências (25/08/2026 — pedido
explícito do Maurício: "adicionar uma inteligência artificial no atlas, de
forma gratuita").

Importante não confundir com a "IA" que já existe no Atlas: hipotese_ia/
confianca_ia (em Divergencia) é a hipótese final reconciliada por um motor
de regras (investigation.py) + um modelo estatístico treinado nos próprios
dados históricos do Atlas (ml/predict.py) — isso é calculado SEMPRE, pra
toda divergência, sem depender de nada externo. O que este módulo faz é
diferente e vem por cima: chama um provedor de IA generativa (LLM) de
fora pra ler o texto livre de uma baixa/divergência e devolver uma leitura
em português — só quando alguém pede explicitamente (botão "Analisar com
IA"/"Resumir com IA" na tela) e só se uma chave estiver configurada. Por
isso os campos novos usam sempre o prefixo `ia_gen_` (IA Generativa), bem
separado de hipotese_ia/confianca_ia.

Provedor padrão: Google Gemini via Google AI Studio — tem camada gratuita
sem pedir cartão de crédito (https://aistudio.google.com/apikey), com cota
diária alta o suficiente pro volume do Atlas. Chamado aqui via `urllib`
(biblioteca padrão do Python) — mesmo padrão já usado no resto do projeto
pra chamadas HTTP externas (ver baixas_operacionais.py, sincronização com
o Lovable) — sem adicionar SDK/dependência nova só pra isso.

Configuração (variáveis de ambiente, mesmo padrão ATLAS_* do resto do
projeto), tudo definido no ambiente do servidor (Render), nunca no código:
- ATLAS_IA_GENERATIVA_API_KEY — a chave criada no Google AI Studio. Sem
  isso, `ia_generativa_configurada()` devolve False e os endpoints que
  dependem disto respondem 503 com mensagem clara — nunca falha
  silenciosamente nem impede o resto do Atlas de funcionar.
- ATLAS_IA_GENERATIVA_MODELO — modelo do Gemini a usar. Padrão:
  "gemini-2.0-flash" (rápido e dentro da camada gratuita para este uso).

Sobre custo/limite: a camada gratuita do Google AI Studio tem um limite de
chamadas por minuto e por dia (o valor exato é definido pelo provedor e
pode mudar — ver https://ai.google.dev/gemini-api/docs/rate-limits antes
de configurar em produção). Por isso a análise em lote
(`analisar_baixas_pendentes_em_lote`, usada pelo endpoint de lote) tem um
limite MÁXIMO por chamada (`LIMITE_MAXIMO_LOTE`) e uma pequena pausa entre
itens — pensado pra não estourar a cota gratuita de uma vez só, não pra
throughput. Analisar item a item pela tela não tem esse limite adicional
(é uma chamada só).
"""
import json
import os
import time
import urllib.error
import urllib.request

MODELO_PADRAO = "gemini-2.0-flash"
LIMITE_MAXIMO_LOTE = 25  # trava de segurança pra não estourar a cota gratuita numa chamada só
PAUSA_ENTRE_CHAMADAS_LOTE_SEGUNDOS = 1.5
PRIORIDADES_VALIDAS = {"Alta", "Média", "Baixa"}


class IAGenerativaIndisponivel(Exception):
    """Chave não configurada, ou a chamada ao provedor de IA generativa
    falhou (rede, cota excedida, resposta bloqueada/inesperada etc.) —
    sempre com uma mensagem clara o suficiente pra mostrar direto na
    tela, sem precisar abrir o log do servidor."""


def _config() -> dict:
    return {
        "api_key": os.environ.get("ATLAS_IA_GENERATIVA_API_KEY"),
        "modelo": os.environ.get("ATLAS_IA_GENERATIVA_MODELO", MODELO_PADRAO),
    }


def ia_generativa_configurada() -> bool:
    return bool(_config()["api_key"])


def status_ia_generativa() -> dict:
    """Usado pelo endpoint GET /ia-generativa/status — o frontend chama
    isso pra decidir se mostra o botão "Analisar com IA" ou um aviso de
    que o recurso não está configurado neste ambiente."""
    cfg = _config()
    return {
        "configurada": bool(cfg["api_key"]),
        "provedor": "Google Gemini (Google AI Studio)",
        "modelo": cfg["modelo"],
        "limite_maximo_lote": LIMITE_MAXIMO_LOTE,
    }


def _chamar_gemini(prompt: str, timeout_segundos: int = 30, esperar_json: bool = True, temperatura: float = 0.2) -> str:
    """`esperar_json=True` (padrão, usado por classificar_e_resumir_baixa/
    resumir_divergencia) força o Gemini a devolver só JSON válido. O
    assistente por voz (app/assistente_ia.py) chama com `esperar_json=False`
    - quer texto corrido em português, pra ser lido em voz alta, não um
    objeto estruturado."""
    cfg = _config()
    if not cfg["api_key"]:
        raise IAGenerativaIndisponivel(
            "IA generativa não configurada neste ambiente: defina a variável de "
            "ambiente ATLAS_IA_GENERATIVA_API_KEY com uma chave gratuita do Google "
            "AI Studio (https://aistudio.google.com/apikey) no servidor do Atlas."
        )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{cfg['modelo']}:generateContent?key={cfg['api_key']}"
    )
    generation_config = {"temperature": temperatura}
    if esperar_json:
        generation_config["responseMimeType"] = "application/json"
    corpo = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }).encode("utf-8")
    requisicao = urllib.request.Request(url, data=corpo, method="POST")
    requisicao.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout_segundos) as resposta:
            payload = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="ignore")
        if erro.code == 429:
            raise IAGenerativaIndisponivel(
                "Cota gratuita da IA generativa excedida por agora (HTTP 429) — a "
                "camada gratuita do provedor limita quantas chamadas por minuto/dia "
                "são aceitas. Tente de novo em alguns minutos, ou analise menos itens "
                "por vez."
            ) from erro
        if erro.code in (400, 403):
            raise IAGenerativaIndisponivel(
                f"O provedor de IA generativa rejeitou a chamada (HTTP {erro.code}) — "
                f"confira se a chave ATLAS_IA_GENERATIVA_API_KEY ainda é válida. "
                f"Detalhe: {detalhe[:300]}"
            ) from erro
        raise IAGenerativaIndisponivel(
            f"Chamada à IA generativa falhou (HTTP {erro.code}): {detalhe[:300]}"
        ) from erro
    except urllib.error.URLError as erro:
        raise IAGenerativaIndisponivel(f"Não foi possível contactar o provedor de IA generativa: {erro}") from erro
    except TimeoutError as erro:
        raise IAGenerativaIndisponivel("O provedor de IA generativa não respondeu a tempo.") from erro

    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as erro:
        bloqueio = (payload.get("promptFeedback") or {}).get("blockReason")
        if bloqueio:
            raise IAGenerativaIndisponivel(f"O provedor de IA generativa bloqueou a resposta (motivo: {bloqueio}).") from erro
        raise IAGenerativaIndisponivel(
            f"Resposta inesperada do provedor de IA generativa: {json.dumps(payload)[:300]}"
        ) from erro


def _extrair_json(texto: str) -> dict:
    """Com responseMimeType=application/json a resposta já deve vir só com
    o JSON — mas alguns modelos ainda envolvem em ```json ... ```; limpa
    isso antes do parse pra não quebrar por um detalhe de formatação."""
    texto = (texto or "").strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        if texto.lower().startswith("json"):
            texto = texto[4:]
    try:
        return json.loads(texto.strip())
    except json.JSONDecodeError as erro:
        raise IAGenerativaIndisponivel(
            f"A IA generativa devolveu uma resposta que não é JSON válido: {texto[:300]}"
        ) from erro


def classificar_e_resumir_baixa(baixa, codigos_hipoteses_validos: list) -> dict:
    """Pede à IA generativa uma leitura de UMA baixa operacional: categoria
    sugerida (sempre dentro do catálogo oficial de Hipóteses do Atlas —
    hipoteses_config.py — pra não inventar categoria fora do que o resto
    do sistema entende), prioridade de atenção, e um resumo em até 2
    frases. Não decide nada por conta própria — é sempre uma sugestão,
    revisável por quem está usando o Atlas (não sobrescreve
    hipotese_aplicada)."""
    payload_obs = baixa.payload_bruto if isinstance(baixa.payload_bruto, dict) else {}
    observacao_livre = (
        payload_obs.get("observacao") or payload_obs.get("observacoes") or payload_obs.get("descricao") or ""
    )
    prompt = f"""Você é um assistente de controle de estoque de uma fábrica de chocolates (Magio Chocolates).
Analise esta baixa operacional de estoque e responda em português do Brasil.

Dados da baixa:
- SKU: {baixa.sku}
- Almoxarifado: {baixa.almoxarifado or "não informado"}
- Motivo informado: {baixa.motivo_baixa_bruto or "não informado"}
- Quantidade: {baixa.quantidade}
- Valor total: R$ {baixa.valor_total if baixa.valor_total is not None else "não informado"}
- Status do fluxo: {baixa.status_fluxo}
- Observação livre registrada (se houver): {observacao_livre or "nenhuma"}

Catálogo oficial de categorias de causa-raiz (escolha EXATAMENTE um destes códigos,
o que melhor descreve a causa mais provável desta baixa):
{", ".join(codigos_hipoteses_validos)}

Responda SOMENTE com um JSON no formato exato, sem texto antes ou depois:
{{"categoria_sugerida": "<um código da lista acima>", "prioridade": "Alta|Média|Baixa", "resumo": "<no máximo 2 frases em português, explicando o porquê da categoria e da prioridade escolhidas>"}}

Critério de prioridade: Alta = valor alto e/ou motivo indica perda real (avaria, perda);
Média = valor moderado ou causa incerta; Baixa = valor baixo e causa provável é só ajuste
de processo/cadastro, sem perda real de estoque."""

    resultado = _extrair_json(_chamar_gemini(prompt))

    categoria = resultado.get("categoria_sugerida")
    if categoria not in codigos_hipoteses_validos:
        categoria = "Outros_Nao_Categorizado" if "Outros_Nao_Categorizado" in codigos_hipoteses_validos else None
    prioridade = resultado.get("prioridade")
    if prioridade not in PRIORIDADES_VALIDAS:
        prioridade = None
    resumo = (resultado.get("resumo") or "").strip()[:600] or None

    return {"categoria_sugerida": categoria, "prioridade": prioridade, "resumo": resumo}


def resumir_divergencia(div) -> dict:
    """Pede à IA generativa um resumo executivo de UMA divergência já
    investigada pelo motor de regras + modelo estatístico do Atlas — NÃO
    decide nem recalcula hipótese nenhuma (isso continua sendo
    hipotese_regras/hipotese_ml/hipotese_ia, calculados por
    investigation.py/ml/predict.py) — só traduz, em português corrido, os
    sinais que já estão espalhados pelos painéis da tela de detalhe
    (Evidências, Casos similares, Distribuição de probabilidades)."""
    evidencias = div.evidencias if isinstance(div.evidencias, list) else []
    evidencias_txt = "; ".join(
        f"{e.get('hipotese')}: {'encontrado' if e.get('encontrado') else 'não encontrado'} (peso {e.get('peso_aplicado', '—')})"
        for e in evidencias
    ) or "nenhuma evidência registrada"
    casos = div.casos_similares if isinstance(div.casos_similares, list) else []
    casos_txt = "; ".join(
        f"SKU {c.get('sku')} resolvido como {c.get('hipotese_confirmada')}" for c in casos[:5]
    ) or "nenhum caso similar encontrado"

    prompt = f"""Você é um assistente de controle de estoque de uma fábrica de chocolates (Magio Chocolates).
Um sistema de regras e um modelo estatístico já analisaram esta divergência de inventário.
Sua tarefa é só traduzir os sinais abaixo num resumo executivo curto, em português do Brasil,
para quem vai decidir a causa final — não invente informação que não esteja aqui.

- SKU: {div.sku} · Almoxarifado: {div.almoxarifado}
- Saldo sistema: {div.saldo_sistema} · Saldo físico: {div.saldo_fisico} · Divergência: {div.divergencia_qtd}
- Valor estimado: R$ {div.valor_estimado}
- Hipótese do motor de regras: {div.hipotese_regras or "nenhuma"} (confiança {div.confianca_regras if div.confianca_regras is not None else "—"})
- Hipótese do modelo estatístico: {div.hipotese_ml or "nenhuma"} (confiança {div.confianca_ml if div.confianca_ml is not None else "—"})
- Hipótese final reconciliada pelo Atlas: {div.hipotese_ia or "nenhuma"} (confiança {div.confianca_ia if div.confianca_ia is not None else "—"})
- Evidências verificadas: {evidencias_txt}
- Observação original da planilha: {div.observacao_origem or "nenhuma"}
- Casos similares já resolvidos: {casos_txt}

Responda SOMENTE com um JSON no formato exato, sem texto antes ou depois:
{{"resumo": "<no máximo 3 frases em português, explicando de forma direta o que os sinais acima apontam e o que reforça (ou contradiz) a hipótese final reconciliada>"}}"""

    resultado = _extrair_json(_chamar_gemini(prompt))
    resumo = (resultado.get("resumo") or "").strip()[:800] or None
    return {"resumo": resumo}


def analisar_baixas_pendentes_em_lote(baixas: list, codigos_hipoteses_validos: list, limite: int) -> dict:
    """Analisa até `limite` baixas (já filtradas por quem chamou — ver
    endpoint /baixas-operacionais/analisar-ia-lote) uma a uma, com uma
    pequena pausa entre chamadas pra não estourar a cota por minuto da
    camada gratuita. Continua no erro de UM item (guarda o motivo) em vez
    de abortar o lote inteiro — item com erro fica sem ia_gen_analisado_em
    preenchido, então aparece de novo no próximo lote."""
    limite = min(limite, LIMITE_MAXIMO_LOTE)
    analisadas, erros = [], []
    for i, baixa in enumerate(baixas[:limite]):
        try:
            resultado = classificar_e_resumir_baixa(baixa, codigos_hipoteses_validos)
            analisadas.append((baixa, resultado))
        except IAGenerativaIndisponivel as erro:
            erros.append({"baixa_id": baixa.id, "erro": str(erro)})
            if "Cota gratuita" in str(erro) or "HTTP 429" in str(erro):
                break  # sem sentido continuar batendo na cota já excedida
        if i < len(baixas[:limite]) - 1:
            time.sleep(PAUSA_ENTRE_CHAMADAS_LOTE_SEGUNDOS)
    return {"analisadas": analisadas, "erros": erros}
