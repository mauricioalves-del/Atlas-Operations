# Atlas — Controle Operacional de Estoques

Sistema de inteligência de negócio para conciliação de estoque: detecta
divergências entre saldo de sistema e saldo físico, investiga a causa
combinando um motor de regras (evidências documentais) com um modelo
estatístico (RandomForest), e aprende com cada caso confirmado.

Reescrito do zero em código (Python), substituindo as versões anteriores
feitas em plataformas no-code (Lovable/Base44). Ver `DECISOES.md` para o
racional de cada correção aplicada em relação à versão anterior.

## Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite (troque para Postgres só
  setando a variável de ambiente `DATABASE_URL`, sem mudar nenhuma linha
  de código)
- **ML**: scikit-learn (RandomForest), embutido no mesmo processo do
  backend (chamada em memória, sem microserviço HTTP separado — mais
  simples de operar)
- **Frontend**: HTML/CSS/JS puro + Chart.js via CDN (sem etapa de build)

## Custo e valor financeiro por SKU

O `valor_estimado` de cada divergência (usado nos KPIs e na lista) agora
é calculado de verdade: `abs(divergencia_qtd) × custo_unitario_do_sku`.

Sem custo cadastrado pra um SKU, o valor fica em 0 (não inventamos
número). Para cadastrar custos:

- Tela **Importar** → seção "Custos por SKU" → CSV com colunas `sku, custo_unitario`
- Ou por linha de comando: `python3 -m data_import.importar_custos --arquivo caminho/custos.csv`

Se você cadastrar custos depois que divergências já existem, use o botão
**Recalcular valores** (tela Divergências) para atualizar o valor
estimado das divergências ainda não resolvidas com o custo atual.

## Backup e atualização segura

**Leia `ATUALIZANDO.md` antes da próxima vez que for atualizar o
código** - tem o passo a passo de quais pastas substituir e quais nunca
tocar, pra não perder dados de novo.

Backup pela tela: Menu → **Auditoria** (admin) → "Baixar backup agora".
O sistema também guarda automaticamente uma cópia em `backend/backups/`
toda vez que o servidor inicia (mantém as últimas 15).

### Painel de Inventário (dashboard) e Pós-Inventário

Duas telas novas dentro do pilar de Fechamento:

- **Painel Inventário**: KPIs (acurácia geral, % de SKUs acima de 95%,
  déficit de faltas, resultado líquido), acurácia por grupo e por
  almoxarifado, ranking financeiro (top 10 faltas/sobras), top 10 itens
  mais recorrentes em divergência (somando todos os fechamentos já
  importados), e evolução mensal (MoM) - o gráfico combina colunas de
  acurácia com uma linha de **quantidade de fechamentos realizados no
  mês**, justamente para não confundir "acurácia caiu" com "auditamos
  mais almoxarifados esse mês" (uma queda no % pode significar cobertura
  maior, não piora real).
- **Pós-Inventário**: lista de ações de acompanhamento (responsável,
  prazo, status) para os itens divergentes. Quando a planilha de
  fechamento já traz uma nota na coluna "obs pós inv" (ex: "Ajustar",
  "Recontar"), uma ação é criada automaticamente como Pendente (ícone 🔄
  na lista) - você só precisa definir responsável e prazo, ou criar ações
  manuais pra qualquer SKU.

## Correção final: as duas fontes se somam, nenhuma exclui a outra

A "correção definitiva" anterior foi longe demais: fazia o livro-caixa
bruto excluir por completo o fluxo antigo sempre que existisse qualquer
dado bruto, mesmo esparso. Isso resolveu o bug do 100% falso, mas criou
o oposto: almoxarifado que concilia de verdade pelo fluxo antigo (não
pelo livro-caixa bruto) aparecia como "nunca conferido", mesmo tendo
divergências reais resolvidas naquele período.

Corrigido com soma, testado nos dois cenários ao mesmo tempo:
- **Universo** = livro-caixa bruto ∪ fluxo antigo (todo dia com QUALQUER registro de qualquer fonte)
- **Conferido** = ajustes de Inventário (livro-caixa) ∪ todo dia do fluxo antigo (cada linha dele já é a conciliação em si)
- Testado: almoxarifado com conferência real só pelo fluxo antigo → 11,4% de cobertura (não mais 0%), 4 dias conferidos batendo com os 4 dias reais de conciliação.
- Testado de novo: almoxarifado com os dois fluxos juntos → continua em 41,3% (furo real), não voltou a 100% falso.

## Detalhe do dia + correção de referência de "atraso" (feedback real de uso)

- **Duplo clique num dia do calendário** abre um pop-up com todos os itens movimentados naquele dia (SKU, descrição, saída, entrada, operações) - cada linha traz status: se já existe divergência registrada pra esse item (com link direto pra abrir), ou "sem divergência ainda" com botão **"Abrir investigação"** (usa o mesmo modal de ação de acompanhamento já existente no resto do sistema). Isso exigiu guardar a movimentação bruta item a item (não só os sinais derivados) - testado com o arquivo de 50 mil linhas da Processo sem travar.
- **"Dias desde a última conferência" não usa mais D-1 fixo como referência** - agora compara contra o último dia que realmente teve movimento pra aquele almoxarifado específico. Isso evita contar fim de semana/feriado como "atraso" quando a operação é segunda a sexta e simplesmente não roda nesses dias.

## Correção definitiva: nunca misturar movimentação bruta com conciliação

Depois do primeiro ajuste, um cenário real revelou um bug de fundo:
almoxarifado com **os dois fluxos** (livro-caixa bruto + importação
diária antiga) acabava com cobertura calculada usando as duas fontes
misturadas - o que inflava a cobertura pra 100% artificialmente
("conciliação contando como se fosse o próprio universo dela").

Corrigido com uma regra estrita, testada com esse exato cenário misto:

- **Se o almoxarifado tem dado no livro-caixa bruto**, o universo
  (denominador) é só isso - qualquer transação, de qualquer tipo - e a
  conciliação (numerador) é só os ajustes de "Inventario" dentro desse
  mesmo livro-caixa. O fluxo antigo de importação diária, se também
  existir pro mesmo almoxarifado, é **ignorado por completo** nesse
  cálculo.
- **Se não tem livro-caixa bruto**, usa o fluxo antigo (cada linha
  importada já É a conciliação em si - 100% é o resultado correto e
  esperado aqui, não bug).
- Testado com o cenário exato: Fábrica com os dois fluxos importados
  juntos → resultado usa só o livro-caixa bruto (41,3%, fonte
  "livro_caixa_bruto"), ignorando a importação diária antiga por
  completo, em vez do 100% artificial de antes.
- A tela agora mostra qual fonte está sendo usada por almoxarifado, pra
  nunca mais precisar adivinhar.

## Correções na Cobertura de Conferência (feedback real de uso)

- **Universo mudou de "todo dia do calendário" pra "dias com movimentação real"**: um dia sem nenhuma operação (fim de semana, ou o almoxarifado simplesmente não rodou nada) não conta mais como "furo" - não tinha nada pra conferir naquele dia. Vem do livro-caixa bruto (qualquer linha, não só as de conferência) + do fluxo antigo de importação diária, como fallback pra almoxarifados que ainda não usam o livro-caixa.
- **D-1 sempre**: o processo trabalha com o dia anterior, não o dia atual (que ainda não está "encerrado" operacionalmente) - hoje nunca entra na análise.
- **Almoxarifados fora da contagem diária ficam de fora, de forma parametrizável**: novo campo "Participa da contagem diária" no cadastro de almoxarifados (tela Cadastros), com toggle direto na tabela - não é uma lista fixa no código, então se o planejamento interno mudar, é só desmarcar/marcar de novo, sem precisar de outra atualização. Ajuste inicial já aplicado (tanto pra bancos novos quanto pra bancos existentes, na migração automática): Almox_SP_Loja, Almox_Box, Almox_Box_2, Almox_SP_Degustacao e Almox_SP_Ativacao começam desmarcados.
- Testado com os 4 arquivos reais (Fábrica, Processo, Pará, Qualidade): números realistas agora (32 a 63 dias no universo, não 90 fixos), e confirmado visualmente na tela que os 5 almoxarifados excluídos não aparecem mais na lista.

## Livro-caixa bruto do sistema (transferências e conferências automáticas)

Importador novo, na tela Importar, pra um formato bem diferente dos
outros: **exportação direta do sistema** (Id_Lanc, Id_Produto, Data,
Operacao, Qtd_Sai, Qtd_Ent, Saldo...) - não é uma planilha de
reconciliação, é o histórico real de transações, um arquivo por
almoxarifado.

- **Transferências cruzadas automaticamente**: a mesma transferência
  aparece nos livros-caixa de origem E destino, com o mesmo número de
  documento e timestamp - uma como saída, outra como entrada. Casando
  pelos dois (documento + SKU), o sistema sabe se a transferência já
  chegou ou ainda está pendente, sem precisar de planilha manual de
  transferências. Testado com os arquivos reais de Fábrica e Processo:
  cruzamento confirmado (mesma transferência com origem/destino/datas
  corretas nos dois lados).
- **Conferências reais**: operações "Inventário (+)/(-)" marcam o
  momento em que uma contagem física foi aplicada como ajuste no
  sistema - alimenta direto a tela Cobertura de Conferência, sem
  precisar de outro arquivo.
- Só considera "INT" (transferência interna) como transferência de
  verdade - outros tipos de documento no mesmo arquivo (consumo de
  produção, recebimento, notas) têm campos parecidos mas não são
  transferência nenhuma (bug real encontrado e corrigido durante os
  testes: sem esse filtro, consumo de produção entrava como
  "transferência pendente" por engano).
- Almoxarifados citados nas operações que ainda não existem no catálogo
  (ex: nomes de PDV específicos) aparecem como "não mapeados" no
  resultado, em vez de silenciosamente adivinhados errado.

## Cobertura de Conferência (dias conferidos × dias pendentes)

Indicador de saúde do **processo de controle**, não do estoque - mede se
a conferência diária foi feita, não se ela achou algo. Um almoxarifado
sem furos pode ter divergências reais (isso é normal, é o que os outros
módulos já tratam); um almoxarifado com um furo grande pode estar
escondendo uma ruptura que nunca foi detectada, simplesmente porque
ninguém checou naquele período.

- **Por almoxarifado**: % de cobertura, dias desde a última conferência,
  maior furo (sequência de dias consecutivos sem nenhum apontamento) e o
  período exato dele.
- **Calendário visual**: cada almoxarifado tem seu próprio "heatmap" de
  dia a dia (verde = conferido, vermelho = pendente).
- Considera o cadastro de almoxarifados como a lista mestre - um
  almoxarifado registrado mas nunca conferido aparece como **0% de
  cobertura**, o cenário mais perigoso (ninguém olhou pra ele, nem uma
  vez, no período).
- Testado com um cenário controlado (furo deliberado de 15 dias num
  almoxarifado, outro nunca conferido, outro só conferido nos últimos 5
  dias) - os três apareceram exatamente certos, com o período do maior
  furo calculado dia a dia.

## Contexto operacional real (importadores Excel + ML)

- **5 novos importadores** na tela Importar (Faturamento, Ficha Técnica BOM, Ordens de Produção, Consumo de OP, Transferências) - aceitam o formato Excel exportado direto do banco SQL da empresa. **Cada envio substitui os dados anteriores por completo** (são tabelas espelhadas, não histórico acumulativo) - reenviar a versão mais atual nunca duplica.
- **Ficha Técnica BOM mais rica**: agora guarda subconjunto (nível intermediário da receita), custo, se o item é comprado de fornecedor (`Gera_Oc` - liga direto com o Controle de Compras) e categoria.
- **Correção de normalização de almoxarifado**: a comparação agora ignora maiúsculas/minúsculas (resolvia "PDV ATIVACAO" não bater com a palavra-chave "Ativa"), e adicionei Box/Box2/Degustação ao catálogo.
- **O modelo de ML agora vê o mesmo contexto que o motor de regras**: transferência pendente, pedido de compra pendente, OP aberta, consumo divergente da ficha técnica, item comprado de fornecedor, faturamento próximo (e se foi no mesmo almoxarifado) - tudo extraído numa função só (`app/feature_extraction.py`), reaproveitada tanto pelo motor de regras quanto pelo treino/previsão do ML. Testado: acurácia do modelo subiu de 68% para 70% no holdout, com melhora visível em Transferência Pendente (f1-score 0,63 → 0,74).
- **Valor Mod** no MoM da Acurácia Ponderada: nova opção no seletor que troca a visão de % de acurácia por R$ de impacto financeiro total do mês (sobra e falta juntos, sem se cancelarem) - mede evolução/involução em dinheiro, não só em percentual.

## Controle de Compras (Estoque Externo)

Resolve um problema específico: fornecedor entrega pedido fracionado (ex:
compra de embalagens chega em várias remessas), e cada contagem física
feita antes da entrega completa parece uma falta real de estoque.

- Registra **pedidos de compra** (fornecedor, SKU, quantidade, prazo) e
  **recebimentos parciais** contra cada pedido - status muda sozinho
  (Aberto → Parcialmente Recebido → Concluído) conforme os recebimentos
  entram.
- **O Atlas não é o sistema de compras** - só registra o suficiente pra
  alimentar o motor de investigação. Isso é o que importa de verdade:
  uma nova evidência em `investigation.py` verifica, pra toda divergência
  que é uma FALTA, se existe pedido em aberto/parcial pra aquele
  SKU+almoxarifado com saldo pendente compatível - se bater, a hipótese
  vira **"Pedido de Compra Pendente"** em vez de perda real, com peso
  cheio se a magnitude bater (tolerância de 20%) ou peso parcial se só
  houver pedido aberto sem bater exato.
- Como Movimentados e Fechamento de Inventário chamam a mesma função
  `investigar()`, o efeito vale pros dois **automaticamente** - não foi
  preciso alterar nenhum dos dois fluxos.
- Testado ponta a ponta: pedido de 1000 un., recebimento parcial de 600,
  falta de exatamente 400 detectada → hipótese correta com 100% de
  confiança. Testei também os controles: falta que não bate com o
  pendente (peso reduzido, não pleno) e sobra (não aciona a hipótese -
  ela só vale pra falta).

## Retreino do modelo de ML (manual e automático)

Toda vez que alguém confirma uma divergência, o caso vai pra uma tabela
de feedback (`CasoMLFeedback`). Isso agora fecha o ciclo de verdade:

- **Manual**: tela **Auditoria** → "Retreinar agora" (ou `python -m app.ml.train --historico <csv>`). Usa o histórico bruto + todos os casos confirmados até agora.
- **Automático**: um agendador em background (thread simples, sem cron/Task Scheduler, sem dependência nova) verifica periodicamente se já é hora - duas condições precisam bater juntas: um mínimo de casos novos confirmados E um intervalo mínimo de tempo desde o último retreino. Configurável via variáveis de ambiente:
  ```
  ATLAS_ML_AUTO_RETREINO=true                 # false desativa
  ATLAS_ML_RETREINO_INTERVALO_HORAS=24
  ATLAS_ML_RETREINO_MIN_CASOS_NOVOS=5
  ATLAS_ML_CHECAGEM_SEGUNDOS=1800             # verifica a cada 30 min
  ```
  O status (ativo, último retreino, casos novos aguardando) aparece na tela Auditoria.

## Excluir uma importação e cadastros sempre atualizados

- **Excluir importação**: tela **Importar** → seção "Importações recentes" lista os últimos lotes (CSV/Excel de movimentação) com botão "Excluir importação" - remove as divergências e o histórico criados por aquele lote específico, sem afetar o resto. Fechamentos de inventário também têm botão de excluir na lista da tela **Fechamento Inventário**.
- **Cadastros propagam na hora**: criar/editar um almoxarifado já aparece no seletor da tela Importar na próxima vez que você escolher um arquivo Excel (sem precisar recarregar a página). Hipóteses novas cadastradas em **Cadastros** já aparecem no seletor "Hipótese confirmada" ao investigar uma divergência.

## Fechamento de Inventário

Módulo pensado para quem fecha o inventário periodicamente (conciliação
contábil × físico). Tela **"Fechamento Inventário"** no menu.

- Importa a planilha de fechamento (aba padrão `Saldo de estoque - ace4`,
  ajustável na tela se sua planilha usar outro nome de aba).
- Cada linha marcada como divergente na própria planilha (coluna
  `Status`) passa pelo mesmo motor de investigação do resto do sistema
  (regras + ML + leitura da observação) - não é um módulo isolado, é o
  motor de sempre aplicado num novo tipo de entrada.
- **Recorrência**: compara cada item divergente com fechamentos
  anteriores do mesmo SKU + almoxarifado. Se já divergiu antes, a linha
  ganha destaque visual (⭐ + contador de quantas vezes) - dá pra ver de
  cara quais itens são "always suspects" em vez de ocorrência isolada.
- **Divergências listadas separadamente**: ao abrir um fechamento, a
  tela já separa "Divergências" de "Itens sem divergência" - você não
  precisa filtrar nada, cai direto na lista que importa para investigar.
- Cada linha divergente tem um botão **Investigar** que abre o caso
  completo (evidências, ML, casos similares, confirmação) na tela de
  Divergências normal.

## Acurácia Ponderada (IAP/IAQ) — módulo dedicado

Tela própria no menu ("Acurácia Ponderada"), separada do Painel Inventário geral - não mistura os dois:

- **IAQ** (ponderado por quantidade) e **IAP** (ponderado por valor) lado a lado com a acurácia item a item clássica, e o **gap em pontos percentuais** entre eles - a prova numérica direta de quanto a métrica clássica esconde.
- **Curva de Pareto**: quanto do valor total em risco está concentrado nos itens de maior impacto (tabela + gráfico).
- **Distribuição por magnitude**: quantos itens divergem por pouco (≤5 un.) vs muito, e quanto valor cada faixa representa - a prova visual de que "toda divergência conta igual" distorce a leitura.
- **Evolução mensal** dos três modelos, pra ver se a distância entre eles está diminuindo (bom sinal) ou aumentando.

O card de IAP **não fica mais** dentro do Painel Inventário geral - ficou isolado, poluía a leitura dos indicadores originais (item a item, % SKUs acima de 95% etc.), que continuam exatamente como eram.

## IAP, Top 10 de Risco e Ciência de Conciliação

- **IAP (Índice de Acurácia Ponderada por valor)**: novo indicador no Painel Inventário, ao lado da acurácia item a item (não a substitui). Fórmula: `1 - (Σ|divergência × custo| ÷ Σ(qtd. sistema × custo))`, só no universo de SKUs com custo cadastrado (cobertura aparece explícita no card). Alimente o custo via **Importar → Custos por SKU** (CSV manual) ou **Custos via planilha de preço** (Excel, lê a aba `tabela de preço` ou equivalente, só grava custo quando ele é consistente em todas as ocorrências do SKU na planilha).
- **Top 10 Itens Recorrentes de Risco**: diferente do "Top recorrentes" (só ocorrências) - aqui o critério é `ocorrências × valor total`, e só entram itens com 2+ ocorrências. Clicar numa linha abre o mesmo modal de ação do Pós-Inventário - se já existir uma ação em aberto pra aquele SKU, ela é carregada; senão, abre em modo de criação.
- **Ciência da conciliação**: no detalhe de um fechamento, botão para confirmar (usuário logado + timestamp = a "assinatura") e gerar um PDF com a lista de itens divergentes congelada no momento da confirmação. Histórico de confirmações fica visível ali mesmo, com link para baixar o PDF de cada uma.
- **Recalcular valores do fechamento**: `POST /api/fechamentos/recalcular-valores` - útil quando você importa custo depois que o fechamento já existia (mesmo padrão do recálculo que já existia pra Divergências).

## Cadastros, auditoria, testes e tema

- **Cadastros** (tela "Cadastros", admin/analista): CRUD de Produtos, Almoxarifados e Hipóteses - criar, editar, desativar/ativar, e excluir (só permite excluir se o registro nunca foi usado em nenhuma movimentação/divergência; senão, sugere desativar em vez de excluir, pra não corromper o histórico).
- **Auditoria** (tela "Auditoria", só admin): log de quem fez o quê - login, importações, confirmações, edições de cadastro. Paginado.
- **Proteção contra força bruta**: 5 tentativas de senha erradas bloqueiam o usuário por 15 minutos (mesmo com a senha certa, não desbloqueia antes do tempo).
- **Paginação**: `/api/divergencias` agora pagina (`?pagina=1&tamanho_pagina=50`) em vez de devolver tudo de uma vez.
- **CORS restringível**: variável de ambiente `ATLAS_ALLOWED_ORIGINS` (lista separada por vírgula) - por padrão continua `*` para não travar o uso local.
- **Testes automatizados**: `cd backend && pytest` roda 23 testes (parsing de CSV, autenticação, motor de investigação, reconciliação regras+ML).
- **Tema claro/escuro**: botão no rodapé do menu lateral, preferência salva no navegador.

## Rodando na nuvem (sem deixar seu computador ligado)

Veja `DEPLOY.md` na raiz do projeto - guia completo pra colocar o Atlas
rodando 24/7 num servidor (Render, gratuito para começar), acessível de
qualquer lugar por uma URL. Inclui banco de dados Postgres durável e
inicialização automática dos dados no primeiro boot (usa os CSVs em
`backend/seed_data/`) - não precisa de acesso a terminal no servidor.

## Autenticação e papéis

Do primeiro `uvicorn app.main:app` em diante, o Atlas exige login. Na
primeiríssima vez que o servidor sobe (banco sem nenhum usuário ainda),
ele cria um usuário `admin` com senha aleatória e imprime no terminal:

```
============================================================
ATLAS - usuário administrador criado automaticamente:
   username: admin
   senha:    xxxxxxxxxxxx
   Troque essa senha depois de logar (tela Usuários).
============================================================
```

Guarde essa senha (ela só aparece uma vez) e troque depois de logar, na
tela **Usuários** (visível só para admins).

Três papéis:

| Papel | Pode ver dashboard/divergências | Pode importar/confirmar/reinvestigar | Pode gerenciar usuários |
|---|---|---|---|
| `leitura` | ✅ | ❌ | ❌ |
| `analista` | ✅ | ✅ | ❌ |
| `admin` | ✅ | ✅ | ✅ |

Criar/resetar usuário por linha de comando (sem precisar da tela, útil se
perder acesso):
```bash
python3 -m data_import.criar_usuario --username joao --senha "SenhaForte123" --papel analista
```

Autenticação usa apenas a biblioteca padrão do Python (PBKDF2 para senha,
HMAC para o token de sessão) - não adiciona nenhuma dependência nova ao
`requirements.txt`, para não repetir problemas de instalação de pacotes
com extensão nativa.

## Como rodar

```bash
cd backend
pip install -r requirements.txt --break-system-packages   # ou use um virtualenv

# 1) popular tabelas de referência (hipóteses, almoxarifados, produtos)
python3 -m data_import.seed_referencias --produtos /caminho/produtos_import.csv

# 2) importar o histórico categorizado (base de conhecimento + treino do ML)
python3 -m data_import.importar_historico --arquivo /caminho/atlas_casos_historicos_categorizados.csv

# 3) importar as tabelas operacionais de apoio (usadas pelo motor de investigação)
python3 -m data_import.importar_operacionais --pasta /caminho/da/pasta/com/os/csvs

# 4) treinar o modelo de ML
python3 -m app.ml.train --historico /caminho/atlas_casos_historicos_categorizados.csv

# 5) subir o servidor
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra `http://localhost:8000` — o dashboard já vem servido pelo próprio
backend.

O banco (`atlas.db`) e o modelo treinado (`app/ml/model.joblib`) já vêm
inclusos neste pacote com os dados reais fornecidos, então você pode pular
os passos 1–4 e ir direto para o passo 5 se só quiser ver funcionando.

## Fluxo de uso

1. **Importar** uma planilha de movimentação (aba "Importar" no dashboard,
   ou `POST /api/importar/movimentacao`) com colunas:
   `sku, almoxarifado, data_movimento, entrada, saida, saldo_sistema, saldo_fisico, unidade`.
2. Linhas sem divergência (saldo físico == saldo sistema) vão direto para
   o histórico. Linhas com divergência criam um registro em `Divergencia` e
   disparam automaticamente:
   - o motor de regras (`app/investigation.py`), que verifica transferência
     pendente, OP aberta, faturamento próximo, ficha técnica, reincidência
     etc., e retorna evidências + uma hipótese com confiança;
   - o modelo estatístico (`app/ml/predict.py`), que retorna sua própria
     hipótese com distribuição de probabilidades;
   - a reconciliação (`investigation.reconciliar`), que funde os dois
     sinais num único `hipotese_ia` / `confianca_ia` auditável (as saídas
     individuais de cada um continuam guardadas separadamente).
3. Um analista revisa a divergência no dashboard (aba "Divergências" →
   clique na linha) e **confirma** a hipótese real. Isso:
   - marca a divergência como Resolvida;
   - ajusta o peso da hipótese que o motor de regras sugeriu (+2 se acertou,
     -2 se errou, dentro de limites 5–60);
   - grava o caso em `casos_ml_feedback`, que entra automaticamente no
     próximo retreino do modelo (rode `python3 -m app.ml.train` de novo
     periodicamente — não há retreino automático agendado nesta v1).

## Endpoints principais

| Rota | Descrição |
|---|---|
| `POST /api/importar/movimentacao` | Sobe um CSV, processa cada linha (histórico ou divergência) |
| `GET /api/divergencias` | Lista divergências (filtros: `almoxarifado`, `status`, `hipotese`) |
| `GET /api/divergencias/{id}` | Detalhe completo (evidências, casos similares, distribuição) |
| `POST /api/divergencias/{id}/confirmar` | Confirma a hipótese real e alimenta o aprendizado |
| `GET /api/dashboard/kpis` | Contagens e taxa de acerto do modelo |
| `GET /api/dashboard/evolucao-por-dia` | Série temporal de divergências |
| `GET /api/dashboard/distribuicao-causas` | Distribuição das causas confirmadas |
| `GET /api/dashboard/heatmap-almoxarifado-hipotese` | Matriz almoxarifado × hipótese |
| `GET /api/dashboard/top-reincidentes` | SKUs e almoxarifados mais recorrentes |
| `GET /api/dashboard/top-divergencias` | Maiores divergências por quantidade |

## Estrutura

```
backend/
  app/
    models.py              modelos do banco (schema corrigido)
    csv_utils.py            parsing seguro de CSV
    hipoteses_config.py      catálogo oficial de hipóteses + de-para auditável
    investigation.py         motor de regras + reconciliação com ML
    ml/
      train.py                treino do RandomForest (dataset corrigido)
      predict.py               predição em runtime
    routers/                  endpoints da API
    main.py                   montagem do app FastAPI
  data_import/                scripts de carga inicial (rodar uma vez)
frontend/
  index.html / style.css / app.js   dashboard (sem build)
```

## Limitações conhecidas desta v1 (para priorizar depois)

- Retreino do ML é manual (rodar o comando periodicamente); dá para
  automatizar com um cron/job depois que houver volume de feedback.
- Classes raras no treino (7–15 exemplos) têm recall baixo — o
  `classification_report` impresso no treino mostra isso com honestidade;
  acumular mais casos confirmados via loop de feedback deve melhorar isso
  com o tempo.
- Campo `valor_estimado` das novas divergências fica 0 por padrão (a
  planilha de movimentação não traz valor unitário) — se você tiver uma
  tabela de custo por SKU, dá para calcular isso na importação.
- O token de sessão dura 12h; depois disso é preciso logar de novo (sem
  "lembrar de mim" nesta v1).
