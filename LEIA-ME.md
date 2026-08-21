# atlas_fix_mbr_secoes_e_fechamento.zip (21/08/2026)

## Por que o relatório não mudava até agora

Nada disso é bug de código: o MBR que estava sendo gerado continuava vindo do
código antigo porque nenhuma das entregas anteriores desta sessão chegou a
alcançar o servidor real. O Atlas roda no Render, e o Render só passa a usar
código novo depois de um deploy explícito (subir este zip e redeployar) — os
arquivos que te mandei antes soltos (.py e depois via device bridge, na pasta
local `Atlas\Atlas`) nunca chegaram lá. Foi isso, não uma falha na correção
em si. A partir de agora sigo o mesmo padrão já usado nas entregas anteriores
deste projeto (zip + LEIA-ME).

## Como aplicar

1. Suba este zip e faça o deploy do backend no Render (mesmo processo já usado
   nos pacotes anteriores, ex. `atlas-v19.zip`).
2. Depois do deploy, gere o MBR de novo escolhendo o fechamento de Julho e
   confira os pontos abaixo.

## O que está dentro

- `backend/app/mbr_generator.py`
- `backend/app/dashboards_externos_extrator.py`
- `backend/app/routers/divergencias_router.py`

## Checklist do que foi aprovado e já está implementado

**Correção de bug — parâmetro de fechamento**
Todas as séries de evolução mensal usadas no MBR (Painel de Inventário,
Acurácia Ponderada, Movimentados, Transferências, Passivos) agora são
cortadas no mês de fechamento escolhido — nenhuma mais mostra o mês corrente
quando você gera um relatório de mês passado. Cobertura de Conferência e o
Scorecard por Almoxarifado também passaram a respeitar o mês escolhido.

**Estrutura de seções**
FEFO e Testes Industriais deixam de ter slide de apresentação (divisória)
próprio — o conteúdo passa a fazer parte da seção "Mapeamento de Passivos e
Riscos". O relatório passa de 7 para 5 seções.

**Resumo Executivo — linha de KPIs**
IAP (Acurácia Ponderada por Valor) no lugar da Acurácia item a item, com a
variação do mês anterior. Baixas Operacionais em pacote (com o total do
prejuízo) no lugar de Passivos Mapeados isolado — cai para o dado nativo se o
dashboard externo não tiver sido enviado. Risco de Validade vindo do Farol de
Shelf externo (perda potencial total) — mesma lógica de fallback nativo.
Controle de Movimentados sem mudança de posição.

**Scorecard do Mês**
Linha de passivos passa a se chamar "Baixas Operacionais (Pacote)" quando o
dashboard externo existir. Controle de Movimentados ganha um status "Em
avanço" quando a tendência real de vários meses é de melhora — evita
contradizer o texto do Resumo Executivo.

**Farol de Shelf Life externo**
Reestruturado em 4 cartões (Vencidos / 0-30 / 31-60 / 61-90 dias) com o valor
exato de cada faixa, mais 3 tabelas Top-5 lado a lado. Os dois gráficos
("Risco por Almoxarifado" e "Custo por Grupo e Status") não entraram porque a
fonte só existe como SVG no HTML exportado — sem tabela ou JSON por trás, não
dava pra extrair com confiança. Isso está documentado no próprio código.

**Baixas Operacionais externo e Recuperação de Shelf**
Mesma decisão: os gráficos mensais dessas duas telas também só existem como
SVG na exportação — não foram adicionados como gráfico nativo no MBR, e o
motivo está no docstring de cada slide. O equivalente nativo já mostrado no
MBR (slide "Passivos — Evolução") ganhou um texto novo com a variação % mês a
mês.

**Dispersão de Ficha Técnica**
Novo gráfico "Tendência Financeira" (Perda × Economia × Impacto Líquido,
últimos 6 meses).

Nenhum destes itens tem crítica pendente — todos foram aprovados na rodada de
mockups. O único passo que falta é o deploy.
