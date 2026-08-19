# Correção: modelo do Gemini descontinuado (HTTP 404)

## O que aconteceu

O deploy subiu certinho (a correção anterior resolveu isso), mas ao usar o
assistente/análise por IA, veio este erro:

> Chamada à IA generativa falhou (HTTP 404): { "error": { "code": 404,
> "message": "This model models/gemini-2.0-flash is no longer available.
> Please update your code to use models/gemini-3.6-flash..." } }

## Causa

O modelo padrão configurado no código (`gemini-2.0-flash`) foi
descontinuado pelo Google. Isso não tem relação com sua chave — ela está
correta; o modelo específico é que saiu de circulação.

## Correção

Atualizei o modelo padrão em `backend/app/ia_generativa.py` para
`gemini-3.6-flash` — exatamente o modelo que a própria resposta de erro do
Google indicou como substituto.

Também deixei o tratamento desse erro específico mais claro: se isso
acontecer de novo no futuro (o Google descontinua modelos periodicamente),
a mensagem de erro vai apontar explicitamente qual modelo usar no lugar, e
você pode corrigir **sem precisar de outro deploy** — só configurando a
variável de ambiente `ATLAS_IA_GENERATIVA_MODELO` no Render com o nome
novo (ex: `ATLAS_IA_GENERATIVA_MODELO=gemini-4.0-flash`, se um dia for o
caso).

## Como aplicar

Substitua `backend/app/ia_generativa.py` pelo deste pacote e faça o deploy
de novo. Nenhuma migração de banco nem outra mudança é necessária.

## Alternativa mais rápida (sem esperar deploy)

Se quiser testar agora mesmo sem esperar o deploy: no Render, adicione a
variável de ambiente `ATLAS_IA_GENERATIVA_MODELO` com o valor
`gemini-3.6-flash` e reinicie o serviço — isso sobrescreve o padrão do
código na hora, mesmo antes de aplicar este arquivo.

## Não pude testar com uma chamada real

Não tenho acesso a uma chave real do Gemini pra confirmar que
`gemini-3.6-flash` responde com sucesso de ponta a ponta — testei (com
mock) que o código agora usa esse nome por padrão e que, se um 404
parecido acontecer de novo, a mensagem de erro fica clara e aponta a
correção certa. Depois do deploy, clique em "Analisar" numa baixa de teste
pra confirmar que a resposta real vem certa.
