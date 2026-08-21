# atlas_fix_mbr_modelo_final_parte1.zip (22/08/2026)

## Antes de aplicar

Mesmo lembrete de sempre: o Atlas roda no Render, e só passa a usar código
novo depois de zip + redeploy manual. Suba este zip e refaça o deploy do
backend antes de gerar um MBR novo pra testar — sem isso, o arquivo gerado
sai idêntico ao anterior.

## O que é este pacote

Você me mandou o `MBR_Atlas_202607_Manual.pptx` — a versão que editou à mão
em PowerPoint e confirmou como "modelo final". Comparei slide a slide com o
que o gerador produz hoje e conversamos sobre as diferenças. Isso aqui é a
**parte 1** do trabalho de alinhar o gerador a esse modelo final — a parte
2 (reconstruir nativamente, com fidelidade ao print, os 4 dashboards que
você substituiu por captura de tela real do Stock Savvy: Baixas Operacionais
— Evolução Mensal, Farol de Shelf-Life — Risco por Almoxarifado, Recuperação
de Shelf e Dispersão de Ficha Técnica) ainda não está pronta — é um trabalho
bem maior (matriz de criticidade 2x2, gráficos anotados, combos de barra +
linha) e prefiro te entregar em uma rodada própria.

Esta parte 1 cobre as duas mudanças mais simples e mais seguras de validar
isoladamente:

1. Remover os 3 tópicos que você tirou do modelo manual.
2. Corrigir o bug de rótulo em 2 linhas que você viu no seu arquivo (slide
   "Resumo Executivo") e encolher os cartões de KPI, como no seu modelo.

Só `backend/app/mbr_generator.py` mudou. Nenhum extrator, endpoint ou
cálculo foi alterado.

## 1) Removidos 3 tópicos (confirmado com você)

- **Painel de Inventário — Detalhamento Financeiro** (o slide companheiro
  "SKUs Recorrentes e Cobertura de Conferência", depois de Painel de
  Inventário na Seção 2).
- **Mapeamento de Risco — Obsolescência** (slide dedicado na Seção 3).
- **Scorecard de Mapeamento de Riscos** (capítulo-síntese que fechava a
  Seção 3).

Os cálculos por trás desses 3 tópicos continuam rodando nos bastidores só
onde ainda são usados por outro slide (ex.: "Mapeamento de Risco —
Obsolescência" ainda aparece como uma linha dentro do Scorecard do Mês e no
Resumo Executivo — só o slide dedicado saiu). As 2 buscas ao banco que só
alimentavam o slide de SKUs Recorrentes/Cobertura, e as 3 buscas extra ao
mês anterior que só alimentavam o Scorecard de Mapeamento de Riscos, também
saíram — sem elas, o Atlas ficaria consultando o banco à toa em toda geração
de MBR, sem nenhum slide pra usar o resultado.

O relatório passa de 30 pra 27 slides de conteúdo (+ capas), Seção 2 de 8
pra 7 slides, Seção 3 de 11 pra 9 slides — a numeração de página se ajusta
automaticamente.

## 2) Bug do rótulo em 2 linhas + cartões mais baixos

**O bug que você viu**: no seu modelo manual, o slide "Resumo Executivo" tem
2 cartões (KPI) onde o texto do rótulo (ex.: "BAIXAS POR PACOTE (BAIXAS
OPERACIONAIS)") é longo demais pra 1 linha só, quebra em 2 linhas, e a 2ª
linha invade visualmente o texto de contexto logo abaixo (ex.: "18,2% em
Vencimento"). Isso é um bug de verdade no gerador, não só do seu arquivo
manual — a posição do texto de contexto é fixa, sem levar em conta se o
rótulo acima ocupou 1 ou 2 linhas.

**Corrigido de duas formas, uma reforçando a outra:**

- Encurtei os 2 rótulos que estavam causando a quebra ("Baixas por Pacote
  (Baixas Operacionais)" → "Baixas por Pacote"; "Valor em Risco de Validade
  (Farol de Shelf)" → "Valor em Risco de Validade") — a fonte do dado já
  fica clara pelo resto do relatório, não precisava repetir dentro do
  espaço apertado do cartão.
- Mais importante: o cartão de KPI agora **garante** que o rótulo nunca
  mais ocupa 2 linhas, seja qual for o texto — se for longo, a fonte do
  rótulo encolhe automaticamente até caber numa linha, e só corta com "…"
  no limite. Isso protege contra qualquer rótulo longo no futuro (ex.: nome
  de indicador dinâmico cadastrado pela equipe), não só os 2 que você viu.

**Cartões mais baixos**: medi os cartões do seu modelo manual (ex.: IAP em
0,837in, Painel de Inventário em 0,739in, contra os 1,05-1,10in atuais) e
apliquei uma altura padrão de 0,85in em todos os 13 lugares do relatório que
usam esse cartão — bem na faixa que você usou. O número continua o elemento
dominante do cartão (só encolheu um pouco, de 32 pra 27pt, pra caber sem
esbarrar no rótulo abaixo).

## Testado

- `python3 -m py_compile` limpo.
- Seção 1 (Resumo Executivo + Scorecard do Mês), Seção 2 completa (7
  slides) e Seção 3 completa (capa + 9 slides) geradas com dado real (mesmos
  arquivos HTML de Farol de Shelf-Life e Baixas Operacionais já validados na
  Fase 2) e dado sintético onde não havia fixture real — renderizadas e
  inspecionadas imagem a imagem, incluindo um teste isolado do cartão de KPI
  com rótulos deliberadamente muito longos (mais longos que o bug original)
  pra confirmar que a correção segura qualquer caso, não só os 2 rótulos
  específicos que você viu.
- Confirmado no Resumo Executivo com dado real: os 2 cartões que antes
  quebravam linha agora mostram "BAIXAS POR PACOTE" e "VALOR EM RISCO DE
  VALIDADE" numa linha só, sem invadir o contexto.
- Nenhuma referência solta a algo que foi removido (revisei todo texto que
  aparece NO SLIDE, não só comentário de código, procurando por menções aos
  3 tópicos removidos — encontrei e corrigi 2: um rodapé no slide de
  Inventário Item a Item que dizia "SKUs recorrentes e cobertura de
  conferência: próximo slide" e uma linha no slide "Stock Savvy — Módulos
  Recentes" que citava o Scorecard de Mapeamento de Riscos como destino).

**Não relacionado a este pacote, encontrado durante a revisão visual**: no
slide "Recuperação de Shelf — Evolução Mensal", os rótulos de valor de 2
barras (Abr/26 e Mai/26) ficam parcialmente atrás da barra vizinha. Esse
slide é exatamente um dos 4 que serão refeitos na parte 2 (reconstrução
nativa com fidelidade ao print) — não vale a pena corrigir separadamente
agora, seria retrabalho.

## Não incluído neste pacote

Os 4 dashboards que você substituiu por print (Baixas Operacionais —
Evolução Mensal, Farol de Shelf-Life — Risco por Almoxarifado, Recuperação
de Shelf, Dispersão de Ficha Técnica) continuam exatamente como estão hoje
no gerador — ainda não reconstruídos com a fidelidade visual do print que
você aprovou. Isso é a parte 2, ainda por vir.
