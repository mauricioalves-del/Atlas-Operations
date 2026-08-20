# Atlas — Gmail/Slack simplificado (uso pessoal), correção de cache e demais itens

09/08/2026

## Gmail/Slack: modelo simplificado, só pra você

Você perguntou se, sendo só pra você, ficaria mais simples - e sim, bastante. Troquei o
modelo "cada pessoa conecta a própria conta" (OAuth completo, com tela de consentimento,
callback etc) por credenciais fixas no servidor, do mesmo jeito que já funciona a chave do
Gemini. Só quem está logado como **Admin** vê e usa este painel (importante: como as
credenciais são de UMA conta pessoal, não por usuário do Atlas, isso evita que qualquer
outra pessoa da equipe veja sua caixa de entrada/Slack).

### Gmail - bem mais simples que antes

Não precisa mais criar nada no Google Cloud Console. Só:

1. Ative a Verificação em duas etapas na sua Conta Google, se ainda não tiver (é pré-requisito).
2. Vá em Conta Google → Segurança → Senhas de app → crie uma nova (qualquer nome, ex:
   "Atlas") → copie a senha de 16 letras que aparece.
3. Nas configurações do Gmail (⚙ → Ver todas as configurações → aba "Encaminhamento e
   POP/IMAP") → "Ativar IMAP" → Salvar alterações.
4. No Render, defina duas variáveis de ambiente:
   - `ATLAS_GMAIL_EMAIL` = seu e-mail do Gmail
   - `ATLAS_GMAIL_APP_SENHA` = a senha de app gerada no passo 2

Acesso é só leitura (nunca envia, marca como lido ou apaga nada).

### Slack - ainda precisa de um App, mas sem o vai-e-volta de OAuth

1. Crie em https://api.slack.com/apps → "Create New App" → "From scratch".
2. Na página do app → "OAuth & Permissions" → em **User Token Scopes** (não "Bot Token
   Scopes") → adicione: `im:read`, `mpim:read`, `search:read`.
3. No topo da mesma página, clique "Install to Workspace" → autorize. Vai aparecer um
   "User OAuth Token" (começa com `xoxp-`) → copie esse valor.
4. No Render, defina: `ATLAS_SLACK_USER_TOKEN` = o token copiado.

Depois de configurar as duas (ou só uma, funcionam de forma independente), o painel de
pendências na tela Início passa a mostrar "configurado" em vez de "não configurado", e o
botão "👏 Ver pendências agora" (ou bater duas palmas perto do microfone) já busca de
verdade.

## O resto desta entrega

### Correção de cache/service worker (provável causa de "atualização que não aparece")

Investigando por que o botão de configuração de perguntas padrão não aparecia pra você,
encontrei que os arquivos da casca do app (`index.html`, `app.js`, `sw.js`) não mandavam
nenhum `Cache-Control`, e o service worker (que torna o Atlas instalável) podia acabar
servindo uma versão antiga em cache mesmo tentando buscar "a mais nova" - Ctrl+Shift+R
sozinho não resolve isso quando o service worker já está no controle da página. Corrigi
os dois pontos (detalhes técnicos no histórico da conversa/no doc do projeto). **Ação
recomendada, uma vez só**: depois de aplicar esta atualização, se ainda não vir a
novidade, abra F12 → aba Application → Service Workers → "Unregister" → recarregue.

### Comando de voz

Testei a lógica de reconhecimento de ponta a ponta com automação de navegador - está
correta ("Atlas, cadastros" abre Cadastros, "Atlas, assistente" abre o assistente, sem
erros). O que só você pode confirmar no seu navegador de verdade: o ícone do microfone
chega a mostrar "ouvindo"? O status muda quando você fala? Algo em vermelho no console
(F12)? Isso ajuda a apontar se o problema é específico do seu navegador/SO.

### "Atlas, Assistente" com pergunta em duas etapas

Diga "Atlas, Assistente", espere o convite terminar de falar, e a próxima coisa que você
disser (sem repetir "Atlas") já vai direto como pergunta pro assistente.

### Módulo de configuração de perguntas padrão

Botão "⚙️ Perguntas padrão" no painel do Assistente Atlas, só pra Admin - cria, edita e
exclui perguntas padrão pelo próprio app (viram botão de atalho e são reconhecidas por
voz/texto), sem precisar de uma sessão como esta pra cada pergunta nova.

## Como aplicar

1. Substitua `backend/` e `frontend/` inteiros pelo conteúdo deste zip.
2. Se quiser usar Gmail/Slack, siga os passos acima e defina as variáveis de ambiente no
   Render.
3. Reimplante, recarregue com Ctrl+Shift+R e, se necessário, remova o service worker
   antigo (ver instrução acima) - só precisa fazer isso uma vez.
4. Teste o comando de voz e me diga os detalhes específicos pedidos acima.
5. Confira o painel "📋 Pendências (Gmail + Slack)" na tela Início (logado como Admin) e
   o botão "⚙️ Perguntas padrão" no painel do assistente.
