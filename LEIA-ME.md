# MBR — slide de FEFO agora usa a Auditoria FEFO importada

## O pedido

Você pediu: "Use o arquivo HTML para alimentar a construção do MBR no módulo
FEFO. O mesmo tem mais informações e bases de registro." Como havia duas
fontes de FEFO possíveis no Atlas hoje, perguntei qual — e você confirmou
**"Auditoria FEFO importada"**: a mesma base que já alimenta o painel
"Auditoria FEFO — histórico importado" na tela FEFO (importada por lá via
Excel diário do André ou pelo dashboard HTML consolidado dele).

## O que mudou

Antes, o slide de FEFO do MBR (e o bloco de FEFO no Resumo Executivo) vinham
do dashboard "Controle de FEFO", enviado em Auditoria > Outros Dashboards —
um arquivo com só os totais já agregados pelo estagiário.

Agora os dois vêm da tabela **Auditoria FEFO importada**, que tem muito mais
detalhe por registro: lote movimentado, validade do lote, e qual seria o
lote mais antigo disponível na Fábrica. Isso é a mesma base já usada no
painel "Auditoria FEFO — histórico importado" da própria tela FEFO — não
precisa importar nada de novo pra alimentar o MBR, só manter esse painel
atualizado como você já faz.

### Slide de FEFO

- KPIs trocados: "Movimentos Auditáveis no Mês", "Quebras de FEFO", "Taxa de
  Quebra" e "Sem Correspondência no Mês" (antes comparava com o total de
  transferências do Atlas, o que não fazia mais sentido com a fonte nova).
- Gráfico de produtos com mais quebras: mesma ideia, agora a partir da
  Auditoria FEFO importada.
- Tabela de quebras por destino: simplificada pra Destino + Quebras (a fonte
  nova não tem o "total movimentado por destino" que o dashboard antigo
  trazia — só quantas quebras por destino).
- Rodapé mostra a origem dos dados do mês (auditoria diária e/ou dashboard
  consolidado) e quantos movimentos ficaram sem correspondência (não contam
  na taxa de quebra).
- Se a Auditoria FEFO importada nunca recebeu nenhum histórico, o slide
  mostra um aviso apontando pro painel certo ("Auditoria FEFO — histórico
  importado" na tela FEFO) — não mais pra Outros Dashboards, que não é o
  caminho certo pra essa fonte.
- Se o histórico existe mas não tem nenhum movimento auditável NO MÊS do
  relatório, mostra um aviso separado (sem confundir com "nunca foi
  importado").

### Resumo Executivo

O texto de FEFO em Avanços/Atenções/Decisões foi atualizado pros mesmos
números (movimentos auditáveis, quebras, taxa) e pra citar "Auditoria FEFO
importada" em vez do dashboard antigo.

## O que NÃO mudou

O dashboard "Controle de FEFO" continua existindo em Auditoria > Outros
Dashboards, se você ainda quiser consultá-lo por lá — só não alimenta mais o
MBR. Não precisei remover nada dessa tela pra fazer essa troca.

## Validado

Testei os três cenários possíveis do slide num banco de teste com histórico
real de Auditoria FEFO (maio a agosto de 2026, 1.298 registros):

- **Mês com dado real** (julho/2026): 353 movimentos auditáveis, 22 quebras
  (6,2%), 45 sem correspondência — slide e Resumo Executivo consistentes,
  conferi visualmente (sem sobreposição, sem corte de texto).
- **Histórico existe mas sem dado NESSE mês** (abril/2026, fora do período
  importado): mostra o aviso certo, sem confundir com "nunca foi
  importado".
- **Nenhum histórico importado ainda**: mostra o aviso apontando pro painel
  "Auditoria FEFO — histórico importado" da tela FEFO.

Também gerei o MBR completo (19 slides) pra julho/2026 e revisei o arquivo
inteiro (`markitdown` + validador de estrutura do arquivo) sem nenhum
problema.

## Arquivo alterado

- `backend/app/mbr_generator.py` — nova função
  `_extrair_resumo_auditoria_fefo`, `_slide_fefo` reescrito, bloco de FEFO
  do Resumo Executivo atualizado, e a coleta de dados do MBR (`fefo_externo`)
  agora chama a fonte nova.

Nenhuma migração de banco necessária — a tabela de Auditoria FEFO importada
já existe e você já usa pra alimentar o painel da tela FEFO.
