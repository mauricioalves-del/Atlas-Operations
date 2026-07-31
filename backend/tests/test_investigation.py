from datetime import date
from app import models
from app.investigation import investigar, reconciliar
from app.hipoteses_config import buscar_evidencias_texto, HIPOTESES


def _seed_hipoteses(db):
    for codigo, nome, descricao in HIPOTESES:
        db.add(models.Hipotese(codigo=codigo, nome=nome, descricao=descricao, peso_padrao=20.0))
    db.commit()


def test_buscar_evidencias_texto_avaria():
    resultado = buscar_evidencias_texto("Solicitado baixa de 9 un por avaria")
    codigos = [c for c, _ in resultado]
    assert "Avaria_Perda" in codigos


def test_buscar_evidencias_texto_sem_observacao():
    assert buscar_evidencias_texto(None) == []
    assert buscar_evidencias_texto("") == []


def test_buscar_evidencias_texto_tolera_acento_e_caixa():
    resultado = buscar_evidencias_texto("AVARIA CONFIRMADA")
    assert any(c == "Avaria_Perda" for c, _ in resultado)


def test_investigar_encontra_transferencia_pendente(db_session):
    _seed_hipoteses(db_session)
    db_session.add(models.Transferencia(
        sku="123", descricao="Item", data_saida=date(2026, 1, 1), data_entrada=None,
        documento="T1", almoxarifado_origem="Almox_A", almoxarifado_destino="Almox_B", quantidade=10, lote="L1",
    ))
    db_session.commit()

    div = models.Divergencia(
        sku="123", almoxarifado="Almox_A", categoria_produto="Materia Prima",
        data_deteccao=date(2026, 1, 5), saldo_sistema=100, saldo_fisico=90,
        divergencia_qtd=-10, valor_estimado=0, status="Aberta",
    )
    db_session.add(div)
    db_session.flush()

    resultado = investigar(db_session, div)
    assert resultado["hipotese_regras"] == "Transferencia_Pendente"
    assert resultado["confianca_regras"] > 0


def test_investigar_sem_nenhuma_evidencia_cai_em_falha_inventario(db_session):
    _seed_hipoteses(db_session)
    div = models.Divergencia(
        sku="999", almoxarifado="Almox_X", categoria_produto="Embalagem",
        data_deteccao=date(2026, 1, 5), saldo_sistema=50, saldo_fisico=40,
        divergencia_qtd=-10, valor_estimado=0, status="Aberta",
    )
    db_session.add(div)
    db_session.flush()

    resultado = investigar(db_session, div)
    assert resultado["hipotese_regras"] == "Falha_Inventario"


def test_investigar_usa_observacao_da_planilha(db_session):
    _seed_hipoteses(db_session)
    div = models.Divergencia(
        sku="555", almoxarifado="Almox_X", categoria_produto="Embalagem",
        data_deteccao=date(2026, 1, 5), saldo_sistema=50, saldo_fisico=49,
        divergencia_qtd=-1, valor_estimado=0, status="Aberta",
        observacao_origem="Solicitado baixa de 1 un por avaria",
    )
    db_session.add(div)
    db_session.flush()

    resultado = investigar(db_session, div)
    assert resultado["hipotese_regras"] == "Avaria_Perda"


def test_reconciliar_combina_regras_e_ml():
    scores_regras = {"Avaria_Perda": 80.0, "Falha_Inventario": 20.0}
    distribuicao_ml = [{"hipotese": "Avaria_Perda", "confianca": 60.0}, {"hipotese": "Falha_Inventario", "confianca": 40.0}]
    hipotese, confianca = reconciliar(scores_regras, distribuicao_ml, peso_regras=0.5)
    assert hipotese == "Avaria_Perda"
    assert confianca == 70.0  # (80*0.5 + 60*0.5)


def test_reconciliar_sem_nenhum_sinal_retorna_none():
    hipotese, confianca = reconciliar({}, [])
    assert hipotese is None
    assert confianca is None
