# Shelf Life — coluna "Grupo" + exclusão de Box/Box 2

## O que mudou

A aba `Lote_Sistema` do arquivo exportado do sistema agora pode trazer uma
coluna **Grupo** (Produto Acabado, Embalagem, Ativo Imobilizado, Materia
Prima, SubConjunto...). O importador do Atlas passou a ler essa coluna
(campo novo `grupo_produto` no lote) e o indicador de Shelf Life (Farol +
Mapeamento de Risco por Obsolescência) agora desconsidera:

- Itens do grupo **Embalagem** ou **Ativo Imobilizado** (antes, só dava
  pra tentar excluir Embalagem por palavra-chave na descrição — e isso
  não pegava tudo, ex: "Luva LO 80GR ao leite com Praliné" é embalagem
  mas não tem nenhuma palavra da lista; "Ativo Imobilizado" não tinha
  filtro nenhum).
- Almoxarifados **Box** e **Box 2** (novo pedido) — em qualquer lote,
  independente do Grupo.

**Retrocompatível:** se você reimportar uma planilha no formato antigo
(sem a coluna Grupo), o Atlas não quebra — só volta a usar o filtro por
palavra-chave na descrição pros lotes daquela importação (menos preciso,
mas funcional). Assim que reimportar no formato novo (com Grupo), a
precisão volta ao normal.

## Arquivos alterados

- `backend/app/models.py` — novo campo `grupo_produto` em `LoteShelfLife`.
- `backend/app/database.py` — migração automática (`ALTER TABLE`) que
  adiciona a coluna nova no banco existente, sem precisar recriar nada.
- `backend/app/shelf_life.py` — leitura da coluna "Grupo", exclusão por
  grupo e por almoxarifado (Box/Box 2) no Farol e no Mapeamento de Risco
  por Obsolescência.
- `backend/app/routers/shelf_life_router.py` — aceita `grupo_produto`
  também no cadastro manual de lote, e devolve o campo na listagem.
- `frontend/index.html` — hint atualizado na tela de importação explicando
  a coluna Grupo e a exclusão de Box/Box 2.

Nenhuma migração manual necessária — a coluna nova é criada
automaticamente no próximo boot do backend.

## Validado (banco de teste local, com o arquivo que você enviou)

Importei o `Lote_Sistema.xlsx` que você mandou (1.060 linhas). Confirmado
com um cálculo manual em paralelo sobre o mesmo arquivo:

- 52 lotes com quantidade > 0 e ativos estavam em Box/Box 2 — todos
  excluídos do indicador (bate exatamente com a contagem manual).
- 241 lotes (dentre os que não são Box/Box 2, ativos e com quantidade >
  0) eram do grupo Embalagem ou Ativo Imobilizado — todos excluídos (bate
  exatamente com a contagem manual). Nenhum item de embalagem (ex: "Luva
  LO 80GR...", "Caixa Base LO 80g") apareceu na lista final do Farol nem
  do Mapeamento de Risco.
- Testei também reimportar uma versão do mesmo arquivo sem a coluna Grupo
  (simulando o formato antigo que você usava até agora): a importação não
  quebrou, só voltou a excluir menos itens (94 em vez de 241) porque caiu
  pro filtro por palavra-chave — confirma o problema que você relatou, e
  confirma que a correção resolve.
- Geração do MBR testada depois da reimportação — sem regressão.
