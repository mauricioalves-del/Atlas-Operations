# Atlas + IA Generativa — classificação e resumo automático de baixas e divergências

## O que você pediu

Adicionar uma inteligência artificial ao Atlas, de forma gratuita — usando um
token/chave gratuita de outro serviço de IA. E que a escolha do que essa IA
faz fosse "Classificação/resumo automático de baixas e divergências".

## O que foi implementado

Uma integração com **Google Gemini** (via Google AI Studio), que tem uma
camada gratuita sem pedir cartão de crédito. Isso é diferente da "IA" que já
existe no Atlas: hoje, toda divergência já passa por um motor de regras +
um modelo estatístico treinado nos próprios dados do Atlas
(`hipotese_regras`, `hipotese_ml`, `hipotese_ia` — sempre calculados, sem
depender de nada externo). O que foi adicionado agora é um LLM externo,
opcional, que só age quando alguém pede — por isso todo campo novo usa o
prefixo `ia_gen_` (**IA Gen**erativa), bem separado dos campos que já
existiam.

Dois lugares novos na tela:

1. **Mapeamento de Passivos → "Ver todos os Passivos"**: cada baixa sem
   leitura ainda tem um botão **"✨ Analisar"**; depois de analisada, mostra
   um selo com a prioridade sugerida (Alta/Média/Baixa) e a categoria
   sugerida (dentro do catálogo oficial de Hipóteses que o Atlas já usa —
   passe o mouse pra ver o resumo em 1-2 frases). Tem também um botão
   **"✨ Analisar pendentes com IA"** que processa várias baixas aprovadas de
   uma vez (as de maior valor primeiro), com uma trava de segurança (no
   máximo 25 por chamada, com pausa entre cada uma) pra não estourar a cota
   gratuita.
2. **Tela de detalhe de uma Divergência**: um painel novo, "Resumo por IA
   Generativa", com o botão **"✨ Resumir com IA"** — pede pra IA traduzir,
   numa leitura corrida em português, os sinais que já estão espalhados
   pelos painéis de Evidências/Casos similares/Distribuição de
   probabilidades.

Em nenhum dos dois casos a IA decide nada em definitivo — é sempre uma
sugestão revisável, e nunca substitui `hipotese_aplicada` (baixas) ou
`hipotese_ia`/`confianca_ia` (divergências).

**Sem custo de dependência nova**: a chamada ao Gemini usa só `urllib`
(biblioteca padrão do Python), o mesmo padrão que o Atlas já usa pra
chamar a sincronização com o Lovable — não foi adicionado nenhum SDK/pacote
novo ao `requirements.txt`.

## Como pegar a chave gratuita (você mesmo, com sua própria conta Google)

Eu não posso criar contas nem preencher formulários de login/senha em seu
nome — isso é uma trava de segurança da minha parte. Mas o passo a passo é
rápido:

1. Acesse **https://aistudio.google.com/apikey** e entre com uma conta
   Google (a mesma do dia a dia serve).
2. Clique em **"Create API key"** (ou "Criar chave de API").
3. Copie a chave gerada (uma string longa, algo como `AIzaSy...`).
4. **Não precisa cartão de crédito** para essa camada gratuita.

⚠️ **Importante sobre os limites da camada gratuita**: o Google define
quantas chamadas por minuto e por dia a camada gratuita aceita, e esse
número pode mudar com o tempo — confira o valor atual em
https://ai.google.dev/gemini-api/docs/rate-limits antes de configurar em
produção. Por isso o botão de análise em lote tem um limite de 25 itens por
chamada (ajustável, ver `ia_generativa.py`) — analisar um volume muito
grande de uma vez só pode estourar a cota do dia.

## Como configurar no Atlas (Render)

No painel do Render (Environment do serviço do backend), adicione:

- `ATLAS_IA_GENERATIVA_API_KEY` = a chave que você copiou no passo acima.
  **Sem essa variável, o recurso fica desativado** — os botões de IA
  continuam aparecendo, mas o clique devolve uma mensagem clara ("IA
  generativa não configurada neste ambiente...") em vez de dar erro feio ou
  quebrar a tela.
- `ATLAS_IA_GENERATIVA_MODELO` (opcional) = por padrão usa
  `gemini-2.0-flash` (rápido e dentro da cota gratuita pra esse uso). Só
  precisa mudar se quiser testar outro modelo do Gemini.

Depois de configurar, é só fazer o deploy de novo — nenhuma migração manual
de banco é necessária, as colunas novas são criadas automaticamente na
próxima vez que o Atlas subir (mesmo mecanismo de auto-migração que o resto
do projeto já usa).

## Validado

- Subi o Atlas completo (FastAPI + SQLite) num banco isolado e testei de
  ponta a ponta pela API real (não só a função isolada): status da IA
  sem/com chave, análise de uma baixa, análise em lote (com e sem
  pendentes), resumo de uma divergência, e que o papel "leitura" não
  consegue acionar nenhuma das duas (só admin/analista podem, mesma regra
  de outras ações que gastam algo externo).
- Simulei a resposta do Gemini (sem gastar cota real, porque ainda não
  tenho uma chave sua) pra confirmar que a categoria/prioridade/resumo são
  gravados certinho e aparecem de volta no Mapeamento de Passivos e na
  tela de detalhe da divergência.
- Testei os casos de erro na integração isolada: chave ausente, HTTP 429
  (cota excedida), HTTP 500, timeout, e resposta que não vem em JSON válido
  (inclusive envolvida em ` ```json `) — todos tratados com mensagem clara,
  nenhum quebra o resto do Atlas.
- Testei que uma categoria ou prioridade fora do catálogo oficial (a IA
  "inventando" um valor) cai num fallback seguro em vez de gravar lixo no
  banco.
- Validei a sintaxe do JavaScript novo (`node --check`) e o HTML do modal
  (parser HTML) sem erros.

**O que eu NÃO pude testar**: uma chamada real ao Gemini com uma chave de
verdade, porque isso depende de você criar a sua conta. Recomendo, depois
de configurar a chave no Render, clicar em "Analisar" numa baixa de teste
pra confirmar que a resposta real do modelo também vem coerente — o
comportamento de parsing/gravação já está validado, só a qualidade da
resposta em si de um caso real ainda não foi vista por mim.

## Arquivos alterados/criados

- `backend/app/ia_generativa.py` **(novo)** — toda a integração com o
  provedor de IA generativa (chamada HTTP, parsing, validação, prompts).
- `backend/app/models.py` — campos novos `ia_gen_*` em `BaixaOperacional` e
  `Divergencia`.
- `backend/app/database.py` — migração automática (`ALTER TABLE`) das
  colunas novas.
- `backend/app/schemas.py` — `DivergenciaOut` passa a incluir
  `ia_gen_resumo`/`ia_gen_analisado_em`.
- `backend/app/routers/baixas_operacionais_router.py` — endpoints
  `GET /baixas-operacionais/ia-generativa/status`,
  `POST /baixas-operacionais/{id}/analisar-ia`,
  `POST /baixas-operacionais/analisar-ia-lote`; `dashboard/itens` agora
  devolve os campos `ia_gen_*`.
- `backend/app/routers/divergencias_router.py` — endpoint
  `POST /divergencias/{id}/resumir-ia`.
- `frontend/app.js` e `frontend/index.html` — botões "Analisar"/"Analisar
  pendentes com IA" no modal de Passivos, e painel "Resumo por IA
  Generativa" na tela de detalhe da divergência.

Nenhuma migração manual de banco necessária.
