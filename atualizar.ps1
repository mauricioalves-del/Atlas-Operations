# atualizar.ps1 - script de atualização de um clique
#
# O que faz: pega tudo que mudou na pasta do projeto e envia pro GitHub
# (que por sua vez aciona o deploy automático no Render) - sem precisar
# digitar git add / git commit / git push na mão toda vez.
#
# Como usar:
#   1. Copie os arquivos novos (do zip que o Claude te mandar) por cima
#      da sua pasta do projeto, como sempre.
#   2. Clique com o botão direito neste arquivo -> "Executar com PowerShell"
#      (ou abra o PowerShell na pasta do projeto e rode: .\atualizar.ps1)
#
# Se aparecer um erro dizendo que a execução de scripts está desabilitada
# nesse computador, abra o PowerShell na pasta do projeto e rode em vez
# disso (só precisa fazer isso uma vez):
#   powershell -ExecutionPolicy Bypass -File .\atualizar.ps1
#
# Nunca toca em atlas.db, .secret_key ou backups/ - esses já ficam de
# fora do Git (.gitignore), então nem entram nesse processo.

Write-Host ""
Write-Host "=== Atlas - atualizacao automatica ===" -ForegroundColor Cyan
Write-Host ""

# Confirma que estamos numa pasta com repositorio git (evita rodar no lugar errado)
if (-not (Test-Path ".git")) {
    Write-Host "ERRO: essa pasta nao parece ser a raiz do projeto (nao encontrei a pasta .git)." -ForegroundColor Red
    Write-Host "Abra o PowerShell dentro da pasta 'Atlas\Atlas' (a que tem 'backend', 'frontend', 'render.yaml') e rode de novo." -ForegroundColor Yellow
    Read-Host "Pressione Enter para fechar"
    exit 1
}

# Garante que a identidade do git esta configurada (evita o erro "Author identity unknown")
$emailConfigurado = git config --global user.email
if (-not $emailConfigurado) {
    Write-Host "Configurando sua identidade no Git pela primeira vez..." -ForegroundColor Yellow
    git config --global user.email "atlas@local.com"
    git config --global user.name "Atlas Admin"
}

Write-Host "Verificando o que mudou..." -ForegroundColor Yellow
git add .

$statusResumo = git status --short
if (-not $statusResumo) {
    Write-Host ""
    Write-Host "Nada mudou desde o ultimo envio - o GitHub ja esta atualizado." -ForegroundColor Green
    Read-Host "Pressione Enter para fechar"
    exit 0
}

Write-Host "Arquivos alterados:" -ForegroundColor Yellow
git status --short
Write-Host ""

$dataHora = Get-Date -Format "dd/MM/yyyy HH:mm"
$mensagem = "Atualizacao automatica - $dataHora"

Write-Host "Salvando alteracoes..." -ForegroundColor Yellow
git commit -m "$mensagem" | Out-Null

Write-Host "Enviando para o GitHub (isso aciona o deploy automatico no Render)..." -ForegroundColor Yellow
git push

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== Envio concluido com sucesso! ===" -ForegroundColor Green
    Write-Host "O Render ja deve estar comecando o novo deploy - acompanhe em:" -ForegroundColor Green
    Write-Host "https://dashboard.render.com  ->  servico atlas  ->  Logs" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "=== Algo deu errado no envio (git push falhou) ===" -ForegroundColor Red
    Write-Host "Copie a mensagem de erro acima e mande para o Claude analisar." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Pressione Enter para fechar"
