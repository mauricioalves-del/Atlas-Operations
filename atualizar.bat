@echo off
REM atualizar.bat - clique duas vezes aqui para atualizar o Atlas.
REM
REM Existe so para chamar o atualizar.ps1 de um jeito que NUNCA esbarra
REM no bloqueio de "execucao de scripts desabilitada" do PowerShell -
REM arquivos .bat nao sao afetados por essa politica, entao isso sempre
REM funciona, mesmo num Windows que nunca rodou um script PowerShell antes.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizar.ps1"
