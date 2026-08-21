# atlas_fix_mbr_secao3_reorder.zip (22/08/2026)

## Antes de aplicar

Mesmo lembrete de sempre: o Atlas roda no Render, e só passa a usar código
novo depois de zip + redeploy manual. Suba este zip e refaça o deploy do
backend antes de gerar um MBR novo pra testar — sem isso, o arquivo gerado
sai idêntico ao anterior.

## O que é este pacote

Dois pedidos seus, nesta ordem:

1. Dar destaque ao IAP/IAQ (Acurácia Ponderada) na Seção 2, por ORDEM —
   sem reduzir o conteúdo item a item.
2. Fundir a Seção 3 ("Mapeamento de Riscos e Passivos", nativa) com a
   antiga Seção 4 ("Outros", dashboards externos), substituindo os
   indicadores nativos que já têm um dashboard externo com modelo aprovado
   cobrindo o mesmo assunto.

Só `backend/app/mbr_generator.py` mudou. Nenhum extrator, endpoint ou
cálculo foi alterado — é 100% reorganização de quais slides entram, em que
ordem, dentro do relatório já existente.

## 1) Seção 2 — Inventários e Movimentados: IAP/IAQ primeiro

Ordem antiga: Painel de Inventário → Painel — Detalhamento Financeiro →
IAP → IAQ → Concentração de Risco → Detalhamento por Faixa → Controle de
Movimentados → Scorecard.

Ordem nova: IAP → IAQ → Concentração de Risco → Detalhamento por Faixa →
Painel de Inventário → Painel — Detalhamento Financeiro → Controle de
Movimentados → Scorecard.

Nenhum slide teve conteúdo, cálculo ou layout interno alterado — só a
ORDEM de chamada em `montar_pptx_mbr`. Testado gerando as 8 slides na nova
ordem com dado sintético (renderizado e inspecionado imagem a imagem):
página segue contínua, nenhum slide quebrado.

## 2) Fusão da Seção 3 com a antiga Seção 4 ("Outros")

**Removidos** (nativos, substituídos por um dashboard externo com modelo
já aprovado cobrindo o mesmo assunto):

- Mapeamento de Passivos
- Passivos — Evolução e Concentração
- Shelf Life

**Aviso importante, que você já confirmou ciente antes desta mudança:** os
3 slides removidos usavam dado 100% exato, direto do banco do Atlas
(fechamento do mês exato; categorização de motivo própria do Atlas). Os
dashboards externos que passam a ser a única fonte pra esses assuntos —
Dashboard Baixas Operacionais e Farol de Shelf-Life — são retrato datado de
uma janela diferente (~60 dias corridos no caso de Baixas Operacionais;
momento da exportação do Stock Savvy no caso do Farol de Shelf-Life) e usam
categorização de motivo própria da equipe, não a do Atlas. Os números dos
dois podem não bater entre si por desenho — não vai ser bug se isso
acontecer.

**Ficam** (sem dashboard externo aprovado cobrindo o mesmo assunto):
Mapeamento de Risco — Obsolescência, Testes Industriais, FEFO, Scorecard de
Mapeamento de Riscos.

**Entram como conteúdo novo** (já existiam na antiga Seção 4, sem
equivalente nativo): Recuperação de Shelf + Evolução Mensal, Dispersão de
Ficha Técnica.

Ordem final da seção fundida (agora Seção 3 de 4, era Seção 3 de 5):

1. Dashboard Baixas Operacionais
2. Dashboard Baixas Operacionais — Evolução Mensal
3. Farol de Shelf-Life
4. Farol de Shelf-Life — Risco por Almoxarifado
5. Mapeamento de Risco — Obsolescência
6. Recuperação de Shelf
7. Recuperação de Shelf — Evolução Mensal
8. Dispersão de Ficha Técnica
9. Testes Industriais
10. FEFO
11. Scorecard de Mapeamento de Riscos (capítulo-síntese, mesmo padrão do
    Scorecard de Inventário por Almoxarifado que já fecha a Seção 2)
12. Indicadores dinâmicos extras (se houver algum cadastrado)

A seção "Outros" deixou de existir — o relatório passa de 5 seções pra 4.
Corrigi também um efeito colateral que essa mudança causaria se eu não
tivesse revisado com atenção: a capa de cada seção mostra "SEÇÃO X DE N" —
esse "N" estava fixo em "5" no código; agora é "4".

Também corrigi 2 textos que apareciam NO SLIDE (não só em comentário)
chamando o Dashboard Baixas Operacionais de "controle paralelo" — não faz
mais sentido chamar de paralelo algo que passou a ser a única fonte.

## Testado

- `python3 -m py_compile` limpo.
- Seção 2 completa (8 slides) gerada na ordem nova com dado sintético,
  renderizada e inspecionada imagem a imagem.
- Seção 3 fundida completa (capa + 11 slides) gerada na ordem nova,
  usando os MESMOS arquivos HTML reais de Farol de Shelf-Life, Recuperação
  de Shelf e Baixas Operacionais já validados na Fase 2 (não dado
  fabricado) — renderizada e inspecionada imagem a imagem: capa mostra
  "SEÇÃO 3 DE 4" corretamente, títulos/legendas novos cabem sem quebrar
  linha, paginação contínua, nenhum slide com defeito visual.
- Mapeamento de Risco — Obsolescência, Dispersão de Ficha Técnica, Testes
  Industriais e FEFO testados também pelo caminho "ainda não
  enviado/sem dados" (mensagem de estado, já existente) — sem exceção.

Não testado nesta rodada (dependeria de um MBR gerado de verdade, com
banco de produção e os dashboards externos reais enviados): se a fusão
bate exatamente com o que você tinha em mente ao ver o PDF final completo.
Recomendo gerar um MBR novo depois do deploy e revisar a Seção 3 fundida
com atenção antes de considerar isso fechado.
