# Decisões de arquitetura e correções aplicadas

Este documento existe para ficar claro *o que mudou* em relação às versões
anteriores (Lovable e Base44) e *por quê* — feedback direto da revisão que
fizemos antes de começar a construir.

## 1. Uma implementação só, em código

Antes havia duas versões paralelas (Lovable+Supabase+ML externo, e
Base44) evoluindo separadamente, com nomes de tabela e comportamento
diferentes. Agora existe uma única fonte de verdade, versionável, sem
depender de um builder de IA reinferir schema a cada prompt.

## 2. Falso positivo incluído no treino do ML

**Antes**: `lovable_casos_ml_seed.csv` excluía 52% dos 1368 casos
históricos rotulados, incluindo a categoria mais frequente — "Sem
divergência real (falso positivo)", 494 casos (36%). O modelo era
estruturalmente incapaz de prever esse desfecho.

**Agora**: `app/hipoteses_config.py` mapeia as 16 categorias brutas do
CSV original para 16 códigos oficiais (14 originais + `Sem_Divergencia_Real`
+ `Outros_Nao_Categorizado`, ambos novos). Nenhuma categoria é descartada.
Se uma categoria nova aparecer no futuro sem mapeamento, o treino **falha
alto** (`raise ValueError`) em vez de descartar silenciosamente.

## 3. Motor de regras e ML reconciliados

**Antes**: o motor de investigação (evidências documentais) e o modelo
estatístico rodavam em serviços separados que nunca se comunicavam —
cada um calculava sua própria confiança sem saber da existência do outro.

**Agora**: `investigation.reconciliar()` funde os dois sinais (score
normalizado das evidências + distribuição de probabilidade do ML) num
único `hipotese_ia`/`confianca_ia`. As saídas individuais continuam
salvas (`hipotese_regras`, `hipotese_ml`) para auditoria — você sempre
pode ver os três valores lado a lado no dashboard.

## 4. Persistência do feedback de ML

**Antes**: o serviço de ML usava um SQLite próprio, separado do banco
principal, hospedado num filesystem efêmero — o histórico de feedback
acumulado seria perdido a cada deploy.

**Agora**: `casos_ml_feedback` é uma tabela no mesmo banco do resto do
app. Se você configurar `DATABASE_URL` para um Postgres gerenciado, o
feedback é durável como qualquer outro dado do sistema.

## 5. Bugs de importação corrigidos na origem, não remendados depois

- **SKU virando número** (perde zero à esquerda): todo `read_csv` de
  coluna de código usa `dtype=str` sem exceção (`app/csv_utils.py:parse_sku`).
- **Data com timestamp**: `parse_data` corta a hora, e **falha alto** se
  a hora não for meia-noite (sinal de dado real sendo truncado, não deve
  ser silenciosamente ignorado).
- **Encoding truncado em "Pará"/"Ativação"** (chegavam como "Par#U" e
  "Ativa#U" no CSV bruto): `normalizar_almoxarifado()` faz de-para por
  prefixo, e qualquer valor que não bater com nenhum prefixo conhecido
  vira `NAO_MAPEADO__<valor original>` — fácil de encontrar e revisar,
  em vez de virar um valor errado silenciosamente.

## 6. Simplificação deliberada: ML embutido, não microserviço

A versão anterior isolava o ML num serviço Flask separado, comunicando
por HTTP. Como agora o time inteiro é código nosso (não no-code + serviço
externo), embuti a predição como um módulo Python chamado em memória
(`app/ml/predict.py`). Menos uma peça de infraestrutura para manter, sem
custo real de flexibilidade — se um dia for necessário escalar o ML
separadamente do resto, é um refactor pequeno (a lógica já está isolada
num módulo próprio).

## O que ficou como limitação conhecida (não resolvido nesta v1)

Ver seção "Limitações conhecidas" no `README.md` — autenticação, retreino
automático, e recall baixo em classes raras do ML.
