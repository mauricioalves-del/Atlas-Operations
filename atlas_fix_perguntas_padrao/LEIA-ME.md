# Módulo de perguntas padrão do Assistente Atlas

## O que foi pedido

A partir de um caso real (você perguntou "Qual almoxarifado representa um risco" e o
assistente respondeu corretamente, mas só com dados agregados do Atlas inteiro, sem
quebrar por almoxarifado), você pediu um "módulo padrão" que:

- Já venha com perguntas padronizadas dentro do Atlas;
- Dê à IA um "norte" de onde buscar a informação pra cada tipo de pergunta;
- Traga respostas mais rápidas e embasadas em perguntas mais específicas;
- Continue extensível, pra você (ou eu, depois) acrescentar novas perguntas padrão sem
  reescrever a lógica de novo.

## Como funciona

Foi criado um catálogo único de "perguntas padrão" (`app/assistente_perguntas_padrao.py`),
com 4 entradas hoje:

1. **Resumo do dia**
2. **Motivos mais recorrentes de divergência**
3. **Riscos pro negócio** (visão agregada, Atlas inteiro)
4. **Qual almoxarifado representa mais risco?** (a pergunta nova, quebrada por almoxarifado)

Quando você pergunta algo pro assistente (por voz ou digitando), o Atlas primeiro compara
o texto contra os "gatilhos" de cada entrada do catálogo (comparação simples de texto, sem
acento/maiúscula - **sem gastar uma segunda chamada de IA generativa pra isso**, então o
custo continua em 1 chamada por pergunta, igual já era). Se bater com uma entrada:

- Quando ela tiver uma função de detalhamento extra (hoje, só a de "risco por
  almoxarifado" tem), o Atlas calcula um bloco de dados mais específico e anexa ao
  retrato que a IA recebe - só pra ESSA pergunta, sem deixar o retrato das outras
  perguntas mais pesado/lento.
- A IA também recebe uma instrução extra dizendo onde focar a resposta.

### O detalhamento por almoxarifado, especificamente

Pra "qual almoxarifado representa mais risco", o Atlas agora calcula, quebrado por
almoxarifado:

- Divergências abertas (top 5 almoxarifados);
- Risco de validade (Shelf Life) - valor estimado em risco;
- Risco de obsolescência (baixo giro) - valor estimado em risco;
- Quebras de FEFO por almoxarifado de destino.

De propósito, o Atlas **não combina esses 4 números numa única "pontuação de risco por
almoxarifado"** - inventar um peso entre divergência/validade/obsolescência/FEFO seria um
dado fabricado, não calculado. Em vez disso, a IA recebe os 4 blocos separados e a
instrução de apontar o(s) almoxarifado(s) que aparecem repetidamente no topo de mais de um
bloco (o sinal mais forte de risco concentrado), e de citar os blocos separadamente se
nada se repetir.

Cada um desses 4 blocos é calculado de forma isolada: se um deles falhar (ex: uma tabela
ainda vazia), os outros 3 continuam aparecendo normalmente - mesmo padrão de resiliência
já usado no retrato geral do assistente.

## Os botões de pergunta rápida agora vêm do mesmo catálogo

Os 3 botões que já existiam na tela Início ("Resumo do dia", "Motivos mais recorrentes de
divergência", "Riscos pro negócio") + o novo botão "Qual almoxarifado representa mais
risco?" não estão mais fixos no HTML - eles são buscados do backend
(`GET /assistente/perguntas-padrao`), que lê direto do mesmo catálogo usado pra identificar
a pergunta. Ou seja: o catálogo é a única fonte de verdade, tanto pro roteamento quanto
pros botões - não tem risco de os dois ficarem desincronizados.

## Como adicionar uma pergunta padrão nova, no futuro

Só é preciso editar `app/assistente_perguntas_padrao.py`:

1. Acrescentar uma entrada em `PERGUNTAS_PADRAO` com `chave`, `rotulo`, `pergunta`,
   `gatilhos` (as variações de frase que devem reconhecer essa pergunta) e
   `instrucao_extra` (o que a IA deve focar).
2. Se a pergunta precisar de um detalhamento de dados mais específico que o retrato geral
   já não cobre, escrever uma função `_contexto_de_algo(db, usuario)` e apontar em
   `contexto_extra_fn`. Se não precisar, deixar `contexto_extra_fn: None` - a pergunta
   ainda é reconhecida e ganha a `instrucao_extra`, só não ganha um bloco de dados extra.
3. O botão na tela Início aparece automaticamente (não precisa tocar no frontend).

## Um ajuste feito durante os testes

Ao testar variações de frase, encontrei um caso de ambiguidade: uma pergunta como "qual
almoxarifado tem mais risco pro negócio?" batia nos gatilhos de DUAS perguntas padrão (a
"Riscos pro negócio" genérica E a nova "por almoxarifado"), e a ordem do catálogo fazia a
pergunta cair na resposta genérica, mesmo mencionando "almoxarifado" explicitamente. Corrigi
colocando a entrada "por almoxarifado" antes da genérica no catálogo (com um comentário
explicando o porquê, pra não ser desfeito por acidente depois) e escrevi um teste
automatizado cobrindo esse caso específico, pra garantir que continue funcionando certo se o
catálogo crescer.

## O que foi testado antes de entregar

- Reconhecimento de pergunta padrão (`identificar_pergunta_padrao`) pra 9 variações de
  frase, incluindo a frase exata do seu print de tela e o caso de ambiguidade acima.
- Cálculo do detalhamento por almoxarifado com dados de teste (divergências, obsolescência,
  Shelf Life e FEFO concentrados de propósito num almoxarifado, pra confirmar que ele
  aparece corretamente no topo de cada bloco).
- O endpoint `POST /assistente/perguntar` de ponta a ponta (login real, banco de teste
  isolado, chamada à IA simulada) - confirmando que o prompt enviado à IA realmente inclui
  o detalhamento extra e a instrução extra quando a pergunta bate com uma entrada padrão,
  e que NÃO inclui nada disso quando a pergunta é genérica (evitando prompt maior/mais
  lento sem necessidade).
- O novo endpoint `GET /assistente/perguntas-padrao`.
- Resiliência: simulei uma falha no cálculo de Shelf Life e confirmei que os outros 3
  blocos do detalhamento continuam aparecendo normalmente.

## Arquivos alterados/criados

- `backend/app/assistente_perguntas_padrao.py` — **novo**: catálogo de perguntas padrão,
  reconhecimento de pergunta e cálculo do detalhamento por almoxarifado.
- `backend/app/assistente_ia.py` — `montar_contexto()` e `responder_pergunta_assistente()`
  agora aceitam um `pergunta_padrao` opcional, pra anexar o detalhamento extra e a
  instrução extra quando houver uma pergunta padrão identificada.
- `backend/app/routers/assistente_router.py` — o endpoint `POST /assistente/perguntar`
  agora identifica a pergunta padrão antes de montar o retrato; novo endpoint
  `GET /assistente/perguntas-padrao`.
- `frontend/index.html` — os 3 botões fixos de pergunta rápida foram substituídos por um
  container vazio, preenchido dinamicamente; `app.js?v=97` (era `v=96`).
- `frontend/app.js` — nova função `carregarPerguntasPadraoAssistente()`, chamada de dentro
  de `mostrarApp()` (depois do login).

## Como aplicar

Substitua os arquivos correspondentes no seu repositório (mesma estrutura de pastas do
zip) e faça o commit/push de costume pro Render redesenhar o deploy. **Nenhuma migração de
banco é necessária** - essa mudança não toca no schema, só em lógica/rotas/frontend.
