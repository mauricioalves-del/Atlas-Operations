# Auditoria FEFO importada — pacote de atualização

Este pacote adiciona ao Atlas um painel nativo que consolida o histórico de
auditoria de FEFO que o estagiário (André) já produz hoje por fora do
sistema (notebooks `Auditar_FEFO.ipynb` + `DashBoard_FEFO.ipynb`). O Atlas
**não recalcula** a comparação lote-vs-movimentação — ele importa e
consolida o resultado já apurado por esse processo, conforme decidido.

O slide de FEFO do MBR **não foi alterado** — continua usando o dashboard
HTML externo, como já estava.

## Arquivos alterados

- `backend/app/models.py` — novo modelo `AuditoriaFefo` (append no fim do arquivo).
- `backend/app/fefo.py` — lógica de importação/consolidação (append no fim do arquivo).
- `backend/app/routers/fefo_router.py` — 4 novos endpoints (append no fim do arquivo).
- `frontend/index.html` — novo painel "Auditoria FEFO — histórico importado" na tela FEFO.
- `frontend/app.js` — carregamento do painel, gráfico, tabelas e os dois uploads.

Basta sobrepor esses 5 arquivos nos mesmos caminhos do seu repositório atual
e fazer o deploy normalmente (nenhuma migração manual de banco é
necessária — o Atlas cria a tabela nova automaticamente no próximo boot,
igual às outras tabelas).

## Como importar o histórico depois do deploy

Na tela FEFO do Atlas, dois uploads novos aparecem no topo do novo painel:

1. **Importar auditoria diária** — selecione os Excels diários que o
   processo do André já gera (`Auditoria_FEFO_DDMMAAAA.xlsx`, aba "Todas as
   Movimentações"). Pode selecionar vários de uma vez. Reimportar o mesmo
   dia substitui só as linhas daquele dia — não duplica.
2. **Importar consolidado (HTML)** — suba o `Controle - FEFO.html` que o
   André já mantinha, pra estender o histórico aos dias mais antigos (sem
   Excel diário bruto). Dias que já tiverem sido cobertos pelo upload (1)
   são automaticamente ignorados nesse import, pra nunca sobrescrever o
   dado mais detalhado com o menos detalhado.

Ordem recomendada: primeiro suba todos os Excels diários que você tiver,
depois suba o HTML consolidado por último (assim ele já sabe quais dias
pular).

## Validação feita nesta sessão

Rodei os dois importadores localmente contra os 8 Excels diários e o HTML
consolidado que você enviou, num banco de teste isolado (não no seu banco
de produção — não tenho acesso a ele). Confirmado:

- Os 8 arquivos diários importaram exatamente as mesmas contagens de
  quebra que cada um já reporta na própria aba "Resumo" (total: 27
  quebras, 325 linhas).
- O HTML consolidado importou 973 linhas (36 dias, 20/05 a 21/07/2026) e
  pulou corretamente os 5 dias que já estavam cobertos pelos Excels
  diários (22/07, 24/07, 28/07, 31/07, 05/08) — sem duplicar nem
  sobrescrever o dado mais detalhado.
- Resumo agregado final: 1.298 movimentos, 60 quebras (4,6%), 44 dias com
  dado, 20/05 a 12/08/2026.
- Reimportar o mesmo arquivo duas vezes não duplica linhas (testado com o
  arquivo de 24/07).
- Upload de arquivo inválido ou sem a aba esperada retorna um erro claro
  por arquivo, sem travar a importação dos outros arquivos do lote.
- Permissão: usuário com papel "leitura" consegue ver os relatórios mas
  recebe 403 ao tentar importar — só admin/analista importam.

O histórico real, porém, só existe no seu banco de produção depois que
você (ou quem administra o Atlas) subir esses mesmos arquivos pela tela,
já que não tenho acesso de escrita ao banco em produção.
