# Atlas — Assistente por voz na tela Início (resumo do dia, dúvidas, navegação)

## O que você pediu

No módulo Início, com a IA já disponível, você quer usar o comando de voz
que o Atlas já tem pra fazer perguntas abertas — por exemplo "Resumo do
dia" trazendo um panorama do que foi feito/está planejado, dúvidas como
"quais os motivos mais recorrentes de divergência" e riscos pro negócio, e
ajuda pra encontrar onde alguma informação específica está no sistema.

## O que já existia (reaproveitado, não recriado)

O Atlas já tinha um comando de voz contínuo no hub: diga **"Atlas,
[módulo]"** em qualquer tela (ex: "Atlas, cadastro") e ele navega pra lá —
com efeito sonoro de "pensando", uma voz sintetizada em português e tudo.
Antes, se você dissesse "Atlas" seguido de algo que **não** era o nome de
um módulo, ele só respondia "não reconheci". Isso é exatamente o gancho
que foi usado agora.

## O que foi adicionado

Quando "Atlas, ..." não bate com nenhum módulo conhecido, em vez de dizer
"não reconheci", o Atlas agora manda essa frase pro **assistente por IA
generativa** (o mesmo Gemini já integrado na entrega anterior) — que
responde, e a resposta é **falada em voz alta** pelo mesmo motor de voz que
já existia, além de aparecer escrita na tela. Cobre os três usos que você
descreveu:

1. **"Resumo do dia"** — panorama do que já foi feito hoje (divergências
   detectadas e resolvidas, baixas aprovadas, fechamentos de inventário
   processados) e do que está planejado/pendente (ações de acompanhamento
   pós-inventário em aberto e atrasadas).
2. **Dúvidas de dados** — "quais os motivos mais recorrentes de
   divergência" (calculado dos últimos 90 dias), "quais os principais
   riscos pro negócio agora" (cruza passivo de baixas pendentes, risco de
   obsolescência por baixo giro, risco de validade/Shelf Life e quebras de
   FEFO — os MESMOS números que já alimentam o painel "Mapa de Demandas de
   Gestão" da própria tela Início).
3. **"Onde encontro X"** — o assistente conhece a lista de módulos do
   Atlas e o que cada um mostra, e indica pra onde ir quando a pergunta é
   sobre algo que não está no panorama que ele já tem em mãos.

Também tem um jeito **sem usar voz**: um painel novo na tela Início
("✨ Assistente Atlas") com 3 botões de pergunta rápida (Resumo do dia /
Motivos mais recorrentes / Riscos pro negócio) e um campo de texto pra
perguntar qualquer outra coisa — útil se o microfone não estiver disponível
ou se você preferir digitar.

## Como funciona por dentro (pra você entender o que a IA vê e não vê)

A IA generativa **nunca consulta o banco de dados direto**. O Atlas monta
primeiro um "retrato" com números já calculados (as mesmas funções que já
alimentam outras telas — Mapa de Demandas, dashboards de FEFO/Shelf Life —
mais contagens de hoje e o ranking dos motivos de divergência mais
recorrentes) e manda esse retrato JUNTO com sua pergunta pra IA. Ou seja:
a IA só traduz/organiza números que o próprio Atlas já calculou — ela não
tem acesso a nada além disso, então não tem como "inventar" um dado que
não exista. Se você perguntar algo fora desse retrato, o assistente admite
que não tem esse dado à mão e indica em qual tela você provavelmente
encontra a resposta, em vez de arriscar um palpite.

Cada bloco do retrato (divergências, baixas, riscos etc.) é calculado de
forma isolada — se um deles falhar por algum motivo, os outros continuam
aparecendo normalmente (testei isso simulando uma falha de propósito).

**Sobre restrição por almoxarifado** (usuários com acesso restrito a
alguns almoxarifados): os números de divergências/baixas de hoje e os
motivos mais recorrentes já respeitam essa restrição. Os números de risco
(obsolescência, Shelf Life, FEFO, passivo pendente) reaproveitados do Mapa
de Demandas **não filtram por almoxarifado** — mas essa é uma limitação que
já existe hoje na própria tela Início, não algo introduzido agora; corrigir
isso é uma mudança maior, em vários módulos, fora do escopo deste pedido.

**Sobre permissão de uso**: qualquer usuário logado pode perguntar
(diferente da análise de baixas/divergências da entrega anterior, que é só
pra admin/analista) — faz sentido aqui porque perguntar não altera nada no
sistema, só ajuda a encontrar informação. Toda pergunta é registrada na
Auditoria (ação `assistente_pergunta`), então dá pra ver quem perguntou o
quê.

**Não precisa de configuração nova**: usa a mesma chave
`ATLAS_IA_GENERATIVA_API_KEY` que você já configurou (ou vai configurar) no
Render, da entrega anterior. Sem essa chave, o assistente responde com uma
mensagem clara ("IA generativa não configurada") em vez de dar erro feio.

## Validado

- Testei `montar_contexto()` isoladamente com dados semeados (divergências
  de hoje, resolvidas hoje, motivo recorrente, baixa aprovada hoje,
  fechamento criado hoje, ação pós-inventário atrasada) e confirmei que
  cada número bate exatamente com o esperado.
- Testei o endpoint completo (`POST /assistente/perguntar`) via API real:
  sem chave configurada (503, mensagem clara), pergunta vazia (400), com
  chave (mock) respondendo "Resumo do dia" e uma pergunta de navegação,
  registro na Auditoria, e que o papel "leitura" também consegue perguntar
  (diferente da análise de baixas, que é só admin/analista).
- Confirmei, pelo mock da chamada à IA, que o prompt enviado realmente leva
  o retrato completo (inclusive o motivo mais recorrente calculado) E a
  lista de módulos, e que pede texto livre (não JSON) — apropriado pra ser
  falado em voz alta.
- Testei a resiliência: forcei um erro de propósito num dos blocos do
  retrato e confirmei que os outros blocos continuam calculados
  normalmente, sem derrubar o assistente inteiro.
- Validei a sintaxe do JavaScript (`node --check`) e do HTML novo (parser
  HTML), e bumpei a versão do `app.js?v=96` no `index.html` pra garantir
  que o navegador carregue a versão nova depois do deploy (cache-busting).

**O que eu não pude testar**: uma resposta real do Gemini (mesma
observação da entrega anterior — depende da sua chave), e o reconhecimento
de voz do navegador em si (webkitSpeechRecognition só existe dentro de um
navegador de verdade, não no ambiente onde rodo os testes) — mas essa parte
do código não foi alterada, só o que acontece quando ela NÃO reconhece um
módulo.

## Arquivos alterados/criados

- `backend/app/assistente_ia.py` **(novo)** — monta o retrato do estado
  atual do Atlas e o prompt pro assistente responder.
- `backend/app/ia_generativa.py` — `_chamar_gemini` ganhou um parâmetro
  `esperar_json` (o assistente pede texto livre, as duas integrações
  anteriores continuam pedindo JSON estruturado, sem mudança de
  comportamento pra elas).
- `backend/app/routers/assistente_router.py` **(novo)** — endpoint
  `POST /assistente/perguntar`.
- `backend/app/main.py` — registra o novo router.
- `frontend/app.js` — comando de voz sem módulo reconhecido agora pergunta
  ao assistente (em vez de só dizer "não reconheci"); painel novo
  "Assistente Atlas" com botões de pergunta rápida + campo de texto.
- `frontend/index.html` — markup do painel novo; `app.js?v=96` (cache-busting).

Nenhuma migração de banco necessária (nenhum campo novo em modelo
existente nesta entrega).
