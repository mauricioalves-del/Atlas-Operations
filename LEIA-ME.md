# Atlas — provável causa real de "atualizações que somem": cache do navegador/service worker

09/08/2026 (continuação da entrega anterior)

## Antes de tudo: o que eu achei

Você pediu pra eu validar por que o botão "⚙️ Perguntas padrão" (e possivelmente outras
coisas de entregas anteriores) não estavam aparecendo mesmo depois do deploy. Investigando
isso a fundo, encontrei uma causa bem concreta e bem provável — **não** era um bug na
lógica do botão em si (já tinha testado isso e continua correto), era um problema de
**cache escondendo o deploy novo**:

- Os arquivos da casca do app (`index.html`, `app.js`, `style.css`, `sw.js`) não mandavam
  NENHUM cabeçalho `Cache-Control` - só `ETag`/`Last-Modified`. Sem isso, o navegador pode
  aplicar cache por conta própria (heurístico), sem nem perguntar ao servidor se há algo
  novo.
- Só isso já seria resolvido com um Ctrl+Shift+R normalmente... MAS o Atlas também tem um
  **service worker** (`sw.js`, pra funcionar como app instalável) que assume o controle do
  carregamento da página. Ele foi desenhado pra ser "network-first" (sempre tentar a rede
  primeiro), só que o `fetch()` usado internamente por ele não pedia explicitamente pra
  ignorar o cache do navegador - então mesmo esse "sempre pega a versão mais nova" podia,
  na prática, receber uma cópia antiga do cache em vez de bater no servidor de verdade.
- Resultado possível: depois de um deploy novo, o Ctrl+Shift+R não resolve, porque quem
  está no controle do carregamento é o service worker, e ele mesmo podia estar servindo
  uma versão antiga sem perceber.

Isso bate exatamente com o padrão dos relatos: "atualizei mas não vejo a novidade".

## O que corrigi

1. `sw.js`: o `fetch()` interno agora usa `{ cache: "no-store" }` explicitamente - força
   ignorar qualquer cache do navegador e ir à rede de verdade, cumprindo o que o
   "network-first" já prometia fazer.
2. `main.py`: adicionei um middleware que manda `Cache-Control: no-cache, must-revalidate`
   em qualquer resposta que não seja de `/api/` (ou seja, na casca do app inteira). O
   navegador ainda pode aproveitar o `ETag` pra uma resposta rápida (não baixa tudo de
   novo se nada mudou), mas sempre CONSULTA o servidor primeiro - nunca responde só do
   que já tinha guardado.

Testei os dois junto com todo o resto (Playwright, servidor real): confirmei que agora
`index.html`/`app.js`/`sw.js` saem com esse cabeçalho, que `/api/...` continua sem
mudança nenhuma (dado dinâmico não deveria ser afetado mesmo), e repeti o teste completo
do login + botão de configuração de perguntas padrão + painel de pendências - tudo
continua funcionando normalmente com a correção aplicada.

**Ação recomendada pra você, uma vez só**: depois de aplicar esta atualização, se ainda
não aparecer a novidade, abra o DevTools do navegador (F12) → aba Application → Service
Workers → clique em "Unregister" no service worker do Atlas, e recarregue a página. Isso
descarta de vez qualquer versão antiga que já estava instalada ANTES desta correção
existir (a correção evita o problema daqui pra frente, mas não limpa sozinha o que já
tinha sido cacheado por um service worker antigo, já em execução no seu navegador).

## Resto desta entrega (o que já tinha sido reportado antes)

Este pacote continua trazendo tudo que já tinha sido entregue: a verificação do comando
de voz (lógica confirmada correta via teste automatizado - ver seção abaixo), o fluxo
"Atlas, Assistente" com pergunta em duas etapas, e o módulo de configuração de perguntas
padrão (botão "⚙️ Perguntas padrão", só admin). Como sempre, `backend/` e `frontend/`
vêm completos, não só os arquivos alterados.

### Comando de voz - o que já foi confirmado

Rodei o Atlas de verdade (backend + frontend reais) com automação de navegador,
simulando comandos de voz de forma determinística. A lógica de reconhecimento está
correta: "Atlas, cadastros" abre Cadastros, "Atlas, assistente" abre o assistente, sem
nenhum erro de JavaScript. Isso descarta bug de código. O que só você pode confirmar
(precisa de microfone/navegador reais):

- O ícone do microfone chega a mostrar o estado "ouvindo"?
- O texto de status muda quando você fala "Atlas, [módulo]" (mesmo que pra um erro)?
- Aparece algo em vermelho no console (F12) enquanto tenta o comando de voz?
- Acontece em qualquer navegador/computador, ou só num específico?

### "Atlas, Assistente" com pergunta em duas etapas

Diga "Atlas, Assistente", espere o convite falado terminar, e a próxima coisa que você
falar (sem repetir "Atlas") já vai direto como pergunta pro assistente. Janela de 10
segundos, testada de ponta a ponta.

### Módulo de configuração de perguntas padrão

Botão "⚙️ Perguntas padrão" no painel do Assistente Atlas, visível só pra usuários com
papel Admin. Deixa criar, editar e excluir perguntas padrão pelo próprio app (elas viram
botão de atalho e são reconhecidas por voz/texto) - sem precisar de uma sessão como esta
pra cada pergunta nova. As perguntas que já vêm prontas com o Atlas continuam fixas no
código, marcadas como "padrão do sistema" na lista (não editáveis por esta tela).

## Como aplicar

1. Substitua `backend/` e `frontend/` inteiros pelo conteúdo deste zip.
2. Reimplante no Render.
3. Recarregue o navegador (Ctrl+Shift+R). Se ainda não ver a novidade, faça o
   "Unregister" do service worker (ver instrução acima) e recarregue de novo - essa parte
   só deve ser necessária UMA vez, pra limpar o que já estava instalado antes desta
   correção.
4. Teste o comando de voz e me responda as perguntas específicas acima - é a parte que só
   dá pra confirmar no seu navegador de verdade.
5. Confirme que agora consegue ver e usar o botão "⚙️ Perguntas padrão" (logado como
   Admin) e, se ainda configurar Gmail/Slack, lembre que isso exige criar as credenciais
   OAuth e colocar como variáveis de ambiente no Render primeiro (passo a passo na entrega
   anterior) - só depois disso o botão "Conectar" aparece no painel de pendências.
