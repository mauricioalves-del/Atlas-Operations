# atualizar.ps1 - script de atualização de um clique
#
# O que faz: pega tudo que mudou na pasta do projeto e envia pro GitHub
# (que por sua vez aciona o deploy automático no Render) - sem precisar
# digitar git add / git commit / git push na mão toda vez.
#
# Como usar (recomendado):
#   1. Copie os arquivos novos (do zip que o Claude te mandar) por cima
#      da sua pasta do projeto, como sempre.
#   2. Dê DUPLO CLIQUE em "atualizar.bat" (não neste arquivo .ps1 direto).
#      O .bat sempre funciona, mesmo se a política de execução do
#      PowerShell deste computador estiver bloqueando scripts - ele já
#      chama este .ps1 da forma que evita esse bloqueio, sem precisar
#      lembrar de nenhum comando extra.
#
# Alternativa manual (se preferir rodar direto no PowerShell, sem o .bat):
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

# 02/09/2026 - CORRECAO DE BUG: antes, quando $statusResumo vinha vazio (nada
# pra commitar), o script dizia direto "o GitHub ja esta atualizado" e
# fechava - mas "nada pra commitar" so quer dizer que a pasta local esta
# limpa, NAO que o ultimo commit chegou a ser enviado. Se um envio anterior
# tivesse commitado localmente e falhado so no "git push" (por exemplo, sem
# internet/DNS naquele momento - ja aconteceu), toda vez que a pessoa rodasse
# de novo o script via cair direto nessa mensagem tranquilizadora, sem NUNCA
# tentar reenviar o commit que ficou preso so na maquina local. A correcao:
# sempre confere se o HEAD local esta a frente do remoto (com um "git fetch"
# antes, pra nao comparar com uma referencia desatualizada) antes de decidir
# que nao ha nada a enviar - se estiver a frente, tenta o push de novo mesmo
# sem nenhum arquivo novo pra commitar.
git fetch origin 2>$null | Out-Null
$branchAtual = git rev-parse --abbrev-ref HEAD
$commitsNaoEnviados = git rev-list --count "origin/$branchAtual..HEAD" 2>$null

if ((-not $statusResumo) -and ($commitsNaoEnviados -eq "0")) {
    Write-Host ""
    Write-Host "Nada mudou desde o ultimo envio - o GitHub ja esta atualizado." -ForegroundColor Green
    Read-Host "Pressione Enter para fechar"
    exit 0
}

if ($statusResumo) {
    Write-Host "Arquivos alterados:" -ForegroundColor Yellow
    git status --short
    Write-Host ""
    $dataHora = Get-Date -Format "dd/MM/yyyy HH:mm"
    $mensagem = "Atualizacao automatica - $dataHora"
    Write-Host "Salvando alteracoes..." -ForegroundColor Yellow
    git commit -m "$mensagem" | Out-Null
} else {
    Write-Host ""
    Write-Host "Ha $commitsNaoEnviados commit(s) salvos localmente que nunca chegaram a ser enviados ao GitHub (uma tentativa anterior deve ter falhado so no envio) - tentando enviar de novo..." -ForegroundColor Yellow
}

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
