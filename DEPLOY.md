# Deploy do Atlas na nuvem (sem precisar rodar no seu notebook)

Isto coloca o Atlas rodando 24/7 num servidor, acessível de qualquer
lugar (celular, outro computador) por uma URL, sem precisar deixar o seu
notebook ligado.

Vou usar o **Render** (render.com) como referência porque tem plano
gratuito para projetos pequenos e não exige cartão de crédito para
começar. Se algo na interface deles estiver diferente do que descrevo
aqui (empresas mudam o painel com o tempo), os *valores* que você
precisa preencher continuam os mesmos - é só achar onde colar cada um.

> Isso exige duas coisas que não existiam ainda: uma conta no GitHub (pra
> guardar o código) e uma conta no Render (pra rodar o código). Ambas são
> gratuitas.

## Passo 1 — Colocar o projeto no GitHub

Se você **já tem** conta no GitHub, pule para "criar o repositório".

### Criar conta no GitHub (se não tiver)
1. Acesse github.com → Sign up → siga o cadastro (é grátis).

### Criar o repositório
1. No GitHub, clique em **New repository** (botão verde).
2. Nome: `atlas` (ou o que preferir). Marque **Private** (só você/sua empresa acessam o código).
3. Não marque nenhuma opção de "adicionar README" — deixe vazio.
4. Clique em **Create repository**. Vai aparecer uma tela com comandos - ignore, vamos usar os comandos abaixo.

### Enviar o projeto do seu notebook pro GitHub
Instale o Git se ainda não tiver: [git-scm.com/downloads](https://git-scm.com/downloads) (Next, Next, Next na instalação padrão serve).

Abra o PowerShell **na pasta do projeto** (`Atlas\atlas`) e rode, um de cada vez:

```powershell
git init
git add .
git commit -m "Atlas - versao inicial"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/atlas.git
git push -u origin main
```

Troque `SEU-USUARIO` pelo seu nome de usuário do GitHub. Na primeira vez, vai pedir pra você logar (uma janela do navegador abre) - autorize.

## Passo 2 — Criar conta no Render e conectar o GitHub

1. Acesse [render.com](https://render.com) → Sign up → escolha **"Sign up with GitHub"** (mais rápido, já conecta as duas contas).
2. Autorize o Render a acessar seus repositórios.

## Passo 3 — Deploy (caminho rápido: Blueprint)

Este projeto já vem com um arquivo `render.yaml` na raiz que descreve tudo que o Render precisa criar.

1. No painel do Render, clique **New +** → **Blueprint**.
2. Escolha o repositório `atlas` que você acabou de subir.
3. O Render vai mostrar o que vai criar: um banco Postgres (`atlas-db`) e um serviço web (`atlas`). Clique em **Apply** / **Create**.
4. Espere o build terminar (aparece um log rodando — leva alguns minutos na primeira vez, porque instala pandas/scikit-learn).
5. Quando terminar, o Render mostra a URL do seu serviço, algo como `https://atlas-xxxx.onrender.com`.

**Se o Blueprint der erro ou não aparecer essa opção**, siga o caminho manual abaixo (Passo 3-B) — ele preenche exatamente as mesmas informações, só clicando em vez de ler um arquivo.

### Passo 3-B — Deploy manual (alternativa se o Blueprint não funcionar)

**Criar o banco:**
1. New + → **PostgreSQL**. Nome: `atlas-db`. Plano gratuito. Create.
2. Espere ficar "Available" e copie o valor **Internal Database URL** (ou "Connection String").

**Criar o serviço web:**
1. New + → **Web Service** → escolha o repositório `atlas`.
2. Runtime: **Python 3**.
3. Build Command: `pip install -r backend/requirements.txt -r backend/requirements-cloud.txt`
4. Start Command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Plano: **Free**.
6. Em **Environment Variables**, adicione:
   - `DATABASE_URL` = (cole a Internal Database URL do banco que você criou)
   - `ATLAS_SECRET_KEY` = qualquer texto longo e aleatório (ex: gere um em https://generate-secret.vercel.app/32 ou digite 32 caracteres aleatórios você mesmo)
7. Create Web Service.

## Passo 4 — Primeiro acesso

Abra a URL que o Render te deu. Na primeira vez, o próprio Atlas:
- cria as tabelas do banco,
- importa os dados de exemplo (histórico + operacionais, os mesmos que você já viu localmente),
- treina o modelo de ML,
- cria o usuário `admin` com senha aleatória.

Isso tudo acontece automaticamente no boot — pode levar 1-2 minutos na
primeira vez. **A senha do admin gerada aparece nos logs do Render**, não
na tela: no painel do serviço, aba **Logs**, procure por:

```
ATLAS - usuário administrador criado automaticamente:
   username: admin
   senha:    xxxxxxxxxxxx
```

Use isso para logar. Depois, crie os outros usuários e troque a senha do admin pela tela **Usuários**.

## Sobre o plano gratuito

O plano free do Render (e da maioria dos concorrentes) tem duas limitações típicas que valem saber:
- **O serviço "dorme"** depois de um tempo sem uso, e demora ~30s pra "acordar" na próxima visita. Isso é normal, não é bug.
- **O banco Postgres gratuito pode ter prazo de expiração** (histórico: 90 dias em alguns planos free). Verifique isso na página de preços do Render no momento em que você criar a conta, porque políticas de free tier mudam com frequência - se expirar, alguns provedores oferecem migrar pra um plano pago barato sem perder dados, avaliar isso quando chegar a hora.

Se esse tipo de limitação não servir pra sua operação, as alternativas mais diretas são Railway ou Fly.io - a estrutura do projeto (Dockerfile-free, variável `DATABASE_URL`, `PORT`) é compatível com qualquer um deles, só muda a tela de configuração.

## Se você já tinha usado o Atlas localmente com dados reais (SQLite)

O deploy em nuvem começa com um banco Postgres vazio (populado só com os
dados de exemplo, se a pasta `seed_data/` existir). Se você já importou
dados reais localmente (fechamentos, custos, ações de acompanhamento,
pedidos de compra) e não quer perder isso, existe um script que copia
tudo do seu `atlas.db` local pro Postgres da nuvem — testado com dados
reais antes desta atualização ser entregue.

**Passo a passo:**

1. Suba o Atlas na nuvem primeiro (Passos 1-4 acima), mesmo que vazio -
   isso cria as tabelas no Postgres.
2. No painel do Render, vá em **atlas-db** (o banco) → aba **Connect** →
   copie a **External Database URL** (começa com `postgresql://` e tem
   um host público, diferente da Internal Database URL que você usou no
   Passo 3 - a interna só funciona de dentro do Render).
3. No seu computador, com o `atlas.db` local intacto, na pasta `backend`:

```powershell
python -m data_import.migrar_sqlite_para_postgres --origem atlas.db --destino "COLE_A_EXTERNAL_DATABASE_URL_AQUI"
```

4. O script mostra quantas linhas migrou de cada tabela. Ao final, entre
   na URL da nuvem - seus dados devem estar todos lá (fechamentos,
   custos, ações, pedidos de compra, usuários com a mesma senha de antes).
5. **Depois de migrar**, rode uma vez pela tela **Painel Inventário** e
   **Acurácia Ponderada** pra confirmar que os números batem com o que
   você via localmente.

**Se der erro de "relation already exists" ou parecido**, é porque o
Postgres já tinha dados de exemplo do primeiro boot - normal, o script
tenta criar as tabelas de novo mas isso não apaga o que já existe; o
problema seria se os dados de EXEMPLO se misturarem com os seus dados
REAIS. Nesse caso, antes de migrar, limpe o banco na nuvem primeiro (no
painel do Render, banco → aba Shell → `TRUNCATE` nas tabelas, ou delete e
recrie o banco do zero) e migre num Postgres realmente vazio.

## Passo 5 — Compartilhar com a equipe

Depois que o Atlas estiver no ar (com ou sem migração de dados), é só:

1. Manda a URL (`https://atlas-xxxx.onrender.com`) pra equipe - qualquer navegador, celular incluído.
2. Logado como admin, vá em **Usuários** → crie uma conta pra cada pessoa, escolhendo o papel certo:
   - **admin**: acesso completo (cadastros, usuários, backup, retreino de ML)
   - **analista**: importa dados, confirma divergências, cria ações - não gerencia usuários/cadastros
   - **leitura**: só visualiza os painéis, sem poder alterar nada
3. Cada pessoa loga com usuário/senha próprios - sem precisar compartilhar a senha do admin.

Pronto - a partir daqui todo mundo acessa o mesmo sistema, os mesmos dados, ao mesmo tempo, de onde estiver.
