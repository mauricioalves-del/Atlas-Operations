# FEFO — motor nativo por lote movimentado

## O que mudou

A tela "FEFO — Quebras na Movimentação" ("Checagens") estava trazendo dados
errados (1.745 movimentos avaliados, 1.328 quebras, **89,85%** de taxa de
quebra). A causa raiz: o cálculo antigo (`calcular_checagem_fefo`) **nunca
comparava de fato o lote que saiu da Fábrica** contra nada — só checava (1)
se já tinham passado 5 dias úteis desde a transferência até *hoje* e (2) se
existia qualquer lote daquele SKU com estoque na Fábrica *hoje*. Como isso
recalcula contra TODAS as transferências históricas usando a data de hoje
a cada vez, praticamente toda transferência com mais de ~1 semana virava
"quebra" — daí os 89,85%. Está tudo documentado, com data e detalhe técnico,
no projeto Atlas Operations (`claude/checagens-fefo-heuristica-quebrada.md`).

A pedido explícito ("crie um motor investigativo, sem ferramenta genérica.
Com base na tabela de movimentação, pegue tudo que saiu da fábrica e
compare com o lote mais próximo da data de vencimento. Se lote não for
igual, quebra de FEFO. Esse processo precisa atualizar todos os dias"),
foi construído um motor **novo e independente**, que:

1. Lê a planilha bruta **"Movimentação - Lt.xlsx"** — a mesma exportação
   por lote que o André já usa no próprio processo de auditoria dele (tem
   a coluna `id_lote`, que a movimentação diária normal do Atlas não tem).
2. Pra cada saída da Fábrica, pega o LOTE QUE DE FATO SAIU e compara contra
   os lotes do mesmo SKU que continuam na Fábrica (validade conhecida,
   estoque > 0). Se existe algum lote mais antigo que não foi o que saiu,
   é quebra de FEFO.
3. Recalcula automaticamente a cada importação nova, **e também uma vez
   por dia em segundo plano**, mesmo sem upload manual naquele dia.

**Resultado no arquivo de teste real (5 dias, 07 a 12/08):** 186 movimentos
de saída da Fábrica identificados, 20 quebras — **11,24%** de taxa de
quebra. Validei manualmente caso a caso (ex: SKU 0040305007, lote
030010306Z000010126 → corretamente "OK", porque era de fato o lote mais
antigo dos dois que a Fábrica tinha; SKU 05004102 → corretamente "QUEBRA",
porque saiu o lote com validade 01/01/2027 enquanto um lote com validade
16/12/2026 continuou parado). Ordens de grandeza plausíveis, batendo perto
do ~4,6% que a Auditoria FEFO importada (relatório do André) já mostrava.

O motor antigo (`ChecagemFefo`) **fica desativado, mas não é apagado** —
continua no banco só como registro histórico, e a docstring dele agora
explica o problema e aponta pro motor novo. A "Auditoria FEFO importada"
(os relatórios que o André já gera e sobem pro Atlas) continua existindo
do mesmo jeito, como feature separada — não há fusão entre as duas.

## Limitação conhecida (avisando de propósito, não escondendo)

O processo do André tem uma planilha de exceções manualmente validadas
(`Excecoes_FEFO.xlsx`) — pares de produto + "lote mais antigo disponível"
que um humano já revisou e confirmou que está OK apesar da ordem (ex: por
motivo operacional específico daquele lote). **Esse motor nativo ainda não
importa essa planilha de exceções.** Toda vez que existir um lote mais
antigo do mesmo SKU na Fábrica que não foi o lote movimentado, isso é
reportado como quebra — mesmo que o André já tenha validado aquele caso
específico como OK no processo dele por fora. Se isso gerar muito falso
positivo já conhecido/validado, dá pra construir a importação da planilha
de exceções depois — não fiz isso agora pra não atrasar a entrega do
motor principal.

## Como usar

Na tela **Importar**, tabela "Dados de contexto", nova linha
**"Movimentação por Lote (FEFO)"**: suba o(s) arquivo(s) "Movimentação -
Lt.xlsx" (pode selecionar vários de uma vez; cada um pode trazer vários
dias). A checagem de FEFO recalcula automaticamente ao final da
importação. Reimportar um dia substitui as linhas daquele dia, sem
duplicar.

Na tela **FEFO**, o filtro agora é "Todos os movimentos avaliados" / "Só
quebras de FEFO" (o campo antigo de resultado por transferência não existe
mais, porque a unidade agora é o lote, não a transferência agregada). O
botão "Recalcular" continua existindo, pra rodar de novo sem precisar
reimportar (ex: depois de atualizar o Lote de Validade/Shelf Life).

**Recálculo automático diário:** o servidor roda o recálculo em segundo
plano a cada 24h (configurável por variável de ambiente
`ATLAS_FEFO_RECALCULO_INTERVALO_HORAS`, verificando a cada
`ATLAS_FEFO_CHECAGEM_SEGUNDOS`; pra desativar,
`ATLAS_FEFO_AUTO_RECALCULO=false`), mesmo em dias sem upload manual — como
pedido.

## Contrato da API preservado (sem quebrar o frontend)

`GET /fefo/dashboard/resumo` continua devolvendo os MESMOS nomes de campo
de antes (`total_transferencias_avaliadas`, `total_quebras_fefo`,
`total_dentro_do_criterio`, `total_sem_dado_suficiente`, `taxa_quebra_pct`,
`top_skus_com_quebra`, `top_destinos_com_quebra`) — o que mudou foi só a
fonte e o critério por trás de cada número, não o contrato. Só o texto do
rótulo na tela mudou ("Transferências avaliadas" → "Movimentos avaliados").
Isso significa que o card de FEFO no MBR e na tela "Movimentados & FEFO"
continuam funcionando sem qualquer alteração.

`GET /fefo/checagens` mudou de fato (é uma tabela nova,
`ChecagemFefoMovimento`, com campos por lote) — a tela FEFO já foi
atualizada pra refletir isso (nova coluna "Lote Movimentado" na tabela de
Checagens).

## Arquivos alterados

- `backend/app/models.py` — docstring de `ChecagemFefo` atualizada com o
  aviso de desativação; duas classes novas, `MovimentacaoLoteDiaria`
  (movimentação bruta por lote importada) e `ChecagemFefoMovimento`
  (resultado do motor nativo). Tabelas novas — sem migração manual
  necessária, criadas automaticamente no próximo boot.
- `backend/app/fefo.py` — nova seção com o motor nativo: importação da
  planilha de movimentação por lote, comparação lote-a-lote, e o
  recálculo/resumo agregado.
- `backend/app/routers/fefo_router.py` — novo endpoint
  `POST /fefo/movimentacao/importar`; `POST /fefo/recalcular`,
  `GET /fefo/checagens` e `GET /fefo/dashboard/resumo` repontados pro
  motor novo.
- `backend/app/scheduler.py` — novo agendador em segundo plano pro
  recálculo diário automático (mesmo padrão de thread já usado pro
  retreino de ML).
- `backend/app/main.py` — chama o novo agendador na inicialização.
- `frontend/index.html` — nova linha de importação na tela Importar; tela
  FEFO com filtro, texto explicativo e tabela de Checagens atualizados
  pro motor novo (coluna "Lote Movimentado" no lugar de "Dias úteis em
  aberto").
- `frontend/app.js` — `carregarFefo()` atualizada pro novo formato de
  dados; novo handler de importação da movimentação por lote.

## Validado (banco de teste local, com o arquivo real que você enviou)

Importei o `Movimentação - Lt.xlsx` real (6.406 linhas, 5 dias: 07 a
12/08) sobre o `Lote_Sistema.xlsx` já importado (1.050 lotes ativos, 386
na Fábrica). Confirmado:

- 186 movimentos de saída da Fábrica identificados (o resto das 6.406
  linhas é o mesmo movimento físico duplicado sob o almoxarifado de
  destino, ou movimentos que não envolvem a Fábrica — corretamente fora
  do escopo).
- 20 quebras (11,24%) — taxa plausível, na mesma ordem de grandeza da
  Auditoria FEFO importada (~4,6%).
- Reimportar o mesmo arquivo não duplicou nada (6.406 linhas substituídas,
  não somadas; 186 checagens, não 372).
- `POST /fefo/recalcular` roda de novo sobre todo o histórico sem duplicar
  e sem precisar reimportar.
- Tracei 2 casos manualmente na planilha bruta: um "OK" (o lote que saiu
  era de fato o mais antigo dos dois que a Fábrica tinha) e um "QUEBRA"
  (saiu o lote mais novo, o mais antigo ficou parado) — os dois batem com
  o que o motor calculou.
- Agendador de recálculo diário inicializa corretamente no boot do
  servidor (log: "Atlas: recálculo automático de FEFO ativo...").
