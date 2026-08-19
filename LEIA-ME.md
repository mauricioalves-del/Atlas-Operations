# MBR — Scorecards por Almoxarifado e por Risco, e slides de venda Atlas + Stock Savvy

## O pedido

Você pediu três coisas na apresentação do MBR:

1. Um **Scorecard de Inventário por Almoxarifado**, mostrando evoluções e
   involuções, com plano de ação por setor, baseado no histórico de
   inventários e na conciliação de movimentados.
2. Um **Scorecard de Mapeamento de Riscos** por ação de mapeamento/controle,
   cruzando Dispersão de Lote (Produção), Testes Industriais, FEFO e Shelf
   Life — com evoluções, involuções e próximos passos.
3. Uma análise "vendendo a ideia" do controle formado por Atlas + Stock
   Savvy (o app paralelo no Lovable), citando especificamente os módulos
   Produção, Shelf Life e Gestão.

Perguntei duas coisas antes de começar: se o conteúdo do Stock Savvy devia
vir só da descrição que você deu ou de eu navegar no sistema — você
confirmou **"entre no sistema, analise os módulos"**; e se os dois novos
Scorecards deviam ganhar seções novas ou entrar como slides dentro das
seções já existentes — você escolheu **slides novos dentro das seções já
existentes**.

## O que foi construído

### 1. Scorecard de Inventário por Almoxarifado (Seção 2 — Inventários e Movimentados)

Uma linha por almoxarifado ativo, cruzando três leituras:

- Acurácia item-a-item do fechamento do mês e a variação vs. o mês
  anterior.
- IAP (acurácia ponderada por valor) do mês, como leitura complementar.
- Acurácia da reconciliação diária de Movimentados e sua variação.

O status da linha (Evolução / Estável / Involução / Sem histórico) usa o
**pior dos dois sinais** — fechamento e movimentados — não a média: um
almoxarifado só aparece "em avanço" se os dois estiverem, no mínimo,
estáveis. O próximo passo é escrito por regra a partir desses mesmos
números (reconferência prioritária, investigar causa raiz, reforçar
conciliação, intensificar cadência, ou manter o ritmo atual) — não é texto
livre.

Almoxarifado sem fechamento ou sem movimentados registrados no mês entra
como "Sem histórico", não é omitido da tabela.

### 2. Scorecard de Mapeamento de Riscos (Seção 3 — Mapeamento de Riscos e Passivos)

Uma linha por frente de risco:

- **Shelf Life (Farol + Obsolescência)** — avaliado só pelo nível atual
  (lotes em risco, críticos por giro zero), porque essa base é uma
  fotografia do dia — hoje não existe série mensal persistida de Shelf
  Life no Atlas, então não dá pra mostrar "evolução" real sem inventar um
  histórico que não existe. Isso está dito explicitamente no rodapé do
  slide, pra não parecer que faltou dado.
- **Dispersão de Ficha Técnica (Produção)**, **Testes Industriais** e
  **FEFO (Auditoria importada)** — esses três comparam o mês do relatório
  com o mês anterior, porque a base de cada um já tem histórico por mês.
  Quando o indicador nunca foi importado, ou não tem dado nesse mês
  específico, ou o arquivo não pôde ser lido, o slide mostra o motivo
  certo (não finge "Estável" sobre dado que não existe).

### 3. Atlas + Stock Savvy — dois slides novos (Seção 7 — Impacto e Próximos Passos)

- **"Atlas + Stock Savvy"**: o posicionamento dos dois sistemas em camadas
  complementares — Stock Savvy como camada operacional (onde a ação
  acontece: solicitar baixa por QR, aprovar com assinatura dupla, registrar
  ação de lote) e Atlas como camada de inteligência executiva (onde as
  frentes se cruzam num relatório único, com histórico e plano de ação).
- **"Stock Savvy — Módulos Recentes"**: tabela com os três módulos que você
  pediu para destacar — Produção (Dispersão de Lote e Ações Corretivas),
  Shelf Life (Mapeamento de Risco, Ações de Lote, Farol e Saving) e Gestão
  (Baixas Operacionais e Dashboard de Baixas) — e como cada um já se
  conecta ao Atlas hoje.

O conteúdo desses dois slides vem de **navegação real no Stock Savvy**
(entrei no sistema, não só na sua descrição), então cada afirmação (ex.:
"Saving Recuperado" aparecendo no Dashboard Shelf Life, o fluxo de
aprovação com assinatura dupla) foi confirmada na tela, não assumida.

## O que NÃO foi possível fazer

Shelf Life não tem série mensal no Atlas hoje (é sempre calculado contra a
data de hoje, sem snapshot por mês salvo em banco). Por isso ele entra no
Scorecard de Riscos sem "evolução vs. mês anterior" — só pelo nível atual.
Se isso for importante pra virar comparação mês a mês, precisa de uma
tabela nova pra guardar o snapshot mensal — não é uma mudança pequena, e
não estava no pedido original, então não foi feita aqui.

## Validado

- Testei o Scorecard de Inventário por Almoxarifado com histórico
  sintético de 3 almoxarifados em 2 meses (Fábrica melhorando, Loja
  piorando, Processo estável) e confirmei que os rótulos de status e o
  próximo passo batem com a regra do "pior dos dois sinais" — inclusive a
  leitura de IAP, que só aparece quando o cadastro de custo do produto
  existe.
- Testei o Scorecard de Mapeamento de Riscos nos 4 estados possíveis por
  frente: nunca importado, sem dado nesse mês, com dado e piora (Involução),
  com dado e melhora (Evolução) — e no caso real do banco de teste (FEFO
  com histórico real de maio a agosto/2026, Shelf Life com risco de
  obsolescência real, Dispersão de Ficha Técnica e Testes Industriais ainda
  não importados).
- Gerei o MBR completo (30 slides) para julho/2026 com todos os slides
  novos presentes, revisei o texto inteiro (`markitdown`) sem sobra de
  rascunho, e validei a estrutura do arquivo (schema, relacionamentos,
  content types) sem nenhum problema.
- Revisão visual de cada slide novo: nenhum corte de texto, nenhuma
  sobreposição. Encontrei e corrigi um corte de texto real no slide "Atlas
  + Stock Savvy" (o parágrafo "Por que manter os dois" estava sendo cortado
  no meio da frase porque a altura da caixa foi um valor fixo que não
  cabia o texto real — troquei pra calcular a altura necessária a partir do
  texto, mesmo padrão já usado em outros slides do MBR). Também encontrei e
  removi uma referência a um caminho de arquivo interno
  (`claude/sincronizacao-lovable-baixas.md`) que tinha ficado, por engano,
  dentro do texto de um dos slides — não é algo que devesse aparecer numa
  apresentação pra executivos.

## Arquivo alterado

- `backend/app/mbr_generator.py`:
  - Novas funções de coleta: `_coletar_scorecard_inventario_almoxarifado`,
    `_linha_scorecard_almoxarifado`, `_coletar_scorecard_mapeamento_riscos`,
    `_linha_risco_com_evolucao`.
  - Novo helper de classificação: `_status_evolucao` (evolução/estável/
    involução/sem histórico a partir de uma variação, diferente do
    `_status_maior_melhor`/`_status_menor_melhor` que já existiam e
    classificam um nível absoluto).
  - Novo helper `_mes_anterior` (mês anterior no formato `YYYY-MM`).
  - Quatro novos slides: `_slide_scorecard_inventario_almoxarifado`,
    `_slide_scorecard_mapeamento_riscos`, `_slide_atlas_stock_savvy_visao`,
    `_slide_atlas_stock_savvy_modulos`.
  - `montar_pptx_mbr` atualizado: os dois Scorecards entram nas seções 2 e
    3 já existentes, os dois slides de Stock Savvy entram na seção 7 — sem
    criar seção nova, como você pediu.

Nenhuma migração de banco necessária — os dois Scorecards novos só leem
dados que o Atlas já calcula em outros lugares (fechamento, movimentados,
FEFO, Shelf Life, dashboards externos); nada foi criado ou alterado no
schema.
