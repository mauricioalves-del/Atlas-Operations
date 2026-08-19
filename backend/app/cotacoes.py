"""
Cotações de dólar e cacau (19/08/2026), pra saudação personalizada do
Assistente Atlas na tela Início: "Hoje é [data], a cotação do dólar é X e
o cacau está por volta de Y".

IMPORTANTE - honestidade sobre a fonte: as ferramentas de busca na web
não estavam disponíveis nesta sessão pra eu confirmar ao vivo qual API
gratuita de cotação de cacau é a mais estável hoje. Escolhi duas fontes
públicas e sem necessidade de chave/cartão de crédito, bem conhecidas:

- Dólar (USD/BRL): AwesomeAPI (https://docs.awesomeapi.com.br/api-de-moedas)
  - serviço brasileiro gratuito, sem chave, muito usado em projetos
  pequenos/médios. Não é o Banco Central oficial (PTAX), mas é próximo do
  câmbio comercial em tempo real, que costuma ser o que se espera numa
  saudação do dia a dia.
- Cacau (futuros ICE, USD por tonelada): endpoint NÃO OFICIAL do Yahoo
  Finance (ticker "CC=F"), sem necessidade de chave - é o mesmo tipo de
  endpoint usado informalmente em muitos projetos hobby, mas o Yahoo pode
  mudar ou limitar o acesso sem aviso, por não ser uma API pública
  documentada oficialmente.

Ambas seguem o MESMO princípio de resiliência do resto do Atlas: se a
fonte falhar ou mudar de formato, a cotação correspondente aparece como
"indisponível" na saudação, em vez de quebrar a tela ou impedir o
assistente de funcionar. Se qualquer uma delas parar de funcionar de
verdade em produção, é só trocar a URL/parsing aqui (ou apontar pra uma
fonte paga/com chave, como Alpha Vantage ou Twelve Data) - nenhuma outra
parte do Atlas depende deste módulo além da saudação.

Cache em memória (TTL configurável, padrão 30 min) pra não bater nessas
APIs públicas a cada carregamento da tela Início de cada usuário - reduz
o risco de ser bloqueado/limitado por uso excessivo.
"""
import json
import time
import urllib.error
import urllib.request

TTL_CACHE_SEGUNDOS = 30 * 60

_cache = {"dolar": None, "dolar_expira_em": 0, "cacau": None, "cacau_expira_em": 0}


def _buscar_json(url: str, headers: dict | None = None, timeout: int = 8) -> dict:
    requisicao = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def _obter_cotacao_dolar_sem_cache() -> dict:
    try:
        dados = _buscar_json("https://economia.awesomeapi.com.br/json/last/USD-BRL")
        valor = float(dados["USDBRL"]["bid"])
        return {"disponivel": True, "valor": round(valor, 4), "fonte": "AwesomeAPI (USD-BRL)"}
    except Exception as erro:
        return {"disponivel": False, "motivo": f"{erro.__class__.__name__}: não consegui buscar a cotação do dólar agora"}


def _obter_cotacao_cacau_sem_cache() -> dict:
    try:
        # User-Agent de navegador comum - o endpoint não-oficial do Yahoo às vezes
        # recusa (HTTP 429/999) requisições sem esse cabeçalho.
        dados = _buscar_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/CC=F",
            headers={"User-Agent": "Mozilla/5.0 (compatible; AtlasMagio/1.0)"},
        )
        meta = dados["chart"]["result"][0]["meta"]
        valor = float(meta["regularMarketPrice"])
        moeda = meta.get("currency", "USD")
        return {
            "disponivel": True,
            "valor": round(valor, 2),
            "unidade": f"{moeda}/tonelada",
            "fonte": "Yahoo Finance (CC=F, futuros ICE - fonte não-oficial)",
        }
    except Exception as erro:
        return {"disponivel": False, "motivo": f"{erro.__class__.__name__}: não consegui buscar a cotação do cacau agora"}


def obter_cotacoes_atuais() -> dict:
    """Ponto único usado pelo endpoint GET /cotacoes/atuais - cada cotação
    é isolada (uma falhar não derruba a outra) e cacheada por
    TTL_CACHE_SEGUNDOS, pra não martelar as APIs públicas a cada acesso à
    tela Início."""
    agora = time.time()

    if _cache["dolar"] is None or agora >= _cache["dolar_expira_em"]:
        _cache["dolar"] = _obter_cotacao_dolar_sem_cache()
        _cache["dolar_expira_em"] = agora + TTL_CACHE_SEGUNDOS

    if _cache["cacau"] is None or agora >= _cache["cacau_expira_em"]:
        _cache["cacau"] = _obter_cotacao_cacau_sem_cache()
        _cache["cacau_expira_em"] = agora + TTL_CACHE_SEGUNDOS

    return {"dolar": _cache["dolar"], "cacau": _cache["cacau"]}
