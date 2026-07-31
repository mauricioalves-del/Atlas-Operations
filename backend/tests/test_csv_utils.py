import pytest
from app.csv_utils import parse_sku, parse_data, parse_decimal, parse_bool
from datetime import date


def test_parse_sku_mantem_zero_a_esquerda():
    assert parse_sku("0010305007") == "0010305007"


def test_parse_sku_remove_sufixo_ponto_zero():
    assert parse_sku("123.0") == "123"


def test_parse_sku_vazio_e_nulo():
    assert parse_sku(None) is None
    assert parse_sku("") is None
    assert parse_sku("nan") is None


def test_parse_data_simples():
    assert parse_data("2026-07-21") == date(2026, 7, 21)


def test_parse_data_com_timestamp_meia_noite():
    assert parse_data("2026-07-21 00:00:00") == date(2026, 7, 21)


def test_parse_data_com_hora_real_falha_alto():
    with pytest.raises(ValueError):
        parse_data("2026-07-21 14:30:00")


def test_parse_decimal_ponto():
    assert parse_decimal("123.45") == 123.45


def test_parse_decimal_formato_brasileiro():
    assert parse_decimal("1.234,56") == 1234.56


def test_parse_decimal_vazio():
    assert parse_decimal("") == 0.0
    assert parse_decimal(None) == 0.0


def test_parse_bool():
    assert parse_bool("Sim") is True
    assert parse_bool("nao") is False
    assert parse_bool(True) is True
