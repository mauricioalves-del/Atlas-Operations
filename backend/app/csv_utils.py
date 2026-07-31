"""
Utilitários de leitura de CSV para importação.

Resolve, na origem (não remendando depois), os 3 bugs recorrentes vistos
nas versões no-code anteriores:

1. SKU/código virando número e perdendo zero à esquerda
   -> sempre ler colunas de código com dtype=str (nunca deixar o pandas
      inferir), aqui isso é forçado via `dtype=str` em TODO read_csv de
      código, sem exceção.

2. Data vindo com timestamp (ex: "2026-05-13 00:00:00")
   -> `parse_data` sempre corta para a parte de data, e falha alto se
      encontrar uma hora diferente de 00:00:00 (isso não deveria acontecer
      nunca; se acontecer é sinal de dado real perdido, não é pra ser
      silenciosamente truncado sem avisar).

3. Número decimal em formato brasileiro (ponto de milhar, vírgula decimal)
   -> `parse_decimal` detecta e converte os dois formatos.
"""
import re
from datetime import date, datetime
from typing import Optional


def parse_sku(valor) -> Optional[str]:
    if valor is None:
        return None
    s = str(valor).strip()
    if s == "" or s.lower() == "nan":
        return None
    # entidade HTML residual (&apos; ou aspas simples soltas) no início do
    # código - comum em exportações de sistemas legados que usam aspas pra
    # forçar formato texto e preservar zero à esquerda, mas escapam errado
    s = re.sub(r"^(&apos;|&#39;|')+", "", s)
    # remove ".0" que aparece quando uma coluna numérica mista com SKU
    # foi lida como float em algum momento anterior do pipeline de origem
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def parse_data(valor) -> Optional[date]:
    if valor is None:
        return None
    s = str(valor).strip()
    if s == "" or s.lower() == "nan":
        return None
    # aceita "2026-05-13" ou "2026-05-13 00:00:00" - mas se vier com hora
    # diferente de meia-noite, isso é dado real perdido, não silencioso.
    if " " in s:
        data_str, hora_str = s.split(" ", 1)
        if hora_str.strip() not in ("00:00:00", "0:00:00"):
            raise ValueError(
                f"Data '{s}' contém componente de hora não-zero - "
                "verifique a origem antes de importar (dado pode estar sendo truncado)."
            )
        s = data_str
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_decimal(valor) -> float:
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if s == "" or s.lower() == "nan":
        return 0.0
    # formato brasileiro: 1.234,56  -> remove ponto de milhar, troca vírgula por ponto
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_bool(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    s = str(valor).strip().lower()
    return s in ("true", "1", "sim", "yes", "x")
