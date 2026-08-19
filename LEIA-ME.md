# Atlas — verificação do comando de voz + "Atlas, Assistente" com pergunta em duas etapas

09/08/2026 (continuação da entrega anterior, `atlas_fix_voz_pendencias.zip`)

Este pacote contém **o backend e o frontend inteiros** (não só os arquivos
alterados). É de propósito: como o relato mais recente foi de que
funcionalidades já entregues (perguntas padrão do assistente, o painel de
pendências Gmail/Slack) sumiram depois do último deploy, a forma mais segura
de eliminar qualquer dúvida é substituir as duas pastas (`backend/` e
`frontend/`) por inteiro, em vez de tentar aplicar só alguns arquivos por
cima. Assim não há risco de ficar com uma mistura de versões.

## 1. O que eu verifiquei de verdade sobre "o comando de voz não funciona"

Da última vez, eu tinha só uma HIPÓTESE (a fala do próprio Atlas voltando pelo
microfone). Dessa vez, seguindo seu pedido de verificar de fato, eu rodei o
Atlas de verdade (o mesmo backend FastAPI servindo o mesmo frontend estático,
exatamente como no Render) num ambiente isolado aqui, e usei automação de
navegador (Playwright) para:

1. Carregar a página de verdade, logar de verdade, e confirmar que a tela
   principal, o botão de microfone, o texto de status e o botão de áudio no
   topo existem e aparecem corretamente.
2. Substituir só o reconhecimento de voz do navegador por uma versão de
   teste controlada (porque este ambiente não tem microfone real) que permite
   "dizer" uma frase de forma determinística e ver exatamente o que o código
   faz com ela — sem depender de já ter ouvido corretamente ou não.
3. Simular a frase "Atlas, cadastros" e confirmar que o Atlas abriu a tela de
   Cadastros corretamente. Simular "Atlas, assistente" e confirmar que abriu
   o painel do assistente. Repetir o teste várias vezes, checando a cada
   passo se havia algum erro de JavaScript escondido (não havia).

**Resultado:** a lógica de reconhecimento (detectar "Atlas", separar o nome
do módulo, trocar de tela, ativar o assistente) está correta e funciona de
ponta a ponta quando alimentada com uma fala já reconhecida. Isso quer dizer
que o bug não está nessa parte do código.

O que isso NÃO prova, e que eu genuinamente não consigo testar aqui (sandbox sem
microfone/hardware de áudio real): se o problema é o **reconhecimento de voz
em si** (o Chrome não estar entendendo o que você fala, a permissão de
microfone, a escuta contínua morrendo silenciosamente no seu navegador
específico, ou uma particularidade do computador/SO). Pra eu conseguir ir
além de "a lógica está certa", preciso de um detalhe muito específico do que
acontece na hora, no seu navegador de verdade:

- O ícone do microfone chega a mostrar o estado "ouvindo" (ele fica com um
  contorno/cor diferente quando ativo)?
- Quando você fala "Atlas, [módulo]", o texto logo abaixo do mapa de módulos
  muda (mesmo que pra uma mensagem de erro)?
- Abrindo o console do navegador (F12 → aba Console) enquanto tenta o
  comando de voz, aparece alguma mensagem em vermelho?
- Isso acontece em qualquer navegador/computador que você testou, ou só em
  um específico?

Essas respostas me dizem exatamente em qual das possibilidades acima focar.

## 2. Nova funcionalidade: "Atlas, Assistente" com pergunta em duas etapas

Você pediu: dizer "Atlas, Assistente", esperar cerca de 1 segundo, e o que
vier depois já ser tratado como a pergunta pro assistente — sem precisar
repetir "Atlas" nem digitar nada.

Implementado assim:

1. Você diz "Atlas, Assistente" → o Atlas abre o painel do assistente e fala
   um convite curto ("Pois não. Pode perguntar.").
2. Assim que o convite termina de ser falado, o Atlas abre uma **janela de
   10 segundos** em que a PRÓXIMA fala reconhecida (mesmo sem dizer "Atlas"
   de novo) é tratada diretamente como a pergunta e enviada ao assistente.
3. Se nada for dito dentro desses 10 segundos, a janela expira sozinha e o
   Atlas volta ao modo normal (só reage a frases que começam com "Atlas").
4. Testei especificamente que, depois de uma pergunta feita assim, comandos
   normais de navegação ("Atlas, cadastros" etc.) continuam funcionando
   normalmente — a janela não "vaza" e trava o resto do reconhecimento.

Testei esse fluxo completo com o mesmo método de automação de navegador
acima (com a IA generativa simulada, já que ela pode não estar configurada
neste ambiente de teste) e confirmei que a pergunta chega corretamente até a
função que fala com o assistente.

O texto de dica na tela Início e no painel do assistente foi atualizado pra
explicar esse novo jeito de perguntar por voz.

## 3. Sobre "perguntas padrão sumiram" e "o módulo solicitado não foi criado"

Isso me preocupou, porque testei o código-fonte que tenho aqui do zero (login
limpo, banco limpo) e as duas coisas aparecem normalmente:

- A lista de botões de "pergunta rápida" (Resumo do dia, Motivos mais
  recorrentes de divergência, Qual almoxarifado representa mais risco...)
  aparece no painel do Assistente Atlas.
- O painel de pendências (Gmail/Slack), com os botões de conectar cada
  serviço e o botão "👏 Ver pendências agora", também aparece normalmente
  logo abaixo do painel do assistente, na tela Início.

Duas explicações prováveis, das quais eu não tenho como saber qual é a certa
daqui:

1. **A entrega anterior só trouxe alguns arquivos**, e se ela foi aplicada
   "por cima" da pasta antiga em vez de substituir a pasta inteira, pode ter
   ficado uma mistura de versões (por isso esta entrega vem com o
   backend/frontend completos, pra eliminar essa possibilidade).
2. Pode ser algo específico do navegador (cache antigo do arquivo `app.js`,
   por exemplo) — o nome do arquivo já muda a cada entrega justamente pra
   evitar isso (`app.js?v=99` nesta versão), mas vale conferir se a tela que
   você viu era realmente depois de recarregar a página.

Se depois de aplicar esta entrega (pasta inteira, não só alguns arquivos)
ainda faltar alguma coisa, me diga exatamente qual módulo você esperava ver e
onde (nome da tela, o que deveria aparecer) — combinado com uma captura de
tela, isso me dá o suficiente pra investigar o que realmente está rodando aí
versus o que está neste pacote.

## 4. Como aplicar

1. Substitua a pasta `backend/` inteira do seu projeto pela pasta `backend/`
   deste zip (mantém `.env`/variáveis de ambiente do Render como estão -
   elas não vêm neste zip).
2. Substitua a pasta `frontend/` inteira do seu projeto pela pasta
   `frontend/` deste zip.
3. Reimplante no Render (ou onde estiver rodando) e recarregue a página no
   navegador com Ctrl+Shift+R (ou Cmd+Shift+R no Mac) pra garantir que o
   `app.js?v=99` novo seja carregado, e não uma versão em cache.
4. Teste o comando de voz e, principalmente, me responda as perguntas da
   seção 1 acima — é a parte que só dá pra confirmar no seu navegador de
   verdade.

## 5. O que eu testei vs. o que só você consegue confirmar

**Testado de verdade, rodando o app completo:**
- Login, tela Início, mapa de módulos, botão/status de microfone, botão de
  áudio no topo.
- Lista de perguntas padrão do assistente carregando do backend.
- Painel de pendências Gmail/Slack aparecendo (mostrando "não configurado",
  como esperado sem as credenciais OAuth).
- Reconhecimento de voz simulado: "Atlas, cadastros" → abre Cadastros.
  "Atlas, assistente" → abre o assistente. Pergunta em duas etapas → chega
  corretamente ao assistente. Comando normal depois → ainda funciona.
- Nenhum erro de JavaScript em nenhum desses passos.

**Só você pode confirmar (precisa de microfone/navegador reais):**
- Se o reconhecimento de voz do seu navegador está de fato entendendo o que
  você fala.
- Se o problema das "perguntas padrão"/"módulo" some depois de aplicar esta
  entrega completa (pasta inteira) e recarregar sem cache.
- As cotações de dólar/cacau na saudação (ver aviso já feito na entrega
  anterior — as fontes usadas não puderam ser testadas ao vivo por aqui).
