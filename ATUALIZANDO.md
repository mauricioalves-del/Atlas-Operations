# Como atualizar o Atlas sem perder dados

## Se você está usando a versão na nuvem (Git + Render) - leia isto primeiro

Existe um jeito bem mais simples agora: o script **`atualizar.ps1`**, na
raiz do projeto. Ele faz o `git add` / `git commit` / `git push` sozinho
- você só precisa:

1. Copiar os arquivos novos (do zip que o Claude te mandar) por cima da
   sua pasta do projeto - pode copiar `backend` e `frontend` inteiras
   sem medo, o `.gitignore` já protege `atlas.db`, `.secret_key` e
   `backups/` de serem enviados ou apagados.
2. Clicar com o botão direito em **`atualizar.ps1`** → **"Executar com
   PowerShell"** (ou abrir o PowerShell na pasta do projeto e rodar
   `.\atualizar.ps1`).
3. Esperar a mensagem de sucesso. O Render redeploya automaticamente.

Isso resolve pra quem já está na nuvem. **O aviso abaixo, sobre nunca
sobrescrever `atlas.db`, é sobre o SEU COMPUTADOR LOCAL** - continua
valendo mesmo usando o script, porque o arquivo nunca deveria estar no
Git de qualquer forma (na nuvem os dados ficam no Postgres, não num
arquivo). Mas se você também usa o Atlas rodando localmente (sem nuvem),
o processo manual abaixo ainda se aplica a esse uso local.

---

**O que aconteceu até agora**: cada zip que te entreguei vinha com o
projeto inteiro, incluindo um `backend/atlas.db` de exemplo. Quando você
substituiu a pasta `backend` inteira, esse arquivo de exemplo sobrescreveu
o seu banco real - foi assim que os dados preenchidos se perderam. A
partir de agora, siga este processo.

## Regra de ouro

**Nunca copie/substitua a pasta `backend` inteira.** Copie só os
arquivos de código. Nunca toque em:

- `backend/atlas.db` — seu banco de dados real
- `backend/.secret_key` — a chave que mantém todo mundo logado
- `backend/backups/` — os backups automáticos

## Passo a passo seguro

1. **Antes de tudo**, baixe um backup pela própria tela do sistema:
   Menu → **Auditoria** → "Baixar backup agora". Guarde esse arquivo
   fora da pasta do projeto (Desktop, Google Drive, onde for).

2. Extraia o zip novo numa pasta **separada** (não dentro da pasta do
   projeto atual) - por exemplo `Desktop\atlas_novo`.

3. Copie **apenas** estas pastas/arquivos do zip novo para dentro do seu
   projeto atual, substituindo o que já existe:
   - `backend\app\` (a pasta inteira, substitui)
   - `backend\data_import\` (a pasta inteira, substitui)
   - `backend\requirements.txt` e `backend\requirements-cloud.txt`
   - `backend\tests\` (se quiser rodar os testes)
   - `frontend\` (a pasta inteira, substitui)
   - `render.yaml`, `DEPLOY.md`, `README.md`, `DECISOES.md` (na raiz)

4. **NÃO copie** `backend\atlas.db`, `backend\.secret_key`, nem
   `backend\seed_data\` (a não ser que você queira reimportar os dados de
   exemplo, o que não é o seu caso).

5. Suba o servidor de novo. Ele mesmo já faz um backup automático no
   início (fica em `backend\backups\`), então mesmo que algo dê errado
   nessa atualização, tem como recuperar.

## Se algo já deu errado e você quer recuperar

Olhe dentro de `backend\backups\` — deve ter cópias automáticas com nome
`auto_AAAAMMDD_HHMMSS.db`. Escolha a mais recente de antes do problema,
renomeie pra `atlas.db`, e coloque em `backend\atlas.db` (com o servidor
parado). Ou, pela tela **Auditoria → Restaurar backup** (se você tiver
uma cópia baixada), que faz isso pela interface.

## Um jeito de tornar isso à prova de erro

Se quiser eliminar esse risco de vez, o caminho é usar Git pra atualizar
(igual expliquei no `DEPLOY.md` pro deploy em nuvem) em vez de
copiar/colar pastas manualmente - o Git nunca toca no `atlas.db` porque
esse arquivo fica fora do controle de versão (`.gitignore`). Isso exigiria
configurar o Git localmente também, não só pro deploy. Se quiser, te
guio nisso a partir daqui.
