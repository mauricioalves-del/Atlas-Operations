"""Testes do botão "Sincronizar agora": buscar_baixas_lovable_agora (busca
paginada no REST do Supabase do Lovable) e sincronizar_com_lovable
(integração com importar_lote). Usa um servidor HTTP local de mentira no
lugar do Supabase de verdade, pra não depender de rede nem de credenciais
reais - só precisa responder ao header Range do jeito que o PostgREST
responde."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import pytest

from app.baixas_operacionais import (
    buscar_baixas_lovable_agora,
    sincronizar_com_lovable,
    SincronizacaoIndisponivel,
)


def _linha_fake(i, status_fluxo="APROVADA", motivo="9717e486-c7a0-4b3d-9515-272f28adbebd", id_local="Alm_SP_Loja"):
    return {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "codigo_produto": f"SKU{i}",
        "id_local": id_local,
        "motivo_baixa_id": motivo,
        "quantidade": 1,
        "valor_total": 10.0,
        "status_fluxo": status_fluxo,
        "data_ocorrencia": "2026-08-01",
        "data_solicitacao": "2026-08-01T12:00:00+00:00",
        "responsavel_nome": "Teste",
    }


class _FakeSupabaseHandler(BaseHTTPRequestHandler):
    linhas = []
    chave_esperada = "chave-teste-123"
    requisicoes_recebidas = []

    def do_GET(self):
        # Headers HTTP não diferenciam maiúsculas/minúsculas (urllib manda
        # "Apikey", não "apikey") - guarda com chave em minúsculo pra não
        # depender de qual capitalização o cliente escolheu.
        type(self).requisicoes_recebidas.append({k.lower(): v for k, v in self.headers.items()})
        if self.headers.get("apikey") != self.chave_esperada or self.headers.get("Authorization") != f"Bearer {self.chave_esperada}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"message": "chave invalida"}')
            return

        parsed = urlparse(self.path)
        assert parsed.path == "/rest/v1/baixa_operacional"
        qs = parse_qs(parsed.query)
        assert qs.get("order") == ["id.asc"]

        range_header = self.headers.get("Range", "0-999")
        inicio, fim = (int(x) for x in range_header.split("-"))
        pagina = self.linhas[inicio : fim + 1]

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(pagina).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # silencia o log padrão do http.server nos testes


@pytest.fixture()
def fake_supabase(monkeypatch):
    """Sobe o servidor de mentira numa porta livre, aponta as env vars da
    sincronização pra ele, e limpa tudo ao final do teste."""
    servidor = HTTPServer(("127.0.0.1", 0), _FakeSupabaseHandler)
    porta = servidor.server_port
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()

    monkeypatch.setenv("LOVABLE_SUPABASE_URL", f"http://127.0.0.1:{porta}")
    monkeypatch.setenv("LOVABLE_SUPABASE_KEY", _FakeSupabaseHandler.chave_esperada)

    _FakeSupabaseHandler.linhas = []
    _FakeSupabaseHandler.requisicoes_recebidas = []
    yield _FakeSupabaseHandler
    servidor.shutdown()
    thread.join(timeout=5)


def test_busca_pagina_unica_com_poucas_linhas(fake_supabase):
    fake_supabase.linhas = [_linha_fake(i) for i in range(5)]
    resultado = buscar_baixas_lovable_agora()
    assert len(resultado) == 5
    assert [r["id"] for r in resultado] == [f"00000000-0000-0000-0000-{i:012d}" for i in range(5)]


def test_busca_pagina_mande_apikey_e_authorization(fake_supabase):
    fake_supabase.linhas = [_linha_fake(0)]
    buscar_baixas_lovable_agora()
    assert len(fake_supabase.requisicoes_recebidas) == 1
    cabecalhos = fake_supabase.requisicoes_recebidas[0]
    assert cabecalhos["apikey"] == "chave-teste-123"
    assert cabecalhos["authorization"] == "Bearer chave-teste-123"


def test_busca_pagina_mais_de_1000_linhas_sem_perder_nem_duplicar(fake_supabase):
    total = 1500
    fake_supabase.linhas = [_linha_fake(i) for i in range(total)]
    resultado = buscar_baixas_lovable_agora()
    assert len(resultado) == total
    ids = [r["id"] for r in resultado]
    assert len(set(ids)) == total  # nenhum duplicado
    assert ids == [f"00000000-0000-0000-0000-{i:012d}" for i in range(total)]  # nenhum pulado/fora de ordem
    # exatamente 2 páginas: 1000 + 500
    assert len(fake_supabase.requisicoes_recebidas) == 2


def test_busca_exatamente_no_limite_da_pagina_faz_uma_terceira_chamada_vazia(fake_supabase):
    # Caso de borda: se a origem tiver exatamente 1000 linhas, a primeira
    # página vem cheia (len == tamanho_pagina) e o código precisa buscar
    # a segunda pra confirmar que não tem mais nada.
    fake_supabase.linhas = [_linha_fake(i) for i in range(1000)]
    resultado = buscar_baixas_lovable_agora()
    assert len(resultado) == 1000
    assert len(fake_supabase.requisicoes_recebidas) == 2


def test_sem_env_vars_configuradas_da_erro_claro(monkeypatch):
    monkeypatch.delenv("LOVABLE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("LOVABLE_SUPABASE_KEY", raising=False)
    with pytest.raises(SincronizacaoIndisponivel, match="LOVABLE_SUPABASE_URL"):
        buscar_baixas_lovable_agora()


def test_chave_errada_da_erro_claro(fake_supabase, monkeypatch):
    fake_supabase.linhas = [_linha_fake(0)]
    monkeypatch.setenv("LOVABLE_SUPABASE_KEY", "chave-errada")
    with pytest.raises(SincronizacaoIndisponivel, match="401"):
        buscar_baixas_lovable_agora()


def test_sincronizar_com_lovable_importa_e_conta_direto_no_banco(fake_supabase, db_session):
    fake_supabase.linhas = [
        _linha_fake(0, status_fluxo="PENDENTE"),
        _linha_fake(1, status_fluxo="APROVADA"),
        _linha_fake(2, status_fluxo="APROVADA", id_local="Alm_Paulista"),  # sem de-para -> aguardando_de_para_almoxarifado
        _linha_fake(3, status_fluxo="APROVADA", motivo="uuid-nao-cadastrado"),  # motivo desconhecido -> BaixaInvalida
    ]
    resultado = sincronizar_com_lovable(db_session)
    db_session.commit()

    assert resultado["total_na_origem"] == 4
    assert resultado["total_recebido"] == 4
    assert resultado["contagem"]["importada_sem_resolver"] == 1  # a PENDENTE
    assert resultado["contagem"]["aguardando_de_para_almoxarifado"] == 1  # a do Alm_Paulista
    assert resultado["contagem"]["aguardando_divergencia"] == 1  # a APROVADA normal, sem divergência aberta pra casar
    assert len(resultado["erros"]) == 1  # a de motivo não cadastrado


def test_sincronizar_de_novo_atualiza_status_em_vez_de_duplicar(fake_supabase, db_session):
    from app import models

    # primeira sincronização: a baixa nasce Pendente
    fake_supabase.linhas = [_linha_fake(0, status_fluxo="PENDENTE")]
    sincronizar_com_lovable(db_session)
    db_session.commit()
    assert db_session.query(models.BaixaOperacional).count() == 1
    assert db_session.query(models.BaixaOperacional).first().status_fluxo == "PENDENTE"

    # segunda sincronização: a MESMA baixa (mesmo id) foi aprovada no Lovable
    fake_supabase.linhas = [_linha_fake(0, status_fluxo="APROVADA")]
    resultado = sincronizar_com_lovable(db_session)
    db_session.commit()

    assert db_session.query(models.BaixaOperacional).count() == 1  # não duplicou
    assert db_session.query(models.BaixaOperacional).first().status_fluxo == "APROVADA"  # atualizou
    assert resultado["contagem"]["aguardando_divergencia"] == 1
