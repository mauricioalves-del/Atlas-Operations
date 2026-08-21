# atlas_fix_mbr_fase2.zip (21/08/2026)

## Antes de aplicar

Mesmo lembrete de sempre: o Atlas roda no Render, e só passa a usar código
novo depois de zip + redeploy manual. Suba este zip e refaça o deploy do
backend (mesmo processo já usado nos pacotes anteriores) antes de gerar um
MBR novo pra testar.

## O que é este pacote

Continuação do pacote anterior (`atlas_fix_mbr_grupo1.zip`) - implementa o
"Grupo 2" que tinha ficado pendente: os gráficos dos 3 dashboards externos
(Farol de Shelf-Life, Recuperação de Shelf, Baixas Operacionais) que só
existiam como gráfico SVG no arquivo exportado, sem tabela ou JSON por trás,
e por isso não entravam no MBR com número real.

Pedido do usuário: "Use os HTML anexados no atlas para alimentar o MBR igual
foi feito aqui... siga com as alterações aprovadas, respeitando as premissas
solicitadas" - usei os arquivos .html reais que você já tinha enviado nesta
conversa (exports de Farol de Shelf, Shelf Life e Baixas Operacionais, de
15/08 e 20/08) pra descobrir como extrair esses 3 gráficos de verdade, e
validei a extração contra eles antes de escrever qualquer coisa no MBR.

## O que está dentro

- `backend/app/mbr_generator.py`
- `backend/app/dashboards_externos_extrator.py`
- `backend/app/routers/divergencias_router.py` (sem mudança nesta fase -
  incluído de novo só por segurança, caso o zip do Grupo 1 ainda não tenha
  sido implantado)

## Como os 3 gráficos foram extraídos (e por que dá pra confiar no número)

**Custo Total por Grupo e Status** (Farol de Shelf-Life) não precisou de
truque nenhum: não é gráfico de verdade, é uma barra feita com `<div>`s
comuns, e cada segmento de status tem um atributo HTML (`title="Perigo:
19.64%"`) com o valor exato. Leitura direta de texto.

Os outros 3 (Risco por Almoxarifado do Farol; Evolução Mensal da Recuperação
de Shelf; Evolução Mensal do Baixas Operacionais) são gráfico SVG puro
(Recharts, sem tabela nem JSON por trás) - mas a geometria do SVG não é uma
aproximação: o Recharts calcula a posição e a altura de cada barra a partir
do valor real através de uma escala LINEAR exata. A extração faz o caminho
inverso, calibrando essa escala pelos próprios ticks do eixo do gráfico
(que trazem rótulo E posição em pixel, os dois no HTML). Validei isso
batendo a soma reconstruída contra um KPI em texto puro do MESMO arquivo, em
7 arquivos reais diferentes que você já tinha enviado - bateu exato (até
R$ 0,01) em todos:

- Farol de Shelf-Life: "Risco por Almoxarifado" reconstruído bateu com
  "Perda potencial de R$ ..." em 3 exports diferentes (R$ 87.224,19,
  R$ 84.965,86 e R$ 87.189,05).
- Recuperação de Shelf: a série "Perda" do gráfico mensal bateu com o KPI
  "Perda Real" em 2 exports diferentes.

Quando a soma reconstruída NÃO bate com o KPI de referência, a extração
descarta o resultado e o slide mostra um aviso ("não foi possível
reconstruir este gráfico neste retrato") em vez de arriscar um número
errado - nunca mostra valor fabricado.

## O que mudou no relatório

Cada um dos 3 dashboards ganhou um slide companheiro (mesmo padrão já usado
no Grupo 1 pro Painel de Inventário):

- **Farol de Shelf-Life — Risco por Almoxarifado**: 2 gráficos lado a lado
  (Risco por Almoxarifado e Custo por Grupo e Status, ambos empilhados por
  status de urgência).
- **Recuperação de Shelf — Evolução Mensal**: Perda × Receita Recuperada ×
  Saving Recuperado, mês a mês. "Saving Recuperado" só aparece a partir do
  mês em que o controle de recuperação passou a atuar - isso é o dado real
  do arquivo, não falha de extração.
- **Baixas Operacionais — Evolução Mensal**: total de baixas por mês no
  histórico completo do export, empilhado por motivo quando o export trouxer
  essa quebra. Cobre uma janela mais longa que o KPI "Prejuízo Total no
  Período" do slide anterior (que é uma janela móvel curta) - os dois
  números não baterem entre si é esperado, o slide já deixa isso explícito
  pra não parecer inconsistência.

Nos 2 gráficos empilhados com muitas séries pequenas (Risco por
Almoxarifado/Grupo, e a Evolução de Baixas quando vem quebrada por motivo),
o rótulo de valor por segmento foi desligado - com tantas séries pequenas
empilhadas ele ficava ilegível/sobreposto na inspeção visual; o eixo e a
legenda já bastam pra leitura. Esse foi um defeito real encontrado e
corrigido durante a validação desta entrega, junto com um título que
quebrava em 2 linhas e invadia o subtítulo (mesmo tipo de ajuste já feito no
pacote anterior).

## O que ainda não entrou

O 2º slide de Controle de Movimentados (Causas Confirmadas + Top 10 Ações)
continua pendente - depende de uma mudança no backend
(`dashboard_distribuicao_causas` hoje só aceita período relativo, não um mês
de fechamento exato), não de leitura de HTML. Fica pra uma próxima rodada,
se você quiser seguir com isso.

## Como foi validado

`py_compile` nos dois arquivos Python, extração testada contra os 7 arquivos
reais que você enviou nesta conversa (Farol de Shelf, Shelf Life e Baixas
Operacionais, versões de 15/08 e 20/08), geração de slide isolada com dados
reais extraídos + casos vazios/indisponíveis (sem exceção em nenhum), e
inspeção visual de cada slide gerado (detectado e corrigido: rótulo
sobreposto nos gráficos empilhados, e um título de slide quebrando em 2
linhas).
