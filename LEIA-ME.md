# Correção do erro de deploy no Render

## O que aconteceu

O deploy falhou ("Exited with status 1") logo na inicialização, numa
consulta a `baixas_operacionais` feita por uma limpeza automática que já
existia (`_remover_duplicatas_status_baixa_operacional`, roda em todo
startup).

## Causa raiz

Na entrega da IA generativa, eu adicionei as colunas novas
(`ia_gen_categoria`, `ia_gen_resumo` etc.) em dois lugares: na declaração
do modelo Python (`models.py`) e num bloco de `ALTER TABLE` dentro de
`garantir_colunas_novas()` (`database.py`). O problema foi a **ordem**
dentro dessa função: eu coloquei o bloco de `ALTER TABLE` perto do FINAL
da função, mas uma consulta que já existia mais no INÍCIO dela
(`_remover_duplicatas_status_baixa_operacional`) lê a tabela inteira via
SQLAlchemy - e uma consulta assim sempre pede TODAS as colunas que o
modelo Python declara, mesmo antes do `ALTER TABLE` ter rodado. Resultado:
no banco de produção (que já existia, sem essas colunas ainda), essa
consulta tentava ler uma coluna que ainda não tinha sido criada -> erro
-> deploy falha.

Isso só apareceu em produção porque lá o banco já existia de antes (com
histórico real); num banco novo, criado do zero, `Base.metadata.create_all`
já cria a tabela com todas as colunas de uma vez, então o bug nunca teria
aparecido nos meus testes anteriores (que sempre partiam de um banco
vazio).

## Correção

Só um arquivo mudou: `backend/app/database.py`. Os blocos de `ALTER TABLE`
das colunas `ia_gen_*` (baixas operacionais e divergências) foram movidos
pro **topo** da função `garantir_colunas_novas()` - antes de qualquer outra
migração ou limpeza que possa consultar essas tabelas. Não muda o que é
adicionado, só quando.

## Validado

Reproduzi o bug de propósito antes de corrigir: criei um banco com o
schema ANTIGO (sem as colunas `ia_gen_*`, simulando o banco de produção de
antes desta entrega), com uma divergência e uma baixa já cadastradas, e
subi o Atlas com o código novo por cima desse banco - confirmei que ele
quebrava exatamente como no seu print do Render. Depois da correção,
repeti o mesmo teste: o Atlas sobe sem erro, as colunas novas são criadas
certinho, e as duas linhas que já existiam (baixa e divergência) continuam
lá, intactas.

## Como aplicar

Só substitua `backend/app/database.py` pelo arquivo deste pacote e faça
o deploy de novo no Render (o `Rollback` não é necessário - esse arquivo
já resolve o problema do commit que falhou). Nenhuma outra mudança é
necessária; as colunas continuam sendo criadas automaticamente no próximo
boot, sem passo manual.
