# Atlas — correção do motor de investigação (baixas operacionais ignoradas)

20/08/2026

## O problema que você reportou

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

## O que foi corrigido

1. **O motor de investigação (`app/investigation.py`) agora consulta de verdade as
   baixas operacionais.** Para cada divergência, ele procura uma baixa do sistema
   Lovable (Avaria, Vencimento, Descarte, Degustação, Cortesia, Perda/Furto, Uso e
   Consumo, Envio/Laboratório, Sensorial/Inovações) compatível por SKU + almoxarifado +
   janela de data, que ainda não tenha sido vinculada a nenhuma outra divergência:
   - Se a baixa já estiver **aprovada**, ela entra como a evidência mais forte do motor
     inteiro (peso bem acima do normal) **e a divergência é resolvida automaticamente**
     — é um documento real já decidido, não faz sentido deixar isso só como "mais uma
     hipótese concorrendo".
   - Se a baixa ainda estiver **pendente** de aprovação, ela entra como evidência forte
     (mais forte que reincidência, mas sem resolver nada sozinha, porque ainda pode ser
     reprovada).
   - Se não existir nenhuma baixa compatível (como era o caso real do #3201), essa
     evidência simplesmente não aparece — o motor cai de volta nos outros sinais, sem
     inventar uma baixa que não existe.

2. **A tela de divergências agora avisa quando há uma baixa pendente.** Tanto na lista
   quanto no detalhe de cada divergência: um ícone 🕒 na lista (ao lado do SKU, com o
   texto completo no hover) e um aviso no painel "Diagnóstico" do detalhe, dizendo qual
   baixa está pendente, quem solicitou, e que ela ainda pode ser reprovada.

## O que eu testei

Rodei o backend real (FastAPI TestClient) contra três cenários controlados, batendo
diretamente nos mesmos endpoints que o frontend usa:

- **Baixa pendente compatível**: a divergência continuou "Aberta" (não resolve sozinha),
  a evidência nova apareceu corretamente, a hipótese do motor de regras passou a refletir
  o motivo real da baixa (não mais só reincidência), e o aviso apareceu tanto na listagem
  quanto no detalhe.
- **Baixa aprovada compatível**: a divergência foi resolvida automaticamente, com a
  hipótese confirmada, solução e responsável certos, e a baixa ficou vinculada a essa
  divergência (não pode ser reusada em outra).
- **Nenhuma baixa compatível**: comportamento idêntico ao de antes da correção — sem
  evidência nova, sem regressão nos outros sinais (transferência pendente, pedido de
  compra, ficha técnica, faturamento, reincidência, erro operacional).

## Como aplicar

Substitua `backend/` e `frontend/` inteiros pelo conteúdo deste zip, reimplante, e
recarregue o navegador (se aparecer algo desatualizado mesmo depois de reimplantar, veja
a instrução de remover o service worker antigo na entrega anterior).

## Vale conversarmos também

Duas coisas que encontrei no caminho e que valem uma decisão sua, não mudei nada nelas
agora:

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
