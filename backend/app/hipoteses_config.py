"""
Catálogo oficial de hipóteses + de-para das categorias brutas encontradas em
atlas_casos_historicos_categorizados.csv (coluna Hipotese_Sugerida, texto
livre em português) para os códigos oficiais usados no banco e no ML.

Por que isso existe como arquivo separado e explícito: a versão anterior do
projeto fazia esse mapeamento "na mão" ao montar o CSV de treino e, no
processo, 52% dos casos históricos (incluindo a categoria MAIS comum,
"Sem divergência real / falso positivo", 494 de 1368 casos) foram
descartados silenciosamente porque não tinham um código correspondente.
Isso deixava o modelo estruturalmente incapaz de prever "não há divergência
real", que é o desfecho mais frequente na prática.

Correção aplicada aqui: nenhuma categoria é descartada. Toda categoria bruta
tem um destino - ou um dos 14 códigos originais, ou um dos 2 códigos novos
abaixo (Sem_Divergencia_Real e Outros_Nao_Categorizado). Se aparecer uma
categoria nova no futuro que não estiver neste dicionário, o loader de dados
falha alto (raise) em vez de descartar silenciosamente - ver data_import/load_historico.py.
"""

HIPOTESES = [
    # código oficial                nome                                    descrição curta
    ("Transferencia_Pendente",      "Transferência Pendente",              "Saída de transferência sem entrada correspondente registrada."),
    ("Consumo_Parcial_OP",          "Consumo Parcial de OP",               "Consumo de matéria-prima abaixo do previsto na ficha técnica."),
    ("Pendencia_Faturamento",       "Pendência de Faturamento",            "Nota fiscal emitida sem baixa de estoque."),
    ("Erro_Operacional",            "Erro Operacional",                    "Divergência pequena, sem documento associado, padrão operacional."),
    ("Erro_Cadastro",               "Erro de Cadastro",                    "SKU/lote não localizado ou incompatibilidade de unidade/ficha."),
    ("Falha_Inventario",            "Falha de Inventário",                 "Divergência sem nenhuma movimentação associada no período; erro de contagem."),
    ("Avaria_Perda",                "Avaria / Perda",                      "Perda física confirmada por avaria."),
    ("Producao_Nao_Encerrada",      "Produção Não Encerrada",              "OP em andamento, ainda não apontada/encerrada no sistema."),
    ("Ajuste_Manual_Incorreto",     "Ajuste Manual Incorreto",             "Ajuste de sistema pendente ou lançado incorretamente."),
    ("Movimentacao_Duplicada",      "Movimentação Duplicada",              "Mesmo evento lançado mais de uma vez."),
    ("Conversao_Unidade_Incorreta", "Conversão de Unidade Incorreta",      "Divergência causada por conversão errada entre unidades."),
    ("Erro_Fiscal",                 "Erro Fiscal",                         "Nota fiscal cancelada ou divergente do estoque físico."),
    ("Perda_Nao_Identificada",      "Perda Não Identificada",              "Falta sem causa raiz identificada; possível furto ou perda não documentada."),
    ("Divergencia_Ficha_Tecnica",   "Divergência de Ficha Técnica",        "Ficha técnica (BOM) desatualizada em relação ao processo real."),
    ("Pedido_Compra_Pendente",      "Pedido de Compra Pendente",           "Falta explicada por pedido de compra em aberto/parcial - mercadoria ainda em trânsito com o fornecedor."),
    # códigos novos, adicionados nesta correção:
    ("Sem_Divergencia_Real",        "Sem Divergência Real (Falso Positivo)", "Após checagem, não há divergência real - erro de contagem/leitura pontual."),
    ("Outros_Nao_Categorizado",     "Outros / Não Categorizado",           "Caso legítimo mas que não se encaixa em nenhuma hipótese conhecida ainda."),
]

HIPOTESE_CODIGOS = {codigo for codigo, _, _ in HIPOTESES}

# De-para: texto bruto (como aparece em Hipotese_Sugerida) -> código oficial.
# Chaves normalizadas (strip) para bater exatamente com o CSV de origem.
MAPA_CATEGORIA_BRUTA_PARA_CODIGO = {
    "Sem divergência real (falso positivo)": "Sem_Divergencia_Real",
    "Produção em andamento (OP não encerrada)": "Producao_Nao_Encerrada",
    "Outros / não categorizado": "Outros_Nao_Categorizado",
    "Aguardando apontamento de produção": "Producao_Nao_Encerrada",
    "Ajuste de sistema pendente": "Ajuste_Manual_Incorreto",
    "Pendência de faturamento": "Pendencia_Faturamento",
    "Avaria / Perda por avaria": "Avaria_Perda",
    "Recontagem necessária": "Falha_Inventario",
    "Transferência pendente": "Transferencia_Pendente",
    "Erro de lote (necessita ajuste)": "Erro_Cadastro",
    "Baixa por consumo (processo semanal)": "Consumo_Parcial_OP",
    "Erro fiscal (NF cancelada)": "Erro_Fiscal",
    "Perda não identificada (possível furto)": "Perda_Nao_Identificada",
    "Divergência de Ficha Técnica": "Divergencia_Ficha_Tecnica",
    "Falha de inventário": "Falha_Inventario",
    "Falta injustificada (não-estoque, revisar)": "Perda_Nao_Identificada",
}

import unicodedata


def _normalizar_texto(txt):
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKD", str(txt).lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


# Palavras-chave observadas nas planilhas reais de movimentação (coluna
# "Obs", preenchida à mão por quem faz a contagem) mapeadas para o código
# oficial de hipótese. Isso é usado como EVIDÊNCIA adicional no motor de
# investigação (investigation.py) - não decide a hipótese por si só, soma
# peso junto com as evidências documentais (transferência, OP, etc).
# Cobre acentos/variações via _normalizar_texto (compara sem acento e em
# minúsculas), então "avaria", "Avaria", "avariado" todos batem.
PALAVRAS_CHAVE_OBSERVACAO = {
    "Avaria_Perda": ["avaria", "avariad", "quebrad", "danificad"],
    "Perda_Nao_Identificada": ["furto", "roubo", "sumiu", "desapareceu"],
    "Transferencia_Pendente": ["transf.", "transferencia pendente", "transferência pendente", "no radar do estoque", "aguardando transferencia"],
    "Consumo_Parcial_OP": ["consumo interno", "consumo parcial", "consumido em"],
    "Producao_Nao_Encerrada": ["op nao encerrada", "op não encerrada", "producao em andamento", "produção em andamento", "aguardando apontamento"],
    "Pendencia_Faturamento": ["pendente faturamento", "nota fiscal", "nf pendente", "aguardando faturamento"],
    "Erro_Fiscal": ["nf cancelada", "nota cancelada", "erro fiscal"],
    "Falha_Inventario": ["recontagem", "recontar", "erro de contagem", "contagem incorreta"],
    "Ajuste_Manual_Incorreto": ["ajuste pendente", "ajuste incorreto", "pendente de baixa", "pendentes de baixa", "aguardando ajuste"],
    "Movimentacao_Duplicada": ["duplicad", "lancado duas vezes", "lançado duas vezes"],
    "Conversao_Unidade_Incorreta": ["conversao de unidade", "conversão de unidade", "unidade errada", "unidade incorreta"],
    "Divergencia_Ficha_Tecnica": ["ficha tecnica", "ficha técnica", "bom desatualizada"],
    "Erro_Cadastro": ["erro de cadastro", "lote incorreto", "cadastro incorreto", "sku incorreto"],
    "Sem_Divergencia_Real": ["falso positivo", "sem divergencia real", "recontado sem diferenca", "ok apos recontagem"],
}


def buscar_evidencias_texto(observacao):
    """Varre um texto livre (campo Obs das planilhas de movimentação) e
    retorna [(codigo_hipotese, palavra_chave_encontrada), ...] - usado
    como evidência adicional no motor de investigação. Retorna lista
    vazia se não houver observação ou nenhuma palavra-chave bater."""
    if not observacao:
        return []
    texto_norm = _normalizar_texto(observacao)
    encontrados = []
    for codigo, palavras in PALAVRAS_CHAVE_OBSERVACAO.items():
        for palavra in palavras:
            if _normalizar_texto(palavra) in texto_norm:
                encontrados.append((codigo, palavra))
                break  # uma palavra-chave já basta por hipótese
    return encontrados


ALMOXARIFADOS_PADRAO = [
    ("Almox_SP_Fabrica", "Fábrica"),
    ("Almox_SP_Processo", "Processo"),
    ("Almox_SP_Qualidade", "Qualidade"),
    ("Almox_PA_Para", "Pará"),
    ("Almox_SP_Ativacao", "Ativação"),
    ("Almox_SP_Loja", "Loja"),
    ("Almox_Box", "Box"),
    ("Almox_Box_2", "Box 2"),
    ("Almox_SP_Degustacao", "Degustação"),
]

# De-para de almoxarifado a partir do arquivo bruto de origem (planilhas).
# Usa prefixo em vez de igualdade exata porque o export original tem um bug
# de encoding conhecido (acentos truncados: "Pará" chega como "Par#U",
# "Ativação" chega como "Ativa#U") - ver atlas_casos_historicos_categorizados.csv.
# Isso é tratado aqui, na importação, e não remendado depois no banco.
ALMOXARIFADO_DE_PARA_PREFIXOS = [
    # Palavras-chave mais ESPECÍFICAS primeiro: o nome do site ("Fabrica",
    # "Geral") costuma aparecer dentro do nome de sub-almoxarifados mais
    # específicos (ex: "4 -Almox Processo - SP Fabrica" contém as duas
    # palavras) - se "Fabrica" for checado antes, "Processo" nunca é
    # alcançado e o sub-almoxarifado errado é escolhido. A ordem abaixo
    # resolve isso: específico -> genérico.
    ("Processo", "Almox_SP_Processo"),
    ("Qualidade", "Almox_SP_Qualidade"),
    ("Ativa", "Almox_SP_Ativacao"),  # cobre "Ativação", "Ativa#U" e "PDV ATIVACAO" (comparação sem diferenciar caixa)
    ("Degusta", "Almox_SP_Degustacao"),
    ("Box2", "Almox_Box_2"),   # sem espaço - checa antes de "Box" isolado
    ("Box 2", "Almox_Box_2"),  # com espaço
    ("Box", "Almox_Box"),
    ("Loja", "Almox_SP_Loja"),
    ("Par", "Almox_PA_Para"),       # cobre "Pará" e a variante truncada "Par#U"
    ("Geral", "Almox_SP_Fabrica"),
    ("Fabrica", "Almox_SP_Fabrica"),  # fallback genérico - só chega aqui se nenhuma palavra específica bateu
]


def normalizar_almoxarifado(valor_origem):
    """Converte um valor de almoxarifado vindo de planilha bruta para o
    código oficial. Aceita tanto o formato antigo ("Geral", "Par#U") por
    prefixo quanto formatos mais livres ("1  -Almox - SP Fabrica") por
    substring - cobre as duas famílias de planilha já vistas na operação.
    A comparação ignora caixa alta/baixa (ex: "PDV ATIVACAO" bate com a
    palavra-chave "Ativa" mesmo em caixa alta) - planilhas diferentes do
    mesmo sistema de origem usam convenções de capitalização diferentes.
    Se não bater com nenhuma palavra-chave conhecida, devolve o valor
    original prefixado com 'NAO_MAPEADO__' para revisão manual, em vez de
    adivinhar errado silenciosamente."""
    if valor_origem is None:
        return "NAO_MAPEADO__vazio"
    v = str(valor_origem).strip()
    v_lower = v.lower()
    for palavra_chave, codigo in ALMOXARIFADO_DE_PARA_PREFIXOS:
        if palavra_chave.lower() in v_lower:
            return codigo
    return f"NAO_MAPEADO__{v}"
