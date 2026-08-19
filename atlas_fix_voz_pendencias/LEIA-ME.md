# Comando de voz, apresentação sob demanda, atalho do assistente, pendências de Gmail/Slack e saudação personalizada

## 1. Por que o comando de voz não estava funcionando

Encontrei a causa mais provável revendo o código: toda vez que uma tela abria (inclusive
por clique normal, não só por voz), o Atlas narrava automaticamente uma "apresentação do
módulo" em voz alta (`apresentarModuloSeNecessario`, chamada de dentro de `mostrarView()`).
O problema é que o microfone do comando de voz contínuo NUNCA parava de escutar enquanto
isso acontecia - então a própria voz do Atlas, saindo pelo alto-falante, era captada de
volta pelo microfone e podia ser interpretada como um comando novo (ou pelo menos
atrapalhava o reconhecimento de verdade, competindo com o áudio real de quem estava
falando). O mesmo valia pras respostas faladas do assistente.

**Duas correções, uma delas é exatamente o que você pediu:**

1. **A apresentação automática foi removida.** Agora ela só toca quando pedida - um botão
   de áudio (🔊) fixo no topo da barra lateral (ao lado do nome "Atlas"), que narra a
   apresentação do módulo em que você está (ou a saudação personalizada, se estiver na
   tela Início).
2. **Trava de microfone durante a fala do Atlas** (correção técnica adicional, não pedida
   explicitamente mas necessária pra resolver "o comando de voz não funciona" de verdade):
   enquanto o Atlas está falando qualquer coisa (apresentação, saudação, resposta do
   assistente), o reconhecimento de voz contínuo ignora tudo que capta, com uma folga de
   700ms depois do fim da fala (a latência do reconhecimento não é instantânea). Isso evita
   que a própria voz do Atlas vire um comando por engano.

Não consigo simular um microfone/alto-falante reais neste ambiente pra confirmar 100% que
era exatamente isso (não tenho acesso a um navegador com áudio de verdade aqui) - mas essa
é a explicação mais consistente com o comportamento observado e com o pedido que você já
fez ("ao invés de criar uma apresentação em todas as telas..."). Se depois de aplicar isso
o comando de voz ainda tiver problema, me diga exatamente o que acontece (nada é
reconhecido? reconhece errado? aparece algum erro na tela?) que eu continuo investigando.

## 2. Botão de áudio no topo (em vez de apresentação automática)

Fica sempre visível, em qualquer tela, ao lado do nome "Atlas" na barra lateral. Clique
pra ouvir a apresentação do módulo atual - ou a saudação personalizada, se estiver na tela
Início. Pode clicar quantas vezes quiser (antes só tocava 1 vez por sessão).

## 3. Gatilho de voz "Atlas, Assistente"

Diga "Atlas, Assistente" (ou variações: "abrir assistente", "abra o assistente", "falar
com o assistente") em qualquer tela - o Atlas abre a tela Início (se não estiver nela), rola
até o painel do Assistente Atlas, foca o campo de pergunta e fala um convite curto ("Pois
não. Pode perguntar."). Assim você não precisa navegar manualmente até lá.

## 4. Pendências de Gmail e Slack ("duas palmas")

Novo painel "📋 Pendências (Gmail + Slack)" na tela Início. Cada pessoa conecta a PRÓPRIA
conta (não é uma conexão única sua que todo mundo usa) - confirmando o que você escolheu
nas perguntas de esclarecimento.

**O que conta como pendência:**
- Gmail: e-mails não lidos da caixa de entrada.
- Slack: mensagens diretas (DM/grupo) não lidas + menções recentes.

**Duas formas de acionar, como você pediu:**
- Bater duas palmas perto do microfone (detector de áudio simples, baseado em volume).
- Clicar no botão "👏 Ver pendências agora" (sempre confiável).

O Atlas responde com a lista (com links pra abrir cada e-mail/conversa direto no Gmail/
Slack) e fala um resumo rápido em voz alta ("Você tem 3 e-mails e 2 mensagens do Slack
pendentes").

### Sobre a confiabilidade das "duas palmas"

Isso é uma heurística de volume (não é câmera nem IA de áudio sofisticada): mede o volume
do microfone continuamente, calibra um "piso de ruído" que se ajusta devagar ao ambiente, e
dispara quando detecta exatamente 2 picos de volume separados por 120ms-900ms (uma palma
dupla típica). Isso PODE falhar em ambientes barulhentos (chão de fábrica, conversas por
perto, ar-condicionado forte) - tanto não detectando as palmas de verdade quanto, mais raro,
disparando com um ruído parecido. **Por isso o botão "Ver pendências agora" está sempre lá
como alternativa confiável.** Eu não tenho como testar palmas de verdade neste ambiente (não
tenho microfone real aqui) - preciso que você calibre/valide isso ao vivo. Se o gatilho
estiver muito sensível ou pouco sensível, me avise que ajusto as constantes
`INTERVALO_MIN_MS`/`INTERVALO_MAX_MS`/o multiplicador do piso de ruído em
`configurarDetectorDePalmas()` (app.js).

### Como configurar (Google Cloud + Slack App - você mesmo precisa criar, pelas mesmas
razões de segurança que me impedem de criar a chave do Gemini por você)

**Google (Gmail):**
1. Acesse https://console.cloud.google.com/apis/credentials, crie um projeto (se não tiver
   um) e um "OAuth client ID" do tipo "Web application".
2. Em "Authorized redirect URIs", adicione: `https://SEU-ATLAS.onrender.com/api/integracoes-pessoais/google/callback`
   (troque pela URL real do seu Atlas no Render).
3. Na tela de consentimento OAuth ("OAuth consent screen"), como o app provavelmente vai
   ficar em modo "Testing" (não precisa passar pela verificação do Google pra uso interno
   da empresa), adicione cada e-mail que for conectar como "Test user" - senão o Google
   recusa o login com "app não verificado".
4. Configure no Render (Environment):
   - `ATLAS_GOOGLE_CLIENT_ID`
   - `ATLAS_GOOGLE_CLIENT_SECRET`
   - `ATLAS_GOOGLE_REDIRECT_URI` (a mesma URL do passo 2)

**Slack:**
1. Acesse https://api.slack.com/apps → "Create New App" → "From scratch".
2. Em "OAuth & Permissions", adicione em "Redirect URLs":
   `https://SEU-ATLAS.onrender.com/api/integracoes-pessoais/slack/callback`.
3. Ainda em "OAuth & Permissions", em **"User Token Scopes"** (não "Bot Token Scopes" -
   precisa ser escopo de USUÁRIO, pra ler como a própria pessoa, não como um bot), adicione:
   `im:read`, `mpim:read`, `search:read`.
4. Configure no Render:
   - `ATLAS_SLACK_CLIENT_ID`
   - `ATLAS_SLACK_CLIENT_SECRET`
   - `ATLAS_SLACK_REDIRECT_URI` (a mesma URL do passo 2)

Sem essas variáveis, os botões de "Conectar" aparecem mas devolvem um aviso claro (503) -
não quebra nada, só fica indisponível até você configurar. **Nenhuma migração manual de
banco é necessária** - as colunas novas de usuário são criadas automaticamente no próximo
deploy (mesmo mecanismo de auto-migração já usado no resto do Atlas).

### Uma limitação da própria API do Slack (importante)

"Menções não lidas" não é um conceito que a API pública do Slack expõe de forma confiável
pra apps de terceiros (isso existe de verdade só dentro do próprio app oficial do Slack).
O que o Atlas mostra em "menções recentes" é uma BUSCA pelas menções mais recentes ao seu
usuário (via `search.messages`), não uma lista garantidamente só das não lidas - por isso o
rótulo diz "recentes", não "não lidas". Já as mensagens diretas (DM) SÃO precisas: a API do
Slack tem um contador de não lidas confiável pra essas.

## 5. Saudação personalizada com cotação de dólar e cacau

Ao logar, o Atlas agora mostra (em texto, na tela Início) e fala em voz alta algo como:

> "Olá, senhor Maurício, seja bem-vindo ao Atlas, o modelo de gestão de controle de estoque
> da Magio Chocolates. Hoje é quarta-feira, 19 de agosto de 2026. A cotação do dólar está
> em 5,43 reais, e o cacau está por volta de 7.890 dólares por tonelada. O que deseja?"

**Uma decisão de design que eu tomei e quero deixar clara:** a saudação toca automaticamente
só **1 vez, no login** (não repete a cada troca de tela) - é exatamente o tipo de narração
automática que você pediu pra remover das telas, só que aqui, uma única vez no início, ela
cumpre o papel de "atendimento personalizado" que você descreveu, sem cair no mesmo problema
de interromper toda navegação. Se preferir que ela NUNCA toque sozinha (só pelo botão de
áudio, igual ao resto), é uma linha pra remover em `mostrarApp()` (app.js) - me avise que eu
ajusto.

**Sobre as fontes de cotação - preciso ser honesto sobre uma limitação desta entrega:** as
ferramentas de busca na web não estavam disponíveis nesta sessão (nem pra pesquisar qual API
gratuita de cacau é mais estável hoje, nem pra testar as URLs ao vivo - o ambiente onde
processei isso bloqueia conexões de saída pra domínios eu não consegui nem simular a
chamada real por aqui). Escolhi duas fontes públicas, gratuitas, sem necessidade de chave
nem cartão de crédito, bem conhecidas da comunidade:

- **Dólar**: AwesomeAPI (`economia.awesomeapi.com.br`) - serviço brasileiro gratuito, muito
  usado em projetos pequenos/médios (não é o Banco Central oficial/PTAX, mas é próximo do
  câmbio comercial em tempo real).
- **Cacau**: endpoint NÃO OFICIAL do Yahoo Finance (ticker `CC=F`, futuros ICE de cacau) -
  não documentado oficialmente pelo Yahoo, mas usado informalmente há anos em projetos
  hobby/pequenos por não exigir chave.

Ambas seguem o mesmo princípio de resiliência do resto do Atlas: se uma fonte falhar ou
mudar de formato, a cotação correspondente simplesmente some da frase (em vez de quebrar a
saudação ou travar o login). **Preciso que você teste isso ao vivo depois do deploy** - se
qualquer uma das duas cotações aparecer sempre "indisponível", me avise que eu troco a fonte
(ex: Banco Central/PTAX pro dólar, ou uma API paga com chave gratuita tipo Alpha Vantage/
Twelve Data pro cacau, se a do Yahoo parar de funcionar).

## O que foi testado antes de entregar

- Todos os arquivos Python (sintaxe + import da aplicação completa).
- `app.js` (sintaxe via `node --check`) e `index.html` (parser HTML, sem erros).
- **Migração de banco**: simulei um banco "de produção" com o schema ANTIGO (sem as
  colunas novas de Gmail/Slack) e depois liguei o código NOVO por cima - confirmei que a
  migração automática cria as colunas certas, sem quebrar o boot nem perder dados
  existentes (mesma técnica de verificação usada nos bugs de deploy anteriores).
- **Fluxo OAuth completo (mockado)**: conectar Google (com e sem credenciais configuradas
  no servidor), callback com state válido/inválido, status refletindo a conexão,
  desconectar, e o mesmo pro Slack.
- **Resiliência de `/pendencias`**: uma falha no Gmail (ex: token expirado) não derruba a
  resposta - o Slack continua aparecendo normalmente, e vice-versa.
- **Cotações**: fontes mockadas retornando sucesso, cache funcionando (não bate na API de
  novo dentro do TTL de 30 min), e resiliência (uma fonte falhar não afeta a outra).

## O que eu NÃO consegui testar (e por quê) - preciso da sua validação ao vivo

- **O comando de voz em si e a trava de microfone durante a fala**: preciso de um navegador
  de verdade com microfone/alto-falante, que não tenho aqui. A lógica está implementada e
  revisada com cuidado, mas só um teste ao vivo confirma se resolveu o problema relatado.
- **O detector de "duas palmas"**: mesma limitação - preciso que você calibre com o
  microfone/ambiente reais do escritório ou chão de fábrica.
- **As URLs de cotação de dólar/cacau ao vivo**: o ambiente onde processei isso bloqueia
  conexões de saída pra esses domínios, então não consegui confirmar que as APIs respondem
  exatamente como esperado hoje - só revisei a lógica de parsing/resiliência.
- **O fluxo OAuth completo com credenciais REAIS do Google/Slack**: só testei com
  credenciais falsas (mockando as respostas dos provedores) - o fluxo real depende de você
  criar as credenciais nos passos acima.

## Arquivos alterados/criados

**Backend:**
- `backend/app/models.py` - novas colunas em `Usuario` (conexão Gmail/Slack).
- `backend/app/database.py` - migração automática das colunas novas.
- `backend/app/integracoes_pessoais.py` - **novo**: OAuth Google/Slack + busca de
  pendências.
- `backend/app/cotacoes.py` - **novo**: cotação de dólar e cacau, com cache.
- `backend/app/routers/integracoes_pessoais_router.py` - **novo**: endpoints de
  conectar/callback/status/desconectar/pendências.
- `backend/app/routers/cotacoes_router.py` - **novo**: endpoint de cotações.
- `backend/app/main.py` - registra os 2 routers novos.

**Frontend:**
- `frontend/app.js` - trava de microfone durante a fala, apresentação sob demanda (botão),
  gatilho "Atlas, Assistente", saudação personalizada, painel de pendências + detector de
  palmas.
- `frontend/index.html` - botão de áudio no topo, banner de saudação, painel de pendências,
  `app.js?v=98`.
- `frontend/style.css` - estilos novos (botão de áudio, destaque temporário, itens de
  pendência).

## Como aplicar

Substitua os arquivos correspondentes no seu repositório e faça o deploy de costume.
Nenhuma migração manual de banco é necessária. Gmail/Slack ficam desativados (com aviso
claro) até você configurar as credenciais OAuth acima - o resto (voz, botão de áudio,
saudação com "indisponível" nas cotações) já funciona sem nenhuma configuração extra.
