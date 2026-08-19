# MBR — 3 ajustes a partir do seu feedback nas capturas de tela

## O que você pediu

Depois de ver as primeiras capturas do MBR novo, você apontou três coisas:

1. No Scorecard de Inventário por Almoxarifado, Box, Box 2, Ativação e Loja
   apareciam sempre como "Sem histórico", mesmo tendo dado de acurácia real
   — porque o Atlas não faz controle de Movimentados nesses almoxarifados,
   e você pediu pra desconsiderar essa premissa nessa análise.
2. No Mapeamento de Passivos, tudo que foi baixado por inventário no
   período devia cair na barra "Mapeada via Inventário Mensal" — e estava
   caindo inteiro em "Aprovada, aguardando divergência".
3. Adicionar, no slide "Atlas", a visão da Rotina Master (seu diário de
   bordo) — entrando no sistema (rotinabusiness.lovable.app), filtrando
   pelo mês de fechamento (1º ao último dia), com um indicador novo de
   curva de evolução ligado a constância e disciplina em manter as tarefas
   em dia.

## 1. Scorecard de Inventário por Almoxarifado — Movimentados não aplicável

A regra de status usava "o pior dos dois sinais" (fechamento vs.
Movimentados). Isso fazia sentido pra almoxarifados que fazem os dois
controles — mas Box, Box_2, Ativação e Loja nunca vão ter dado de
Movimentados (decisão operacional sua, não uma lacuna de dado), então a
regra os travava em "Sem histórico" pra sempre, escondendo evolução real de
acurácia de fechamento.

Corrigido reaproveitando o cadastro que já existe pra isso:
`Almoxarifado.participa_contagem_diaria` — o mesmo campo que já exclui
esses almoxarifados da Cobertura de Conferência. Quando esse campo é
`False`, o Scorecard agora usa **só o sinal de fechamento** pra decidir o
status daquele almoxarifado, e a leitura mostra "Movimentados: não
aplicável a este almoxarifado" em vez de um "—" que parecia lacuna de dado.
Almoxarifados que fazem os dois controles continuam com a regra original
(pior dos dois sinais).

## 2. Mapeamento de Passivos — baixas de inventário mensal sem vínculo formal

O motivo raiz: uma baixa só era classificada como "Mapeada via Inventário
Mensal" se estivesse formalmente vinculada (`divergencia_vinculada_id`) a
uma divergência de fechamento, e esse vínculo automático só acontece
dentro de uma janela de poucos dias (1 dia antes a 4 dias depois) entre a
data da baixa e a data da divergência. Essa janela foi calibrada pra
reconciliação DIÁRIA de Movimentados — faz sentido lá, porque a baixa
correspondente costuma ser aprovada poucos dias depois.

Fechamento mensal não se encaixa nessa janela: a divergência só é detectada
no dia do fechamento (geralmente fim do mês), enquanto a baixa
correspondente pode ter sido aprovada em qualquer dia daquele mês, semanas
antes. Por isso, praticamente nenhuma baixa de inventário mensal ganhava o
vínculo formal, e todas ficavam presas em "Aprovada, aguardando
divergência" mesmo sendo, de fato, inventário.

Corrigido sem tocar no vínculo formal nem na resolução automática de
divergências (isso continua exigindo o casamento de sempre, com sua
janela de dias — não queria arriscar mexer nisso, que afeta pesos de ML e
resolução real de divergências). A correção é só na classificação/exibição:
se existe qualquer divergência de fechamento mensal pro mesmo SKU +
almoxarifado no mesmo mês da baixa, ela conta como "Mapeada via Inventário
Mensal" na tela e no MBR, mesmo sem o vínculo formal. Essa correção está no
único endpoint por trás da tela Mapeamento de Passivos
(`/dashboard/resumo-executivo`) e em todos os outros painéis que usam a
mesma categorização (KPIs, motivos, drill-down de itens) — não só no MBR.

## 3. Novo slide: Constância e Disciplina — Diário de Bordo

Adicionado na Seção 7 (Atlas), logo depois de "Impacto do Atlas". Entrei na
Rotina Master (rotinabusiness.lovable.app) com o filtro de período já em
01/07/26 a 31/07/26 (mês de fechamento) e trouxe:

- Cumprimento geral do mês (97%, 294 de 302 rotinas) e conclusões no prazo
  vs. em atraso.
- Um indicador novo — que você pediu — de constância: separei os dias
  úteis dos fins de semana (fim de semana não tem rotina devida naquele
  app, então cumprimento 0% ali não é uma falha, é ausência de tarefa) e
  calculei a média só nos dias úteis (84,7%), a maior sequência de dias
  úteis consecutivos a 100% (8 dias) e os lapsos pontuais do mês (09/07,
  10/07 e 30/07 — sempre recuperados no dia útil seguinte, sem se
  arrastar).
- Uma curva de evolução semanal (5 pontos, só dias úteis) que mostra
  claramente a queda na semana de 06 a 10/07 (58,6%, por causa dos dois
  lapsos consecutivos) e a recuperação total nas semanas seguintes.

**Importante sobre este indicador**: ele não vem de uma consulta ao banco
do Atlas como todo o resto do MBR — a Rotina Master é um app separado,
sem integração automática ainda. Os números vieram de uma coleta manual
feita agora (21/08/2026), navegando direto no Dashboard de Performance
daquele app. Se quiser esse indicador em todo MBR futuro, alguém precisa
repetir essa coleta manual a cada mês (ou construir uma integração
automática entre os dois sistemas, que não existe hoje) — deixei isso
registrado no rodapé do próprio slide e no código, pra não passar a
impressão de que é um dado ao vivo.

## Validado

- Scorecard de Almoxarifado: testado com um almoxarifado sintético (Box)
  sem controle de Movimentados e com evolução real de acurácia (+30 p.p.)
  — confirmei que ele agora aparece como "Evolução" (antes ficava "Sem
  histórico").
- Mapeamento de Passivos: testado com uma baixa aprovada 21 dias antes do
  fechamento do mês (fora da janela de poucos dias) — confirmei que ela
  agora entra em "Mapeada via Inventário Mensal", e que uma baixa sem
  fechamento correspondente continua em "Aprovada, aguardando
  divergência" (a correção não é indiscriminada).
- Slide de Diário de Bordo: testado nos dois estados (mês com coleta e mês
  sem coleta) e revisado visualmente — corrigi um rótulo de KPI que estava
  quebrando em 2 linhas e ficando colado na borda do card.
- Gerei o MBR completo de novo (31 slides) e revisei a estrutura do
  arquivo e o texto de todos os slides afetados — sem sobreposição, sem
  corte de texto, sem problema de validação.

## Arquivos alterados

- `backend/app/mbr_generator.py` — `_linha_scorecard_almoxarifado` agora
  ignora o sinal de Movimentados quando não aplicável; novo indicador
  `_coletar_indicador_diario_bordo` + slide `_slide_diario_bordo`.
- `backend/app/routers/baixas_operacionais_router.py` —
  `_categoria_mapeamento` reconhece inventário mensal por mês/SKU/
  almoxarifado quando não há vínculo formal ainda; nova função
  `_mapa_fechamentos_mensais_por_sku_almox`.

Nenhuma migração de banco necessária.
