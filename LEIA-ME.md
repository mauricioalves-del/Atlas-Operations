# Atlas — correção do motor de investigação (baixas operacionais ignoradas)

20/08/2026 (atualizado no mesmo dia: conciliação por quantidade, não mais por data)

## Atualização: conciliação por Almoxarifado x Item x Quantidade

Depois da primeira correção abaixo, você testou de novo (divergência #3198) e o aviso de
baixa pendente continuava não aparecendo — e você foi direto ao ponto: a conciliação
precisa considerar **Almoxarifado x Item x Quantidade**, verificando se a diferença tem
correlação com a baixa pendente, **desconsiderando aprovadas e reprovadas** nessa análise
específica.

Você estava certo, e o motivo era outro bug de precisão, não falta de dados: a primeira
versão da correção casava a baixa pendente com a divergência usando uma **janela de
poucos dias de tolerância de data** (o mesmo critério usado pra resolver automaticamente
com uma baixa já aprovada). Baixas pendentes, principalmente as de padrão "semanal", são
solicitadas ou aprovadas em lote bem depois do dia em que a diferença foi detectada — e
se a data não batesse dentro dessa janela curta, a baixa pendente simplesmente não era
considerada, mesmo existindo e sendo do SKU/Almoxarifado certo.

**Correção**: criei `calcular_correlacao_baixas_pendentes` (`app/baixas_operacionais.py`),
que agora soma TODAS as baixas com status `PENDENTE` do mesmo SKU + Almoxarifado (sem
olhar pra data) e compara essa soma com o tamanho da divergência:

- Diferença de até 20% → correlação forte ("compatível").
- Diferença entre 20% e 50% → correlação mais fraca, mas ainda mostrada ("parcialmente
  compatível") — ainda vale seu julgamento, não escondo isso.
- Diferença acima de 50% → trato como "não relacionado" e não mostro nada (uma baixa
  pendente de 4 unidades não deveria sugerir que explica uma falta de 400).
- **Aprovadas e reprovadas nunca entram nessa soma** — aprovadas já têm o caminho próprio
  de resolução automática (explicado abaixo); reprovadas nunca deveriam influenciar nada.
- Uma divergência de SOBRA (contagem física maior que o sistema) nunca correlaciona com
  baixa pendente nenhuma — baixa é sempre saída de estoque, não explicaria uma sobra.

Isso agora aparece tanto como evidência no motor de regras quanto no aviso da tela (lista
e detalhe), e a mensagem já diz se é "compatível" ou "parcialmente compatível", com os
números da soma e da divergência lado a lado.

## O problema original que você reportou

Na divergência #3201 (SKU 05004097), o motor apontou "Baixa Semanal de Avarias" como
causa, com 100% de confiança no motor de regras — mas essa baixa não existia de fato
para este caso. Você identificou corretamente a causa: **o motor não estava avaliando
as baixas operacionais (pendentes ou aprovadas) do sistema de baixas para montar a
hipótese.**

## O que eu encontrei

Investigando o código, achei um bug real, não só uma questão de calibragem. O módulo
`app/baixas_operacionais.py` já tinha, desde a integração original com o sistema de
baixas, duas funções prontas para exatamente esse propósito:

- `buscar_baixa_compativel` — deveria ser chamada pelo motor de investigação para
  procurar uma baixa (pendente ou aprovada) compatível com o SKU/almoxarifado da
  divergência.
- `buscar_avisos_baixa_pendente` — deveria preencher um aviso na tela quando existisse
  uma baixa pendente de aprovação.

**Nenhuma das duas nunca foi chamada por nenhum outro lugar do código.** O comentário no
próprio módulo já descrevia esse comportamento como existente — mas ele nunca foi
conectado. Na prática, o motor de investigação só tinha acesso a sinais indiretos
(transferência pendente, pedido de compra, OP aberta, faturamento próximo, e
reincidência histórica) — nunca ao registro real de uma baixa. No caso #3201,
provavelmente o que aconteceu foi isto: um caso anterior deste mesmo SKU já tinha sido
resolvido como "Baixa Semanal de Avarias" no passado, e a única evidência que bateu
desta vez foi a reincidência (peso baixo, mas como foi a ÚNICA evidência encontrada, a
normalização do motor mostrou 100% de confiança — um problema de leitura do painel que
também vale registrar: "100%" ali significa "só uma hipótese teve qualquer evidência",
não necessariamente "tenho certeza disso").

## O que foi corrigido (visão completa, já com a atualização acima)

1. **O motor de investigação (`app/investigation.py`) agora consulta de verdade as
   baixas operacionais**, em dois caminhos diferentes e complementares:
   - Baixa **APROVADA** compatível (SKU + Almoxarifado + janela de data, porque aqui a
     data ainda importa - é uma ação definitiva): entra como a evidência mais forte do
     motor inteiro **e resolve a divergência automaticamente** - documento real já
     decidido, não faz sentido tratar como "mais uma hipótese concorrendo".
   - Baixas **PENDENTES** compatíveis (Almoxarifado x Item x soma de Quantidade, SEM
     janela de data - ver seção acima): entram como evidência (forte se a correlação for
     boa, mais fraca se for só parcial), mas **nunca resolvem nada sozinhas** - ainda
     podem ser reprovadas. Reprovadas nunca entram nessa conta.
   - Se não existir nenhuma correlação plausível (como era o caso real do #3201), essa
     evidência simplesmente não aparece — o motor cai de volta nos outros sinais, sem
     inventar uma baixa que não existe.

2. **A tela de divergências agora avisa quando há correlação com baixa pendente.** Tanto
   na lista quanto no detalhe de cada divergência: um ícone 🕒 na lista (ao lado do SKU,
   com o texto completo no hover) e um aviso no painel "Diagnóstico" do detalhe, dizendo
   quantas baixas, qual motivo, quem solicitou, a soma de quantidade, e se é compatível
   ou só parcialmente compatível com esta divergência.

## O que eu testei

Rodei o backend real (FastAPI TestClient) contra oito cenários controlados, batendo
diretamente nos mesmos endpoints que o frontend usa:

- **Baixa pendente com data bem distante da divergência, mas quantidade exata**: agora
  aparece corretamente (esse era exatamente o caso do #3198 - a correlação por data
  escondia isso antes).
- **Correlação parcial (diferença de ~43%)**: aparece como "parcialmente compatível",
  não desaparece nem finge ser 100% seguro.
- **Quantidade muito diferente (diferença > 50%)**: fica em silêncio de propósito, pra
  não sugerir uma correlação que não se sustenta.
- **Múltiplas baixas pendentes pequenas somando o valor certo**: a soma é usada
  corretamente (padrão "baixa semanal" em vários lançamentos pequenos).
- **Divergência de SOBRA**: nunca correlaciona com baixa pendente nenhuma, mesmo
  existindo uma baixa com quantidade idêntica.
- **Só existe uma baixa REPROVADA**: é completamente ignorada, como pedido.
- **Baixa aprovada compatível** (regressão): continua resolvendo a divergência
  automaticamente, com hipótese confirmada e responsável certos.
- **Nenhuma baixa em nenhum status**: comportamento idêntico ao de antes de toda essa
  correção — sem evidência nova, sem regressão nos outros sinais (transferência
  pendente, pedido de compra, ficha técnica, faturamento, reincidência, erro
  operacional).

## Como aplicar

Substitua `backend/` e `frontend/` inteiros pelo conteúdo deste zip, reimplante, e
recarregue o navegador (se aparecer algo desatualizado mesmo depois de reimplantar, veja
a instrução de remover o service worker antigo na entrega anterior).

## Vale conversarmos também

Três coisas que encontrei no caminho e que valem uma decisão sua, não mudei nada nelas
agora:

- **Os limites de 20% (correlação forte) e 50% (silêncio total) na conciliação por
  quantidade são um ponto de partida razoável, não um número calibrado com seus dados
  reais.** Se você notar muitos casos "parcialmente compatível" que na prática deveriam
  contar como fortes (ou vice-versa), ou casos que deveriam aparecer e não aparecem por
  ficarem pouco acima de 50%, me diga que ajusto esses dois números
  (`TOLERANCIA_CORRELACAO_QUANTIDADE` e `TOLERANCIA_CORRELACAO_QUANTIDADE_PESO_CHEIO`,
  em `app/baixas_operacionais.py`) — é uma mudança de uma linha cada.
- **O "100%" de confiança do motor de regras pode ser enganoso quando só uma hipótese
  tem qualquer evidência** (mesmo uma evidência fraca, como reincidência). Isso é uma
  característica de como a confiança é calculada (normalização sobre o total de scores),
  não um bug pontual — mudar isso afeta a confiança mostrada em toda divergência do
  sistema, então prefiro entender com você se isso é importante de ajustar antes de
  tocar nisso.
- **Reinvestigar agora pode resolver uma divergência automaticamente** se, entre a
  criação do caso e o clique em "Reinvestigar", uma baixa aprovada compatível apareceu no
  sistema. Isso é o comportamento correto (documento real disponível = caso resolvido),
  mas é uma mudança de comportamento em relação a antes (onde "Reinvestigar" nunca mudava
  o status). Se isso te incomodar em algum fluxo, me avise que ajusto.
