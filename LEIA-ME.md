# atlas_fix_divergencias_ordenacao_filtros.zip (26/08/2026)

## Antes de aplicar

Mesmo lembrete de sempre: o Atlas roda no Render, e só passa a usar código
novo depois de zip + redeploy manual. Este pacote mexe em backend E
frontend — suba os dois (`backend/app/routers/divergencias_router.py` e os
3 arquivos de `frontend/`) e refaça o deploy antes de testar.

## O que você pediu

Na tela de Divergências (`Painel de Divergências` → aba "Divergências"),
com as duas telas que você mandou:

> "Adicionar classificação de valores para as colunas de numeros, do maior
> para o menor. Fixar cabeçalho no topo e adicionar filtro para
> recorrentes e baixas operacionais em aberto."

Três coisas, as três implementadas:

## 1) Ordenação nas colunas de número (ID, Valor, Confiança)

Cliquei no cabeçalho de qualquer uma das 3 colunas numéricas da tabela
(**ID**, **Valor**, **Confiança**) e ela ordena a lista inteira — não só a
página carregada — do maior pro menor (como você pediu). Clicar de novo na
mesma coluna inverte pra menor→maior; clicar numa coluna diferente sempre
começa em maior→menor. Uma setinha (▼/▲) ao lado do nome da coluna mostra
qual está ativa e em que direção.

**Importante**: como a lista é paginada no servidor (50 por página), a
ordenação teve que entrar na própria consulta ao banco (`ORDER BY`), não
só reordenar o que já estava na tela — senão "do maior pro menor" só valeria
dentro de cada página de 50, não da lista toda. Isso significa que a API
`GET /divergencias` agora aceita `ordenar_por` (`id` | `valor` |
`confianca`) e `ordenar_direcao` (`asc` | `desc`) — sem esses parâmetros, o
comportamento é idêntico a antes (mais recente primeiro, por data). Não
toquei em Data nem Descrição pra ordenação — Data continua sendo a ordem
padrão sem clique nenhum, e as outras colunas não são "número".

Divergências sem confiança calculada (`Confiança = —`) sempre ficam no
final da lista quando você ordena por essa coluna, tanto maior→menor
quanto menor→maior — pra não "furar" pro topo do ranking.

## 2) Cabeçalho fixo no topo

O cabeçalho da tabela (ID, SKU, Descrição, Almoxarifado, Data, Valor,
Hipótese (IA), Confiança, Status) agora fica sempre visível enquanto você
rola pelas divergências da página atual.

Pra isso funcionar direito, precisei mudar como a lista rola: em vez da
página inteira rolar (cabeçalho junto), a **tabela em si virou uma caixa
com altura limitada e rolagem própria** (ocupa a altura da tela menos o
espaço da barra de filtros) — é dentro dessa caixa que o cabeçalho fica
fixo. Os filtros de busca/almoxarifado/status continuam sempre visíveis
acima, e a paginação ("Anterior/Próxima") saiu de dentro da caixa e ficou
fixa logo abaixo dela — assim você não precisa rolar até o fim da lista
pra trocar de página.

Achei o motivo de isso não funcionar só com `position: sticky` direto no
cabeçalho (testei e não colava no topo antes de fazer essa mudança): o
layout raiz da aplicação (`.shell`, usado em toda tela do Atlas) tem uma
propriedade (`overflow: hidden`, usada só pra recortar a animação de fundo)
que sem querer também vira o "recipiente de rolagem" pro cabeçalho fixo se
grudar — só que ele nunca rola de verdade sozinho, então o cabeçalho nunca
ficava fixo em lugar nenhum. Resolvido dando à própria caixa da tabela essa
responsabilidade, sem tocar em `.shell` (que é global — não quis arriscar
efeito colateral na animação de fundo de todas as outras telas por causa
de um pedido específico desta tela).

**Isso está limitado só à tela de Divergências** — as outras ~25 tabelas
do sistema continuam exatamente como estavam, sem cabeçalho fixo.

**No celular**, desliguei esse comportamento (cabeçalho fixo + caixa com
altura limitada) e mantive o de sempre (página inteira rola). O motivo:
nas telas estreitas o Atlas já tem um tratamento próprio pra tabela (ela
vira uma caixa com rolagem horizontal, pra caber tabelas largas numa tela
pequena) e as duas técnicas juntas não se combinam bem — testei e preferi
manter o comportamento mobile de sempre a arriscar um cabeçalho fixo
quebrado nesse caso.

## 3) Dois filtros novos: Recorrentes e Baixas operacionais em aberto

Dois checkboxes novos na barra de filtros, ao lado do filtro de Status —
combinam livremente com busca/almoxarifado/status (e entre si).

- **Recorrentes**: mostra só divergências cujo SKU já apareceu em **mais de
  uma divergência detectada** (em qualquer almoxarifado, data ou status) —
  mesmo critério que já existe hoje no "Top 10 Itens Mais Recorrentes em
  Divergência" (tela de Fechamentos). Essa checagem é sobre o SKU no
  histórico inteiro do sistema, não só nas linhas que batem com os outros
  filtros da tela no momento — assim "recorrente" continua significando a
  mesma coisa não importa que outro filtro esteja ligado.

- **Baixas operacionais em aberto**: mostra só divergências que já têm uma
  baixa operacional (Lovable) **pendente** (ainda não aprovada nem
  reprovada) batendo com ela — o mesmo sinal que já gera aquele ícone 🕒 ao
  lado do SKU na lista hoje (correlação SKU + Almoxarifado + quantidade,
  ver `aviso_baixa_pendente`). Não inventei um conceito novo pra "em
  aberto" — reaproveitei o que o Atlas já calculava, só virou filtro
  também, não só um aviso visual.

**Único ponto de atenção de desempenho**: diferente dos outros filtros
(que viram `WHERE` direto no banco), "Baixas operacionais em aberto"
precisa calcular a correlação de cada divergência aberta uma por uma antes
de poder paginar direito — é mais pesado que os outros filtros, mas não
deve pesar de verdade no volume de dados de hoje. Se algum dia a lista de
divergências abertas ficar muito grande e esse filtro específico ficar
lento, me avisa que otimizo isso separadamente.

## Duas decisões que vale você confirmar

Nenhuma das duas telas anexadas nem o texto do pedido definiam exatamente
"recorrente" nem "em aberto" — decidi pelo critério que já existia em
outro canto do sistema (pros dois casos), mas são interpretações minhas:

1. "Recorrente" hoje considera o SKU sozinho (não SKU + Almoxarifado) —
   ou seja, o mesmo SKU divergindo em dois almoxarifados diferentes já
   conta como recorrente. Se você queria por SKU **dentro do mesmo**
   almoxarifado, é uma mudança pequena, me avisa.
2. "Baixas operacionais em aberto" está restrito a divergências **ainda
   não resolvidas** (`Aberta`/`Em_Investigacao`) — uma divergência já
   `Resolvida` nunca aparece nesse filtro, mesmo que tenha tido uma baixa
   pendente no passado. Faz sentido pra mim (resolvida = não está mais
   "em aberto"), mas é uma decisão, não um dado óbvio do seu pedido.

## Testado

- `python3 -m py_compile` limpo no router.
- Lógica de ordenação (`ORDER BY ... NULLS LAST`) e a subquery de
  recorrência testadas rodando de verdade contra um banco SQLite de teste
  (não só lidas/revisadas) — confirmei que os nulos de confiança vão pro
  fim nos dois sentidos, e que a subquery de recorrência pega o SKU certo
  cruzando almoxarifados diferentes.
- `node --check` limpo no JavaScript.
- Testei a tela de ponta a ponta num navegador de verdade (Chromium,
  headless), com a API simulada: estado inicial, ordenação por Valor
  (maior→menor e invertendo pra menor→maior), ordenação por Confiança,
  os dois filtros novos ligados juntos, cabeçalho fixo rolando a lista
  (conferido que o cabeçalho realmente fica parado no topo da caixa, não só
  visualmente parecido), e o layout no celular (confirmei que volta pro
  comportamento de sempre, sem cabeçalho fixo).
- Revisão visual das capturas de tela geradas nesse teste — sem
  sobreposição, paginação sempre visível, filtros sempre visíveis acima da
  tabela.

## Não incluído neste pacote

Não toquei em nenhuma outra tela (Relatório de Baixa, Mapeamento de
Passivos, Fechamentos, etc.) — só a tela de Divergências (`GET
/divergencias` e a tabela correspondente). Se quiser cabeçalho fixo ou
ordenação por coluna em alguma outra tabela do sistema, me avisa que
replico.
