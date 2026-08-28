# atlas_fix_grafico_acuracia_almoxarifado.zip (28/08/2026)

## Antes de aplicar

Mesmo lembrete de sempre: o Atlas roda no Render, e só passa a usar código
novo depois de zip + redeploy manual.

## O que você pediu

> "Estou com espaço vago nesse indicador da contagem de movimentados. Quero
> adicionar um grafico de barras invertido trazendo a acuracidade acumulada
> por Almoxarifado."

Junto vieram 2 prints do painel **"Almoxarifado × Hipótese"** (dentro do
Painel de Divergências), com a área vazia embaixo do heatmap marcada em
vermelho.

**Ponto de atenção (decisão que tomei, vale conferir)**: o texto da mensagem
fala em "indicador da contagem de movimentados", mas os prints mostram
claramente o card "Almoxarifado × Hipótese", não a tela "Controle de
Movimentados" (que também existe no menu). Fui pelos prints — o espaço vago
marcado é inequívoco — e adicionei o gráfico ali. Se a intenção era outra
tela, me avisa que eu ajusto.

## O que foi feito

Adicionei um novo gráfico de barras invertido logo abaixo do heatmap
"Almoxarifado × Hipótese", no mesmo card, ocupando o espaço vazio do print:
**"Acurácia Acumulada por Almoxarifado"**.

- Cada barra é um almoxarifado, com a acurácia acumulada de TODO o recorte
  (não dia a dia — é a mesma conta usada no gráfico "Itens Inventariados e
  Acurácia por Dia", só que somada por almoxarifado em vez de por data).
- Cor da barra segue o mesmo farol usado no resto do Atlas: vermelho
  (<50%), amarelo (50-75%) e verde (≥75%).
- Ordenado do PIOR pro melhor (a barra do topo é sempre o almoxarifado com
  menor acurácia) — o objetivo é chamar atenção pra quem precisa de atenção
  primeiro, mesma lógica dos rankings de reincidência que já existem no
  painel.
- Clicar numa barra filtra o painel inteiro por aquele almoxarifado (mesmo
  comportamento de "clique-para-filtrar" que o heatmap e os outros gráficos
  já têm) e abre o resumo daquele ponto, com a acurácia e a quantidade de
  itens inventariados.
- Só respeita o filtro de **período** (Tudo / Mês atual / 30 / 60 / 90
  dias), não o de almoxarifado — igual aos outros indicadores desse mesmo
  grupo de cards (heatmap, causas, reincidência, top divergências): um
  gráfico "por almoxarifado" não faz sentido se a tela já estiver filtrada
  pra um único almoxarifado.

### Por trás dos panos

- Endpoint novo no backend: `GET /api/dashboard/acuracia-por-almoxarifado`
  — mesma lógica do endpoint que já existia pra acurácia por dia, só que
  agrupando por almoxarifado.
- O card cresceu um pouco de altura pra caber o gráfico novo — no celular
  ele empilha normalmente, junto com o resto do painel (que já vira uma
  coluna só em telas pequenas).

## Testado

- `python3 -m py_compile` (backend) e `node --check` (frontend) limpos.
- Testei a conta do endpoint novo de verdade, com um banco de teste em
  memória: confirmei que a acurácia por almoxarifado bate (inclusive
  casos de 0% e 100%), que registros de fechamento de inventário ficam de
  fora (mesma regra dos outros indicadores) e que o filtro de período corta
  corretamente os itens fora do mês atual.
- Testei o gráfico no navegador (Playwright): renderiza com as cores do
  farol certas, ordenado do pior pro melhor, sem estourar o card nem
  sobrepor o heatmap acima; cliquei numa barra e confirmei que o filtro de
  almoxarifado do painel muda e o resumo do ponto abre com o texto certo.

## Não incluído neste pacote

Não mexi em nenhum outro gráfico, endpoint ou filtro do Painel de
Divergências — só adicionei o gráfico novo no espaço vazio indicado.
