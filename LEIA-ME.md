# Shelf Life — lotes já baixados continuavam no Farol como "Vencido"

## O problema

Você mostrou a tela "Lotes em risco" com 3 itens de sorvete (SKUs
05004156, 05004157, 05004158, lotes "V.06052026...") aparecendo como
"Vencido" — mesmo já tendo sido baixados/consumidos no sistema real (não
aparecem mais na planilha `Lote_Sistema.xlsx` mais recente).

## Causa raiz

O importador da planilha de Lote de Validade (`importar_linhas_lote_sistema`)
foi construído de propósito pra NUNCA apagar nada que não estivesse na
planilha nova — a ideia original era proteger lotes cadastrados manualmente
na tela. Só que isso também significava que um lote vindo de uma
importação ANTERIOR, e que sumiu da planilha porque foi consumido/baixado
no sistema real, ficava marcado como ativo pra sempre — reimportar a
planilha atualizava os lotes que continuavam lá, mas nunca desativava os
que saíram dela. Confirmei isso diretamente: os 3 SKUs do seu print não
aparecem em nenhuma linha do arquivo `Lote_Sistema.xlsx` mais recente que
você já tinha enviado — ou seja, são resíduo de uma importação mais
antiga.

## Correção

Agora, toda vez que você reimporta a planilha de Lote de Validade, qualquer
lote que:

- tenha vindo de uma importação de planilha anterior (não cadastro manual), **e**
- não apareça em NENHUMA linha da planilha nova,

é automaticamente **desativado** (sai do Farol e do Mapeamento de Risco de
Obsolescência). Não apago a linha do banco — só marco como inativo, pra
manter o histórico e pra o caso de o item voltar a aparecer numa planilha
futura (ex: reposição de estoque), quando ele é reativado automaticamente
com a validade/quantidade novas.

**Lotes cadastrados manualmente na tela Shelf Life continuam protegidos** —
uma importação de planilha nunca desativa um lote manual, só os que vieram
de uma importação anterior.

O resultado da importação agora também informa quantos itens foram
desativados (ex: "1.060 atualizado(s) · 3 desativado(s) (não aparecem mais
na planilha)").

## Validado

Reproduzi exatamente o seu cenário num banco de teste: inseri os 3 lotes
de sorvete como estavam na sua tela (ativos, "Vencido") e reimportei o
`Lote_Sistema.xlsx` mais recente que você já tinha enviado. Resultado:
1.060 lotes atualizados normalmente, e os 3 lotes de sorvete corretamente
desativados — confirmei que eles não aparecem mais na lista de "Lotes em
risco" depois da reimportação.

Testei também os dois casos que não podiam quebrar: um lote cadastrado
manualmente continuou ativo depois de reimportar a planilha (não foi
tocado), e um lote que eu simulei "voltando a aparecer" numa planilha
seguinte foi reativado normalmente com a validade e quantidade da nova
linha.

## Arquivos alterados

- `backend/app/shelf_life.py` — `importar_linhas_lote_sistema` agora
  desativa lotes de importação que saíram da planilha.
- `backend/app/routers/shelf_life_router.py` — docstring do endpoint
  atualizada.
- `frontend/app.js` — mostra a contagem de itens desativados no resultado
  da importação.
- `frontend/index.html` — hint da tela Importar explicando o novo
  comportamento.

Nenhuma migração de banco necessária.
