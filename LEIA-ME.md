# atlas_fix_mbr_grupo1.zip (21/08/2026)

## Antes de aplicar — o passo que faltava nas entregas anteriores

O Atlas roda no Render (nuvem), e o Render só passa a usar código novo depois
de um deploy explícito — subir o zip e redeployar, do mesmo jeito que já é
feito com os pacotes `atlas-vNN.zip`. Arquivo enviado solto no chat, ou
gravado na sua pasta local `Atlas\Atlas`, não chega ao servidor que gera o
MBR. Se o próximo relatório gerado continuar idêntico ao anterior, o passo do
deploy no Render é o primeiro lugar a checar.

## Como aplicar

1. Suba este zip e faça o deploy do backend no Render (mesmo processo já
   usado nos pacotes anteriores).
2. Depois do deploy, gere o MBR de novo escolhendo o fechamento de julho e
   confira os pontos abaixo.

## O que está dentro

- `backend/app/mbr_generator.py`
- `backend/app/dashboards_externos_extrator.py`
- `backend/app/routers/divergencias_router.py`

## O que foi implementado neste pacote (Grupo 1 — dado real já existente no backend)

Isto cobre o que foi aprovado nos mockups v4/v5/v8/v9/v10/v11 e que já tem uma
fonte de dado real e confiável no Atlas (sem precisar inventar número nem
reconstruir gráfico a partir de SVG). O que ficou de fora está listado na
seção "O que ainda não entrou" abaixo — nenhum item foi descartado, só
priorizado.

**Correção de bug — parâmetro de fechamento** (já confirmada nas entregas
anteriores, reforçada aqui): todas as séries mensais usadas no MBR são
cortadas no mês de fechamento escolhido.

**Painel de Inventário**
- Selo de tendência (melhora/piora/estável) ao lado do gráfico de evolução da
  acurácia, calculado por regressão linear simples sobre os últimos meses.
- Novo slide "Painel de Inventário — Detalhamento Financeiro": tabela por
  almoxarifado + Top Faltas + Top Sobras + resumo do ciclo.

**Acurácia Ponderada**
- Slide único (IAQ+IAP) virou 2 slides dedicados — "Acurácia Ponderada (IAP)"
  e "Acurácia Ponderada (IAQ)" — cada um com KPI, gráfico de evolução, selo de
  tendência e as mesmas 3 tabelas (Almoxarifado / Top Faltas / Top Sobras).
- "Concentração de Risco": curva de Pareto ampliada de 10 para 20 SKUs (+
  ponto de cauda "+N itens"), e a tabela de exemplos ampliada de 3 para
  10 linhas, 8 colunas (SKU, Descrição, Almoxarifado, Qtd. Sistema, Qtd.
  Conferida, Diferença, Valor, % Acumulado).
- Novo slide "Detalhamento por Faixa": Top 5 por valor dentro de cada faixa
  de magnitude (0-5 un. / 5-20 un. / 20-100 un. / mais de 100 un.), lado a
  lado.

**Controle de Movimentados**
- Nova tabela "Resultado por Almoxarifado (Movimentados)", ordenada do pior
  para o melhor por acurácia da reconciliação.

Todos os itens acima foram validados com dados sintéticos (populados e vazios)
sem erro, e inspecionados visualmente slide a slide — sem estouro de texto,
sobreposição ou corte.

## O que ainda não entrou (Grupo 2 — fica para o próximo pacote)

Estes itens dependem de coisas que não têm dado estruturado hoje, e por isso
exigem trabalho adicional antes de entrar com segurança:

- **Farol de Shelf Life** — os 2 gráficos "Risco por Almoxarifado" e "Custo
  por Grupo e Status": só existem como `<svg>` no HTML exportado da tela
  externa, sem tabela ou JSON por trás — precisaria reconstruir a geometria
  do SVG para virar gráfico nativo, o que ainda não foi feito.
- **Recuperação de Shelf** — gráfico de evolução mensal: mesma limitação (só
  SVG na exportação).
- **Baixas Operacionais externo (Pacote)** — gráfico mensal: mesma limitação.
- **Controle de Movimentados — 2º slide** (Causas Confirmadas + Top 10 Ações):
  o endpoint `dashboard_distribuicao_causas` hoje só aceita período relativo
  (não aceita um mês exato de fechamento) — precisa de uma mudança no backend
  antes de alimentar este slide.

Nenhum destes tem dado fabricado ou aproximado neste pacote — preferi deixar
de fora a mostrar número que não bate com a fonte real.
