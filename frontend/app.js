const API = "/api";

// ---------- sessão / autenticação ----------
let usuarioAtual = null; // {username, nome_exibicao, papel}

function tokenSalvo() {
  return localStorage.getItem("atlas_token");
}

function salvarSessao(token, usuario) {
  localStorage.setItem("atlas_token", token);
  localStorage.setItem("atlas_user", JSON.stringify(usuario));
}

function limparSessao() {
  localStorage.removeItem("atlas_token");
  localStorage.removeItem("atlas_user");
  usuarioAtual = null;
}

async function apiFetch(url, options = {}) {
  const token = tokenSalvo();
  const headers = { ...(options.headers || {}) };
  if (token) headers["Authorization"] = "Bearer " + token;
  // cache: "no-store" por padrão em toda chamada à API - sem isso, GET
  // repetido pra mesma URL (ex: recarregar uma lista depois de
  // sincronizar/importar) pode ser respondido pelo cache HTTP do
  // navegador em vez de ir ao servidor, dando a impressão de que a tela
  // "não atualizou" mesmo com o dado já mudado no banco.
  const res = await fetch(url, { cache: "no-store", ...options, headers });
  if (res.status === 401) {
    limparSessao();
    mostrarTelaLogin("Sua sessão expirou. Faça login de novo.");
    throw new Error("Sessão expirada");
  }
  return res;
}

function mostrarTelaLogin(mensagemErro = "") {
  document.getElementById("tela-login").classList.remove("hidden");
  document.getElementById("shell-app").classList.add("hidden");
  document.getElementById("login-erro").textContent = mensagemErro;
}

function mostrarApp() {
  document.getElementById("tela-login").classList.add("hidden");
  document.getElementById("shell-app").classList.remove("hidden");
  aplicarPermissoesNaUI();
  atualizarHipotesesCache();
  mostrarView("hub");
  window.ativarEscutaAtlasSeNecessario();
}

function aplicarPermissoesNaUI() {
  if (!usuarioAtual) return;
  const info = document.getElementById("usuario-logado-info");
  const nomeLabel = usuarioAtual.nome_exibicao || usuarioAtual.username;
  const papelLabel = { admin: "Admin", analista: "Analista", leitura: "Leitura" }[usuarioAtual.papel] || usuarioAtual.papel;
  info.textContent = `${nomeLabel} · ${papelLabel}`;

  document.getElementById("nav-usuarios").classList.toggle("hidden", usuarioAtual.papel !== "admin");
  document.getElementById("nav-auditoria").classList.toggle("hidden", usuarioAtual.papel !== "admin");
  document.getElementById("nav-cadastros").classList.toggle("hidden", usuarioAtual.papel === "leitura");

  const navImportar = document.querySelector('.rail-item[data-view="importar"]');
  if (navImportar) navImportar.classList.toggle("hidden", usuarioAtual.papel === "leitura");
  const navFechamentos = document.querySelector('.rail-item[data-view="fechamentos"]');
  if (navFechamentos) navFechamentos.classList.toggle("hidden", usuarioAtual.papel === "leitura");
  const navPosInventario = document.querySelector('.rail-item[data-view="pos-inventario"]');
  if (navPosInventario) navPosInventario.classList.toggle("hidden", usuarioAtual.papel === "leitura");

  const btnRecalcular = document.getElementById("btn-recalcular-valores");
  if (btnRecalcular) btnRecalcular.classList.toggle("hidden", usuarioAtual.papel === "leitura");
  const btnGerarCiencia = document.getElementById("btn-gerar-ciencia");
  if (btnGerarCiencia) btnGerarCiencia.classList.toggle("hidden", usuarioAtual.papel === "leitura");
  const btnCriarPedido = document.getElementById("btn-criar-pedido");
  if (btnCriarPedido) btnCriarPedido.classList.toggle("hidden", usuarioAtual.papel === "leitura");
}

document.getElementById("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const senha = document.getElementById("login-senha").value;
  const erroEl = document.getElementById("login-erro");
  erroEl.textContent = "";
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, senha }),
    });
    const data = await res.json();
    if (!res.ok) {
      erroEl.textContent = data.detail || "Usuário ou senha incorretos.";
      return;
    }
    usuarioAtual = { username: data.username, nome_exibicao: data.nome_exibicao, papel: data.papel };
    salvarSessao(data.access_token, usuarioAtual);
    mostrarApp();
  } catch (erro) {
    erroEl.textContent = "Não consegui conectar ao servidor.";
  }
});

document.getElementById("btn-logout").addEventListener("click", () => {
  limparSessao();
  mostrarTelaLogin();
});

async function inicializarSessao() {
  const token = tokenSalvo();
  const userSalvo = localStorage.getItem("atlas_user");
  if (!token || !userSalvo) {
    mostrarTelaLogin();
    return;
  }
  try {
    const res = await apiFetch(`${API}/auth/me`);
    if (!res.ok) throw new Error("token inválido");
    const dados = await res.json();
    usuarioAtual = { username: dados.username, nome_exibicao: dados.nome_exibicao, papel: dados.papel };
    salvarSessao(token, usuarioAtual);
    mostrarApp();
  } catch (erro) {
    limparSessao();
    mostrarTelaLogin();
  }
}

// ---------- exportar dashboard como HTML autônomo, com gráficos vivos e filtros funcionando offline ----------

// mesmo plugin de rótulos registrado no app principal (linha ~276) -
// precisa existir também dentro do arquivo exportado, senão os rótulos
// que ficam sempre visíveis em cima das barras desaparecem lá.
const CODIGO_PLUGIN_ROTULOS = `
Chart.register({
  id: "rotulosDados",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((dataset, i) => {
      if (!dataset.rotulos) return;
      const meta = chart.getDatasetMeta(i);
      if (meta.hidden) return;
      meta.data.forEach((el, idx) => {
        const valor = dataset.data[idx];
        if (valor == null) return;
        const texto = dataset.rotulos[idx];
        if (!texto) return;
        const pos = el.tooltipPosition ? el.tooltipPosition() : { x: el.x, y: el.y };
        ctx.save();
        ctx.font = "600 11px Inter, sans-serif";
        ctx.fillStyle = dataset.corRotulo || getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#888";
        if (chart.options.indexAxis === "y") {
          if (dataset.stack) {
            const centro = ((el.x ?? pos.x) + (el.base ?? pos.x)) / 2;
            ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(texto, centro, pos.y);
          } else {
            ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(texto, pos.x + 6, pos.y);
          }
        } else if (meta.type === "doughnut" || meta.type === "pie") {
          ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(texto, pos.x, pos.y);
        } else {
          ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(texto, pos.x, pos.y - 4);
        }
        ctx.restore();
      });
    });
  },
});`;

function _cartesiano(arrays) {
  return arrays.reduce((acc, curr) => acc.flatMap((a) => curr.map((c) => [...a, c])), [[]]);
}

/** Percorre um objeto (as `options` de um gráfico) trocando toda função por
 * um "marcador" serializável em JSON ({ __atlasFn: true, src: "..." }) -
 * usado para as `options` de tooltip/eixo, que têm lógica variada demais
 * pra pré-calcular como os rótulos de dataset acima. O par
 * `_atlasReidratarFuncoes` (que roda dentro do arquivo exportado, por isso
 * vai embutido como texto em CODIGO_REIDRATAR_FUNCOES) reconstrói essas
 * funções lá, protegendo cada chamada com try/catch: se a função depender
 * de algo que só existe no app principal, ela simplesmente não retorna nada
 * (o Chart.js trata isso como "sem rótulo nesse ponto"), em vez de quebrar
 * o gráfico inteiro. */
function _serializarComFuncoes(valor) {
  if (typeof valor === "function") {
    return { __atlasFn: true, src: valor.toString() };
  }
  if (Array.isArray(valor)) {
    return valor.map((v) => _serializarComFuncoes(v));
  }
  if (valor && typeof valor === "object") {
    const resultado = {};
    Object.keys(valor).forEach((k) => {
      resultado[k] = _serializarComFuncoes(valor[k]);
    });
    return resultado;
  }
  return valor;
}

// contraparte de _serializarComFuncoes que roda DENTRO do arquivo exportado -
// por isso vai como texto-fonte, embutida no <script> do HTML gerado.
const CODIGO_REIDRATAR_FUNCOES = `
function _atlasReidratarFuncoes(valor) {
  if (valor && typeof valor === "object" && valor.__atlasFn) {
    let real = null;
    try { real = eval("(" + valor.src + ")"); } catch (e) { real = null; }
    return function (...args) {
      if (!real) return undefined;
      try { return real.apply(this, args); } catch (e) { return undefined; }
    };
  }
  if (Array.isArray(valor)) return valor.map((v) => _atlasReidratarFuncoes(v));
  if (valor && typeof valor === "object") {
    const resultado = {};
    Object.keys(valor).forEach((k) => { resultado[k] = _atlasReidratarFuncoes(valor[k]); });
    return resultado;
  }
  return valor;
}`;

/** Monta o texto-fonte (pra embutir no <script> do arquivo exportado) dos
 * ajudantes de formatação mais usados dentro das opções de gráfico
 * (tooltips, ticks) - formatarMoeda, corFarolAcuracia, formatarDataCurta e
 * rotulo (hipóteses). Sem isso, qualquer tooltip/tick que chame
 * formatarMoeda(...), por exemplo, quebraria no arquivo exportado (essas
 * funções só existem no app principal, que não é levado inteiro pro
 * export). `rotulo` depende de duas variáveis vivas (HIPOTESE_LABEL +
 * HIPOTESES_DINAMICAS) - aqui é embutido como um dicionário já resolvido
 * (congelado no momento da exportação), já que o arquivo exportado é uma
 * foto estática mesmo. */
function _codigoAjudantesExportacao() {
  const mapaHipoteses = JSON.stringify(todasHipoteses());
  return `
${formatarMoeda.toString()}
${corFarolAcuracia.toString()}
${formatarDataCurta.toString()}
const _ATLAS_MAPA_HIPOTESES = ${mapaHipoteses};
function rotulo(h) { return _ATLAS_MAPA_HIPOTESES[h] || h || "—"; }
`;
}

/** Captura o estado atual (HTML + configuração de cada gráfico) de tudo
 * dentro do container EXCETO o cabeçalho de filtros - isso vira um
 * "snapshot" independente que o arquivo exportado troca ao mudar o
 * filtro, sem precisar do servidor.
 *
 * Os rótulos de dados (dataset.formatarRotulo) são resolvidos AGORA,
 * enquanto ainda temos o app inteiro carregado (com formatarMoeda e
 * qualquer outra variável que a função capture) - o resultado já pronto
 * (texto final) é o que vai pro arquivo exportado, em vez do código-fonte
 * da função. Isso evita o bug em que o arquivo exportado tentava reexecutar
 * a função original e quebrava com "formatarMoeda is not defined" (os
 * helpers do app principal não são levados pro arquivo exportado),
 * deixando os gráficos sem rótulo/com aparência de dado vazio.
 *
 * Já as opções do gráfico (tooltips, ticks) podem ter funções com lógica
 * mais complexa - essas são preservadas como texto-fonte via
 * _serializarComFuncoes/_atlasReidratarFuncoes (ver mais abaixo) e alguns
 * ajudantes comuns (formatarMoeda etc.) são levados junto pro arquivo
 * exportado para que essas funções continuem funcionando lá também. */
function _capturarSnapshotAtual(original) {
  const header = original.querySelector(".view-header");
  const partesResto = Array.from(original.children).filter((el) => el !== header);
  const graficos = {};
  const alturasPorId = {};

  partesResto.forEach((parte) =>
    parte.querySelectorAll("canvas").forEach((c) => {
      const inst = window.Chart && Chart.getChart(c);
      if (!inst || !c.id) return;
      // guarda a altura de exibição REAL desse gráfico ao vivo (ex: o
      // "height=90" no HTML original, ou o que o Chart.js calculou) -
      // sem isso, o gráfico exportado perde a proporção pretendida e
      // fica esmagado/pequeno, mesmo com muitas categorias pra mostrar.
      alturasPorId[c.id] = c.getBoundingClientRect().height;
      const dadosSerializaveis = JSON.parse(
        JSON.stringify(inst.config.data, (chave, valor) => (typeof valor === "function" ? undefined : valor))
      );
      // pré-calcula o TEXTO FINAL de cada rótulo agora (ver comentário acima da
      // função) - o arquivo exportado só exibe esse texto, nunca reexecuta
      // formatarRotulo sozinho.
      (inst.config.data.datasets || []).forEach((ds, i) => {
        if (typeof ds.formatarRotulo === "function") {
          dadosSerializaveis.datasets[i].rotulos = (ds.data || []).map((valor) => {
            try {
              return ds.formatarRotulo(valor);
            } catch (e) {
              return null;
            }
          });
        }
      });
      const opcoesSerializaveis = _serializarComFuncoes(inst.config.options || {});
      graficos[c.id] = { type: inst.config.type, data: dadosSerializaveis, options: opcoesSerializaveis };
    })
  );

  const divTemp = document.createElement("div");
  partesResto.forEach((p) => divTemp.appendChild(p.cloneNode(true)));
  divTemp.querySelectorAll("button, .btn-secundario, .btn-primario").forEach((el) => el.remove());
  divTemp.querySelectorAll("canvas").forEach((c) => {
    // o Chart.js grava tanto os atributos de resolução (width/height)
    // quanto um style inline em pixel fixo (ex: "width: 813px") - se só
    // limpar os atributos, o style inline continua travando o layout no
    // tamanho exato de quando foi exportado, sem se ajustar à tela de
    // quem abrir o arquivo depois. Limpa os dois, mas define de volta
    // uma ALTURA fixa (a real, capturada ao vivo) - só a largura fica
    // flexível. Sem isso, o gráfico perde a proporção original (fica
    // esmagado, texto/barras pequenos demais pra quantidade de categorias).
    c.removeAttribute("width");
    c.removeAttribute("height");
    c.removeAttribute("style");
    if (alturasPorId[c.id]) c.style.height = alturasPorId[c.id] + "px";
  });

  return { html: divTemp.innerHTML, graficos };
}

/** Espera até que todo <canvas> dentro do container tenha uma instância
 * Chart.js associada (ou o tempo limite seja atingido) - mais confiável
 * que uma espera fixa, que às vezes não é suficiente dependendo de
 * quanto dado aquela combinação de filtro precisa processar. */
async function _esperarGraficosProntos(container, timeoutMs = 1500) {
  const inicio = Date.now();
  while (Date.now() - inicio < timeoutMs) {
    const canvases = Array.from(container.querySelectorAll("canvas"));
    const todosProntos = canvases.every((c) => !!(window.Chart && Chart.getChart(c)));
    if (todosProntos) return;
    await new Promise((r) => setTimeout(r, 50));
  }
}

async function exportarDashboardComoHTML(containerId, nomeArquivoBase, tituloExibicao, idsFiltros, funcaoRecarregar, opcoes = {}) {
  const maxCombinacoes = opcoes.maxCombinacoes || 150;
  const original = document.getElementById(containerId);
  const botao = document.getElementById(`btn-exportar-html-${containerId.replace("view-", "")}`);
  if (!original) return;

  const selects = idsFiltros.map((id) => document.getElementById(id)).filter(Boolean);
  const valoresOriginais = selects.map((s) => s.value);
  const opcoesPorSelect = selects.map((s) => Array.from(s.options).map((o) => o.value));
  let todasCombinacoes = _cartesiano(opcoesPorSelect);

  // Telas com muitas combinações de filtro possíveis (ex: 4 seletores
  // independentes) não conseguem ter TODAS pré-geradas sem travar o
  // navegador por minutos - nesse caso, captura só o recorte selecionado
  // no momento da exportação e avisa isso claramente no arquivo gerado.
  const modoUnico = todasCombinacoes.length > maxCombinacoes;
  if (modoUnico) todasCombinacoes = [valoresOriginais];

  const textoOriginalBotao = botao ? botao.textContent : null;
  if (botao) botao.disabled = true;

  const snapshots = {};
  for (let i = 0; i < todasCombinacoes.length; i++) {
    const combo = todasCombinacoes[i];
    if (botao) botao.textContent = `Gerando (${i + 1}/${todasCombinacoes.length})...`;
    selects.forEach((s, idx) => (s.value = combo[idx]));
    await funcaoRecarregar();
    await _esperarGraficosProntos(original);
    snapshots[combo.join("||")] = _capturarSnapshotAtual(original);
  }

  // restaura o estado que o usuário tinha antes de exportar
  selects.forEach((s, idx) => (s.value = valoresOriginais[idx]));
  await funcaoRecarregar();
  if (botao) {
    botao.disabled = false;
    botao.textContent = textoOriginalBotao;
  }

  const headerClone = original.querySelector(".view-header").cloneNode(true);
  headerClone.querySelectorAll("button").forEach((el) => el.remove());

  let cssTexto = "";
  try {
    cssTexto = await fetch("style.css").then((r) => r.text());
  } catch (e) {
    console.error("Atlas: falha ao buscar style.css pra exportação:", e);
  }
  let chartJsTexto = "";
  try {
    chartJsTexto = await fetch("vendor/chart.umd.js").then((r) => r.text());
  } catch (e) {
    console.error("Atlas: falha ao buscar Chart.js pra exportação:", e);
  }

  const tema = document.documentElement.getAttribute("data-theme") || "dark";
  const agora = new Date().toLocaleString("pt-BR");
  const chaveInicial = valoresOriginais.join("||");

  const html = `<!DOCTYPE html>
<html data-theme="${tema}">
<head>
<meta charset="UTF-8">
<title>Atlas — ${tituloExibicao} — ${agora}</title>
<style>
${cssTexto}
body { padding: 24px; max-width: 1400px; margin: 0 auto; }
.export-aviso { background: var(--panel-2); border: 1px solid var(--border); border-radius: var(--radius-input); padding: 10px 14px; margin-bottom: 18px; font-size: 12px; color: var(--muted); }
</style>
</head>
<body>
<div class="export-aviso">📄 Exportado do Atlas em ${agora} — instantâneo com os filtros congelados no momento da exportação (os dados não atualizam automaticamente; para ver ao vivo, acesse o sistema). Passe o mouse sobre os gráficos pra ver os valores.${modoUnico ? " Esta tela tem muitas combinações de filtro possíveis - este arquivo captura só o recorte que estava selecionado no momento da exportação; mudar os filtros aqui não vai encontrar outra combinação pronta." : ""}</div>
${headerClone.outerHTML}
<div id="atlas-snapshot-container"></div>
<script>
${chartJsTexto}
${CODIGO_PLUGIN_ROTULOS}
${CODIGO_REIDRATAR_FUNCOES}
${_codigoAjudantesExportacao()}
</script>
<script>
const ATLAS_SNAPSHOTS = ${JSON.stringify(snapshots)};
const ATLAS_IDS_FILTROS = ${JSON.stringify(idsFiltros)};
let atlasChartsAtivos = [];

function atlasChaveAtual() {
  return ATLAS_IDS_FILTROS.map((id) => document.getElementById(id)?.value || "").join("||");
}

function atlasRenderizarSnapshot(chave) {
  const snap = ATLAS_SNAPSHOTS[chave];
  const container = document.getElementById("atlas-snapshot-container");
  if (!snap) { container.innerHTML = "<p class='hint' style='padding:20px'>Combinação de filtro não capturada na exportação.</p>"; return; }
  atlasChartsAtivos.forEach((c) => c.destroy());
  atlasChartsAtivos = [];
  container.innerHTML = snap.html;
  Object.entries(snap.graficos).forEach(([canvasId, cfg]) => {
    const el = document.getElementById(canvasId);
    if (!el) return;
    const opcoes = _atlasReidratarFuncoes(cfg.options);
    try {
      atlasChartsAtivos.push(new Chart(el, { type: cfg.type, data: cfg.data, options: opcoes }));
    } catch (e) { console.error("Atlas: falha ao recriar gráfico exportado", canvasId, e); }
  });
}

ATLAS_IDS_FILTROS.forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => atlasRenderizarSnapshot(atlasChaveAtual()));
});

atlasRenderizarSnapshot("${chaveInicial}");
</script>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `atlas_${nomeArquivoBase}_${new Date().toISOString().slice(0, 10)}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("btn-exportar-html-dashboard").addEventListener("click", () =>
  exportarDashboardComoHTML("view-dashboard", "painel_divergencias", "Painel de Divergências", ["filtro-periodo", "filtro-almoxarifado"], carregarDashboard)
);
document.getElementById("btn-exportar-html-fechamento-dashboard").addEventListener("click", () =>
  exportarDashboardComoHTML("view-fechamento-dashboard", "painel_inventario", "Painel de Inventário", ["fd-filtro-mes", "fd-filtro-almoxarifado"], carregarDashboardFechamento)
);
document.getElementById("btn-exportar-html-acuracia-ponderada").addEventListener("click", () =>
  exportarDashboardComoHTML("view-acuracia-ponderada", "acuracia_ponderada", "Acurácia Ponderada", ["ap-filtro-mes", "ap-filtro-almoxarifado"], carregarAcuraciaPonderada)
);
document.getElementById("btn-exportar-html-cobertura-conferencia").addEventListener("click", () =>
  exportarDashboardComoHTML("view-cobertura-conferencia", "cobertura_conferencia", "Cobertura de Conferência", ["cc-filtro-dias"], carregarCoberturaConferencia)
);
document.getElementById("btn-exportar-html-compras").addEventListener("click", () =>
  exportarDashboardComoHTML("view-compras", "controle_compras", "Controle de Compras", ["cp-filtro-status"], carregarPedidosCompra)
);
document.getElementById("btn-exportar-html-pos-inventario").addEventListener("click", () =>
  exportarDashboardComoHTML("view-pos-inventario", "pos_inventario", "Pós-Inventário", ["pi-filtro-status"], carregarAcoesPosInventario)
);
document.getElementById("btn-exportar-html-mapeamento-passivos").addEventListener("click", () =>
  exportarDashboardComoHTML(
    "view-mapeamento-passivos", "mapeamento_passivos", "Mapeamento de Passivos",
    ["mp-filtro-ano", "mp-filtro-mes", "mp-filtro-almoxarifado", "mp-filtro-motivo"],
    carregarPassivosFiltrados,
    { maxCombinacoes: 150 }
  )
);

// Exportar Excel (13/08/2026): mesmo recorte dos filtros da tela, 4 abas (Inventário/Passivos/
// Acumulado/Resumo) - ver /dashboard/exportar-excel no backend.
document.getElementById("btn-exportar-excel-mapeamento-passivos").addEventListener("click", async () => {
  const btn = document.getElementById("btn-exportar-excel-mapeamento-passivos");
  const textoOriginal = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Gerando...";
  try {
    const qs = "?" + new URLSearchParams(montarParamsResumoExecutivoMp()).toString();
    const resp = await apiFetch(`${API}/baixas-operacionais/dashboard/exportar-excel${qs}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mapeamento_passivos_${new Date().toISOString().slice(0, 10)}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (erro) {
    alert("Não consegui gerar o Excel: " + erro.message);
  } finally {
    btn.disabled = false;
    btn.textContent = textoOriginal;
  }
});

// ---------- tema claro/escuro ----------
function aplicarTemaSalvo() {
  const tema = localStorage.getItem("atlas_theme") || "dark";
  document.documentElement.setAttribute("data-theme", tema);
}
document.getElementById("btn-tema").addEventListener("click", () => {
  const atual = document.documentElement.getAttribute("data-theme") || "dark";
  const novo = atual === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", novo);
  localStorage.setItem("atlas_theme", novo);
});
aplicarTemaSalvo();

const HIPOTESE_LABEL = {
  Transferencia_Pendente: "Transferência Pendente",
  Consumo_Parcial_OP: "Consumo Parcial de OP",
  Pendencia_Faturamento: "Pendência de Faturamento",
  Erro_Operacional: "Erro Operacional",
  Erro_Cadastro: "Erro de Cadastro",
  Falha_Inventario: "Falha de Inventário",
  Avaria_Perda: "Avaria / Perda",
  Producao_Nao_Encerrada: "Produção Não Encerrada",
  Ajuste_Manual_Incorreto: "Ajuste Manual Incorreto",
  Movimentacao_Duplicada: "Movimentação Duplicada",
  Conversao_Unidade_Incorreta: "Conversão de Unidade Incorreta",
  Erro_Fiscal: "Erro Fiscal",
  Perda_Nao_Identificada: "Perda Não Identificada",
  Divergencia_Ficha_Tecnica: "Divergência de Ficha Técnica",
  Sem_Divergencia_Real: "Sem Divergência Real",
  Outros_Nao_Categorizado: "Outros / Não Categorizado",
};
// Hipóteses cadastradas via tela Cadastros - some com o fallback estático
// acima, então hipóteses novas aparecem nos seletores sem precisar
// recarregar a página. Atualizada no login e sempre que um cadastro muda.
let HIPOTESES_DINAMICAS = {};

async function atualizarHipotesesCache() {
  try {
    const lista = await apiFetch(`${API}/hipoteses-cadastro?incluir_inativos=true`).then((r) => r.json());
    HIPOTESES_DINAMICAS = {};
    lista.forEach((h) => (HIPOTESES_DINAMICAS[h.codigo] = h.nome));
  } catch (erro) {
    console.warn("Não consegui atualizar a lista de hipóteses:", erro);
  }
}

function todasHipoteses() {
  return { ...HIPOTESE_LABEL, ...HIPOTESES_DINAMICAS };
}

const rotulo = (h) => HIPOTESES_DINAMICAS[h] || HIPOTESE_LABEL[h] || h || "—";

// ---------- farol de acurácia (0-50 vermelho · 50-75 amarelo · 75-100 verde) ----------
function corFarolAcuracia(pct) {
  if (pct == null || isNaN(pct)) return "#8ca0a3"; // sem dado
  if (pct < 50) return "#e5534b";
  if (pct < 75) return "#f9a825";
  return "#4caf50";
}

// ---------- clique-para-filtrar nos gráficos (estilo Power BI) ----------
// Clicar numa barra/ponto de um gráfico já joga aquele valor no filtro
// correspondente da própria tela e recarrega - mesma lógica do "cross-filter"
// do Power BI. Convive com qualquer duplo clique que já existia nesse mesmo
// gráfico (ex: abrir um modal com o detalhe) - são eventos diferentes
// ("click" x "dblclick"), então o pop-up de sempre continua funcionando.
function ativarCliqueParaFiltrar(chart, canvas, dados, extrairValor, idSelectFiltro, gerarResumoPonto) {
  // as funções de render são chamadas de novo a cada recarregamento (troca
  // de filtro) - sem este controle, cada chamada empilharia mais um
  // "addEventListener" no mesmo canvas, e um único clique acabaria
  // disparando várias vezes (com dados cada vez mais desatualizados nas
  // chamadas antigas). Por isso o listener real só é registrado UMA VEZ por
  // canvas; toda vez que a tela recarrega, só atualiza a referência com
  // o gráfico/dados mais recentes, que é o que o clique de fato consulta.
  //
  // `gerarResumoPonto` (opcional) recebe (linhaClicada, valorExtraido) e
  // devolve { titulo, resumo } - se fornecido, abre o pop-up de resumo
  // operacional daquele ponto (ver abrirModalResumoPonto abaixo), mesmo
  // quando o gráfico já estava nesse recorte (clicar de novo no mesmo
  // ponto continua mostrando o resumo, a pedido do Maurício: "manter os
  // pops ao clicar, mesmo que não seja habilitada uma ação direta").
  canvas.style.cursor = "pointer";
  canvas._atlasClickFiltro = { chart, dados, extrairValor, idSelectFiltro, gerarResumoPonto };
  if (canvas._atlasClickFiltroAtivo) return;
  canvas._atlasClickFiltroAtivo = true;
  canvas.addEventListener("click", (evt) => {
    const ctxAtual = canvas._atlasClickFiltro;
    if (!ctxAtual || !ctxAtual.chart) return;
    const pontos = ctxAtual.chart.getElementsAtEventForMode(evt, "index", { intersect: true }, true);
    if (!pontos.length) return;
    const linha = ctxAtual.dados[pontos[0].index];
    const valor = ctxAtual.extrairValor(linha);
    if (valor == null) return;
    const select = document.getElementById(ctxAtual.idSelectFiltro);
    if (select && select.value !== String(valor)) {
      select.value = valor;
      select.dispatchEvent(new Event("change"));
    }
    if (typeof ctxAtual.gerarResumoPonto === "function") {
      try {
        const info = ctxAtual.gerarResumoPonto(linha, valor) || {};
        if (info.resumo) abrirModalResumoPonto(info.titulo || String(valor), info.resumo);
      } catch (e) {
        console.error("Atlas: falha ao gerar o resumo do ponto clicado:", e);
      }
    }
  });
}

// ---------- pop-up genérico de "resumo operacional do ponto" (13/08/2026) ----------
// Abre ao clicar num ponto/barra de qualquer gráfico com clique-para-filtrar
// habilitado (ver ativarCliqueParaFiltrar acima) e no heatmap/ranking do Painel
// de Divergências (ver filtrarPainelPorAlmoxarifado mais abaixo) - mostra um
// resumo em texto corrido do que aconteceu naquele ponto específico. Fica
// disponível mesmo quando o gráfico não tem nenhuma ação direta habilitada -
// é só informativo, igual ao resumo executivo já usado em Mapeamento de
// Passivos, só que por ponto clicado em vez de por KPI.
let _textoResumoPontoAtual = "";
function abrirModalResumoPonto(titulo, resumo) {
  _textoResumoPontoAtual = resumo;
  document.getElementById("modal-resumo-ponto-titulo").textContent = titulo;
  document.getElementById("modal-resumo-ponto-corpo").innerHTML =
    `<p class="hint" style="white-space:pre-line; line-height:1.6; margin:0">${resumo}</p>`;
  document.getElementById("modal-resumo-ponto-overlay").classList.remove("hidden");
}
document.getElementById("btn-fechar-modal-resumo-ponto").addEventListener("click", () => {
  document.getElementById("modal-resumo-ponto-overlay").classList.add("hidden");
});
document.getElementById("modal-resumo-ponto-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-resumo-ponto-overlay") document.getElementById("modal-resumo-ponto-overlay").classList.add("hidden");
});
document.getElementById("btn-narrar-resumo-ponto").addEventListener("click", () => {
  if (_textoResumoPontoAtual) falarResumoModulo(_textoResumoPontoAtual);
});

// ---------- rótulos de dados nos gráficos (opt-in por dataset, via dataset.formatarRotulo) ----------
if (window.Chart) {
  Chart.register({
    id: "rotulosDados",
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      chart.data.datasets.forEach((dataset, i) => {
        if (!dataset.formatarRotulo) return;
        const meta = chart.getDatasetMeta(i);
        if (meta.hidden) return;
        meta.data.forEach((el, idx) => {
          const valor = dataset.data[idx];
          if (valor == null) return;
          const texto = dataset.formatarRotulo(valor);
          if (!texto) return;
          const pos = el.tooltipPosition ? el.tooltipPosition() : { x: el.x, y: el.y };
          ctx.save();
          ctx.font = "600 11px Inter, sans-serif";
          ctx.fillStyle = dataset.corRotulo || getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#888";
          if (chart.options.indexAxis === "y") {
            if (dataset.stack) {
              // barra horizontal EMPILHADA: centraliza o rótulo dentro do próprio
              // segmento (base..x) - se ancorar no fim do segmento (como faz a
              // barra horizontal simples abaixo), o texto invade visualmente o
              // próximo segmento da pilha, parecendo rótulo do vizinho errado.
              const centro = ((el.x ?? pos.x) + (el.base ?? pos.x)) / 2;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillText(texto, centro, pos.y);
            } else {
              ctx.textAlign = "left";
              ctx.textBaseline = "middle";
              ctx.fillText(texto, pos.x + 6, pos.y);
            }
          } else if (meta.type === "doughnut" || meta.type === "pie") {
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(texto, pos.x, pos.y);
          } else if (meta.type === "line") {
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            ctx.fillText(texto, pos.x, pos.y - 8);
          } else {
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            ctx.fillText(texto, pos.x, pos.y - 4);
          }
          ctx.restore();
        });
      });
    },
  });
}

// ---------- navegação ----------
document.querySelectorAll(".rail-item").forEach((btn) => {
  btn.addEventListener("click", () => mostrarView(btn.dataset.view));
});
document.getElementById("btn-voltar-detalhe").addEventListener("click", () => mostrarView("lista"));

const rail = document.getElementById("rail");
const btnToggleRail = document.getElementById("btn-toggle-rail");
if (rail && btnToggleRail) {
  btnToggleRail.addEventListener("click", () => {
    rail.classList.toggle("collapsed");
    setTimeout(() => {
      // força os gráficos a recalcularem a largura depois da transição do menu
      [chartAcuraciaDia, chartCausas, chartTendencia, chartMom].forEach((c) => c && c.resize());
    }, 200);
  });
} else {
  console.warn("Botão de recolher menu não encontrado - verifique se o index.html está atualizado.");
}

function mostrarView(nome) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById("view-" + nome).classList.remove("hidden");
  document.querySelectorAll(".rail-item").forEach((b) => b.classList.toggle("active", b.dataset.view === nome));
  document.querySelectorAll(".bottom-nav-item[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === nome));
  apresentarModuloSeNecessario(nome);
  if (nome === "hub") { renderizarHub(); carregarMapaDemandas(); }
  if (nome === "dashboard") carregarDashboard();
  if (nome === "lista") carregarLista();
  if (nome === "cobertura-conferencia") carregarCoberturaConferencia();
  if (nome === "relatorio-baixa") carregarRelatorioBaixa();
  if (nome === "shelf-life") carregarShelfLife();
  if (nome === "mapeamento-passivos") carregarMapeamentoPassivos();
  if (nome === "usuarios") carregarUsuarios();
  if (nome === "cadastros") carregarAbaCadastroAtiva();
  if (nome === "auditoria") carregarAuditoria();
  if (nome === "importar") {
    carregarLotesImportacao();
    carregarLotesAjusteInventario();
    carregarOpcoesAlmoxarifadoImportadorBruto();
  }
  if (nome === "fechamentos") carregarFechamentos();
  if (nome === "fechamento-dashboard") carregarDashboardFechamento();
  if (nome === "acuracia-ponderada") carregarAcuraciaPonderada();
  if (nome === "compras") carregarPedidosCompra();
  if (nome === "pos-inventario") carregarAcoesPosInventario();
}

// ---------- barra inferior mobile (13/08/2026) ----------
// Os 5 atalhos fixos (Início, Divergências, Inventário, Acurácia, Passivos)
// só chamam mostrarView, igual os botões da rail lateral - a barra some no
// desktop via CSS, só a rail existe lá. O "Mais" abre uma bandeja com os
// módulos que não couberam na barra (a mesma lista de módulos visíveis da
// rail, na mesma ordem, respeitando permissão - reaproveita a lógica já
// usada pelo hub orbital em renderizarHub) + atalhos de Tema/Sair, que na
// tela estreita ficam escondidos junto com o resto do rodapé da rail.
document.querySelectorAll(".bottom-nav-item[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => mostrarView(btn.dataset.view));
});

const VIEWS_NA_BARRA_INFERIOR = ["hub", "dashboard", "fechamento-dashboard", "acuracia-ponderada", "mapeamento-passivos"];

function abrirBandejaMais() {
  const itens = Array.from(document.querySelectorAll(".rail-item"))
    .filter((b) => !b.classList.contains("hidden") && !VIEWS_NA_BARRA_INFERIOR.includes(b.dataset.view))
    .map((b) => ({ view: b.dataset.view, label: b.querySelector(".rail-label").textContent, iconHtml: b.querySelector(".rail-icon").innerHTML }));

  const lista = document.getElementById("bottom-sheet-mais-lista");
  lista.innerHTML =
    itens
      .map(
        (item) =>
          `<button class="bottom-sheet-item" data-view="${item.view}"><span class="bottom-nav-icon">${item.iconHtml}</span><span>${item.label}</span></button>`
      )
      .join("") +
    `<button class="bottom-sheet-item" id="btn-bottom-sheet-tema"><span class="bottom-nav-icon">🌓</span><span>Alternar tema</span></button>` +
    `<button class="bottom-sheet-item" id="btn-bottom-sheet-sair"><span class="bottom-nav-icon">↪</span><span>Sair</span></button>`;

  lista.querySelectorAll(".bottom-sheet-item[data-view]").forEach((btn) =>
    btn.addEventListener("click", () => {
      mostrarView(btn.dataset.view);
      fecharBandejaMais();
    })
  );
  document.getElementById("btn-bottom-sheet-tema").addEventListener("click", () => document.getElementById("btn-tema").click());
  document.getElementById("btn-bottom-sheet-sair").addEventListener("click", () => document.getElementById("btn-logout").click());

  document.getElementById("bottom-sheet-mais-overlay").classList.remove("hidden");
}
function fecharBandejaMais() {
  document.getElementById("bottom-sheet-mais-overlay").classList.add("hidden");
}
const btnBottomNavMais = document.getElementById("btn-bottom-nav-mais");
if (btnBottomNavMais) btnBottomNavMais.addEventListener("click", abrirBandejaMais);
document.getElementById("btn-fechar-bottom-sheet-mais").addEventListener("click", fecharBandejaMais);
document.getElementById("bottom-sheet-mais-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "bottom-sheet-mais-overlay") fecharBandejaMais();
});

// ---------- dashboard ----------
let chartAcuraciaDia, chartCausas, chartTendencia, chartMom;
let ultimoAcuraciaDiaDados = [], ultimoAcuraciaMensalDados = [];

async function carregarDashboard() {
  const almox = document.getElementById("filtro-almoxarifado").value;
  const periodo = document.getElementById("filtro-periodo").value;
  const params = new URLSearchParams();
  if (almox) params.set("almoxarifado", almox);
  if (periodo) params.set("periodo", periodo);
  const qs = "?" + params.toString();
  const qsSemAlmox = "?" + new URLSearchParams(periodo ? { periodo } : {}).toString();

  const [kpis, acuraciaDia, acuraciaMensal, causas, heatmap, rank, top] = await Promise.all([
    apiFetch(`${API}/dashboard/kpis${qsSemAlmox}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/acuracia-por-dia${qs}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/acuracia-mensal${qs}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/distribuicao-causas${qsSemAlmox}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/heatmap-almoxarifado-hipotese${qsSemAlmox}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/top-reincidentes${qsSemAlmox}`).then((r) => r.json()),
    apiFetch(`${API}/dashboard/top-divergencias${qsSemAlmox}`).then((r) => r.json()),
  ]);

  renderKpis(kpis);
  tentarRenderizar(() => renderAcuraciaDia(acuraciaDia));
  tentarRenderizar(() => renderCausas(causas));
  tentarRenderizar(() => renderTendencia(acuraciaDia));
  tentarRenderizar(() => renderMom(acuraciaMensal));
  tentarRenderizar(() => renderHeatmap(heatmap));
  tentarRenderizar(() => renderRanking(rank));
  tentarRenderizar(() => renderTop(top));
  tentarRenderizar(() => preencherFiltroAlmoxarifado(heatmap));
  tentarRenderizar(() => renderizarResumoExecutivoNarrado("dashboard-resumo-executivo", construirResumoExecutivoDashboard(kpis, causas)));
}

function tentarRenderizar(fn) {
  try {
    fn();
  } catch (erro) {
    console.error("Falha ao renderizar parte do dashboard:", erro);
  }
}

function formatarMoeda(v) {
  return (v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function definirLinhaTotal(idTabela, htmlCelulas) {
  // Escreve (ou limpa) a linha de total no <tfoot> de uma tabela, pra dar
  // ao usuário um jeito rápido de conferir se os valores exibidos batem
  // com o esperado. htmlCelulas já vem como string de <td>...</td> prontos
  // (cada chamador decide quantas colunas/o que preencher); passar null
  // ou string vazia limpa a linha (ex.: tabela sem dados).
  const tfoot = document.querySelector(`#${idTabela} tfoot`);
  if (!tfoot) return;
  tfoot.innerHTML = htmlCelulas ? `<tr>${htmlCelulas}</tr>` : "";
}

function renderKpis(k) {
  const cards = [
    { label: "Divergências abertas", value: k.divergencias_abertas },
    { label: "Em investigação", value: k.em_investigacao },
    { label: "Resolvidas", value: k.resolvidas },
    { label: "Valor total em aberto", value: formatarMoeda(k.valor_total_em_aberto), accent: true },
    { label: "Taxa de acerto do modelo", value: k.taxa_acerto_modelo_pct != null ? k.taxa_acerto_modelo_pct + "%" : "—", cor: corFarolAcuracia(k.taxa_acerto_modelo_pct) },
  ];
  document.getElementById("kpi-row").innerHTML = cards
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value ${c.accent ? "accent" : ""}" style="${c.cor ? "color:" + c.cor : ""}">${c.value}</div></div>`)
    .join("");
}

function renderAcuraciaDia(dados) {
  const ctx = document.getElementById("chart-acuracia-dia");
  ultimoAcuraciaDiaDados = dados;
  if (chartAcuraciaDia) chartAcuraciaDia.destroy();
  chartAcuraciaDia = new Chart(ctx, {
    data: {
      labels: dados.map((d) => formatarDataCurta(d.data)),
      datasets: [
        {
          type: "bar",
          label: "Itens Inventariados",
          data: dados.map((d) => d.itens_inventariados),
          backgroundColor: "rgba(90,156,143,0.55)",
          borderRadius: 3,
          yAxisID: "y",
          order: 2,
        },
        {
          type: "line",
          label: "Acurácia %",
          data: dados.map((d) => d.acuracia_pct),
          borderColor: "#4caf50",
          backgroundColor: "#4caf50",
          pointBackgroundColor: dados.map((d) => corFarolAcuracia(d.acuracia_pct)),
          pointBorderColor: dados.map((d) => corFarolAcuracia(d.acuracia_pct)),
          pointRadius: 4,
          tension: 0.3,
          yAxisID: "y1",
          order: 1,
        },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { display: false } },
        y: { position: "left", ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" }, beginAtZero: true, title: { display: true, text: "itens", color: "#8ca0a3", font: { size: 10 } } },
        y1: { position: "right", ticks: { color: "#4caf50", font: { size: 10 } }, grid: { display: false }, min: 0, max: 100, title: { display: true, text: "acurácia %", color: "#4caf50", font: { size: 10 } } },
      },
    },
  });
}

function formatarDataCurta(iso) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

// regressão linear simples (mínimos quadrados) sobre uma série y (índice = x)
function regressaoLinear(valores) {
  const pontos = valores.map((v, i) => [i, v]).filter(([, v]) => v != null && !isNaN(v));
  const n = pontos.length;
  if (n < 2) return { slope: 0, intercept: pontos[0]?.[1] ?? 0 };
  const somaX = pontos.reduce((s, [x]) => s + x, 0);
  const somaY = pontos.reduce((s, [, y]) => s + y, 0);
  const somaXY = pontos.reduce((s, [x, y]) => s + x * y, 0);
  const somaX2 = pontos.reduce((s, [x]) => s + x * x, 0);
  const slope = (n * somaXY - somaX * somaY) / (n * somaX2 - somaX * somaX || 1);
  const intercept = (somaY - slope * somaX) / n;
  return { slope, intercept };
}

function renderTendencia(dados) {
  const ctx = document.getElementById("chart-tendencia");
  if (chartTendencia) chartTendencia.destroy();
  if (!dados.length) return;
  const serie = dados.map((d) => d.acuracia_pct);
  const { slope, intercept } = regressaoLinear(serie);
  const n = serie.length;
  const projecaoDias = 5;

  const labels = dados.map((d) => formatarDataCurta(d.data));
  const labelsProjecao = [];
  for (let i = 1; i <= projecaoDias; i++) labelsProjecao.push("+" + i);

  const linhaTendencia = serie.map((_, i) => round1(intercept + slope * i));
  const linhaProjecao = new Array(n - 1).fill(null).concat(
    [round1(intercept + slope * (n - 1))],
    Array.from({ length: projecaoDias }, (_, i) => round1(intercept + slope * (n - 1 + i + 1)))
  );

  chartTendencia = new Chart(ctx, {
    type: "line",
    data: {
      labels: [...labels, ...labelsProjecao],
      datasets: [
        {
          label: "Acurácia real",
          data: serie,
          borderColor: "#5b75ac",
          backgroundColor: "#5b75ac",
          pointRadius: 3,
          pointBackgroundColor: serie.map((v) => corFarolAcuracia(v)),
          pointBorderColor: serie.map((v) => corFarolAcuracia(v)),
          tension: 0.25,
        },
        {
          label: "Tendência",
          data: [...linhaTendencia, ...new Array(projecaoDias).fill(null)],
          borderColor: "#f9a825",
          borderDash: [6, 4],
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "Projeção",
          data: linhaProjecao,
          borderColor: "#e5534b",
          borderDash: [2, 3],
          pointStyle: "circle",
          pointRadius: 3,
          pointBackgroundColor: "#e5534b",
          borderWidth: 2,
          formatarRotulo: (v) => (v == null ? "" : Math.round(v) + "%"),
          corRotulo: "#e5534b",
        },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#212b30" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" }, min: 0, max: 100 },
      },
    },
  });

  const badge = document.getElementById("tendencia-badge");
  const footer = document.getElementById("tendencia-footer");
  const inclinacaoPorDia = round2(slope);
  if (Math.abs(inclinacaoPorDia) < 0.05) {
    badge.textContent = "Estável";
    badge.className = "tendencia-badge estavel";
  } else if (inclinacaoPorDia > 0) {
    badge.textContent = "↑ Tendência de melhora";
    badge.className = "tendencia-badge alta";
  } else {
    badge.textContent = "↓ Tendência de queda";
    badge.className = "tendencia-badge queda";
  }
  const projecaoFinal = linhaProjecao[linhaProjecao.length - 1];
  footer.textContent = `Inclinação: ${inclinacaoPorDia > 0 ? "+" : ""}${inclinacaoPorDia} pp/dia   |   Projeção em 5 dias: ~${projecaoFinal != null ? round1(projecaoFinal) : "—"}% de acurácia`;
}

function round1(v) { return v == null ? null : Math.round(v * 10) / 10; }
function round2(v) { return v == null ? null : Math.round(v * 100) / 100; }

function renderMom(dados) {
  const ctx = document.getElementById("chart-mom");
  ultimoAcuraciaMensalDados = dados;
  if (chartMom) chartMom.destroy();
  chartMom = new Chart(ctx, {
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        {
          type: "bar",
          label: "Acurácia do mês",
          data: dados.map((d) => d.acuracia_pct),
          backgroundColor: dados.map((d) => (d.variacao_mom_pp == null ? "#5b75ac" : d.variacao_mom_pp >= 0 ? "rgba(76,175,80,0.6)" : "rgba(229,83,75,0.6)")),
          borderRadius: 3,
          yAxisID: "y",
          formatarRotulo: (v) => v + "%",
        },
        {
          type: "line",
          label: "Variação MoM (pp)",
          data: dados.map((d) => d.variacao_mom_pp),
          borderColor: "#f9a825",
          backgroundColor: "#f9a825",
          pointRadius: 3,
          yAxisID: "y1",
          spanGaps: true,
          formatarRotulo: (v) => (v == null ? "" : (v > 0 ? "+" : "") + v + " pp"),
          corRotulo: "#f9a825",
        },
      ],
    },
    options: {
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.label === "Variação MoM (pp)") {
                const v = ctx.raw;
                return v == null ? "Variação MoM: —" : `Variação MoM: ${v > 0 ? "+" : ""}${v} pp`;
              }
              return `${ctx.dataset.label}: ${ctx.raw}%`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { display: false } },
        y: { position: "left", min: 0, max: 100, ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" }, title: { display: true, text: "acurácia %", color: "#8ca0a3", font: { size: 10 } } },
        y1: { position: "right", ticks: { color: "#f9a825", font: { size: 10 } }, grid: { display: false }, title: { display: true, text: "variação (pp)", color: "#f9a825", font: { size: 10 } } },
      },
    },
  });
}

function renderCausas(dados) {
  const ctx = document.getElementById("chart-causas");
  if (chartCausas) chartCausas.destroy();
  const cores = ["#6fa3a8", "#5b75ac", "#f9a825", "#e5534b", "#4caf50", "#7c93c2", "#8ca0a3", "#24393c"];
  chartCausas = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: dados.map((d) => rotulo(d.hipotese)),
      datasets: [{ data: dados.map((d) => d.quantidade), backgroundColor: cores, borderWidth: 0, formatarRotulo: (v) => v, corRotulo: "#12181b" }],
    },
    options: {
      plugins: { legend: { position: "right", labels: { color: "#8ca0a3", font: { size: 11 } } } },
    },
  });
}

function baseChartOptions() {
  return {
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" } },
      y: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" }, beginAtZero: true },
    },
  };
}

function renderHeatmap(dados) {
  const almoxs = [...new Set(dados.map((d) => d.almoxarifado))];
  const hipoteses = [...new Set(dados.map((d) => d.hipotese))];
  const max = Math.max(1, ...dados.map((d) => d.quantidade));
  const valor = (a, h) => dados.find((d) => d.almoxarifado === a && d.hipotese === h)?.quantidade || 0;

  // resumo operacional do almoxarifado clicado (texto corrido, pro pop-up) -
  // mesma ideia do resumo de ponto dos gráficos Chart.js, mas o heatmap é
  // HTML puro, então monta o texto na mão a partir dos mesmos `dados`.
  const resumoAlmox = (a) => {
    const linhas = dados.filter((d) => d.almoxarifado === a && d.quantidade > 0).sort((x, y) => y.quantidade - x.quantidade);
    const total = linhas.reduce((s, d) => s + d.quantidade, 0);
    if (!total) return `Nenhuma divergência registrada para o almoxarifado ${a} neste recorte.`;
    const detalhe = linhas.map((d) => `${rotulo(d.hipotese)}: ${d.quantidade}`).join(", ");
    return `O almoxarifado ${a} tem ${total} divergência${total === 1 ? "" : "s"} neste recorte, por hipótese — ${detalhe}.`;
  };

  const html = almoxs
    .map((a) => {
      const cells = hipoteses
        .map((h) => {
          const v = valor(a, h);
          const intensidade = v / max;
          const cor = v === 0 ? "#212b30" : mixColor(intensidade);
          return `<div class="heatmap-cell" data-almox="${a}" style="background:${cor};cursor:pointer" title="${a} × ${rotulo(h)}: ${v} · clique pra filtrar por este almoxarifado">${v || ""}</div>`;
        })
        .join("");
      return `<div class="heatmap-row"><div class="row-label" data-almox="${a}" style="cursor:pointer" title="Clique pra filtrar por este almoxarifado">${a}</div><div class="heatmap-cells">${cells}</div></div>`;
    })
    .join("");
  document.getElementById("heatmap").innerHTML = html || "<span style='color:var(--muted)'>Sem dados ainda.</span>";

  document.querySelectorAll("#heatmap [data-almox]").forEach((el) =>
    el.addEventListener("click", () => filtrarPainelPorAlmoxarifado(el.dataset.almox, `Almoxarifado ${el.dataset.almox}`, resumoAlmox(el.dataset.almox)))
  );
}

// usado tanto pelo heatmap quanto pelo ranking de almoxarifados reincidentes
// abaixo - clicar joga o valor no filtro de almoxarifado do próprio painel
// e recarrega (mesma lógica de cross-filter dos gráficos Chart.js). Quando
// um `resumo` é passado, também abre o pop-up de resumo operacional daquele
// almoxarifado (mesmo clicando de novo no que já está selecionado).
function filtrarPainelPorAlmoxarifado(almoxarifado, tituloResumo, resumo) {
  const select = document.getElementById("filtro-almoxarifado");
  if (select && select.value !== almoxarifado) {
    select.value = almoxarifado;
    select.dispatchEvent(new Event("change"));
  }
  if (resumo) abrirModalResumoPonto(tituloResumo || `Almoxarifado ${almoxarifado}`, resumo);
}

function mixColor(intensidade) {
  const r = Math.round(36 + intensidade * (200 - 36));
  const g = Math.round(31 + intensidade * (121 - 31));
  const b = Math.round(22 + intensidade * (58 - 22));
  return `rgb(${r},${g},${b})`;
}

function renderRanking(rank) {
  document.getElementById("rank-sku").innerHTML = rank.top_skus
    .map((r) => `<li><span>${r.sku}${r.descricao ? " — " + r.descricao : ""}</span><span class="qtd">${r.quantidade}</span></li>`)
    .join("") || "<li>Sem dados</li>";
  document.getElementById("rank-almox").innerHTML = rank.top_almoxarifados
    .map((r) => `<li data-almox="${r.almoxarifado}" style="cursor:pointer" title="Clique pra filtrar por este almoxarifado">${r.almoxarifado} <span class="qtd">${r.quantidade}</span></li>`)
    .join("") || "<li>Sem dados</li>";
  document.querySelectorAll("#rank-almox li[data-almox]").forEach((li) => {
    const r = rank.top_almoxarifados.find((x) => x.almoxarifado === li.dataset.almox);
    const resumo = r ? `O almoxarifado ${r.almoxarifado} aparece no ranking de reincidência com ${r.quantidade} ocorrência${r.quantidade === 1 ? "" : "s"} neste recorte.` : null;
    li.addEventListener("click", () => filtrarPainelPorAlmoxarifado(li.dataset.almox, `Almoxarifado ${li.dataset.almox}`, resumo));
  });
}

function renderTop(top) {
  document.querySelector("#tabela-top tbody").innerHTML = top
    .map(
      (d) => `<tr>
        <td>${d.sku}</td><td class="col-descricao">${d.descricao_produto || "—"}</td><td>${d.almoxarifado}</td><td>${d.saldo_sistema}</td>
        <td>${d.saldo_fisico}</td><td>${d.divergencia_qtd}</td><td>${badge(d.status)}</td>
      </tr>`
    )
    .join("");
}

function preencherFiltroAlmoxarifado(heatmapDados) {
  const sel = document.getElementById("filtro-almoxarifado");
  if (sel.options.length > 1) return;
  const almoxs = [...new Set(heatmapDados.map((d) => d.almoxarifado))];
  almoxs.forEach((a) => {
    const opt = document.createElement("option");
    opt.value = a;
    opt.textContent = a;
    sel.appendChild(opt);
  });
}
document.getElementById("filtro-almoxarifado").addEventListener("change", carregarDashboard);
document.getElementById("filtro-periodo").addEventListener("change", carregarDashboard);

// ---------- duplo clique nas barras do Painel: itens divergentes do período ----------
// Mesmo padrão já usado no calendário de Cobertura de Conferência
// (dblclick num elemento do gráfico abre um modal com a lista de itens,
// com ação "Ver" pra abrir a investigação por linha).
document.getElementById("chart-acuracia-dia").addEventListener("dblclick", (ev) => {
  if (!chartAcuraciaDia) return;
  // modo "index" (não "nearest"+intersect) - encontra a barra pela
  // posição no eixo X sem exigir acerto pixel-perfeito na área exata do
  // elemento, bem mais robusto quando o gráfico acabou de ser redesenhado
  // (ex: depois de abrir/fechar um modal)
  const pontos = chartAcuraciaDia.getElementsAtEventForMode(ev, "index", { intersect: false }, true);
  if (!pontos.length) return;
  const dia = ultimoAcuraciaDiaDados[pontos[0].index];
  if (!dia) return;
  abrirModalItensPeriodo(dia.data, dia.data, `Itens divergentes — ${formatarDataCurta(dia.data)}`);
});

document.getElementById("chart-mom").addEventListener("dblclick", (ev) => {
  if (!chartMom) return;
  const pontos = chartMom.getElementsAtEventForMode(ev, "index", { intersect: false }, true);
  if (!pontos.length) return;
  const mesInfo = ultimoAcuraciaMensalDados[pontos[0].index];
  if (!mesInfo) return;
  const [inicio, fim] = _primeiroUltimoDiaDoMes(mesInfo.mes);
  abrirModalItensPeriodo(inicio, fim, `Itens divergentes — ${mesInfo.mes}`);
});

function _primeiroUltimoDiaDoMes(mesStr) {
  // mesStr no formato "YYYY-MM"
  const [ano, mes] = mesStr.split("-").map(Number);
  const inicio = `${mesStr}-01`;
  const ultimoDia = new Date(ano, mes, 0).getDate(); // dia 0 do mês seguinte = último dia deste mês
  const fim = `${mesStr}-${String(ultimoDia).padStart(2, "0")}`;
  return [inicio, fim];
}

async function abrirModalItensPeriodo(dataInicio, dataFim, titulo) {
  const almox = document.getElementById("filtro-almoxarifado").value;
  const params = new URLSearchParams({ data_inicio: dataInicio, data_fim: dataFim });
  if (almox) params.set("almoxarifado", almox);
  const res = await apiFetch(`${API}/dashboard/itens-periodo?${params.toString()}`);
  if (!res.ok) {
    alert("Não foi possível carregar os itens desse período.");
    return;
  }
  const dados = await res.json();
  document.getElementById("modal-painel-periodo-titulo").textContent = `${titulo} (${dados.total})`;
  document.querySelector("#tabela-modal-painel-periodo tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr>
        <td>${i.sku}</td><td class="col-descricao">${i.descricao_produto || "—"}</td><td>${i.almoxarifado || "—"}</td>
        <td>${formatarDataCurta(i.data)}</td><td>${formatarMoeda(i.valor_estimado)}</td>
        <td>${rotulo(i.hipotese)}</td>
        <td>${i.tipo === "divergencia" ? badge(i.status) : `<span class="hint">Histórico resolvido</span>`}</td>
        <td>${i.tipo === "divergencia" ? `<button class="btn-secundario btn-ver-item-periodo" data-id="${i.id}">Ver</button>` : ""}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="8" style="color:var(--muted)">Nenhum item divergente nesse período.</td></tr>`;

  document.querySelectorAll(".btn-ver-item-periodo").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.getElementById("modal-painel-periodo-overlay").classList.add("hidden");
      mostrarView("lista");
      abrirDetalhe(parseInt(btn.dataset.id));
    })
  );

  document.getElementById("modal-painel-periodo-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-painel-periodo").addEventListener("click", () => {
  document.getElementById("modal-painel-periodo-overlay").classList.add("hidden");
});
document.getElementById("modal-painel-periodo-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-painel-periodo-overlay") document.getElementById("modal-painel-periodo-overlay").classList.add("hidden");
});

function badge(status) {
  const cls = "badge-" + status.toLowerCase();
  const texto = { Aberta: "Aberta", Em_Investigacao: "Em investigação", Resolvida: "Resolvida" }[status] || status;
  return `<span class="badge ${cls}">${texto}</span>`;
}

// ---------- lista de divergências ----------
let paginaAtualLista = 1;

async function carregarLista(pagina = 1) {
  paginaAtualLista = pagina;
  const status = document.getElementById("lista-filtro-status").value;
  const params = new URLSearchParams({ pagina, tamanho_pagina: 50 });
  if (status) params.set("status", status);
  const resposta = await apiFetch(`${API}/divergencias?${params.toString()}`).then((r) => r.json());
  const divs = resposta.itens || [];
  const tbody = document.querySelector("#tabela-lista tbody");
  tbody.innerHTML = divs
    .map(
      (d) => `<tr data-id="${d.id}">
        <td>${d.id}</td><td>${d.sku}${d.tem_investigacao_pendente ? ' <span title="Este SKU já tem outro caso em investigação" style="color:var(--alto)">⚠️</span>' : ""}</td><td class="col-descricao">${d.descricao_produto || "—"}</td><td>${d.almoxarifado}</td>
        <td>${formatarDataCurta(d.data_deteccao)}</td>
        <td>${formatarMoeda(d.valor_estimado)}</td>
        <td>${rotulo(d.hipotese_ia)}</td><td>${d.confianca_ia != null ? d.confianca_ia + "%" : "—"}</td>
        <td>${badge(d.status)}</td><td>&rarr;</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="10" style="color:var(--muted)">Nenhuma divergência encontrada.</td></tr>`;
  tbody.querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", () => abrirDetalhe(tr.dataset.id)));

  const paginacaoEl = document.getElementById("paginacao-lista");
  if (paginacaoEl) {
    paginacaoEl.innerHTML = `
      <button id="pag-anterior" ${resposta.pagina <= 1 ? "disabled" : ""}>&larr; Anterior</button>
      <span>Página ${resposta.pagina} de ${resposta.paginas} · ${resposta.total} divergência(s)</span>
      <button id="pag-proxima" ${resposta.pagina >= resposta.paginas ? "disabled" : ""}>Próxima &rarr;</button>
    `;
    const btnAnterior = document.getElementById("pag-anterior");
    const btnProxima = document.getElementById("pag-proxima");
    if (btnAnterior) btnAnterior.addEventListener("click", () => carregarLista(resposta.pagina - 1));
    if (btnProxima) btnProxima.addEventListener("click", () => carregarLista(resposta.pagina + 1));
  }
}
document.getElementById("lista-filtro-status").addEventListener("change", () => carregarLista(1));

const btnRecalcularValores = document.getElementById("btn-recalcular-valores");
if (btnRecalcularValores) {
  btnRecalcularValores.addEventListener("click", async () => {
    btnRecalcularValores.textContent = "Recalculando...";
    const res = await apiFetch(`${API}/divergencias/recalcular-valores`, { method: "POST" });
    const data = await res.json();
    btnRecalcularValores.textContent = "Recalcular valores";
    alert(`Verificadas: ${data.divergencias_verificadas} · Atualizadas: ${data.divergencias_atualizadas}`);
    carregarLista();
  });
}


// ---------- detalhe ----------
let historicoSkuCompleto = [];

async function abrirDetalhe(id) {
  const [d, historico, faltasSobras, motivos, correlacaoRede] = await Promise.all([
    apiFetch(`${API}/divergencias/${id}`).then((r) => r.json()),
    apiFetch(`${API}/divergencias/${id}/historico-sku`).then((r) => (r.ok ? r.json() : [])),
    apiFetch(`${API}/divergencias/${id}/faltas-sobras-mensal`).then((r) => (r.ok ? r.json() : [])),
    apiFetch(`${API}/divergencias/${id}/motivos-sku`).then((r) => (r.ok ? r.json() : [])),
    apiFetch(`${API}/divergencias/${id}/correlacao-rede`).then((r) => (r.ok ? r.json() : { encontrado: false, candidatos: [] })),
  ]);
  historicoSkuCompleto = historico;
  window.__divIdAtual = id;
  document.getElementById("detalhe-titulo").textContent = `Divergência #${d.id} — SKU ${d.sku}${d.descricao_produto ? " — " + d.descricao_produto : ""}`;

  const obsHtml = d.observacao_origem
    ? `<div class="evidencia-item sim"><span>Obs. original da planilha</span><span>"${d.observacao_origem}"</span></div>`
    : `<p class="hint">Nenhuma observação registrada na planilha de origem para este caso.</p>`;

  const evidenciasHtml = (d.evidencias || [])
    .map(
      (e) => `<div class="evidencia-item ${e.encontrado ? "sim" : "nao"}">
        <span>${rotulo(e.hipotese)} — ${e.verificacao}</span><span>${e.encontrado ? "peso " + e.peso_aplicado : "não encontrado"}</span>
      </div>`
    )
    .join("") || "<p class='hint'>Sem evidências registradas.</p>";

  const casosHtml = (d.casos_similares || [])
    .map((c) => {
      const qtd = c.divergencia_qtd != null ? `${c.divergencia_qtd > 0 ? "+" : ""}${c.divergencia_qtd}` : "—";
      const valor = c.valor != null && c.valor !== 0 ? ` · ${formatarMoeda(c.valor)}` : "";
      const extra = c.solucao_aplicada ? ` · "${c.solucao_aplicada}"${c.responsavel ? " (" + c.responsavel + ")" : ""}` : "";
      const descricao = c.descricao_produto ? ` — ${c.descricao_produto}` : "";
      return `<div class="evidencia-item sim">
        <span>SKU ${c.sku}${descricao} · ${c.almoxarifado || "—"} · qtd ${qtd}${valor} <span class="hint" style="display:inline">(${c.criterio})</span></span>
        <span>${rotulo(c.hipotese_confirmada)} — ${formatarDataCurta(c.data)}${extra}</span>
      </div>`;
    })
    .join("") || "<p class='hint'>Nenhum caso similar encontrado ainda.</p>";

  const distribHtml = (d.distribuicao_probabilidades || [])
    .map((p) => `<div class="evidencia-item sim"><span>${rotulo(p.hipotese)}</span><span>${p.confianca}%</span></div>`)
    .join("");

  const ultimosApontamentos = historico.slice(-4).reverse();
  const ultimosApontamentosHtml = ultimosApontamentos.length
    ? ultimosApontamentos.map((p) => `<div class="evidencia-item ${p.divergencia_qtd ? "nao" : "sim"}"><span>${p.almoxarifado}</span><span>${formatarDataCurta(p.data)} · ${p.status}</span></div>`).join("")
    : "<p class='hint'>Sem histórico anterior para este SKU.</p>";

  const podeEditar = usuarioAtual && usuarioAtual.papel !== "leitura";

  document.getElementById("detalhe-conteudo").innerHTML = `
    <div>
      <div class="panel">
        <div class="panel-title-row">
          <h2>Diagnóstico</h2>
          <div style="display:flex; gap:8px">
            ${d.status === "Aberta" && podeEditar ? `<button class="btn-secundario" id="btn-em-investigacao">🔎 Deixar em investigação</button>` : ""}
            ${d.status !== "Resolvida" && podeEditar ? `<button class="btn-secundario" id="btn-reinvestigar">↻ Reinvestigar</button>` : ""}
          </div>
        </div>
        ${d.tem_investigacao_pendente ? `<p style="color:var(--alto)">⚠️ Este SKU já tem outro caso ainda em investigação - pode ser reincidência antes da causa anterior ser resolvida.</p>` : ""}
        <p><strong>Hipótese (motor de regras):</strong> ${rotulo(d.hipotese_regras)} ${d.confianca_regras != null ? "(" + d.confianca_regras + "%)" : ""}</p>
        <p><strong>Hipótese (modelo estatístico):</strong> ${rotulo(d.hipotese_ml)} ${d.confianca_ml != null ? "(" + d.confianca_ml + "%)" : ""}</p>
        <p><strong>Hipótese final reconciliada:</strong> ${rotulo(d.hipotese_ia)} ${d.confianca_ia != null ? "(" + d.confianca_ia + "%)" : ""}</p>
        <p>Saldo sistema: <strong>${d.saldo_sistema}</strong> · Saldo físico: <strong>${d.saldo_fisico}</strong> · Divergência: <strong>${d.divergencia_qtd}</strong></p>
        <p>Valor estimado: <strong>${formatarMoeda(d.valor_estimado)}</strong>${d.valor_estimado === 0 ? " <span class='hint' style='display:inline'>(sem custo cadastrado para este SKU)</span>" : ""}</p>
        <p>Data de detecção: <strong>${formatarDataCurta(d.data_deteccao)}</strong></p>
      </div>
      <div class="panel"><h2>Observação original (planilha)</h2>${obsHtml}</div>
      <div class="panel"><h2>Evidências</h2>${evidenciasHtml}</div>
      <div class="panel"><h2>Casos similares</h2>${casosHtml}</div>
      <div class="panel"><h2>Distribuição de probabilidades</h2>${distribHtml}</div>
    </div>
    <div>
      <div class="panel form-confirmar">
        <h2>Confirmar diagnóstico</h2>
        ${
          d.status === "Resolvida"
            ? `<p class="hint">Já resolvida como <strong>${rotulo(d.hipotese_confirmada)}</strong> por ${d.responsavel || "—"}.</p>`
            : !podeEditar
            ? `<p class="hint">Seu papel (leitura) não permite confirmar diagnósticos.</p>`
            : `
          <label>Hipótese confirmada</label>
          <select id="f-hipotese">${Object.entries(todasHipoteses()).map(([c, n]) => `<option value="${c}" ${c === d.hipotese_ia ? "selected" : ""}>${n}</option>`).join("")}</select>
          <label>Solução aplicada</label>
          <input id="f-solucao" type="text" placeholder="Ex: NF baixada manualmente">
          <label>Responsável</label>
          <input id="f-responsavel" type="text" placeholder="Nome">
          <label>Tempo de resolução (min)</label>
          <input id="f-tempo" type="number" placeholder="15">
          <button class="btn-primario" id="btn-confirmar">Confirmar e resolver</button>
        `
        }
      </div>
      <div class="panel">
        <div class="panel-title-row">
          <h2>Histórico do SKU</h2>
          <select id="sel-tipo-historico" class="select-filtro" style="font-size:12px">
            <option value="todos">Linear (tudo)</option>
            <option value="movimentacao">Movimentados</option>
            <option value="fechamento_inventario">Inventários</option>
          </select>
        </div>
        <p class="panel-sub">Quando divergiu e quando estabilizou, e por qual almoxarifado passou</p>
        <canvas id="chart-historico-sku" height="140"></canvas>
      </div>
      <div class="panel">
        <h2>Projeção de acurácia deste item</h2>
        <p class="panel-sub" id="projecao-sku-subtitulo">Regressão linear sobre o histórico de apontamentos deste SKU</p>
        <canvas id="chart-projecao-sku" height="140"></canvas>
        <p class="hint" id="projecao-sku-footer"></p>
      </div>
      <div class="panel">
        <h2>Falta × Sobra por período</h2>
        <p class="panel-sub">Sobra e falta contam separadamente (não se cancelam) - mostra se a direção da divergência está mudando</p>
        <canvas id="chart-faltas-sobras-sku" height="140"></canvas>
      </div>
      <div class="panel">
        <h2>Motivos das divergências deste SKU</h2>
        <canvas id="chart-motivos-sku" height="180"></canvas>
      </div>
      <div class="panel">
        <h2>Correlação de rede</h2>
        <p class="panel-sub">Existe sobra/falta oposta do mesmo SKU em outro almoxarifado, perto dessa data?</p>
        <div id="correlacao-rede-conteudo"></div>
      </div>
      <div class="panel">
        <h2>Últimos apontamentos</h2>
        ${ultimosApontamentosHtml}
      </div>
    </div>
  `;

  if (d.status !== "Resolvida" && podeEditar) {
    document.getElementById("btn-confirmar").addEventListener("click", () => confirmarDivergencia(d.id));
    const btnReinvestigar = document.getElementById("btn-reinvestigar");
    if (btnReinvestigar) {
      btnReinvestigar.addEventListener("click", async () => {
        btnReinvestigar.textContent = "Reinvestigando...";
        await apiFetch(`${API}/divergencias/${d.id}/reinvestigar`, { method: "POST" });
        abrirDetalhe(d.id);
      });
    }
    const btnEmInvestigacao = document.getElementById("btn-em-investigacao");
    if (btnEmInvestigacao) {
      btnEmInvestigacao.addEventListener("click", async () => {
        await apiFetch(`${API}/divergencias/${d.id}/marcar-investigacao`, { method: "POST" });
        abrirDetalhe(d.id);
      });
    }
  }
  tentarRenderizar(() => renderHistoricoSku(historico));
  tentarRenderizar(() => renderProjecaoSku(historico));
  tentarRenderizar(() => renderFaltasSobrasSku(faltasSobras));
  tentarRenderizar(() => renderMotivosSku(motivos));
  tentarRenderizar(() => renderCorrelacaoRede(correlacaoRede));

  document.getElementById("sel-tipo-historico").addEventListener("change", (ev) => {
    const tipo = ev.target.value;
    const filtrado = tipo === "todos" ? historicoSkuCompleto : historicoSkuCompleto.filter((p) => p.tipo_origem === tipo);
    renderHistoricoSku(filtrado);
    renderProjecaoSku(filtrado);
  });

  mostrarView("detalhe");
}

let chartProjecaoSku, chartFaltasSobrasSku, chartMotivosSku;

function renderProjecaoSku(historico) {
  const ctx = document.getElementById("chart-projecao-sku");
  if (!ctx) return;
  if (chartProjecaoSku) chartProjecaoSku.destroy();
  const footer = document.getElementById("projecao-sku-footer");
  ctx.style.display = "";
  if (!historico.length) {
    ctx.style.display = "none";
    footer.textContent = "Nenhum apontamento desse tipo para este SKU - tente outra opção no seletor acima.";
    return;
  }
  if (historico.length < 2) {
    footer.textContent = "Poucos apontamentos ainda para projetar uma tendência (mínimo 2).";
    return;
  }

  const serie = historico.map((p) => p.acuracia_pct);
  const { slope, intercept } = regressaoLinear(serie);
  const n = serie.length;
  const projecaoPontos = 5;
  const labels = historico.map((p) => formatarDataCurta(p.data));
  const labelsProjecao = Array.from({ length: projecaoPontos }, (_, i) => "+" + (i + 1));

  const clamp = (v) => (v == null ? null : Math.max(0, Math.min(100, v)));
  const linhaTendencia = serie.map((_, i) => clamp(round1(intercept + slope * i)));
  const linhaProjecao = new Array(n - 1).fill(null).concat(
    [clamp(round1(intercept + slope * (n - 1)))],
    Array.from({ length: projecaoPontos }, (_, i) => clamp(round1(intercept + slope * (n - 1 + i + 1))))
  );

  chartProjecaoSku = new Chart(ctx, {
    type: "line",
    data: {
      labels: [...labels, ...labelsProjecao],
      datasets: [
        { label: "Acurácia real", data: serie, borderColor: "#5b75ac", backgroundColor: "#5b75ac", pointRadius: 3, pointBackgroundColor: serie.map((v) => corFarolAcuracia(v)), tension: 0.25 },
        { label: "Tendência", data: [...linhaTendencia, ...new Array(projecaoPontos).fill(null)], borderColor: "#f9a825", borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
        { label: "Projeção", data: linhaProjecao, borderColor: "#e5534b", borderDash: [2, 3], pointRadius: 3, pointBackgroundColor: "#e5534b", borderWidth: 2 },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 9 } }, grid: { display: false } },
        y: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { color: "#2e3a40" }, min: 0, max: 100 },
      },
    },
  });

  const inclinacao = round2(slope);
  const projecaoFinalBruta = linhaProjecao[linhaProjecao.length - 1];
  const projecaoFinal = projecaoFinalBruta != null ? Math.max(0, Math.min(100, projecaoFinalBruta)) : null;
  const direcao = Math.abs(inclinacao) < 0.05 ? "estável" : inclinacao > 0 ? "↑ melhorando" : "↓ piorando";
  footer.textContent = `Tendência: ${direcao} (${inclinacao > 0 ? "+" : ""}${inclinacao} pp por apontamento) · Projeção: ~${projecaoFinal != null ? round1(projecaoFinal) : "—"}% de acurácia nos próximos apontamentos.`;
}

function renderFaltasSobrasSku(dados) {
  const ctx = document.getElementById("chart-faltas-sobras-sku");
  if (!ctx) return;
  if (chartFaltasSobrasSku) chartFaltasSobrasSku.destroy();
  if (!dados.length) return;
  chartFaltasSobrasSku = new Chart(ctx, {
    type: "bar",
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        { label: "Falta (qtd)", data: dados.map((d) => -d.qtd_faltas), backgroundColor: "#e5534b", borderRadius: 3 },
        { label: "Sobra (qtd)", data: dados.map((d) => d.qtd_sobras), backgroundColor: "#4caf50", borderRadius: 3 },
      ],
    },
    options: {
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const d = dados[items[0].dataIndex];
              return [
                `Valor em falta: ${formatarMoeda(d.valor_faltas)}`,
                `Valor em sobra: ${formatarMoeda(d.valor_sobras)}`,
                "Duplo clique pra ver o detalhe (almoxarifado, data, sistema × contagem)",
              ];
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { color: "#8ca0a3", font: { size: 10 }, callback: (v) => Math.abs(v) }, grid: { color: "#2e3a40" } },
      },
    },
  });

  ctx.ondblclick = async (evt) => {
    const pontos = chartFaltasSobrasSku.getElementsAtEventForMode(evt, "index", { intersect: true }, true);
    if (!pontos.length) return;
    const mes = dados[pontos[0].index].mes;
    await abrirModalDetalheMes(mes);
  };
}

async function abrirModalDetalheMes(mes) {
  const res = await apiFetch(`${API}/divergencias/${window.__divIdAtual}/detalhes-mes?mes=${encodeURIComponent(mes)}`);
  if (!res.ok) {
    alert("Não foi possível carregar o detalhe desse mês.");
    return;
  }
  const dados = await res.json();
  document.getElementById("modal-detalhe-mes-titulo").textContent = `${dados.sku}${dados.descricao_produto ? " — " + dados.descricao_produto : ""} — ${mes}`;
  document.querySelector("#tabela-modal-detalhe-mes tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr>
        <td>${formatarDataCurta(i.data)}</td><td>${i.almoxarifado}</td>
        <td>${i.saldo_sistema}</td><td>${i.saldo_fisico}</td>
        <td style="color:${i.divergencia_qtd < 0 ? "var(--critico)" : "var(--ok)"}">${i.divergencia_qtd > 0 ? "+" : ""}${i.divergencia_qtd}</td>
        <td>${rotulo(i.hipotese)}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="6" style="color:var(--muted)">Nenhum apontamento encontrado nesse mês.</td></tr>`;
  document.getElementById("modal-detalhe-mes-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-detalhe-mes").addEventListener("click", () => {
  document.getElementById("modal-detalhe-mes-overlay").classList.add("hidden");
});
document.getElementById("modal-detalhe-mes-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-detalhe-mes-overlay") document.getElementById("modal-detalhe-mes-overlay").classList.add("hidden");
});

function renderMotivosSku(dados) {
  const ctx = document.getElementById("chart-motivos-sku");
  if (!ctx) return;
  if (chartMotivosSku) chartMotivosSku.destroy();
  if (!dados.length) {
    ctx.parentElement.querySelector(".hint-motivos")?.remove();
    const p = document.createElement("p");
    p.className = "hint hint-motivos";
    p.textContent = "Nenhuma divergência anterior registrada para este SKU.";
    ctx.after(p);
    return;
  }
  const cores = ["#5b75ac", "#e5534b", "#4caf50", "#f9a825", "#8e7cc3", "#e8873a", "#4ba3c7", "#c77dbb", "#7fae6f", "#b0846a"];
  chartMotivosSku = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: dados.map((d) => rotulo(d.hipotese)),
      datasets: [{ data: dados.map((d) => d.quantidade), backgroundColor: dados.map((_, i) => cores[i % cores.length]) }],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
    },
  });
}

function renderCorrelacaoRede(dados) {
  const div = document.getElementById("correlacao-rede-conteudo");
  if (!div) return;
  if (!dados.encontrado) {
    div.innerHTML = `<p class="hint">Nenhuma ${dados.tipo_desta_divergencia === "falta" ? "sobra" : "falta"} correspondente encontrada em outro almoxarifado, nesta janela de tempo.</p>`;
    return;
  }
  const rotuloOposto = dados.tipo_desta_divergencia === "falta" ? "Sobra encontrada" : "Falta encontrada";
  div.innerHTML = dados.candidatos
    .map(
      (c) => `<div class="evidencia-item sim">
        <span>${rotuloOposto} em <strong>${c.almoxarifado}</strong> · qtd ${c.divergencia_qtd > 0 ? "+" : ""}${c.divergencia_qtd}${c.valor_estimado ? " · " + formatarMoeda(c.valor_estimado) : ""}</span>
        <span>${formatarDataCurta(c.data_deteccao)} · ${c.status}</span>
      </div>`
    )
    .join("");
}

let chartHistoricoSku;
function renderHistoricoSku(historico) {
  const ctx = document.getElementById("chart-historico-sku");
  if (!ctx) return;
  if (chartHistoricoSku) chartHistoricoSku.destroy();
  ctx.parentElement.querySelector(".hint-sem-dado-historico")?.remove();
  ctx.style.display = "";
  if (!historico.length) {
    ctx.style.display = "none";
    const p = document.createElement("p");
    p.className = "hint hint-sem-dado-historico";
    p.textContent = "Nenhum apontamento desse tipo para este SKU - tente outra opção no seletor acima.";
    ctx.after(p);
    return;
  }
  chartHistoricoSku = new Chart(ctx, {
    type: "line",
    data: {
      labels: historico.map((p) => formatarDataCurta(p.data)),
      datasets: [{
        label: "Divergência (qtd)",
        data: historico.map((p) => p.divergencia_qtd || 0),
        borderColor: "#e8873a",
        backgroundColor: "rgba(232,135,58,0.15)",
        fill: true,
        tension: 0.2,
        pointRadius: 3,
        pointBackgroundColor: historico.map((p) => (p.divergencia_qtd ? "#e5534b" : "#4caf50")),
      }],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const p = historico[items[0].dataIndex];
              return [`Almoxarifado: ${p.almoxarifado}`, `Status: ${p.status}`, p.hipotese ? `Hipótese: ${rotulo(p.hipotese)}` : ""];
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "var(--muted)", font: { size: 9 } }, grid: { display: false } },
        y: { ticks: { color: "var(--muted)", font: { size: 10 } }, grid: { color: "var(--border)" } },
      },
    },
  });
}

async function confirmarDivergencia(id) {
  const payload = {
    hipotese_confirmada: document.getElementById("f-hipotese").value,
    solucao_aplicada: document.getElementById("f-solucao").value,
    responsavel: document.getElementById("f-responsavel").value,
    tempo_resolucao_minutos: parseFloat(document.getElementById("f-tempo").value) || null,
  };
  await apiFetch(`${API}/divergencias/${id}/confirmar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  mostrarView("lista");
}

// ---------- importação ----------
const inputArquivo = document.getElementById("input-arquivo");
const wrapAlmoxarifado = document.getElementById("wrap-almoxarifado");
const selectAlmoxarifadoImport = document.getElementById("input-almoxarifado");

function ehExcel(nomeArquivo) {
  return /\.(xlsx|xlsm)$/i.test(nomeArquivo);
}

async function atualizarSelectAlmoxarifadoImport() {
  const lista = await apiFetch(`${API}/importar/almoxarifados`).then((r) => r.json());
  selectAlmoxarifadoImport.innerHTML = lista.map((a) => `<option value="${a.codigo}">${a.nome} (${a.codigo})</option>`).join("");
}

inputArquivo.addEventListener("change", async () => {
  const arquivo = inputArquivo.files[0];
  if (!arquivo) return;
  if (ehExcel(arquivo.name)) {
    await atualizarSelectAlmoxarifadoImport(); // sempre busca a lista atual - nunca fica desatualizado
    wrapAlmoxarifado.classList.remove("hidden");
  } else {
    wrapAlmoxarifado.classList.add("hidden");
  }
});

document.getElementById("btn-importar").addEventListener("click", async () => {
  const resultado = document.getElementById("resultado-importacao");
  if (!inputArquivo.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const arquivo = inputArquivo.files[0];
  const form = new FormData();
  form.append("arquivo", arquivo);

  let url = `${API}/importar/movimentacao`;
  if (ehExcel(arquivo.name)) {
    if (!selectAlmoxarifadoImport.value) {
      resultado.textContent = "Selecione o almoxarifado deste arquivo antes de importar.";
      return;
    }
    form.append("almoxarifado", selectAlmoxarifadoImport.value);
    url = `${API}/importar/movimentacao-excel`;
  }

  resultado.textContent = "Importando...";
  try {
    const res = await apiFetch(url, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    resultado.textContent = JSON.stringify(data, null, 2);
    carregarLotesImportacao();
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

// ---------- lotes de importação (excluir importação) ----------
async function carregarLotesImportacao() {
  const tbody = document.querySelector("#tabela-lotes-importacao tbody");
  if (!tbody) return;
  const lotes = await apiFetch(`${API}/importar/lotes`).then((r) => r.json());
  tbody.innerHTML = lotes
    .map(
      (l) => `<tr>
        <td>${new Date(l.criado_em).toLocaleString("pt-BR")}</td>
        <td>${l.tipo === "movimentacao_excel" ? "Excel" : "CSV"}</td>
        <td class="col-descricao">${l.arquivo_origem || "—"}${l.almoxarifado ? " (" + l.almoxarifado + ")" : ""}</td>
        <td>${l.usuario || "—"}</td><td>${l.linhas_processadas}</td><td>${l.divergencias_criadas}</td>
        <td><button class="btn-secundario btn-excluir-lote" data-id="${l.id}">Excluir importação</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="7" style="color:var(--muted)">Nenhuma importação registrada ainda.</td></tr>`;

  document.querySelectorAll(".btn-excluir-lote").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("Excluir esta importação? Todas as divergências e o histórico criados por ela serão removidos.")) return;
      const res = await apiFetch(`${API}/importar/lotes/${btn.dataset.id}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      alert(`Removidas: ${data.divergencias_removidas} divergência(s) e ${data.historico_removido} registro(s) de histórico.`);
      carregarLotesImportacao();
    })
  );
}

// ---------- gestão de usuários (admin) ----------
async function carregarUsuarios() {
  const res = await apiFetch(`${API}/usuarios`);
  const usuarios = await res.json();
  const tbody = document.querySelector("#tabela-usuarios tbody");
  tbody.innerHTML = usuarios
    .map(
      (u) => `<tr data-id="${u.id}" data-ativo="${u.ativo}">
        <td>${u.username}</td><td>${u.nome_exibicao || "—"}</td>
        <td><span class="badge-papel badge-${u.papel}">${u.papel}</span></td>
        <td>${u.ativo ? "Ativo" : "Desativado"}</td>
        <td><button class="btn-secundario btn-toggle-usuario" data-id="${u.id}" data-ativo="${u.ativo}">${u.ativo ? "Desativar" : "Ativar"}</button></td>
      </tr>`
    )
    .join("");
  tbody.querySelectorAll(".btn-toggle-usuario").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ativo = btn.dataset.ativo === "true";
      await apiFetch(`${API}/usuarios/${btn.dataset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ativo: !ativo }),
      });
      carregarUsuarios();
    });
  });
}

document.getElementById("btn-criar-usuario").addEventListener("click", async () => {
  const msg = document.getElementById("usuario-msg");
  const payload = {
    username: document.getElementById("novo-usuario-username").value.trim(),
    senha: document.getElementById("novo-usuario-senha").value,
    nome_exibicao: document.getElementById("novo-usuario-nome").value.trim() || null,
    papel: document.getElementById("novo-usuario-papel").value,
  };
  if (!payload.username || !payload.senha) {
    msg.textContent = "Preencha username e senha.";
    return;
  }
  const res = await apiFetch(`${API}/usuarios`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    msg.textContent = data.detail || "Erro ao criar usuário.";
    return;
  }
  msg.textContent = `Usuário '${data.username}' criado com sucesso.`;
  document.getElementById("novo-usuario-username").value = "";
  document.getElementById("novo-usuario-senha").value = "";
  document.getElementById("novo-usuario-nome").value = "";
  carregarUsuarios();
});

// ---------- importação de custos ----------
const inputArquivoCustos = document.getElementById("input-arquivo-custos");
document.getElementById("btn-importar-custos").addEventListener("click", async () => {
  const resultado = document.getElementById("resultado-importacao-custos");
  if (!inputArquivoCustos.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", inputArquivoCustos.files[0]);
  const aba = document.getElementById("input-aba-custos").value.trim();
  if (aba) form.append("aba", aba);
  resultado.textContent = "Importando...";
  try {
    const res = await apiFetch(`${API}/importar/custos`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    resultado.textContent = JSON.stringify(data, null, 2);
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

document.getElementById("btn-importar-custos-preco").addEventListener("click", async () => {
  const input = document.getElementById("input-arquivo-custos-preco");
  const resultado = document.getElementById("resultado-importacao-custos-preco");
  if (!input.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", input.files[0]);
  form.append("aba", document.getElementById("input-aba-custos-preco").value || "tabela de preço");
  resultado.textContent = "Importando (pode levar alguns segundos em planilhas grandes)...";
  try {
    const res = await apiFetch(`${API}/importar/custos-planilha-preco`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    resultado.textContent = JSON.stringify(data, null, 2);
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

async function carregarOpcoesAlmoxarifadoImportadorBruto() {
  const res = await apiFetch(`${API}/almoxarifados-cadastro`);
  if (!res.ok) return;
  const lista = await res.json();
  const opcoesHtml =
    `<option value="">Selecione...</option>` +
    lista
      .filter((a) => a.ativo)
      .map((a) => `<option value="${a.codigo}">${a.codigo}${a.nome_exibicao && a.nome_exibicao !== a.codigo ? " — " + a.nome_exibicao : ""}</option>`)
      .join("");
  document.querySelectorAll("#tabela-importador-bruto .cb-almoxarifado").forEach((sel) => {
    const valorAtual = sel.value;
    sel.innerHTML = opcoesHtml;
    if (valorAtual) sel.value = valorAtual;
  });
}

document.getElementById("btn-adicionar-linha-bruto").addEventListener("click", () => {
  const tbody = document.querySelector("#tabela-importador-bruto tbody");
  const novaLinha = tbody.rows[0].cloneNode(true);
  novaLinha.querySelectorAll("input").forEach((i) => (i.value = ""));
  novaLinha.querySelectorAll("select").forEach((s) => (s.selectedIndex = 0));
  novaLinha.querySelector(".cb-resultado").textContent = "";
  tbody.appendChild(novaLinha);
});

document.querySelector("#tabela-importador-bruto tbody").addEventListener("click", async (ev) => {
  const btn = ev.target.closest(".btn-importar-bruto");
  if (!btn) return;
  const linha = btn.closest("tr");
  const almoxarifado = linha.querySelector(".cb-almoxarifado").value.trim();
  const inputArquivo = linha.querySelector(".cb-arquivo");
  const aba = linha.querySelector(".cb-aba").value.trim();
  const resultado = linha.querySelector(".cb-resultado");

  if (!almoxarifado) {
    resultado.textContent = "Informe o almoxarifado.";
    return;
  }
  if (!inputArquivo.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", inputArquivo.files[0]);
  form.append("almoxarifado", almoxarifado);
  if (aba) form.append("aba", aba);

  btn.disabled = true;
  resultado.textContent = "Importando (pode levar um pouco em arquivos grandes)...";
  try {
    const res = await apiFetch(`${API}/importar/movimentacao-bruta-sistema`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro: ${data.detail || JSON.stringify(data)}`;
    } else {
      resultado.textContent = `${data.dias_com_movimento_registrados} dia(s) com movimento · ${data.conferencias_registradas} conferência(s) · ${data.transferencias_criadas} transferência(s) nova(s) · ${data.transferencias_atualizadas} cruzada(s)${
        data.almoxarifados_nao_mapeados.length ? " · não mapeados: " + data.almoxarifados_nao_mapeados.join(", ") : ""
      }`;
    }
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
  btn.disabled = false;
});

document.querySelectorAll(".btn-importar-contexto").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const linha = btn.closest("tr");
    const inputArquivo = linha.querySelector(".ctx-arquivo");
    const inputAba = linha.querySelector(".ctx-aba");
    const resultado = linha.querySelector(".ctx-resultado");
    const endpoint = inputArquivo.dataset.endpoint;

    if (!inputArquivo.files.length) {
      resultado.textContent = "Selecione um arquivo primeiro.";
      return;
    }
    const form = new FormData();
    form.append("arquivo", inputArquivo.files[0]);
    if (inputAba.value.trim()) form.append("aba", inputAba.value.trim());

    btn.disabled = true;
    resultado.textContent = "Importando...";
    try {
      const res = await apiFetch(`${API}/importar/${endpoint}`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        resultado.textContent = `Erro: ${data.detail || JSON.stringify(data)}`;
      } else {
        resultado.textContent = `${data.linhas_importadas} linha(s) importada(s) (substituiu os dados anteriores)${data.ignorados_sem_numero_op ? " · " + data.ignorados_sem_numero_op + " ignorada(s) sem nº de OP" : ""}`;
      }
    } catch (erro) {
      resultado.textContent = "Falha ao importar: " + erro.message;
    }
    btn.disabled = false;
  });
});

// ---------- acurácia ponderada (IAP/IAQ) ----------
let apChartComparativo, apChartPareto, apChartMagnitude, apChartEvolucao, apChartGrupo3, apChartAlmox3, apChartMom;
let apFiltrosCarregados = false;
let apEvolucaoCache = [];

async function carregarAcuraciaPonderada() {
  const mes = document.getElementById("ap-filtro-mes").value;
  const almox = document.getElementById("ap-filtro-almoxarifado").value;
  const params = new URLSearchParams();
  if (mes) params.set("mes", mes);
  if (almox) params.set("almoxarifado", almox);
  const qs = "?" + params.toString();

  async function buscarOuErroAp(url) {
    const res = await apiFetch(url);
    const dados = await res.json();
    if (!res.ok) {
      console.error(`Atlas: erro ${res.status} em ${url}:`, dados);
      throw new Error(dados.detail || `Erro ${res.status} ao carregar ${url}`);
    }
    return dados;
  }

  let comparativo, pareto, magnitude, evolucao, porAlmox, porGrupo3, porAlmox3;
  try {
    [comparativo, pareto, magnitude, evolucao, porAlmox, porGrupo3, porAlmox3] = await Promise.all([
      buscarOuErroAp(`${API}/fechamentos/dashboard/comparativo-acuracia${qs}`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/concentracao-valor${qs}&top_n=10`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/distribuicao-magnitude${qs}`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/evolucao-ponderada-mensal${almox ? "?almoxarifado=" + almox : ""}`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/por-almoxarifado`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/comparativo-por-grupo${qs}`),
      buscarOuErroAp(`${API}/fechamentos/dashboard/comparativo-por-almoxarifado${mes ? "?mes=" + mes : ""}`),
    ]);
  } catch (erro) {
    document.getElementById("ap-kpi-row").innerHTML =
      `<div class="kpi-card" style="grid-column:1/-1"><div class="kpi-label" style="color:var(--critico)">Não consegui carregar esta tela</div><div style="font-size:13px;color:var(--muted);margin-top:6px">${erro.message}. Isso costuma acontecer quando o backend ainda não foi atualizado para a versão mais recente - confirme que substituiu a pasta backend/app completa (veja ATUALIZANDO.md) e reinicie o servidor.</div></div>`;
    return;
  }

  tentarRenderizar(() => renderApKpis(comparativo));
  tentarRenderizar(() => renderApComparativo(comparativo));
  tentarRenderizar(() => renderApPorGrupo(porGrupo3));
  tentarRenderizar(() => renderApPorAlmoxarifado(porAlmox3));
  tentarRenderizar(() => renderApPareto(pareto));
  tentarRenderizar(() => renderApMagnitude(magnitude));
  tentarRenderizar(() => renderApEvolucao(evolucao));
  tentarRenderizar(() => renderApMom(evolucao));
  tentarRenderizar(() => renderizarResumoExecutivoNarrado("ap-resumo-executivo", construirResumoExecutivoAcuraciaPonderada(comparativo)));

  if (!apFiltrosCarregados) {
    evolucao.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.mes;
      opt.textContent = d.mes;
      document.getElementById("ap-filtro-mes").appendChild(opt);
    });
    porAlmox.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.almoxarifado;
      opt.textContent = d.almoxarifado;
      document.getElementById("ap-filtro-almoxarifado").appendChild(opt);
    });
    apFiltrosCarregados = true;
  }
}
document.getElementById("ap-filtro-mes").addEventListener("change", carregarAcuraciaPonderada);
document.getElementById("ap-filtro-almoxarifado").addEventListener("change", carregarAcuraciaPonderada);

function renderApKpis(c) {
  const cards = [
    { label: "Acurácia item a item", value: c.item_a_item_pct != null ? c.item_a_item_pct + "%" : "—", cor: corFarolAcuracia(c.item_a_item_pct) },
    { label: "IAQ (ponderado por quantidade)", value: c.iaq_pct != null ? c.iaq_pct + "%" : "—", cor: corFarolAcuracia(c.iaq_pct) },
    { label: "IAP (ponderado por valor)", value: c.iap_pct != null ? c.iap_pct + "%" : `— (custo: ${c.cobertura_custo_pct}%)`, cor: c.iap_pct != null ? corFarolAcuracia(c.iap_pct) : "var(--muted)" },
    { label: "Gap item×IAQ", value: c.gap_item_vs_iaq_pp != null ? (c.gap_item_vs_iaq_pp > 0 ? "+" : "") + c.gap_item_vs_iaq_pp + " pp" : "—", accent: true },
    { label: "Gap item×IAP", value: c.gap_item_vs_iap_pp != null ? (c.gap_item_vs_iap_pp > 0 ? "+" : "") + c.gap_item_vs_iap_pp + " pp" : "—", accent: true },
  ];
  document.getElementById("ap-kpi-row").innerHTML = cards
    .map((cd) => `<div class="kpi-card"><div class="kpi-label">${cd.label}</div><div class="kpi-value ${cd.accent ? "accent" : ""}" style="${cd.cor ? "color:" + cd.cor : ""}">${cd.value}</div></div>`)
    .join("");
}

function renderApComparativo(c) {
  const ctx = document.getElementById("ap-chart-comparativo");
  if (apChartComparativo) apChartComparativo.destroy();
  const dados = [c.item_a_item_pct, c.iaq_pct, c.iap_pct];
  apChartComparativo = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Item a item (atual)", "IAQ (quantidade)", "IAP (valor)"],
      datasets: [{
        data: dados, backgroundColor: dados.map((v) => corFarolAcuracia(v)), borderRadius: 4,
        formatarRotulo: (v) => (v != null ? v + "%" : "sem custo"),
      }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 12 } }, grid: { display: false } },
      },
    },
  });
}

function _grupoDataset3Modelos(dados, chaveCategoria) {
  return {
    labels: dados.map((d) => d[chaveCategoria]),
    datasets: [
      { label: "Item a item", data: dados.map((d) => d.item_a_item_pct), backgroundColor: "#f9a825" },
      { label: "IAQ (quantidade)", data: dados.map((d) => d.iaq_pct), backgroundColor: "#4caf50" },
      { label: "IAP (valor)", data: dados.map((d) => d.iap_pct), backgroundColor: "#5b75ac" },
    ],
  };
}

function renderApPorGrupo(dados) {
  const ctx = document.getElementById("ap-chart-grupo");
  if (apChartGrupo3) apChartGrupo3.destroy();
  apChartGrupo3 = new Chart(ctx, {
    type: "bar",
    data: _grupoDataset3Modelos(dados, "grupo"),
    options: {
      indexAxis: "y",
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
      scales: {
        x: { min: 0, max: 100, ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

function renderApPorAlmoxarifado(dados) {
  const ctx = document.getElementById("ap-chart-almox");
  if (apChartAlmox3) apChartAlmox3.destroy();
  apChartAlmox3 = new Chart(ctx, {
    type: "bar",
    data: _grupoDataset3Modelos(dados, "almoxarifado"),
    options: {
      indexAxis: "y",
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
      scales: {
        x: { min: 0, max: 100, ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });

  ativarCliqueParaFiltrar(apChartAlmox3, ctx, dados, (d) => d.almoxarifado, "ap-filtro-almoxarifado", (d) => ({
    titulo: `Acurácia Ponderada — ${d.almoxarifado}`,
    resumo: `No almoxarifado ${d.almoxarifado}, a acurácia item a item foi de ${d.item_a_item_pct}%, o IAQ (ponderado por quantidade) foi de ${d.iaq_pct}% e o IAP (ponderado por valor) foi de ${d.iap_pct != null ? d.iap_pct + "%" : "sem dado"}.`,
  }));
}

const AP_MOM_ROTULOS = { iap_pct: "IAP (valor)", iaq_pct: "IAQ (quantidade)", item_a_item_pct: "Item a item" };
const AP_MOM_VARIACAO_CHAVE = { iap_pct: "variacao_iap_pp", iaq_pct: "variacao_iaq_pp", item_a_item_pct: "variacao_item_pp" };

function renderApMom(dados) {
  apEvolucaoCache = dados;
  const metrica = document.getElementById("ap-mom-metrica").value;
  const ehValorMod = metrica === "valor_mod";
  const ctx = document.getElementById("ap-chart-mom");
  if (apChartMom) apChartMom.destroy();

  document.getElementById("ap-mom-subtitulo").textContent = ehValorMod
    ? "Colunas: valor total em divergência no mês (sobra + falta juntos, sem se cancelar) · Linha: variação MoM em R$"
    : "Colunas: acurácia do mês · Linha: variação MoM em pontos percentuais";

  const datasetBarra = ehValorMod
    ? {
        type: "bar", label: "Valor Mod — impacto financeiro do mês (R$)", data: dados.map((d) => d.valor_mod),
        backgroundColor: "#e5534b", borderRadius: 3, yAxisID: "y",
        formatarRotulo: (v) => (v != null ? formatarMoeda(v) : "—"),
      }
    : {
        type: "bar", label: `Acurácia do mês — ${AP_MOM_ROTULOS[metrica]}`, data: dados.map((d) => d[metrica]),
        backgroundColor: dados.map((d) => corFarolAcuracia(d[metrica])), borderRadius: 3, yAxisID: "y",
        formatarRotulo: (v) => (v != null ? v + "%" : "—"),
      };

  const datasetLinha = ehValorMod
    ? {
        type: "line", label: "Variação MoM (R$)", data: dados.map((d) => d.variacao_valor_mod), borderColor: "#f9a825",
        backgroundColor: "#f9a825", pointRadius: 4, yAxisID: "y1", spanGaps: true,
        formatarRotulo: (v) => (v == null ? "" : (v > 0 ? "+" : "") + formatarMoeda(v)), corRotulo: "#f9a825",
      }
    : {
        type: "line", label: "Variação MoM (pp)", data: dados.map((d) => d[AP_MOM_VARIACAO_CHAVE[metrica]]), borderColor: "#f9a825",
        backgroundColor: "#f9a825", pointRadius: 4, yAxisID: "y1", spanGaps: true,
        formatarRotulo: (v) => (v == null ? "" : (v > 0 ? "+" : "") + v + " pp"), corRotulo: "#f9a825",
      };

  apChartMom = new Chart(ctx, {
    data: { labels: dados.map((d) => d.mes), datasets: [datasetBarra, datasetLinha] },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3" } } },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: ehValorMod
          ? { position: "left", ticks: { color: "#8ca0a3", callback: (v) => formatarMoeda(v) }, grid: { color: "#2e3a40" } }
          : { position: "left", min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y1: ehValorMod
          ? { position: "right", ticks: { color: "#f9a825", callback: (v) => formatarMoeda(v) }, grid: { display: false } }
          : { position: "right", ticks: { color: "#f9a825" }, grid: { display: false } },
      },
    },
  });
}
document.getElementById("ap-mom-metrica").addEventListener("change", () => renderApMom(apEvolucaoCache));

function renderApPareto(p) {
  const ctx = document.getElementById("ap-chart-pareto");
  if (apChartPareto) apChartPareto.destroy();
  const itens = p.itens || [];
  apChartPareto = new Chart(ctx, {
    data: {
      labels: itens.map((i) => i.sku),
      datasets: [
        { type: "bar", label: "Valor (R$)", data: itens.map((i) => i.valor), backgroundColor: "rgba(90,156,143,0.6)", yAxisID: "y", order: 2 },
        { type: "line", label: "% acumulado do valor", data: itens.map((i) => i.pct_valor_acumulado), borderColor: "#f9a825", backgroundColor: "#f9a825", pointRadius: 3, yAxisID: "y1", order: 1 },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: "#8ca0a3", font: { size: 9 } }, grid: { display: false } },
        y: { position: "left", ticks: { color: "#8ca0a3", font: { size: 9 } }, grid: { color: "#2e3a40" } },
        y1: { position: "right", min: 0, max: 100, ticks: { color: "#f9a825", font: { size: 9 } }, grid: { display: false } },
      },
    },
  });

  document.getElementById("ap-pareto-footer").textContent =
    p.top_n_pct_do_valor != null ? `Os top ${p.top_n} itens (${p.total_itens_divergentes ? Math.round((p.top_n / p.total_itens_divergentes) * 100) : 0}% dos divergentes) concentram ${p.top_n_pct_do_valor}% do valor total em risco (R$ ${p.valor_total.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}).` : "Sem dados suficientes ainda.";

  document.querySelector("#ap-tabela-pareto tbody").innerHTML = itens
    .slice(0, 10)
    .map((i) => `<tr data-sku="${i.sku}" data-almox="${i.almoxarifado || ""}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}" style="cursor:pointer"><td>${i.posicao}</td><td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${formatarMoeda(i.valor)}</td><td>${i.pct_valor_acumulado}%</td></tr>`)
    .join("") || `<tr><td colspan="5" style="color:var(--muted)">Sem divergências neste recorte.</td></tr>`;

  document.querySelectorAll("#ap-tabela-pareto tbody tr[data-sku]").forEach((tr) =>
    tr.addEventListener("click", () => {
      abrirModalAcaoPorSku(tr.dataset.sku, tr.dataset.almox || null, tr.dataset.desc || null, () => carregarAcuraciaPonderada());
    })
  );
}

function renderApMagnitude(m) {
  const ctx = document.getElementById("ap-chart-magnitude");
  if (apChartMagnitude) apChartMagnitude.destroy();
  const faixas = m.faixas || [];
  apChartMagnitude = new Chart(ctx, {
    data: {
      labels: faixas.map((f) => f.faixa),
      datasets: [
        { type: "bar", label: "Nº de itens", data: faixas.map((f) => f.quantidade_itens), backgroundColor: "#5b75ac", yAxisID: "y", formatarRotulo: (v) => v },
        { type: "line", label: "Valor (R$)", data: faixas.map((f) => f.valor_total), borderColor: "#e5534b", backgroundColor: "#e5534b", pointRadius: 4, yAxisID: "y1" },
      ],
    },
    options: {
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: { position: "left", ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } },
        y1: { position: "right", ticks: { color: "#e5534b" }, grid: { display: false } },
      },
    },
  });

  ctx.ondblclick = (evt) => {
    const pontos = apChartMagnitude.getElementsAtEventForMode(evt, "index", { intersect: true }, true);
    if (pontos.length) abrirModalMagnitude(pontos[0].index);
  };
}

async function abrirModalMagnitude(faixaIdx) {
  const mes = document.getElementById("ap-filtro-mes").value;
  const almox = document.getElementById("ap-filtro-almoxarifado").value;
  const params = new URLSearchParams({ faixa_idx: faixaIdx });
  if (mes) params.set("mes", mes);
  if (almox) params.set("almoxarifado", almox);

  const res = await apiFetch(`${API}/fechamentos/dashboard/itens-por-magnitude?${params.toString()}`);
  if (!res.ok) {
    alert("Não foi possível carregar os itens dessa faixa.");
    return;
  }
  const dados = await res.json();
  document.getElementById("modal-magnitude-titulo").textContent = `Itens na faixa: ${dados.faixa} (${dados.itens.length})`;
  document.querySelector("#tabela-modal-magnitude tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr>
        <td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.almoxarifado || "—"}</td>
        <td>${i.divergencia_qtd}</td><td>${formatarMoeda(i.valor)}</td>
        <td><button class="btn-secundario btn-criar-acao-magnitude" data-sku="${i.sku}" data-almox="${i.almoxarifado || ""}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}">Criar ação</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="6" style="color:var(--muted)">Nenhum item nessa faixa.</td></tr>`;

  document.querySelectorAll(".btn-criar-acao-magnitude").forEach((btn) =>
    btn.addEventListener("click", () => {
      abrirModalAcaoPorSku(btn.dataset.sku, btn.dataset.almox || null, btn.dataset.desc || null, () => carregarAcuraciaPonderada());
    })
  );

  document.getElementById("modal-magnitude-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-magnitude").addEventListener("click", () => {
  document.getElementById("modal-magnitude-overlay").classList.add("hidden");
});
document.getElementById("modal-magnitude-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-magnitude-overlay") document.getElementById("modal-magnitude-overlay").classList.add("hidden");
});

function renderApEvolucao(dados) {
  const ctx = document.getElementById("ap-chart-evolucao");
  if (apChartEvolucao) apChartEvolucao.destroy();
  apChartEvolucao = new Chart(ctx, {
    type: "line",
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        { label: "Item a item", data: dados.map((d) => d.item_a_item_pct), borderColor: "#5b75ac", backgroundColor: "#5b75ac", tension: 0.2 },
        { label: "IAQ", data: dados.map((d) => d.iaq_pct), borderColor: "#4caf50", backgroundColor: "#4caf50", tension: 0.2 },
        { label: "IAP", data: dados.map((d) => d.iap_pct), borderColor: "#f9a825", backgroundColor: "#f9a825", tension: 0.2, spanGaps: true },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3" } } },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: { min: 0, max: 100, ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } },
      },
    },
  });

  ativarCliqueParaFiltrar(apChartEvolucao, ctx, dados, (d) => d.mes, "ap-filtro-mes", (d) => ({
    titulo: `Acurácia Ponderada — ${d.mes}`,
    resumo: `Em ${d.mes}, a acurácia item a item foi de ${d.item_a_item_pct}%, o IAQ foi de ${d.iaq_pct}% e o IAP foi de ${d.iap_pct != null ? d.iap_pct + "%" : "sem dado nesse mês"}.`,
  }));
}

// ---------- painel de inventário (dashboard do módulo de fechamento) ----------
let fdChartGrupo, fdChartAlmox, fdChartEvolucaoMensal, fdChartFaltas, fdChartSobras;
let fdMesesCarregados = false;

async function carregarDashboardFechamento() {
  const mes = document.getElementById("fd-filtro-mes").value;
  const almox = document.getElementById("fd-filtro-almoxarifado").value;
  const params = new URLSearchParams();
  if (mes) params.set("mes", mes);
  if (almox) params.set("almoxarifado", almox);
  const qs = "?" + params.toString();

  async function buscarOuErro(url) {
    const res = await apiFetch(url);
    const dados = await res.json();
    if (!res.ok) {
      console.error(`Atlas: erro ${res.status} em ${url}:`, dados);
      throw new Error(dados.detail || `Erro ${res.status} ao carregar ${url}`);
    }
    return dados;
  }

  let kpis, porGrupo, porAlmox, ranking, recorrentes, impactoFinanceiro, evolucaoMensal, risco;
  try {
    [kpis, porGrupo, porAlmox, ranking, recorrentes, impactoFinanceiro, evolucaoMensal, risco] = await Promise.all([
      buscarOuErro(`${API}/fechamentos/dashboard/kpis${qs}`),
      buscarOuErro(`${API}/fechamentos/dashboard/por-grupo${qs}`),
      buscarOuErro(`${API}/fechamentos/dashboard/por-almoxarifado${mes ? "?mes=" + mes : ""}`),
      buscarOuErro(`${API}/fechamentos/dashboard/ranking-financeiro${qs}`),
      buscarOuErro(`${API}/fechamentos/dashboard/top-recorrentes${almox ? "?almoxarifado=" + almox : ""}`),
      buscarOuErro(`${API}/fechamentos/dashboard/top-impacto-financeiro${almox ? "?almoxarifado=" + almox : ""}`),
      buscarOuErro(`${API}/fechamentos/dashboard/evolucao-mensal${almox ? "?almoxarifado=" + almox : ""}`),
      buscarOuErro(`${API}/fechamentos/dashboard/top-recorrentes-risco${almox ? "?almoxarifado=" + almox : ""}`),
    ]);
  } catch (erro) {
    document.getElementById("fd-kpi-row").innerHTML =
      `<div class="kpi-card" style="grid-column:1/-1"><div class="kpi-label" style="color:var(--critico)">Não consegui carregar o painel</div><div style="font-size:13px;color:var(--muted);margin-top:6px">${erro.message}. Confirme que o backend foi atualizado para a versão mais recente (veja ATUALIZANDO.md) e reinicie o servidor.</div></div>`;
    return;
  }

  tentarRenderizar(() => renderFdKpis(kpis));
  tentarRenderizar(() => renderFdTabelaRisco(risco));
  tentarRenderizar(() => renderFdPorGrupo(porGrupo));
  tentarRenderizar(() => renderFdPorAlmox(porAlmox));
  tentarRenderizar(() => renderFdRankingFinanceiro(ranking));
  tentarRenderizar(() => renderFdRecorrentes(recorrentes));
  tentarRenderizar(() => renderFdImpactoFinanceiro(impactoFinanceiro));
  tentarRenderizar(() => renderFdEvolucaoMensal(evolucaoMensal));
  tentarRenderizar(() => preencherFiltrosFechamentoDashboard(evolucaoMensal, porAlmox));
  tentarRenderizar(() => renderizarResumoExecutivoNarrado("fd-resumo-executivo", construirResumoExecutivoFechamento(kpis)));
}

function renderFdKpis(k) {
  const cards = [
    { label: "Itens avaliados", value: k.total_itens },
    { label: "Divergências", value: k.total_divergentes },
    { label: "Acurácia geral", value: k.acuracia_geral_pct != null ? k.acuracia_geral_pct + "%" : "—", cor: corFarolAcuracia(k.acuracia_geral_pct) },
    { label: "% SKUs acima de 95%", value: k.pct_skus_acima_95 != null ? k.pct_skus_acima_95 + "%" : "—", cor: corFarolAcuracia(k.pct_skus_acima_95) },
    { label: "Déficit (faltas)", value: formatarMoeda(k.deficit_faltas), accent: true },
    { label: "Resultado líquido", value: formatarMoeda(k.resultado_liquido) },
  ];
  document.getElementById("fd-kpi-row").innerHTML = cards
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value ${c.accent ? "accent" : ""}" style="${c.cor ? "color:" + c.cor : ""}">${c.value}</div></div>`)
    .join("");
}

function renderFdPorGrupo(dados) {
  const ctx = document.getElementById("fd-chart-grupo");
  if (fdChartGrupo) fdChartGrupo.destroy();
  fdChartGrupo = new Chart(ctx, {
    type: "bar",
    data: {
      labels: dados.map((d) => d.grupo),
      datasets: [{ label: "Acurácia %", data: dados.map((d) => d.acuracia_pct), backgroundColor: dados.map((d) => corFarolAcuracia(d.acuracia_pct)), borderRadius: 3, formatarRotulo: (v) => v + "%" }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

function renderFdPorAlmox(dados) {
  const ctx = document.getElementById("fd-chart-almox");
  if (fdChartAlmox) fdChartAlmox.destroy();
  const cores = dados.map((d) => corFarolAcuracia(d.acuracia_pct));
  fdChartAlmox = new Chart(ctx, {
    type: "bar",
    data: { labels: dados.map((d) => d.almoxarifado), datasets: [{ label: "Acurácia %", data: dados.map((d) => d.acuracia_pct), backgroundColor: cores, borderRadius: 3, formatarRotulo: (v) => v + "%" }] },
    options: {
      indexAxis: "y",
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });

  ativarCliqueParaFiltrar(fdChartAlmox, ctx, dados, (d) => d.almoxarifado, "fd-filtro-almoxarifado", (d) => ({
    titulo: `Painel de Inventário — ${d.almoxarifado}`,
    resumo: `O almoxarifado ${d.almoxarifado} fechou o período com ${d.acuracia_pct}% de acurácia.${document.getElementById("fd-filtro-mes")?.value ? " Duplo clique nesta mesma barra abre o fechamento correspondente." : " Selecione um mês específico (em vez de \"Todos os meses\") e dê duplo clique nesta barra pra abrir o fechamento correspondente."}`,
  }));

  ctx.ondblclick = async (evt) => {
    const pontos = fdChartAlmox.getElementsAtEventForMode(evt, "index", { intersect: true }, true);
    if (!pontos.length) return;
    const almoxarifado = dados[pontos[0].index].almoxarifado;
    const mes = document.getElementById("fd-filtro-mes").value;
    if (!mes) {
      alert('Selecione um mês específico (em vez de "Todos os meses") pra abrir o fechamento correspondente - com vários meses, não dá pra saber qual fechamento você quer ver.');
      return;
    }
    const fechamentos = await apiFetch(`${API}/fechamentos?almoxarifado=${encodeURIComponent(almoxarifado)}&mes=${encodeURIComponent(mes)}`).then((r) => r.json());
    if (!fechamentos.length) {
      alert(`Nenhum fechamento encontrado para ${almoxarifado} em ${mes}.`);
      return;
    }
    abrirFechamentoDetalhe(fechamentos[0].id);
  };
}

function renderFdEvolucaoMensal(dados) {
  const ctx = document.getElementById("fd-chart-evolucao-mensal");
  if (fdChartEvolucaoMensal) fdChartEvolucaoMensal.destroy();
  fdChartEvolucaoMensal = new Chart(ctx, {
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        { type: "bar", label: "Acurácia %", data: dados.map((d) => d.acuracia_pct), backgroundColor: dados.map((d) => corFarolAcuracia(d.acuracia_pct)), borderRadius: 3, yAxisID: "y", order: 2, formatarRotulo: (v) => v + "%" },
        { type: "line", label: "Fechamentos realizados", data: dados.map((d) => d.qtd_fechamentos_realizados), borderColor: "#f9a825", backgroundColor: "#f9a825", pointRadius: 4, yAxisID: "y1", order: 1 },
      ],
    },
    options: {
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3" } },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const d = dados[items[0].dataIndex];
              return [`Almoxarifados avaliados: ${d.qtd_almoxarifados_avaliados}`, `Variação MoM: ${d.variacao_mom_pp != null ? (d.variacao_mom_pp > 0 ? "+" : "") + d.variacao_mom_pp + " pp" : "—"}`];
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: { position: "left", min: 0, max: 100, ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" }, title: { display: true, text: "acurácia %", color: "#8ca0a3" } },
        y1: { position: "right", ticks: { color: "#f9a825", stepSize: 1 }, grid: { display: false }, title: { display: true, text: "qtd. fechamentos", color: "#f9a825" } },
      },
    },
  });

  ativarCliqueParaFiltrar(fdChartEvolucaoMensal, ctx, dados, (d) => d.mes, "fd-filtro-mes", (d) => ({
    titulo: `Painel de Inventário — ${d.mes}`,
    resumo: `Em ${d.mes}, a acurácia geral foi de ${d.acuracia_pct}%, com ${d.qtd_fechamentos_realizados} fechamento(s) realizado(s) em ${d.qtd_almoxarifados_avaliados} almoxarifado(s) avaliado(s).${d.variacao_mom_pp != null ? ` Variação em relação ao mês anterior: ${d.variacao_mom_pp > 0 ? "+" : ""}${d.variacao_mom_pp} pontos percentuais.` : ""}`,
  }));
}

function renderFdRankingFinanceiro(ranking) {
  const ctxF = document.getElementById("fd-chart-faltas");
  if (fdChartFaltas) fdChartFaltas.destroy();
  fdChartFaltas = new Chart(ctxF, {
    type: "bar",
    data: { labels: ranking.top_faltas.map((i) => i.descricao || i.sku), datasets: [{ data: ranking.top_faltas.map((i) => i.valor), backgroundColor: "#e5534b", borderRadius: 3, formatarRotulo: (v) => formatarMoeda(v) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, layout: { padding: { right: 70 } }, scales: { x: { ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } }, y: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { display: false } } } },
  });

  const ctxS = document.getElementById("fd-chart-sobras");
  if (fdChartSobras) fdChartSobras.destroy();
  fdChartSobras = new Chart(ctxS, {
    type: "bar",
    data: { labels: ranking.top_sobras.map((i) => i.descricao || i.sku), datasets: [{ data: ranking.top_sobras.map((i) => i.valor), backgroundColor: "#4caf50", borderRadius: 3, formatarRotulo: (v) => formatarMoeda(v) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, layout: { padding: { right: 70 } }, scales: { x: { ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } }, y: { ticks: { color: "#8ca0a3", font: { size: 10 } }, grid: { display: false } } } },
  });
}

function renderFdRecorrentes(lista) {
  document.querySelector("#fd-tabela-recorrentes tbody").innerHTML = lista
    .map((i) => `<tr data-sku="${i.sku}" data-almox="${i.almoxarifado || ""}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}" style="cursor:pointer"><td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.ocorrencias}</td><td>${formatarMoeda(i.valor_total)}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhum item recorrente ainda.</td></tr>`;

  document.querySelectorAll("#fd-tabela-recorrentes tbody tr[data-sku]").forEach((tr) =>
    tr.addEventListener("click", () => {
      abrirModalAcaoPorSku(tr.dataset.sku, tr.dataset.almox || null, tr.dataset.desc || null, () => carregarDashboardFechamento());
    })
  );
}

function renderFdImpactoFinanceiro(lista) {
  document.querySelector("#fd-tabela-impacto-financeiro tbody").innerHTML = lista
    .map((i) => `<tr data-sku="${i.sku}" data-almox="${i.almoxarifado || ""}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}" style="cursor:pointer"><td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.ocorrencias}</td><td>${formatarMoeda(i.valor_total)}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhum passivo registrado ainda.</td></tr>`;

  document.querySelectorAll("#fd-tabela-impacto-financeiro tbody tr[data-sku]").forEach((tr) =>
    tr.addEventListener("click", () => {
      abrirModalAcaoPorSku(tr.dataset.sku, tr.dataset.almox || null, tr.dataset.desc || null, () => carregarDashboardFechamento());
    })
  );
}

function renderFdTabelaRisco(lista) {
  document.querySelector("#fd-tabela-risco tbody").innerHTML = lista
    .map(
      (i) => `<tr data-sku="${i.sku}" data-almox="${i.almoxarifado || ""}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}" style="cursor:pointer">
        <td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.almoxarifado || "—"}</td>
        <td>${i.ocorrencias}</td><td>${formatarMoeda(i.valor_total)}</td>
        <td><strong>${i.score_risco.toLocaleString("pt-BR")}</strong></td>
        <td>${i.ultima_ocorrencia ? formatarDataCurta(i.ultima_ocorrencia) : "—"}</td>
        <td>→</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="8" style="color:var(--muted)">Nenhum item recorrente com 2+ ocorrências ainda.</td></tr>`;

  document.querySelectorAll("#fd-tabela-risco tbody tr[data-sku]").forEach((tr) =>
    tr.addEventListener("click", () => {
      abrirModalAcaoPorSku(tr.dataset.sku, tr.dataset.almox || null, tr.dataset.desc || null, () => carregarDashboardFechamento());
    })
  );
}

function preencherFiltrosFechamentoDashboard(evolucaoMensal, porAlmox) {
  if (!fdMesesCarregados) {
    const selMes = document.getElementById("fd-filtro-mes");
    evolucaoMensal.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.mes;
      opt.textContent = d.mes;
      selMes.appendChild(opt);
    });
    const selAlmox = document.getElementById("fd-filtro-almoxarifado");
    porAlmox.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.almoxarifado;
      opt.textContent = d.almoxarifado;
      selAlmox.appendChild(opt);
    });
    fdMesesCarregados = true;
  }
}
document.getElementById("fd-filtro-mes").addEventListener("change", carregarDashboardFechamento);
document.getElementById("fd-filtro-almoxarifado").addEventListener("change", carregarDashboardFechamento);

// ---------- pós-inventário ----------
let acoesCarregadas = [];

async function carregarAcoesPosInventario() {
  const status = document.getElementById("pi-filtro-status").value;
  const acoes = await apiFetch(`${API}/fechamentos/acoes${status ? "?status=" + status : ""}`).then((r) => r.json());
  acoesCarregadas = acoes;
  tentarRenderizar(() => renderizarResumoExecutivoNarrado("pi-resumo-executivo", construirResumoExecutivoPosInventario(acoes)));
  document.querySelector("#tabela-pos-inventario tbody").innerHTML = acoes
    .map(
      (a) => `<tr data-id="${a.id}">
        <td><input type="checkbox" class="pi-check" data-id="${a.id}"></td>
        <td>${a.origem_automatica ? "🔄" : ""}</td>
        <td>${a.sku}</td><td class="col-descricao">${a.descricao_produto || "—"}</td>
        <td class="col-descricao">${a.acao_descricao}</td><td>${a.responsavel || "—"}</td>
        <td>${a.prazo ? formatarDataCurta(a.prazo) : "—"}</td>
        <td>
          <select class="select-status-acao" data-id="${a.id}">
            <option value="Pendente" ${a.status === "Pendente" ? "selected" : ""}>Pendente</option>
            <option value="Em_Andamento" ${a.status === "Em_Andamento" ? "selected" : ""}>Em andamento</option>
            <option value="Concluida" ${a.status === "Concluida" ? "selected" : ""}>Concluída</option>
            <option value="Cancelada" ${a.status === "Cancelada" ? "selected" : ""}>Cancelada</option>
          </select>
        </td>
        <td><button class="btn-secundario btn-excluir-acao" data-id="${a.id}">Excluir</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="9" style="color:var(--muted)">Nenhuma ação registrada ainda.</td></tr>`;

  document.querySelectorAll(".select-status-acao").forEach((sel) =>
    sel.addEventListener("click", (ev) => ev.stopPropagation())
  );
  document.querySelectorAll(".select-status-acao").forEach((sel) =>
    sel.addEventListener("change", async () => {
      await apiFetch(`${API}/fechamentos/acoes/${sel.dataset.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: sel.value }),
      });
      carregarAcoesPosInventario();
    })
  );
  document.querySelectorAll(".btn-excluir-acao").forEach((btn) =>
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Excluir esta ação?")) return;
      await apiFetch(`${API}/fechamentos/acoes/${btn.dataset.id}`, { method: "DELETE" });
      carregarAcoesPosInventario();
    })
  );
  document.querySelectorAll(".pi-check").forEach((chk) => {
    chk.addEventListener("click", (ev) => ev.stopPropagation());
    chk.addEventListener("change", atualizarBarraLotePosInventario);
  });
  document.querySelectorAll("#tabela-pos-inventario tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => abrirModalAcao(parseInt(tr.dataset.id)))
  );
  atualizarBarraLotePosInventario();
}
document.getElementById("pi-filtro-status").addEventListener("change", carregarAcoesPosInventario);

document.getElementById("pi-marcar-todos").addEventListener("change", (ev) => {
  document.querySelectorAll(".pi-check").forEach((chk) => (chk.checked = ev.target.checked));
  atualizarBarraLotePosInventario();
});

function atualizarBarraLotePosInventario() {
  const selecionados = Array.from(document.querySelectorAll(".pi-check:checked")).map((c) => c.dataset.id);
  const barra = document.getElementById("pi-barra-lote");
  barra.classList.toggle("hidden", selecionados.length === 0);
  document.getElementById("pi-lote-contagem").textContent = `${selecionados.length} selecionada(s)`;
}

document.getElementById("btn-aplicar-lote").addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".pi-check:checked")).map((c) => parseInt(c.dataset.id));
  const novoStatus = document.getElementById("pi-lote-status").value;
  if (!ids.length) return;
  if (!confirm(`Marcar ${ids.length} ação(ões) como "${novoStatus}"?`)) return;
  await apiFetch(`${API}/fechamentos/acoes/confirmar-lote`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, status: novoStatus }),
  });
  document.getElementById("pi-marcar-todos").checked = false;
  carregarAcoesPosInventario();
});

document.getElementById("btn-reconciliar-acoes").addEventListener("click", async () => {
  const btn = document.getElementById("btn-reconciliar-acoes");
  btn.textContent = "Verificando...";
  const res = await apiFetch(`${API}/fechamentos/acoes/reconciliar-automaticamente`, { method: "POST" });
  const data = await res.json();
  btn.textContent = "↻ Reconciliar automaticamente";
  if (res.ok) {
    alert(`Verificadas: ${data.verificadas} · Resolvidas automaticamente (já não divergiam mais): ${data.resolvidas_automaticamente}`);
    carregarAcoesPosInventario();
  } else {
    alert(data.detail || "Erro ao reconciliar.");
  }
});

document.getElementById("btn-criar-acao").addEventListener("click", async () => {
  const msg = document.getElementById("pi-msg");
  const payload = {
    sku: document.getElementById("pi-sku").value.trim(),
    almoxarifado: document.getElementById("pi-almox").value.trim() || null,
    acao_descricao: document.getElementById("pi-acao").value.trim(),
    responsavel: document.getElementById("pi-responsavel").value.trim() || null,
    prazo: document.getElementById("pi-prazo").value || null,
  };
  if (!payload.sku || !payload.acao_descricao) {
    msg.textContent = "Informe pelo menos SKU e a ação.";
    return;
  }
  const res = await apiFetch(`${API}/fechamentos/acoes`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao criar ação."; return; }
  msg.textContent = "Ação criada.";
  ["pi-sku", "pi-almox", "pi-acao", "pi-responsavel", "pi-prazo"].forEach((id) => (document.getElementById(id).value = ""));
  carregarAcoesPosInventario();
});

// ---------- modal de detalhe/acompanhamento da ação ----------
let acaoModalAtual = null;
let acaoModalAoSalvar = null;
let checklistModalAtual = [];
let chartModalHistorico;

async function abrirModalAcao(id) {
  const res = await apiFetch(`${API}/fechamentos/acoes/${id}`);
  if (!res.ok) return;
  const acao = await res.json();
  abrirModalComAcao(acao, () => carregarAcoesPosInventario());
}

async function abrirModalAcaoPorSku(sku, almoxarifado, descricao, aoSalvar) {
  const existentes = await apiFetch(`${API}/fechamentos/acoes?sku=${encodeURIComponent(sku)}`).then((r) => r.json());
  const existente = existentes.find((a) => a.status !== "Concluida" && a.status !== "Cancelada") || existentes[0];
  if (existente) {
    abrirModalComAcao(existente, aoSalvar);
  } else {
    abrirModalComAcao(
      { sku, almoxarifado, descricao_produto: descricao, acao_descricao: "", responsavel: null, prazo: null, status: "Pendente", observacao_conclusao: null, checklist: [] },
      aoSalvar
    );
  }
}

function abrirModalComAcao(acao, aoSalvar) {
  acaoModalAtual = acao; // se não tiver .id, o modal está em modo "criar nova"
  acaoModalAoSalvar = aoSalvar;
  checklistModalAtual = Array.isArray(acao.checklist) ? [...acao.checklist] : [];

  document.getElementById("modal-acao-titulo").textContent = `${acao.sku} — ${acao.descricao_produto || "sem descrição"}${acao.id ? "" : " (nova ação)"}`;
  document.getElementById("modal-acao-descricao").value = acao.acao_descricao || "";
  document.getElementById("modal-acao-responsavel").value = acao.responsavel || "";
  document.getElementById("modal-acao-prazo").value = acao.prazo || "";
  document.getElementById("modal-acao-status").value = acao.status || "Pendente";
  document.getElementById("modal-acao-observacao").value = acao.observacao_conclusao || "";
  renderChecklistModal();

  document.getElementById("modal-acao-overlay").classList.remove("hidden");

  document.getElementById("modal-acompanhamento-kpis").innerHTML = `<p class="hint" style="grid-column:1/-1">Carregando...</p>`;
  document.getElementById("modal-linha-do-tempo").innerHTML = "";
  (async () => {
    try {
      const params = acao.almoxarifado ? `?almoxarifado=${encodeURIComponent(acao.almoxarifado)}` : "";
      const historico = await apiFetch(`${API}/fechamentos/historico-sku/${encodeURIComponent(acao.sku)}${params}`).then((r) => r.json());
      renderAcompanhamentoModal(historico);
    } catch (erro) {
      document.getElementById("modal-acompanhamento-kpis").innerHTML = `<p class="hint" style="grid-column:1/-1">Não foi possível carregar o histórico.</p>`;
    }
  })();
}

function renderChecklistModal() {
  document.getElementById("modal-checklist-itens").innerHTML = checklistModalAtual
    .map(
      (item, idx) => `<div class="checklist-item ${item.concluido ? "concluido" : ""}">
        <input type="checkbox" data-idx="${idx}" class="checklist-toggle" ${item.concluido ? "checked" : ""}>
        <span>${item.descricao}</span>
        <button data-idx="${idx}" class="checklist-remover">remover</button>
      </div>`
    )
    .join("") || "<p class='hint'>Nenhum item no checklist ainda.</p>";

  document.querySelectorAll(".checklist-toggle").forEach((chk) =>
    chk.addEventListener("change", () => {
      checklistModalAtual[parseInt(chk.dataset.idx)].concluido = chk.checked;
      renderChecklistModal();
    })
  );
  document.querySelectorAll(".checklist-remover").forEach((btn) =>
    btn.addEventListener("click", () => {
      checklistModalAtual.splice(parseInt(btn.dataset.idx), 1);
      renderChecklistModal();
    })
  );
}

document.getElementById("btn-add-checklist").addEventListener("click", () => {
  const input = document.getElementById("modal-checklist-novo");
  const texto = input.value.trim();
  if (!texto) return;
  checklistModalAtual.push({ descricao: texto, concluido: false });
  input.value = "";
  renderChecklistModal();
});

function renderAcompanhamentoModal(historico) {
  const kpis = [
    { rotulo: "Dias movimentados", valor: historico.dias_movimentados },
    { rotulo: "Dias pendente", valor: historico.dias_pendente, cor: "var(--critico)" },
    { rotulo: "Dias resolvido", valor: historico.dias_resolvido, cor: "var(--ok)" },
  ];
  document.getElementById("modal-acompanhamento-kpis").innerHTML = kpis
    .map((k) => `<div class="kpi-mini"><div class="valor" style="${k.cor ? "color:" + k.cor : ""}">${k.valor}</div><div class="rotulo">${k.rotulo}</div></div>`)
    .join("");

  const linha = historico.linha_do_tempo || [];
  const ctx = document.getElementById("modal-chart-historico");
  if (chartModalHistorico) chartModalHistorico.destroy();
  if (linha.length) {
    chartModalHistorico = new Chart(ctx, {
      type: "line",
      data: {
        labels: linha.map((p) => formatarDataCurta(p.data)),
        datasets: [{
          label: "Divergente",
          data: linha.map((p) => (p.divergente ? 1 : 0)),
          borderColor: "#e5534b",
          backgroundColor: "#e5534b",
          pointBackgroundColor: linha.map((p) => (p.divergente ? "#e5534b" : "#4caf50")),
          pointRadius: 5,
          stepped: true,
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { min: 0, max: 1, ticks: { stepSize: 1, color: "#8ca0a3", callback: (v) => (v === 1 ? "Divergente" : "OK") }, grid: { color: "#2e3a40" } },
          x: { ticks: { color: "#8ca0a3", font: { size: 9 } }, grid: { display: false } },
        },
      },
    });
  }

  document.getElementById("modal-linha-do-tempo").innerHTML = linha
    .slice()
    .reverse()
    .map((p) => `<div class="linha-tempo-item"><span>${formatarDataCurta(p.data)} · ${p.almoxarifado}</span><span style="color:${p.divergente ? "var(--critico)" : "var(--ok)"}">${p.divergente ? "Divergente" : "OK"}</span></div>`)
    .join("");
}

document.getElementById("btn-fechar-modal-acao").addEventListener("click", () => {
  document.getElementById("modal-acao-overlay").classList.add("hidden");
});
document.getElementById("modal-acao-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-acao-overlay") document.getElementById("modal-acao-overlay").classList.add("hidden");
});

document.getElementById("btn-salvar-modal-acao").addEventListener("click", async () => {
  if (!acaoModalAtual) return;
  const payload = {
    acao_descricao: document.getElementById("modal-acao-descricao").value.trim(),
    responsavel: document.getElementById("modal-acao-responsavel").value.trim() || null,
    prazo: document.getElementById("modal-acao-prazo").value || null,
    status: document.getElementById("modal-acao-status").value,
    observacao_conclusao: document.getElementById("modal-acao-observacao").value.trim() || null,
    checklist: checklistModalAtual,
  };
  let res;
  if (acaoModalAtual.id) {
    res = await apiFetch(`${API}/fechamentos/acoes/${acaoModalAtual.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } else {
    if (!payload.acao_descricao) {
      alert("Descreva a ação antes de salvar.");
      return;
    }
    res = await apiFetch(`${API}/fechamentos/acoes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku: acaoModalAtual.sku, almoxarifado: acaoModalAtual.almoxarifado, descricao_produto: acaoModalAtual.descricao_produto, acao_descricao: payload.acao_descricao, responsavel: payload.responsavel, prazo: payload.prazo }),
    });
    // a criação (POST) só aceita os campos básicos - se o status/checklist/observação
    // foram além do padrão ("Pendente", sem checklist), complementa com um PATCH.
    if (res.ok) {
      const criada = await res.json();
      if (payload.status !== "Pendente" || checklistModalAtual.length || payload.observacao_conclusao) {
        res = await apiFetch(`${API}/fechamentos/acoes/${criada.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
      }
    }
  }
  if (res.ok) {
    document.getElementById("modal-acao-overlay").classList.add("hidden");
    if (acaoModalAoSalvar) acaoModalAoSalvar();
  } else {
    alert("Não foi possível salvar.");
  }
});

document.getElementById("btn-voltar-fechamento").addEventListener("click", () => mostrarView("fechamentos"));

async function carregarFechamentos() {
  const [lista, almoxarifados] = await Promise.all([
    apiFetch(`${API}/fechamentos`).then((r) => r.json()),
    apiFetch(`${API}/almoxarifados-cadastro`).then((r) => r.json()),
  ]);
  document.querySelector("#tabela-fechamentos tbody").innerHTML = lista
    .map(
      (f) => `<tr data-id="${f.id}">
        <td>${formatarDataCurta(f.data_fechamento)}</td><td>${f.almoxarifado}</td>
        <td>${f.total_itens}</td><td>${f.total_divergentes}</td><td>${formatarMoeda(f.valor_total_divergente)}</td>
        <td>${f.status_assinatura === "Inventário Fechado" ? `<span style="color:var(--ok)">✅ Inventário Fechado</span>` : `<span style="color:var(--critico)">⏳ Inventário em Aberto</span>`}</td>
        <td>&rarr;</td>
        <td>
          <select class="select-corrigir-almox" data-id="${f.id}" style="margin-right:6px">
            <option value="">Corrigir para...</option>
            ${almoxarifados.map((a) => `<option value="${a.codigo}">${a.codigo}</option>`).join("")}
          </select>
          <button class="btn-secundario btn-excluir-fechamento" data-id="${f.id}">Excluir</button>
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="8" style="color:var(--muted)">Nenhum fechamento importado ainda.</td></tr>`;
  document.querySelectorAll("#tabela-fechamentos tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", (ev) => {
      if (ev.target.closest(".btn-excluir-fechamento") || ev.target.closest(".select-corrigir-almox")) return;
      abrirFechamentoDetalhe(tr.dataset.id);
    })
  );
  document.querySelectorAll(".select-corrigir-almox").forEach((sel) =>
    sel.addEventListener("click", (ev) => ev.stopPropagation())
  );
  document.querySelectorAll(".select-corrigir-almox").forEach((sel) =>
    sel.addEventListener("change", async () => {
      const novoAlmox = sel.value;
      if (!novoAlmox) return;
      if (!confirm(`Corrigir este fechamento (e todas as divergências/histórico ligados a ele) para "${novoAlmox}"?`)) {
        sel.value = "";
        return;
      }
      const res = await apiFetch(`${API}/fechamentos/${sel.dataset.id}/corrigir-almoxarifado?novo_almoxarifado=${encodeURIComponent(novoAlmox)}`, { method: "PATCH" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível corrigir."); return; }
      alert(`Corrigido: ${data.itens_corrigidos} item(ns) movidos de "${data.almoxarifado_anterior}" para "${data.almoxarifado_novo}".`);
      carregarFechamentos();
    })
  );
  document.querySelectorAll(".btn-excluir-fechamento").forEach((btn) =>
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Excluir este fechamento? Todos os itens, divergências e ações pós-inventário ligados a ele serão removidos.")) return;
      try {
        const res = await apiFetch(`${API}/fechamentos/${btn.dataset.id}`, { method: "DELETE" });
        let data = {};
        try {
          data = await res.json();
        } catch (_) {
          // resposta de erro nao veio em JSON (ex: erro 500 cru do banco) - segue sem detalhe extra
        }
        if (!res.ok) {
          alert(`Não foi possível excluir (erro ${res.status}).${data.detail ? " " + data.detail : ""}`);
          return;
        }
        alert(`Removidos: ${data.itens_removidos} item(ns), ${data.divergencias_removidas} divergência(s), ${data.acoes_removidas} ação(ões).`);
        carregarFechamentos();
      } catch (erro) {
        console.error("Atlas: falha ao excluir fechamento:", erro);
        alert("Falha ao excluir: " + erro.message);
      }
    })
  );
}

document.getElementById("btn-importar-fechamento").addEventListener("click", async () => {
  const input = document.getElementById("input-arquivo-fechamento");
  const resultado = document.getElementById("resultado-importacao-fechamento");
  if (!input.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", input.files[0]);
  form.append("aba", document.getElementById("input-aba-fechamento").value || "Saldo de estoque - ace4");
  resultado.textContent = "Importando e investigando divergências...";
  try {
    const res = await apiFetch(`${API}/fechamentos/importar`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    resultado.textContent = JSON.stringify(data, null, 2);
    carregarFechamentos();
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

document.getElementById("mp-btn-importar-ajustes").addEventListener("click", async () => {
  const input = document.getElementById("mp-input-arquivo-ajustes");
  const resultado = document.getElementById("mp-resultado-importacao-ajustes");
  if (!input.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", input.files[0]);
  resultado.textContent = "Importando conciliação oficial de inventário...";
  try {
    const res = await apiFetch(`${API}/ajustes-inventario/importar`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    const linhas = [
      `Importado: ${data.importadas} de ${data.total_linhas} linha(s) da aba "${data.aba_usada}".`,
      `Contadas como ajuste de inventário: ${data.contadas_como_ajuste_inventario} (${formatarMoeda(data.valor_total_ajustes_contados)})`,
      `Ignoradas (coluna "Não" - já mapeada em Baixas): ${data.ignoradas_flag_nao}`,
      `Ignoradas (legado pré-separação Sim/Não): ${data.ignoradas_legado_pre_separacao}`,
    ];
    if (data.duplicadas_no_arquivo) {
      linhas.push(`🔁 ${data.duplicadas_no_arquivo} linha(s) 100% duplicada(s) dentro do próprio arquivo foram ignoradas automaticamente (não contam nem entram no banco).`);
    }
    if (data.duplicadas_de_importacao_anterior) {
      linhas.push(`🔁 ${data.duplicadas_de_importacao_anterior} linha(s) 100% idêntica(s) a uma importação anterior foram ignoradas automaticamente (não contam nem entram no banco de novo).`);
    }
    if (data.custos_corrigidos) {
      linhas.push(`💲 ${data.custos_corrigidos} lançamento(s) já existente(s) tiveram só o Custo/Valor atualizado por essa importação (mesmo movimento, custo recalculado) - variação líquida de ${formatarMoeda(data.valor_correcao_custo)}.`);
    }
    if (data.ids_invent_repetidos.length) {
      linhas.push(`⚠️ ${data.ids_invent_repetidos.length} Id_Invent já existiam de uma importação anterior - confira se não é upload duplicado.`);
    }
    if (data.erros.length) {
      linhas.push("", `Erros (${data.erros.length}):`, ...data.erros.slice(0, 20));
    }
    resultado.textContent = linhas.join("\n");
    input.value = "";
    carregarLotesAjusteInventario();
    carregarMapeamentoPassivos();
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

// ---------- lotes de ajuste de inventário oficial (Ace4) - histórico/excluir ----------
async function carregarLotesAjusteInventario() {
  const tbody = document.querySelector("#tabela-lotes-ajuste-inventario tbody");
  if (!tbody) return;
  const lotes = await apiFetch(`${API}/ajustes-inventario/lotes`).then((r) => r.json());
  tbody.innerHTML = lotes
    .map(
      (l) => `<tr>
        <td>${l.criado_em ? new Date(l.criado_em).toLocaleString("pt-BR") : "—"}</td>
        <td class="col-descricao">${l.arquivo_origem || "—"}</td>
        <td>${l.criado_por || "—"}</td>
        <td>${l.importadas}</td>
        <td>${l.contadas_como_ajuste_inventario}</td>
        <td>${formatarMoeda(l.valor_total_ajustes_contados)}</td>
        <td><button class="btn-secundario btn-excluir-lote-ajuste-inventario" data-id="${l.id}">Excluir</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="7" style="color:var(--muted)">Nenhuma conciliação importada ainda.</td></tr>`;

  document.querySelectorAll(".btn-excluir-lote-ajuste-inventario").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("Excluir esta importação? Todas as linhas de ajuste de inventário criadas por ela serão removidas.")) return;
      const res = await apiFetch(`${API}/ajustes-inventario/lotes/${btn.dataset.id}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      alert(`Removida(s) ${data.linhas_removidas} linha(s) desta conciliação.`);
      carregarLotesAjusteInventario();
      carregarMapeamentoPassivos();
    })
  );
}

async function abrirFechamentoDetalhe(id) {
  fechamentoDetalheAtualId = id;
  const [f, divergentes, ok] = await Promise.all([
    apiFetch(`${API}/fechamentos/${id}`).then((r) => r.json()),
    apiFetch(`${API}/fechamentos/${id}/itens?divergente=true`).then((r) => r.json()),
    apiFetch(`${API}/fechamentos/${id}/itens?divergente=false`).then((r) => r.json()),
  ]);

  document.getElementById("fechamento-detalhe-titulo").textContent =
    `Fechamento — ${f.almoxarifado} — ${formatarDataCurta(f.data_fechamento)}`;

  document.getElementById("fechamento-kpi-row").innerHTML = [
    { label: "Itens avaliados", value: f.total_itens },
    { label: "Divergências", value: f.total_divergentes },
    { label: "Valor em risco", value: formatarMoeda(f.valor_total_divergente), accent: true },
    { label: "Recorrentes (⭐)", value: divergentes.filter((i) => i.destaque_recorrente).length },
  ]
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value ${c.accent ? "accent" : ""}">${c.value}</div></div>`)
    .join("");

  document.querySelector("#tabela-itens-divergentes tbody").innerHTML = divergentes
    .map(
      (item) => `<tr class="${item.destaque_recorrente ? "linha-recorrente" : ""}" data-div-id="${item.divergencia_id || ""}">
        <td>${item.destaque_recorrente ? `<span class="estrela-recorrente" title="${item.recorrencias_anteriores} vez(es) anterior(es)">★ ${item.recorrencias_anteriores}</span>` : ""}</td>
        <td>${item.sku}</td><td class="col-descricao">${item.descricao_produto || "—"}</td>
        <td>${item.divergencia_qtd}</td><td>${formatarMoeda(item.valor_estimado)}</td>
        <td>${item.resumo_planilha || "—"}</td><td class="col-descricao">${item.observacao_pos_inventario || "—"}</td>
        <td>${item.divergencia_id ? `<button class="btn-secundario btn-investigar-item">Investigar</button>` : "—"}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="8" style="color:var(--muted)">Nenhuma divergência neste fechamento.</td></tr>`;

  document.querySelectorAll(".btn-investigar-item").forEach((btn) => {
    const tr = btn.closest("tr");
    btn.addEventListener("click", () => abrirDetalhe(tr.dataset.divId));
  });

  document.querySelector("#tabela-itens-ok tbody").innerHTML = ok
    .map((item) => `<tr><td>${item.sku}</td><td class="col-descricao">${item.descricao_produto || "—"}</td><td>${item.qtd_sistema}</td><td>${item.qtd_contagem}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">—</td></tr>`;

  carregarCiencia(id);
  mostrarView("fechamento-detalhe");
}

let fechamentoDetalheAtualId = null;

const ROTULOS_PAPEL_ASSINATURA = { Diretor_Operacoes: "Diretor de Operações", Coordenador_Financeiro: "Coordenador Financeiro" };

async function carregarCiencia(fechamentoId) {
  const [lista, status] = await Promise.all([
    apiFetch(`${API}/fechamentos/${fechamentoId}/ciencia`).then((r) => r.json()),
    apiFetch(`${API}/fechamentos/${fechamentoId}/status-assinatura`).then((r) => r.json()),
  ]);

  const resumo = document.getElementById("ciencia-status-resumo");
  if (status.status === "Inventário Fechado") {
    resumo.innerHTML = `<span style="color:var(--ok); font-weight:600">✅ Inventário Fechado</span> - ambas as assinaturas foram colhidas (${status.papeis_assinados.join(", ")}).`;
  } else {
    resumo.innerHTML = `<span style="color:var(--critico); font-weight:600">⏳ Inventário em Aberto</span> - falta assinatura de: ${status.papeis_faltantes.join(", ")}.`;
  }

  document.querySelector("#tabela-ciencia tbody").innerHTML = lista
    .map(
      (c) => `<tr>
        <td>${new Date(c.data_assinatura).toLocaleString("pt-BR")}</td>
        <td>${ROTULOS_PAPEL_ASSINATURA[c.papel_assinatura] || "—"}</td>
        <td>${c.gestor_nome || c.gestor_username}</td>
        <td>${c.total_itens_divergentes}</td>
        <td>${formatarMoeda(c.valor_total_divergente)}</td>
        <td class="col-descricao">${c.observacao || "—"}</td>
        <td><button class="btn-secundario btn-ver-pdf-ciencia" data-id="${c.id}">Ver PDF</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="7" style="color:var(--muted)">Nenhuma confirmação de ciência registrada ainda para este fechamento.</td></tr>`;

  document.querySelectorAll(".btn-ver-pdf-ciencia").forEach((btn) =>
    btn.addEventListener("click", () => abrirPdfCiencia(btn.dataset.id))
  );
}

async function abrirPdfCiencia(cienciaId) {
  try {
    const res = await apiFetch(`${API}/fechamentos/ciencia/${cienciaId}/pdf`);
    if (!res.ok) {
      let detalhe = "";
      try {
        const corpo = await res.json();
        detalhe = corpo.detail || "";
      } catch (_) {
        // resposta de erro não veio em JSON - segue sem detalhe extra
      }
      console.error(`Atlas: erro ${res.status} ao baixar PDF de ciência ${cienciaId}.`, detalhe);
      alert(`Não foi possível abrir o PDF (erro ${res.status}).${detalhe ? " " + detalhe : ""}`);
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const aba = window.open(url, "_blank");
    if (!aba) {
      alert("O navegador bloqueou a abertura do PDF em nova aba (pop-up bloqueado). Permita pop-ups para este site e clique em \"Ver PDF\" de novo.");
    }
  } catch (erro) {
    console.error("Atlas: falha ao baixar PDF de ciência:", erro);
    alert("Falha ao baixar o PDF: " + erro.message);
  }
}

document.getElementById("btn-gerar-ciencia").addEventListener("click", async () => {
  if (!fechamentoDetalheAtualId) return;
  const papel = document.getElementById("ciencia-papel").value;
  if (!papel) {
    alert("Selecione qual papel está assinando (Diretor de Operações ou Coordenador Financeiro) antes de confirmar.");
    return;
  }
  const btn = document.getElementById("btn-gerar-ciencia");
  const observacao = document.getElementById("ciencia-observacao").value.trim() || null;
  btn.disabled = true;
  btn.textContent = "Gerando...";
  try {
    const res = await apiFetch(`${API}/fechamentos/${fechamentoDetalheAtualId}/ciencia`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ observacao, papel_assinatura: papel }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Não foi possível gerar a ciência.");
    } else {
      document.getElementById("ciencia-observacao").value = "";
      document.getElementById("ciencia-papel").value = "";
      await carregarCiencia(fechamentoDetalheAtualId);
      abrirPdfCiencia(data.id);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "📝 Confirmar ciência e gerar documento";
  }
});

// ---------- controle de compras (estoque externo) ----------
let pedidoModalAtual = null;

async function carregarPedidosCompra() {
  const status = document.getElementById("cp-filtro-status").value;
  const [kpis, pedidos] = await Promise.all([
    apiFetch(`${API}/compras/pedidos/dashboard/kpis`).then((r) => r.json()),
    apiFetch(`${API}/compras/pedidos${status ? "?status=" + status : ""}`).then((r) => r.json()),
  ]);

  document.getElementById("cp-kpi-row").innerHTML = [
    { label: "Total de pedidos", value: kpis.total_pedidos },
    { label: "Pedidos abertos", value: kpis.pedidos_abertos },
    { label: "Pedidos atrasados", value: kpis.pedidos_atrasados, cor: kpis.pedidos_atrasados > 0 ? "var(--critico)" : "var(--ok)" },
    { label: "Quantidade pendente (soma)", value: kpis.itens_pendentes_qtd.toLocaleString("pt-BR") },
  ]
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value" style="${c.cor ? "color:" + c.cor : ""}">${c.value}</div></div>`)
    .join("");

  tentarRenderizar(() => renderizarResumoExecutivoNarrado("cp-resumo-executivo", construirResumoExecutivoCompras(kpis)));

  document.querySelector("#tabela-pedidos tbody").innerHTML = pedidos
    .map(
      (p) => `<tr data-id="${p.id}" style="cursor:pointer">
        <td>${p.numero_pedido || "—"}</td><td>${p.fornecedor_id ? "#" + p.fornecedor_id : "—"}</td>
        <td>${p.sku}</td><td class="col-descricao">${p.descricao_produto || "—"}</td><td>${p.almoxarifado_destino}</td>
        <td>${p.quantidade_pedida}</td><td>${p.quantidade_recebida_total}</td><td>${p.quantidade_pendente}</td>
        <td>${p.pct_concluido}%</td>
        <td>${p.prazo_entrega_previsto ? formatarDataCurta(p.prazo_entrega_previsto) : "—"} ${p.atrasado ? '<span style="color:var(--critico)">⚠️ atrasado</span>' : ""}</td>
        <td>${badge(p.status)}</td><td>→</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="12" style="color:var(--muted)">Nenhum pedido de compra registrado ainda.</td></tr>`;

  document.querySelectorAll("#tabela-pedidos tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => abrirModalPedido(parseInt(tr.dataset.id)))
  );
}
document.getElementById("cp-filtro-status").addEventListener("change", carregarPedidosCompra);

document.getElementById("btn-criar-pedido").addEventListener("click", async () => {
  const msg = document.getElementById("cp-msg");
  const payload = {
    fornecedor_nome: document.getElementById("cp-fornecedor").value.trim() || null,
    numero_pedido: document.getElementById("cp-numero-pedido").value.trim() || null,
    sku: document.getElementById("cp-sku").value.trim(),
    descricao_produto: document.getElementById("cp-descricao").value.trim() || null,
    almoxarifado_destino: document.getElementById("cp-almoxarifado").value.trim(),
    quantidade_pedida: parseFloat(document.getElementById("cp-quantidade").value),
    data_pedido: document.getElementById("cp-data-pedido").value,
    prazo_entrega_previsto: document.getElementById("cp-prazo").value || null,
  };
  if (!payload.sku || !payload.almoxarifado_destino || !payload.quantidade_pedida || !payload.data_pedido) {
    msg.textContent = "Informe pelo menos SKU, almoxarifado, quantidade e data do pedido.";
    return;
  }
  const res = await apiFetch(`${API}/compras/pedidos`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao criar pedido."; return; }
  msg.textContent = "Pedido criado.";
  ["cp-fornecedor", "cp-numero-pedido", "cp-sku", "cp-descricao", "cp-almoxarifado", "cp-quantidade", "cp-data-pedido", "cp-prazo"].forEach(
    (id) => (document.getElementById(id).value = "")
  );
  carregarPedidosCompra();
});

async function abrirModalPedido(pedidoId) {
  const res = await apiFetch(`${API}/compras/pedidos/${pedidoId}`);
  if (!res.ok) return;
  const pedido = await res.json();
  pedidoModalAtual = pedido;

  document.getElementById("modal-pedido-titulo").textContent = `Pedido — ${pedido.sku} (${pedido.descricao_produto || "sem descrição"})`;
  document.getElementById("modal-pedido-resumo").innerHTML = [
    { rotulo: "Pedida", valor: pedido.quantidade_pedida },
    { rotulo: "Recebida", valor: pedido.quantidade_recebida_total },
    { rotulo: "Pendente", valor: pedido.quantidade_pendente },
  ]
    .map((k) => `<div class="kpi-mini"><div class="valor">${k.valor}</div><div class="rotulo">${k.rotulo}</div></div>`)
    .join("");

  await carregarRecebimentosModal(pedidoId);
  document.getElementById("modal-pedido-overlay").classList.remove("hidden");
}

async function carregarRecebimentosModal(pedidoId) {
  const recebimentos = await apiFetch(`${API}/compras/pedidos/${pedidoId}/recebimentos`).then((r) => r.json());
  document.querySelector("#tabela-modal-recebimentos tbody").innerHTML = recebimentos
    .map(
      (r) => `<tr>
        <td>${formatarDataCurta(r.data_recebimento)}</td><td>${r.quantidade_recebida}</td>
        <td>${r.numero_nota_fiscal || "—"}</td><td>${r.recebido_por || "—"}</td>
        <td><button class="btn-secundario btn-excluir-recebimento" data-id="${r.id}">Excluir</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="5" style="color:var(--muted)">Nenhum recebimento registrado ainda.</td></tr>`;

  document.querySelectorAll(".btn-excluir-recebimento").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("Excluir este recebimento?")) return;
      await apiFetch(`${API}/compras/recebimentos/${btn.dataset.id}`, { method: "DELETE" });
      await carregarRecebimentosModal(pedidoModalAtual.id);
      const atualizado = await apiFetch(`${API}/compras/pedidos/${pedidoModalAtual.id}`).then((r) => r.json());
      pedidoModalAtual = atualizado;
      document.getElementById("modal-pedido-resumo").innerHTML = [
        { rotulo: "Pedida", valor: atualizado.quantidade_pedida },
        { rotulo: "Recebida", valor: atualizado.quantidade_recebida_total },
        { rotulo: "Pendente", valor: atualizado.quantidade_pendente },
      ]
        .map((k) => `<div class="kpi-mini"><div class="valor">${k.valor}</div><div class="rotulo">${k.rotulo}</div></div>`)
        .join("");
      carregarPedidosCompra();
    })
  );
}

document.getElementById("btn-registrar-recebimento").addEventListener("click", async () => {
  if (!pedidoModalAtual) return;
  const msg = document.getElementById("modal-pedido-msg");
  const payload = {
    data_recebimento: document.getElementById("mp-data-recebimento").value,
    quantidade_recebida: parseFloat(document.getElementById("mp-quantidade-recebida").value),
    numero_nota_fiscal: document.getElementById("mp-nota-fiscal").value.trim() || null,
    recebido_por: document.getElementById("mp-recebido-por").value.trim() || null,
  };
  if (!payload.data_recebimento || !payload.quantidade_recebida) {
    msg.textContent = "Informe data e quantidade recebida.";
    return;
  }
  const res = await apiFetch(`${API}/compras/pedidos/${pedidoModalAtual.id}/recebimentos`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao registrar recebimento."; return; }
  msg.textContent = "Recebimento registrado.";
  pedidoModalAtual = data;
  document.getElementById("modal-pedido-resumo").innerHTML = [
    { rotulo: "Pedida", valor: data.quantidade_pedida },
    { rotulo: "Recebida", valor: data.quantidade_recebida_total },
    { rotulo: "Pendente", valor: data.quantidade_pendente },
  ]
    .map((k) => `<div class="kpi-mini"><div class="valor">${k.valor}</div><div class="rotulo">${k.rotulo}</div></div>`)
    .join("");
  ["mp-data-recebimento", "mp-quantidade-recebida", "mp-nota-fiscal", "mp-recebido-por"].forEach((id) => (document.getElementById(id).value = ""));
  await carregarRecebimentosModal(pedidoModalAtual.id);
  carregarPedidosCompra();
});

document.getElementById("btn-cancelar-pedido").addEventListener("click", async () => {
  if (!pedidoModalAtual) return;
  if (!confirm("Cancelar este pedido? Ele deixa de contar como pendência em aberto.")) return;
  await apiFetch(`${API}/compras/pedidos/${pedidoModalAtual.id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "Cancelado" }),
  });
  document.getElementById("modal-pedido-overlay").classList.add("hidden");
  carregarPedidosCompra();
});

document.getElementById("btn-excluir-pedido").addEventListener("click", async () => {
  if (!pedidoModalAtual) return;
  if (!confirm("Excluir este pedido permanentemente? Use isso só quando o pedido foi criado com dado errado - diferente de \"Cancelar\", isso remove o registro por completo, junto com os recebimentos já lançados nele.")) return;
  const res = await apiFetch(`${API}/compras/pedidos/${pedidoModalAtual.id}`, { method: "DELETE" });
  if (!res.ok) {
    let msg = "Não foi possível excluir.";
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    alert(msg);
    return;
  }
  document.getElementById("modal-pedido-overlay").classList.add("hidden");
  carregarPedidosCompra();
});

document.getElementById("btn-fechar-modal-pedido").addEventListener("click", () => {
  document.getElementById("modal-pedido-overlay").classList.add("hidden");
});
document.getElementById("modal-pedido-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-pedido-overlay") document.getElementById("modal-pedido-overlay").classList.add("hidden");
});

// ---------- cobertura de conferência (dias conferidos x pendentes) ----------
let ccDadosCache = null;

async function carregarCoberturaConferencia() {
  const dias = document.getElementById("cc-filtro-dias").value;
  const res = await apiFetch(`${API}/divergencias/dashboard/cobertura-conferencia?dias=${dias}`);
  if (!res.ok) {
    document.getElementById("cc-kpi-row").innerHTML = `<div class="kpi-card" style="grid-column:1/-1"><div class="kpi-label" style="color:var(--critico)">Não consegui carregar</div></div>`;
    return;
  }
  const dados = await res.json();
  ccDadosCache = dados;

  const lista = dados.por_almoxarifado;
  const comDados = lista.filter((a) => !a.sem_dados);
  const coberturaMedia = comDados.length ? Math.round((comDados.reduce((s, a) => s + a.pct_cobertura, 0) / comDados.length) * 10) / 10 : null;
  const semNenhumaConferencia = comDados.filter((a) => a.dias_conferidos === 0).length;
  const comFuroAtivo = comDados.filter((a) => a.dias_desde_ultima_conferencia != null && a.dias_desde_ultima_conferencia >= 3).length;
  const maiorFuroGeral = lista.reduce((max, a) => Math.max(max, a.maior_furo_dias), 0);
  const semDadosCount = lista.filter((a) => a.sem_dados).length;

  document.getElementById("cc-kpi-row").innerHTML = [
    { label: "Cobertura média", value: coberturaMedia != null ? coberturaMedia + "%" : "—", cor: coberturaMedia != null ? corFarolAcuracia(coberturaMedia) : "var(--muted)" },
    { label: "Almoxarifados sem nenhuma conferência", value: semNenhumaConferencia, cor: semNenhumaConferencia > 0 ? "var(--critico)" : "var(--ok)" },
    { label: "Com furo ativo agora (3+ dias)", value: comFuroAtivo, cor: comFuroAtivo > 0 ? "var(--alto)" : "var(--ok)" },
    { label: "Maior furo já registrado", value: maiorFuroGeral + " dia(s)", cor: maiorFuroGeral > 7 ? "var(--critico)" : "var(--muted)" },
  ]
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value" style="color:${c.cor}">${c.value}</div></div>`)
    .join("");

  tentarRenderizar(() =>
    renderizarResumoExecutivoNarrado(
      "cc-resumo-executivo",
      construirResumoExecutivoCobertura(lista, coberturaMedia, semNenhumaConferencia, comFuroAtivo, maiorFuroGeral, semDadosCount)
    )
  );

  document.querySelector("#tabela-cobertura-almoxarifado tbody").innerHTML = lista
    .map((a) =>
      a.sem_dados
        ? `<tr>
            <td>${a.almoxarifado}</td>
            <td colspan="5" class="hint">Sem dados de movimentação no período - importe o livro-caixa bruto ou a movimentação diária pra esse almoxarifado.</td>
          </tr>`
        : `<tr>
            <td>${a.almoxarifado}<div class="hint" style="margin-top:2px">${a.fonte === "livro_caixa_bruto" ? "livro-caixa bruto" : "fluxo diário (Sistema × Contagem)"}</div></td>
            <td style="color:${corFarolAcuracia(a.pct_cobertura)}"><strong>${a.pct_cobertura}%</strong></td>
            <td>${a.dias_conferidos} / ${a.dias_totais}</td>
            <td style="color:${a.dias_desde_ultima_conferencia == null ? "var(--muted)" : a.dias_desde_ultima_conferencia >= 7 ? "var(--critico)" : a.dias_desde_ultima_conferencia >= 3 ? "var(--alto)" : "var(--muted)"}">${a.dias_desde_ultima_conferencia != null ? a.dias_desde_ultima_conferencia + " dia(s)" : "nunca conferido"}</td>
            <td>${a.maior_furo_dias} dia(s)</td>
            <td class="hint">${a.maior_furo_periodo || "—"}</td>
          </tr>`
    )
    .join("") || `<tr><td colspan="6" style="color:var(--muted)">Nenhum almoxarifado cadastrado pra contagem diária (veja Cadastros > Almoxarifados).</td></tr>`;

  const select = document.getElementById("cc-select-almoxarifado");
  select.innerHTML = lista.map((a) => `<option value="${a.almoxarifado}">${a.almoxarifado} (${a.sem_dados ? "sem dados" : a.pct_cobertura + "%"})</option>`).join("");
  if (lista.length) await carregarCalendarioAlmoxarifado(lista[0].almoxarifado);
}

document.getElementById("cc-filtro-dias").addEventListener("change", carregarCoberturaConferencia);
document.getElementById("cc-select-almoxarifado").addEventListener("change", (ev) => carregarCalendarioAlmoxarifado(ev.target.value));

async function carregarCalendarioAlmoxarifado(almoxarifado) {
  const dias = document.getElementById("cc-filtro-dias").value;
  const res = await apiFetch(`${API}/divergencias/dashboard/calendario-conferencia?almoxarifado=${encodeURIComponent(almoxarifado)}&dias=${dias}`);
  const calendario = res.ok ? await res.json() : [];
  const container = document.getElementById("cc-calendario");
  container.innerHTML = calendario
    .map((d) => `<span class="cc-dia ${d.conferido ? "cc-dia-ok" : "cc-dia-furo"}" data-data="${d.data}" data-almox="${almoxarifado}" title="${formatarDataCurta(d.data)} — ${d.conferido ? "conferido" : "sem conferência"} (duplo clique pra ver os itens)"></span>`)
    .join("");

  document.querySelectorAll("#cc-calendario .cc-dia").forEach((el) =>
    el.addEventListener("dblclick", () => abrirModalDetalheDiaConferencia(el.dataset.almox, el.dataset.data))
  );
}

async function abrirModalDetalheDiaConferencia(almoxarifado, data) {
  const res = await apiFetch(`${API}/divergencias/dashboard/detalhe-dia-conferencia?almoxarifado=${encodeURIComponent(almoxarifado)}&data=${data}`);
  if (!res.ok) {
    alert("Não foi possível carregar o detalhe desse dia.");
    return;
  }
  const dados = await res.json();
  document.getElementById("modal-dia-conferencia-titulo").textContent = `${almoxarifado} — ${formatarDataCurta(data)} — ${dados.total_itens} item(ns) movimentado(s)`;
  document.querySelector("#tabela-modal-dia-conferencia tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr>
        <td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td>
        <td>${i.qtd_saida || 0}</td><td>${i.qtd_entrada || 0}</td>
        <td class="hint">${i.operacoes.join(", ")}</td>
        <td>
          ${
            i.tem_divergencia
              ? `<span style="color:var(--critico)">⚠ Divergência (${i.divergencia_status})</span> <button class="btn-secundario btn-ver-divergencia-dia" data-id="${i.divergencia_id}">Ver</button>`
              : `<span class="hint">Sem divergência registrada ainda</span> <button class="btn-secundario btn-abrir-investigacao-dia" data-sku="${i.sku}" data-almox="${almoxarifado}" data-desc="${(i.descricao || "").replace(/"/g, "&quot;")}">Abrir investigação</button>`
          }
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="6" style="color:var(--muted)">Nenhum item movimentado nesse dia.</td></tr>`;

  document.querySelectorAll(".btn-ver-divergencia-dia").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.getElementById("modal-dia-conferencia-overlay").classList.add("hidden");
      mostrarView("lista");
      abrirDetalhe(parseInt(btn.dataset.id));
    })
  );
  document.querySelectorAll(".btn-abrir-investigacao-dia").forEach((btn) =>
    btn.addEventListener("click", () => {
      abrirModalAcaoPorSku(btn.dataset.sku, btn.dataset.almox, btn.dataset.desc || null, () => {});
    })
  );

  document.getElementById("modal-dia-conferencia-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-dia-conferencia").addEventListener("click", () => {
  document.getElementById("modal-dia-conferencia-overlay").classList.add("hidden");
});
document.getElementById("modal-dia-conferencia-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-dia-conferencia-overlay") document.getElementById("modal-dia-conferencia-overlay").classList.add("hidden");
});

// ---------- cadastros: navegação entre abas ----------
let abaCadastroAtiva = "produtos";
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    abaCadastroAtiva = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".cadastro-bloco").forEach((el) => el.classList.add("hidden"));
    document.getElementById("cadastro-" + abaCadastroAtiva).classList.remove("hidden");
    carregarAbaCadastroAtiva();
  });
});

function carregarAbaCadastroAtiva() {
  if (abaCadastroAtiva === "produtos") carregarProdutos();
  if (abaCadastroAtiva === "almoxarifados") carregarAlmoxarifadosCadastro();
  if (abaCadastroAtiva === "hipoteses") carregarHipotesesCadastro();
}

// ---------- cadastros: produtos ----------
let produtoEmEdicao = null;

async function carregarProdutos() {
  const incluirInativos = document.getElementById("prod-incluir-inativos").checked;
  const produtos = await apiFetch(`${API}/produtos?incluir_inativos=${incluirInativos}`).then((r) => r.json());
  document.querySelector("#tabela-produtos tbody").innerHTML = produtos
    .map(
      (p) => `<tr>
        <td>${p.sku}</td><td>${p.descricao || "—"}</td><td>${p.categoria_produto || "—"}</td><td>${p.unidade || "—"}</td>
        <td>${p.custo_unitario != null ? formatarMoeda(p.custo_unitario) : "—"}</td>
        <td>${p.ativo ? "Ativo" : "Inativo"}</td>
        <td>
          <button class="btn-secundario btn-editar-produto" data-sku="${p.sku}">Editar</button>
          <button class="btn-secundario btn-toggle-produto" data-sku="${p.sku}" data-ativo="${p.ativo}">${p.ativo ? "Desativar" : "Ativar"}</button>
          <button class="btn-secundario btn-excluir-produto" data-sku="${p.sku}">Excluir</button>
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="7" style="color:var(--muted)">Nenhum produto cadastrado.</td></tr>`;

  document.querySelectorAll(".btn-editar-produto").forEach((btn) =>
    btn.addEventListener("click", () => {
      const p = produtos.find((x) => x.sku === btn.dataset.sku);
      produtoEmEdicao = p.sku;
      document.getElementById("prod-sku").value = p.sku;
      document.getElementById("prod-sku").disabled = true;
      document.getElementById("prod-descricao").value = p.descricao || "";
      document.getElementById("prod-categoria").value = p.categoria_produto || "";
      document.getElementById("prod-unidade").value = p.unidade || "";
      document.getElementById("prod-custo").value = p.custo_unitario ?? "";
      document.getElementById("btn-salvar-produto").textContent = "Salvar edição";
    })
  );
  document.querySelectorAll(".btn-toggle-produto").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const ativo = btn.dataset.ativo === "true";
      await apiFetch(`${API}/produtos/${btn.dataset.sku}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ativo: !ativo }),
      });
      carregarProdutos();
    })
  );
  document.querySelectorAll(".btn-excluir-produto").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm(`Excluir o produto ${btn.dataset.sku}? Só funciona se ele nunca tiver sido usado.`)) return;
      const res = await apiFetch(`${API}/produtos/${btn.dataset.sku}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      carregarProdutos();
    })
  );
}
document.getElementById("prod-incluir-inativos").addEventListener("change", carregarProdutos);

function limparFormularioProduto() {
  produtoEmEdicao = null;
  document.getElementById("prod-sku").value = "";
  document.getElementById("prod-sku").disabled = false;
  document.getElementById("prod-descricao").value = "";
  document.getElementById("prod-categoria").value = "";
  document.getElementById("prod-unidade").value = "";
  document.getElementById("prod-custo").value = "";
  document.getElementById("btn-salvar-produto").textContent = "Salvar";
}

document.getElementById("btn-salvar-produto").addEventListener("click", async () => {
  const msg = document.getElementById("prod-msg");
  const custoVal = document.getElementById("prod-custo").value;
  const payload = {
    descricao: document.getElementById("prod-descricao").value || null,
    categoria_produto: document.getElementById("prod-categoria").value || null,
    unidade: document.getElementById("prod-unidade").value || null,
    custo_unitario: custoVal !== "" ? parseFloat(custoVal) : null,
  };
  let res;
  if (produtoEmEdicao) {
    res = await apiFetch(`${API}/produtos/${produtoEmEdicao}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } else {
    const sku = document.getElementById("prod-sku").value.trim();
    if (!sku) { msg.textContent = "Informe o SKU."; return; }
    res = await apiFetch(`${API}/produtos`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sku, ...payload }),
    });
  }
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao salvar."; return; }
  msg.textContent = `Produto '${data.sku}' salvo.`;
  limparFormularioProduto();
  carregarProdutos();
});

// ---------- cadastros: almoxarifados ----------
let almoxEmEdicao = null;

async function carregarAlmoxarifadosCadastro() {
  const incluirInativos = document.getElementById("almox-incluir-inativos").checked;
  const lista = await apiFetch(`${API}/almoxarifados-cadastro?incluir_inativos=${incluirInativos}`).then((r) => r.json());
  document.querySelector("#tabela-almoxarifados tbody").innerHTML = lista
    .map(
      (a) => `<tr>
        <td>${a.codigo}</td><td>${a.nome_exibicao || "—"}</td><td>${a.ativo ? "Ativo" : "Inativo"}</td>
        <td><input type="checkbox" class="chk-contagem-diaria" data-codigo="${a.codigo}" ${a.participa_contagem_diaria ? "checked" : ""}></td>
        <td>
          <button class="btn-secundario btn-editar-almox" data-codigo="${a.codigo}">Editar</button>
          <button class="btn-secundario btn-toggle-almox" data-codigo="${a.codigo}" data-ativo="${a.ativo}">${a.ativo ? "Desativar" : "Ativar"}</button>
          <button class="btn-secundario btn-excluir-almox" data-codigo="${a.codigo}">Excluir</button>
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="5" style="color:var(--muted)">Nenhum almoxarifado cadastrado.</td></tr>`;

  document.querySelectorAll(".chk-contagem-diaria").forEach((chk) =>
    chk.addEventListener("change", async () => {
      await apiFetch(`${API}/almoxarifados-cadastro/${chk.dataset.codigo}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ participa_contagem_diaria: chk.checked }),
      });
    })
  );

  document.querySelectorAll(".btn-editar-almox").forEach((btn) =>
    btn.addEventListener("click", () => {
      const a = lista.find((x) => x.codigo === btn.dataset.codigo);
      almoxEmEdicao = a.codigo;
      document.getElementById("almox-codigo").value = a.codigo;
      document.getElementById("almox-codigo").disabled = true;
      document.getElementById("almox-nome").value = a.nome_exibicao || "";
      document.getElementById("btn-salvar-almox").textContent = "Salvar edição";
    })
  );
  document.querySelectorAll(".btn-toggle-almox").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const ativo = btn.dataset.ativo === "true";
      await apiFetch(`${API}/almoxarifados-cadastro/${btn.dataset.codigo}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ativo: !ativo }),
      });
      carregarAlmoxarifadosCadastro();
    })
  );
  document.querySelectorAll(".btn-excluir-almox").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm(`Excluir o almoxarifado ${btn.dataset.codigo}? Só funciona se ele nunca tiver sido usado.`)) return;
      const res = await apiFetch(`${API}/almoxarifados-cadastro/${btn.dataset.codigo}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      carregarAlmoxarifadosCadastro();
    })
  );
}
document.getElementById("almox-incluir-inativos").addEventListener("change", carregarAlmoxarifadosCadastro);

document.getElementById("btn-salvar-almox").addEventListener("click", async () => {
  const msg = document.getElementById("almox-msg");
  const payload = { nome_exibicao: document.getElementById("almox-nome").value || null };
  let res;
  if (almoxEmEdicao) {
    res = await apiFetch(`${API}/almoxarifados-cadastro/${almoxEmEdicao}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } else {
    const codigo = document.getElementById("almox-codigo").value.trim();
    if (!codigo) { msg.textContent = "Informe o código."; return; }
    res = await apiFetch(`${API}/almoxarifados-cadastro`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codigo, ...payload }),
    });
  }
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao salvar."; return; }
  msg.textContent = `Almoxarifado '${data.codigo}' salvo.`;
  almoxEmEdicao = null;
  document.getElementById("almox-codigo").value = "";
  document.getElementById("almox-codigo").disabled = false;
  document.getElementById("almox-nome").value = "";
  document.getElementById("btn-salvar-almox").textContent = "Salvar";
  carregarAlmoxarifadosCadastro();
});

// ---------- cadastros: hipóteses ----------
let hipoteseEmEdicao = null;

async function carregarHipotesesCadastro() {
  const incluirInativos = document.getElementById("hip-incluir-inativos").checked;
  const lista = await apiFetch(`${API}/hipoteses-cadastro?incluir_inativos=${incluirInativos}`).then((r) => r.json());
  document.querySelector("#tabela-hipoteses tbody").innerHTML = lista
    .map(
      (h) => `<tr>
        <td>${h.codigo}</td><td>${h.nome || "—"}</td><td>${h.peso_padrao}</td><td>${h.ativo ? "Ativo" : "Inativo"}</td>
        <td>
          <button class="btn-secundario btn-editar-hip" data-codigo="${h.codigo}">Editar</button>
          <button class="btn-secundario btn-toggle-hip" data-codigo="${h.codigo}" data-ativo="${h.ativo}">${h.ativo ? "Desativar" : "Ativar"}</button>
          <button class="btn-secundario btn-excluir-hip" data-codigo="${h.codigo}">Excluir</button>
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="5" style="color:var(--muted)">Nenhuma hipótese cadastrada.</td></tr>`;

  document.querySelectorAll(".btn-editar-hip").forEach((btn) =>
    btn.addEventListener("click", () => {
      const h = lista.find((x) => x.codigo === btn.dataset.codigo);
      hipoteseEmEdicao = h.codigo;
      document.getElementById("hip-codigo").value = h.codigo;
      document.getElementById("hip-codigo").disabled = true;
      document.getElementById("hip-nome").value = h.nome || "";
      document.getElementById("hip-descricao").value = h.descricao || "";
      document.getElementById("hip-peso").value = h.peso_padrao;
      document.getElementById("btn-salvar-hipotese").textContent = "Salvar edição";
    })
  );
  document.querySelectorAll(".btn-toggle-hip").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const ativo = btn.dataset.ativo === "true";
      await apiFetch(`${API}/hipoteses-cadastro/${btn.dataset.codigo}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ativo: !ativo }),
      });
      carregarHipotesesCadastro();
      atualizarHipotesesCache();
    })
  );
  document.querySelectorAll(".btn-excluir-hip").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm(`Excluir a hipótese ${btn.dataset.codigo}? Só funciona se ela nunca tiver sido usada.`)) return;
      const res = await apiFetch(`${API}/hipoteses-cadastro/${btn.dataset.codigo}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      carregarHipotesesCadastro();
      atualizarHipotesesCache();
    })
  );
}
document.getElementById("hip-incluir-inativos").addEventListener("change", carregarHipotesesCadastro);

document.getElementById("btn-salvar-hipotese").addEventListener("click", async () => {
  const msg = document.getElementById("hip-msg");
  const payload = {
    nome: document.getElementById("hip-nome").value || null,
    descricao: document.getElementById("hip-descricao").value || null,
    peso_padrao: parseFloat(document.getElementById("hip-peso").value) || 20,
  };
  let res;
  if (hipoteseEmEdicao) {
    res = await apiFetch(`${API}/hipoteses-cadastro/${hipoteseEmEdicao}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } else {
    const codigo = document.getElementById("hip-codigo").value.trim();
    if (!codigo || !payload.nome) { msg.textContent = "Informe código e nome."; return; }
    res = await apiFetch(`${API}/hipoteses-cadastro`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codigo, ...payload }),
    });
  }
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao salvar."; return; }
  msg.textContent = `Hipótese '${data.codigo}' salva.`;
  hipoteseEmEdicao = null;
  document.getElementById("hip-codigo").value = "";
  document.getElementById("hip-codigo").disabled = false;
  document.getElementById("hip-nome").value = "";
  document.getElementById("hip-descricao").value = "";
  document.getElementById("hip-peso").value = "20";
  document.getElementById("btn-salvar-hipotese").textContent = "Salvar";
  carregarHipotesesCadastro();
  atualizarHipotesesCache();
});

// ---------- auditoria ----------
async function carregarStatusBackup() {
  const el = document.getElementById("backup-status");
  try {
    const status = await apiFetch(`${API}/backup/status`).then((r) => r.json());
    if (status.tipo_banco === "sqlite local") {
      el.textContent = `Banco local (SQLite), ${status.tamanho_atual_mb} MB. ${status.backups_automaticos.length} backup(s) automático(s) guardado(s).`;
    } else {
      el.textContent = status.mensagem;
      document.getElementById("btn-baixar-backup").classList.add("hidden");
    }
  } catch (erro) {
    el.textContent = "Não foi possível verificar o status do backup.";
  }
}

document.getElementById("btn-baixar-backup").addEventListener("click", async () => {
  const res = await apiFetch(`${API}/backup/download`);
  if (!res.ok) {
    alert("Não foi possível baixar o backup.");
    return;
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `atlas_backup_${new Date().toISOString().slice(0, 10)}.db`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
});

// ---------- modelo de machine learning ----------
async function carregarStatusMl() {
  const el = document.getElementById("ml-status");
  try {
    const status = await apiFetch(`${API}/ml/status`).then((r) => r.json());
    if (!status.modelo_treinado) {
      el.textContent = "Nenhum modelo treinado ainda. O motor de regras continua funcionando normalmente sem ele.";
    } else {
      const data = new Date(status.modificado_em * 1000).toLocaleString("pt-BR");
      el.textContent = `Treinado em ${data} · ${status.classes ? status.classes.length : "?"} hipótese(s) aprendida(s) · ${status.tamanho_kb} KB.`;
    }
    el.textContent += ` ${status.casos_feedback_acumulados} caso(s) confirmado(s) no total.`;
    if (!status.historico_bruto_disponivel) {
      document.getElementById("btn-retreinar-ml").disabled = true;
      el.textContent += " (histórico bruto não encontrado em seed_data/ - retreino pela tela desativado, use a linha de comando.)";
    }

    const a = status.automatico;
    const elAuto = document.getElementById("ml-status-automatico");
    if (elAuto && a) {
      if (!a.ativo) {
        elAuto.textContent = "Retreino automático desativado (ATLAS_ML_AUTO_RETREINO=false).";
      } else {
        const ultimo = a.ultimo_retreino_em ? new Date(a.ultimo_retreino_em).toLocaleString("pt-BR") + ` (${a.origem_ultimo_retreino})` : "nunca rodou ainda";
        elAuto.textContent = `Automático ativo: a cada ${a.intervalo_horas}h, mínimo ${a.minimo_casos_novos} casos novos. Último retreino: ${ultimo}. Casos novos aguardando: ${a.casos_novos_desde_ultimo_retreino}.`;
      }
    }
  } catch (erro) {
    el.textContent = "Não foi possível verificar o status do modelo.";
  }
}

document.getElementById("btn-retreinar-ml").addEventListener("click", async () => {
  const btn = document.getElementById("btn-retreinar-ml");
  const resultado = document.getElementById("ml-resultado");
  btn.disabled = true;
  btn.textContent = "Retreinando...";
  resultado.textContent = "Isso pode levar alguns segundos...";
  try {
    const res = await apiFetch(`${API}/ml/retreinar`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro: ${data.detail}`;
    } else {
      resultado.textContent = JSON.stringify(data, null, 2);
      carregarStatusMl();
    }
  } catch (erro) {
    resultado.textContent = "Falha ao retreinar: " + erro.message;
  }
  btn.disabled = false;
  btn.textContent = "Retreinar agora";
});

document.getElementById("btn-reinvestigar-falhas").addEventListener("click", async () => {
  const btn = document.getElementById("btn-reinvestigar-falhas");
  const resultado = document.getElementById("resultado-reinvestigar-falhas");
  btn.disabled = true;
  btn.textContent = "Reprocessando...";
  resultado.textContent = "Isso pode levar alguns segundos, dependendo de quantos casos estão afetados...";
  try {
    const res = await apiFetch(`${API}/divergencias/reinvestigar-falhas`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro: ${data.detail}`;
    } else {
      resultado.textContent = `${data.total_afetadas} caso(s) encontrados sem diagnóstico · ${data.corrigidas} corrigido(s) agora${
        data.ainda_com_erro.length ? ` · ${data.ainda_com_erro.length} ainda com erro (veja o console do navegador)` : ""
      }`;
      if (data.ainda_com_erro.length) console.error("Atlas: casos que ainda falharam no reprocessamento:", data.ainda_com_erro);
    }
  } catch (erro) {
    resultado.textContent = "Falha ao reprocessar: " + erro.message;
  }
  btn.disabled = false;
  btn.textContent = "Reprocessar agora";
});

async function carregarAuditoria(pagina = 1) {
  carregarStatusBackup();
  carregarStatusMl();
  const resposta = await apiFetch(`${API}/auditoria?pagina=${pagina}&tamanho_pagina=50`).then((r) => r.json());
  document.querySelector("#tabela-auditoria tbody").innerHTML = resposta.itens
    .map(
      (l) => `<tr>
        <td>${new Date(l.criado_em).toLocaleString("pt-BR")}</td><td>${l.username}</td><td>${l.acao}</td>
        <td>${l.entidade ? l.entidade + (l.entidade_id ? " #" + l.entidade_id : "") : "—"}</td>
        <td class="col-descricao">${l.detalhes ? JSON.stringify(l.detalhes) : "—"}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="5" style="color:var(--muted)">Sem registros.</td></tr>`;

  const paginacaoEl = document.getElementById("paginacao-auditoria");
  paginacaoEl.innerHTML = `
    <button id="aud-anterior" ${resposta.pagina <= 1 ? "disabled" : ""}>&larr; Anterior</button>
    <span>Página ${resposta.pagina} de ${resposta.paginas} · ${resposta.total} registro(s)</span>
    <button id="aud-proxima" ${resposta.pagina >= resposta.paginas ? "disabled" : ""}>Próxima &rarr;</button>
  `;
  const btnAnt = document.getElementById("aud-anterior");
  const btnProx = document.getElementById("aud-proxima");
  if (btnAnt) btnAnt.addEventListener("click", () => carregarAuditoria(resposta.pagina - 1));
  if (btnProx) btnProx.addEventListener("click", () => carregarAuditoria(resposta.pagina + 1));
}

// ---------- relatório de baixa (baixas operacionais importadas do Lovable) ----------
function badgeStatusBaixa(statusFluxo) {
  const cls = "badge-" + (statusFluxo || "").toLowerCase();
  const texto = { PENDENTE: "Pendente", APROVADA: "Aprovada", REPROVADA: "Reprovada" }[statusFluxo] || statusFluxo || "—";
  return `<span class="badge ${cls}">${texto}</span>`;
}

function _preencherFiltroRelatorioBaixa(idSelect, valores) {
  // Reconstrói as opções toda vez (não só na primeira carga) - depois de
  // "Sincronizar agora" trazer baixas com um almoxarifado/motivo que
  // ainda não existia na lista, esse valor precisa aparecer como opção
  // de filtro sem precisar recarregar a página inteira. Preserva a
  // seleção atual se o valor ainda existir na lista nova; senão volta
  // pro "Todos".
  const sel = document.getElementById(idSelect);
  const selecionadoAntes = sel.value;
  const unicos = [...new Set(valores.filter(Boolean))].sort();
  const opcaoTodos = sel.options[0]; // primeira opção ("Todos os...") é sempre fixa
  sel.innerHTML = "";
  sel.appendChild(opcaoTodos);
  unicos.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = idSelect === "rb-filtro-hipotese" ? rotulo(v) : v;
    sel.appendChild(opt);
  });
  sel.value = unicos.includes(selecionadoAntes) ? selecionadoAntes : "";
}

async function carregarRelatorioBaixa() {
  const params = new URLSearchParams();
  const status = document.getElementById("rb-filtro-status").value;
  const almox = document.getElementById("rb-filtro-almoxarifado").value;
  const hipotese = document.getElementById("rb-filtro-hipotese").value;
  if (status) params.set("status_fluxo", status);
  if (almox) params.set("almoxarifado", almox);
  if (hipotese) params.set("hipotese_aplicada", hipotese);
  const qs = params.toString();

  let dados;
  try {
    dados = await apiFetch(`${API}/baixas-operacionais${qs ? "?" + qs : ""}`, { cache: "no-store" }).then((r) => r.json());
  } catch (erro) {
    console.error("Atlas: falha ao carregar relatório de baixa:", erro);
    document.getElementById("rb-kpi-row").innerHTML = `<div class="kpi-card" style="grid-column:1/-1"><div class="kpi-label" style="color:var(--critico)">Não consegui carregar</div></div>`;
    return;
  }
  const resumo = dados.resumo || {};
  const itens = dados.itens || [];

  document.getElementById("rb-kpi-row").innerHTML = [
    { label: "Total de baixas", value: resumo.total ?? 0 },
    { label: "Pendentes", value: resumo.pendentes ?? 0, cor: "var(--medio)" },
    { label: "Aprovadas", value: resumo.aprovadas ?? 0, cor: "var(--ok)" },
    { label: "Reprovadas", value: resumo.reprovadas ?? 0, cor: "var(--critico)" },
    { label: "Resolveram divergência sozinhas", value: resumo.resolvidas_automaticamente ?? 0 },
    { label: "Aguardando divergência", value: resumo.aguardando_divergencia ?? 0 },
    { label: "Valor total", value: (resumo.valor_total ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) },
  ]
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value" style="${c.cor ? "color:" + c.cor : ""}">${c.value}</div></div>`)
    .join("");

  _preencherFiltroRelatorioBaixa("rb-filtro-almoxarifado", itens.map((i) => i.almoxarifado));
  _preencherFiltroRelatorioBaixa("rb-filtro-hipotese", itens.map((i) => i.hipotese_aplicada));

  document.querySelector("#tabela-relatorio-baixa tbody").innerHTML = itens
    .map(
      (b) => `<tr>
        <td>${b.sku || "—"}</td><td>${b.almoxarifado || "—"}</td><td>${b.motivo || "—"}</td>
        <td>${rotulo(b.hipotese_aplicada)}</td><td>${b.quantidade ?? "—"}</td>
        <td>${b.valor_total != null ? b.valor_total.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "—"}</td>
        <td>${badgeStatusBaixa(b.status_fluxo)}</td><td>${b.solicitante_nome || "—"}</td>
        <td>${b.data_baixa ? formatarDataCurta(b.data_baixa) : "—"}</td>
        <td>${b.divergencia_vinculada_id ? "#" + b.divergencia_vinculada_id : "—"}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="10" style="color:var(--muted)">Nenhuma baixa importada ainda.</td></tr>`;
}

document.getElementById("rb-filtro-status").addEventListener("change", carregarRelatorioBaixa);
document.getElementById("rb-filtro-almoxarifado").addEventListener("change", carregarRelatorioBaixa);
document.getElementById("rb-filtro-hipotese").addEventListener("change", carregarRelatorioBaixa);

document.getElementById("btn-sincronizar-lovable").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sincronizar-lovable");
  const msg = document.getElementById("rb-sync-msg");
  btn.disabled = true;
  btn.textContent = "Sincronizando...";
  msg.textContent = "Buscando o estado atual no Lovable...";
  msg.style.color = "";
  try {
    const res = await apiFetch(`${API}/baixas-operacionais/sincronizar`, { method: "POST", cache: "no-store" });
    const data = await res.json();
    if (!res.ok) {
      msg.style.color = "var(--critico)";
      msg.textContent = data.detail || "Não foi possível sincronizar com o Lovable.";
    } else {
      // Zera os filtros ANTES de recarregar - depois de sincronizar, a
      // tela deve mostrar os dados atuais completos (não um recorte
      // filtrado de antes, que pode nem existir mais do jeito que
      // estava - ex: itens que eram "Pendente" e sincronizaram como
      // "Aprovada" desaparecem de um filtro travado em Pendente,
      // dando a impressão de que a tela "não atualizou").
      document.getElementById("rb-filtro-status").value = "";
      document.getElementById("rb-filtro-almoxarifado").value = "";
      document.getElementById("rb-filtro-hipotese").value = "";
      await carregarRelatorioBaixa();
      msg.style.color = "var(--ok)";
      msg.textContent =
        `Sincronizado agora: ${data.total_na_origem} baixa(s) na origem do Lovable · ` +
        `${data.contagem?.resolvida_automaticamente || 0} resolveram divergência sozinhas.`;
    }
  } catch (erro) {
    msg.style.color = "var(--critico)";
    msg.textContent = "Falha ao sincronizar com o Lovable: " + erro.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "🔄 Sincronizar agora";
  }
});

document.getElementById("rb-link-importar").addEventListener("click", (ev) => {
  ev.preventDefault();
  mostrarView("importar");
});

document.getElementById("rb-btn-reconciliar").addEventListener("click", async () => {
  const input = document.getElementById("rb-input-arquivo-reconciliar");
  const resultado = document.getElementById("rb-resultado-reconciliar");
  const btn = document.getElementById("rb-btn-reconciliar");
  if (!input.files.length) {
    resultado.textContent = "Selecione a planilha primeiro (export \"Baixar relatório completo\" da tela Baixas Operacionais).";
    return;
  }
  const form = new FormData();
  form.append("arquivo", input.files[0]);
  btn.disabled = true;
  btn.textContent = "Reconciliando...";
  resultado.textContent = "Comparando a planilha com o que já está no Atlas...";
  try {
    const res = await apiFetch(`${API}/baixas-operacionais/reconciliar-planilha`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    const linhas = [
      `Linhas na planilha: ${data.total_planilha}`,
      `Já existiam no Atlas (sem mudança): ${data.ja_existentes}`,
      `Status atualizado no lugar (ex: virou Aprovada/Reprovada): ${data.atualizadas_status || 0}`,
      `Novas importadas agora (não existiam antes): ${data.novas_importadas}`,
      `Resolveram divergência automaticamente: ${data.resolvidas_automaticamente}`,
      `Aguardando divergência compatível: ${data.aguardando_divergencia}`,
    ];
    if (data.aguardando_de_para_almoxarifado) {
      linhas.push(`Aguardando de-para de almoxarifado (código não mapeado): ${data.aguardando_de_para_almoxarifado}`);
    }
    if (data.erros && data.erros.length) {
      linhas.push(`\n${data.erros.length} erro(s):`);
      data.erros.slice(0, 20).forEach((e) => linhas.push("  - " + e));
      if (data.erros.length > 20) linhas.push(`  ... e mais ${data.erros.length - 20}.`);
    }
    resultado.textContent = linhas.join("\n");
    input.value = "";
    document.getElementById("rb-filtro-status").value = "";
    document.getElementById("rb-filtro-almoxarifado").value = "";
    document.getElementById("rb-filtro-hipotese").value = "";
    await carregarRelatorioBaixa();
  } catch (erro) {
    resultado.textContent = "Falha ao reconciliar a planilha: " + erro.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Reconciliar planilha";
  }
});

// ---------- dashboard "Mapeamento de Passivos" ----------
let chartMpMotivosMensal = null, chartMpFluxoInventario = null, chartMpEvolucaoMensal = null, chartMpResultadoAlmoxarifado = null;
let dadosMpMotivosMensal = null, dadosMpFluxoInventario = [], dadosMpEvolucaoMensal = [], dadosMpResultadoAlmoxarifado = [];

// Fluxo de Inventário = "Mapeamento de grana de todos os inventários": Total de Entradas (sobra
// encontrada no fechamento, contagem física > sistema) - Total de Saídas (falta, contagem < sistema)
// = Resultado do mês. Ver _fluxo_inventario_por_mes no backend.
const CORES_FLUXO_INVENTARIO = { entrada: "#4caf50", saida: "#e5534b", resultado: "#5b75ac" };

// ---------- resumo operacional (12/08/2026, estendido em 13/08/2026) ----------
// Os 2 KPI cards centrais (Passivos, Resultado de Inventário Acumulado) e TODOS os gráficos/
// tabelas do relatório (Evolução Mensal, Fluxo de Inventário, Resultado por Almoxarifado, Motivos
// Mensal/Resumo, Top 10s) respondem ao MESMO filtro de Data/Mês/Ano/Almoxarifado/Motivo - antes
// (13/08/2026) só os 2 cards respondiam, os gráficos e tabelas ficavam sempre com a base inteira.
// Ver carregarPassivosFiltrados() abaixo, que refaz TODAS as chamadas com o recorte atual sempre
// que um filtro muda. Justificativas de Ajuste de Inventário continua fora desse recorte (é uma
// lista de trabalho, não uma métrica do relatório).
const MESES_PT = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];
const IDS_FILTRO_MP = ["mp-filtro-ano", "mp-filtro-mes", "mp-filtro-data-inicio", "mp-filtro-data-fim", "mp-filtro-almoxarifado", "mp-filtro-motivo"];
let dadosMpResumoExecutivo = null;

function montarParamsResumoExecutivoMp() {
  const params = {};
  const ano = document.getElementById("mp-filtro-ano").value;
  const mes = document.getElementById("mp-filtro-mes").value;
  const dataInicio = document.getElementById("mp-filtro-data-inicio").value;
  const dataFim = document.getElementById("mp-filtro-data-fim").value;
  const almoxarifado = document.getElementById("mp-filtro-almoxarifado").value;
  const motivo = document.getElementById("mp-filtro-motivo").value;
  if (ano) params.ano = ano;
  if (mes) params.mes = mes;
  if (dataInicio) params.data_inicio = dataInicio;
  if (dataFim) params.data_fim = dataFim;
  if (almoxarifado) params.almoxarifado = almoxarifado;
  if (motivo) params.motivo = motivo;
  return params;
}

async function carregarFiltrosMp() {
  const f = await apiFetch(`${API}/baixas-operacionais/dashboard/resumo-executivo/filtros`).then((r) => r.json());

  const selAno = document.getElementById("mp-filtro-ano");
  const anoAtual = selAno.value;
  selAno.innerHTML = `<option value="">Todos os anos</option>` + f.anos.map((a) => `<option value="${a}">${a}</option>`).join("");
  selAno.value = anoAtual;

  const selMes = document.getElementById("mp-filtro-mes");
  const mesAtual = selMes.value;
  selMes.innerHTML = `<option value="">Todos os meses</option>` + f.meses.map((m) => `<option value="${m}">${MESES_PT[m - 1]}</option>`).join("");
  selMes.value = mesAtual;

  const selAlmox = document.getElementById("mp-filtro-almoxarifado");
  const almoxAtual = selAlmox.value;
  selAlmox.innerHTML = `<option value="">Todos os almoxarifados</option>` + f.almoxarifados.map((a) => `<option value="${a}">${a}</option>`).join("");
  selAlmox.value = almoxAtual;

  const selMotivo = document.getElementById("mp-filtro-motivo");
  const motivoAtual = selMotivo.value;
  selMotivo.innerHTML = `<option value="">Todos os motivos</option>` + f.motivos.map((m) => `<option value="${m}">${m}</option>`).join("");
  selMotivo.value = motivoAtual;
}

async function carregarResumoExecutivoMp() {
  const params = new URLSearchParams(montarParamsResumoExecutivoMp());
  const dados = await apiFetch(`${API}/baixas-operacionais/dashboard/resumo-executivo?${params.toString()}`).then((r) => r.json());
  dadosMpResumoExecutivo = dados;

  const ri = dados.resultado_inventario;
  document.getElementById("mp-kpi-row-resumo").innerHTML = `
    <div class="kpi-card-grande" id="mp-card-passivos" title="Duplo clique para o resumo executivo">
      <div class="kpi-label">Passivos</div>
      <div class="kpi-value">${formatarMoeda(dados.passivos.valor)}</div>
      <div class="kpi-dica">${dados.passivos.quantidade} baixa(s) aprovada(s) neste recorte · duplo clique para o resumo executivo</div>
    </div>
    <div class="kpi-card-grande" id="mp-card-resultado-inventario" title="Duplo clique para o resumo executivo">
      <div class="kpi-label">Resultado de Inventário Acumulado</div>
      <div class="kpi-value" style="color:${ri.resultado_valor >= 0 ? CORES_FLUXO_INVENTARIO.entrada : CORES_FLUXO_INVENTARIO.saida}">${formatarMoeda(ri.resultado_valor)}</div>
      <div class="kpi-dica">Entradas ${formatarMoeda(ri.entradas_valor)} − Saídas ${formatarMoeda(ri.saidas_valor)} · duplo clique para o resumo executivo</div>
    </div>
  `;
  ["mp-card-passivos", "mp-card-resultado-inventario"].forEach((id) =>
    document.getElementById(id).addEventListener("dblclick", abrirModalResumoExecutivoMp)
  );
}

function abrirModalResumoExecutivoMp() {
  const dados = dadosMpResumoExecutivo;
  if (!dados) return;
  const cat = dados.passivos.por_categoria;
  const ri = dados.resultado_inventario;
  const dv = dados.divergencias_resolvidas;

  document.getElementById("modal-resumo-executivo-mp-corpo").innerHTML = `
    <div class="kpi-row-modal">
      <div class="kpi-mini"><div class="valor">${formatarMoeda(dados.passivos.valor)}</div><div class="rotulo">Passivos</div></div>
      <div class="kpi-mini"><div class="valor">${formatarMoeda(ri.resultado_valor)}</div><div class="rotulo">Resultado Inventário</div></div>
      <div class="kpi-mini"><div class="valor">${formatarMoeda(dv.perda_real.valor)}</div><div class="rotulo">Perda real confirmada</div></div>
    </div>
    <p class="hint" style="white-space:pre-line; line-height:1.6; margin-bottom:16px">${dados.resumo_narrado}</p>
    <p class="panel-sub" style="margin-bottom:6px">Passivos por categoria de mapeamento</p>
    <table class="tabela" style="margin-bottom:16px">
      <thead><tr><th>Categoria</th><th>Quantidade</th><th>Valor</th></tr></thead>
      <tbody>
        <tr><td>${cat.inventario_mensal.label}</td><td>${cat.inventario_mensal.quantidade}</td><td>${formatarMoeda(cat.inventario_mensal.valor)}</td></tr>
        <tr><td>${cat.movimentacao_diaria.label}</td><td>${cat.movimentacao_diaria.quantidade}</td><td>${formatarMoeda(cat.movimentacao_diaria.valor)}</td></tr>
        <tr><td>${cat.aguardando_divergencia.label}</td><td>${cat.aguardando_divergencia.quantidade}</td><td>${formatarMoeda(cat.aguardando_divergencia.valor)}</td></tr>
        <tr><td>${cat.nao_decidida.label}</td><td>${cat.nao_decidida.quantidade}</td><td>${formatarMoeda(cat.nao_decidida.valor)}</td></tr>
      </tbody>
    </table>
    <p class="panel-sub" style="margin-bottom:6px">Divergências já resolvidas neste recorte — ajuste de processo (não é passivo real) x perda real confirmada</p>
    <table class="tabela">
      <thead><tr><th>Divergências resolvidas</th><th>Quantidade</th><th>Valor</th></tr></thead>
      <tbody>
        <tr><td>Ajuste de processo (não é passivo real)</td><td>${dv.ajuste_processo.quantidade}</td><td>${formatarMoeda(dv.ajuste_processo.valor)}</td></tr>
        <tr><td>Perda real confirmada</td><td>${dv.perda_real.quantidade}</td><td>${formatarMoeda(dv.perda_real.valor)}</td></tr>
        <tr><td>Não classificada</td><td>${dv.nao_classificado.quantidade}</td><td>${formatarMoeda(dv.nao_classificado.valor)}</td></tr>
      </tbody>
    </table>
  `;
  document.getElementById("modal-resumo-executivo-mp-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-resumo-executivo-mp").addEventListener("click", () => {
  document.getElementById("modal-resumo-executivo-mp-overlay").classList.add("hidden");
});
document.getElementById("modal-resumo-executivo-mp-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-resumo-executivo-mp-overlay") document.getElementById("modal-resumo-executivo-mp-overlay").classList.add("hidden");
});

// Narração em voz do resumo executivo (13/08/2026) - reaproveita a mesma voz/mecanismo
// da apresentação dos módulos (falarResumoModulo, definida mais abaixo neste arquivo;
// funciona aqui por hoisting de function declaration). Um botão no cantinho do painel
// e outro dentro do próprio pop-up, os dois chamam a mesma função.
function narrarResumoExecutivoMp() {
  if (!dadosMpResumoExecutivo) return;
  falarResumoModulo(dadosMpResumoExecutivo.resumo_narrado);
}
document.getElementById("btn-narrar-resumo-executivo-mp").addEventListener("click", narrarResumoExecutivoMp);
document.getElementById("btn-narrar-resumo-executivo-mp-modal").addEventListener("click", narrarResumoExecutivoMp);

IDS_FILTRO_MP.forEach((id) => document.getElementById(id).addEventListener("change", () => carregarPassivosFiltrados()));
document.getElementById("btn-limpar-filtros-mp").addEventListener("click", () => {
  IDS_FILTRO_MP.forEach((id) => (document.getElementById(id).value = ""));
  carregarPassivosFiltrados();
});

// Recarrega TODO o relatório (KPIs + gráficos + tabelas Top 10) com o recorte atual dos filtros
// (Data/Mês/Ano/Almoxarifado/Motivo) - chamada tanto pelos próprios filtros da tela quanto pelo
// export em HTML (que precisa do mesmo recorte por combinação de filtro capturada).
async function carregarPassivosFiltrados() {
  const qs = "?" + new URLSearchParams(montarParamsResumoExecutivoMp()).toString();
  const [motivosMensal, motivosResumo, evolucaoMensal, topRecorrentes, topImpacto, fluxoInventarioMensal, resultadoAlmoxarifado, top10Movimentos] = await Promise.all([
    apiFetch(`${API}/baixas-operacionais/dashboard/motivos-mensal${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/motivos-resumo${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/evolucao-mensal${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/top-recorrentes${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/top-impacto-financeiro${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/fluxo-inventario-mensal${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/resultado-por-almoxarifado${qs}`).then((r) => r.json()),
    apiFetch(`${API}/baixas-operacionais/dashboard/top-10-movimentos${qs}`).then((r) => r.json()),
  ]);

  renderMpMotivosMensal(motivosMensal);
  renderMpMotivosResumo(motivosResumo);
  renderMpFluxoInventario(fluxoInventarioMensal);
  renderMpEvolucaoMensal(evolucaoMensal);
  renderMpTabelaTop("mp-tabela-recorrentes", topRecorrentes);
  renderMpTabelaTop("mp-tabela-impacto-financeiro", topImpacto);
  renderMpResultadoPorAlmoxarifado(resultadoAlmoxarifado);
  renderMpTop10Movimentos(top10Movimentos);
  await carregarResumoExecutivoMp();
}

async function carregarMapeamentoPassivos() {
  await carregarFiltrosMp();
  await carregarPassivosFiltrados();
  carregarJustificativasAjusteInventario();
}

function renderMpMotivosResumo(dados) {
  // Substitui o indicador genérico "Classificação Oficial (Ace4)" (3 cards
  // abstratos: ajuste x passivo x legado) por algo acionável - quanto cada
  // motivo de baixa (Avaria, Vencimento, Descarte...) realmente custou, em
  // quantidade e R$. Mesmo filtro do gráfico de motivos acima (sem
  // Inventário Mensal), mas SEM o top-N/"Outros" - aqui é tabela, mostra
  // todo mundo.
  document.querySelector("#mp-tabela-motivos-resumo tbody").innerHTML = dados
    .map(
      (d) => `<tr data-motivo="${d.motivo}" style="cursor:pointer"><td>${d.motivo}</td><td>${d.quantidade}</td><td>${formatarMoeda(d.valor)}</td></tr>`
    )
    .join("") || `<tr><td colspan="3" style="color:var(--muted)">Nenhuma baixa aprovada ainda.</td></tr>`;

  document.querySelectorAll("#mp-tabela-motivos-resumo tbody tr[data-motivo]").forEach((tr) =>
    tr.addEventListener("click", () =>
      abrirModalPassivosItens(
        { motivo: tr.dataset.motivo, excluir_categoria_mapeamento: "inventario_mensal", status_fluxo: "APROVADA" },
        `${tr.dataset.motivo}`
      )
    )
  );

  definirLinhaTotal(
    "mp-tabela-motivos-resumo",
    dados.length
      ? `<td>Total</td><td>${dados.reduce((s, d) => s + (d.quantidade || 0), 0)}</td><td>${formatarMoeda(dados.reduce((s, d) => s + (d.valor || 0), 0))}</td>`
      : null
  );
}

const CORES_MOTIVOS_BAIXA = ["#5b75ac", "#4caf50", "#e5534b", "#f9a825", "#8e5b9e", "#3fb6c9"];
const COR_MOTIVO_OUTROS = "#8ca0a3";

function renderMpMotivosMensal(dados) {
  // Principais motivos de baixa mapeados, mês a mês, SEM contar o que já é inventário mensal
  // (esse fluxo tem seu próprio painel dedicado acima) - horizontal empilhado, um segmento por
  // motivo (top N + "Outros" agrupando o resto, pra não estourar a legenda).
  dadosMpMotivosMensal = dados;
  const INDICE_OUTROS = dados.motivos.indexOf("Outros");
  const totalPorMes = dados.meses.map((_, i) => dados.motivos.reduce((s, motivo) => s + (dados.valores[motivo][i] || 0), 0));
  const maiorTotalMes = Math.max(1, ...totalPorMes);

  const ctx = document.getElementById("mp-chart-motivos-mensal");
  if (chartMpMotivosMensal) chartMpMotivosMensal.destroy();
  chartMpMotivosMensal = new Chart(ctx, {
    type: "bar",
    data: {
      labels: dados.meses,
      datasets: dados.motivos.map((motivo, i) => ({
        label: motivo, data: dados.valores[motivo],
        backgroundColor: i === INDICE_OUTROS ? COR_MOTIVO_OUTROS : CORES_MOTIVOS_BAIXA[i % CORES_MOTIVOS_BAIXA.length],
        stack: "total", borderRadius: 2,
        formatarRotulo: (v) => (v && v / maiorTotalMes >= 0.08 ? formatarMoeda(v) : ""), corRotulo: "#12181b",
      })),
    },
    options: {
      indexAxis: "y",
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3" } },
        tooltip: {
          callbacks: {
            footer: (items) => `Total do mês: ${formatarMoeda(items.reduce((s, it) => s + it.raw, 0))}`,
          },
        },
      },
      scales: {
        x: { stacked: true, beginAtZero: true, ticks: { color: "#8ca0a3", callback: (v) => formatarMoeda(v) }, grid: { color: "#2e3a40" } },
        y: { stacked: true, ticks: { color: "#8ca0a3" }, grid: { display: false } },
      },
    },
  });

  ctx.onclick = (ev) => {
    // "index" acha o MÊS de forma confiável (categoria no eixo y, já que é horizontal). Pra saber
    // qual SEGMENTO/motivo foi clicado, testamos se ev.offsetX cai dentro da faixa horizontal
    // (base..x) daquele segmento - mesmo raciocínio do painel de Evolução Mensal, só que no eixo X
    // em vez do Y, porque aqui a barra é invertida (indexAxis: "y").
    const pontosIndex = chartMpMotivosMensal.getElementsAtEventForMode(ev, "index", { intersect: false }, true);
    if (!pontosIndex.length) return;
    const mes = dados.meses[pontosIndex[0].index];
    let segmentoClicado = pontosIndex.find((p) => {
      const el = chartMpMotivosMensal.getDatasetMeta(p.datasetIndex).data[p.index];
      const inicio = Math.min(el.x, el.base ?? el.x), fim = Math.max(el.x, el.base ?? el.x);
      return ev.offsetX >= inicio && ev.offsetX <= fim;
    });
    if (!segmentoClicado) {
      let menorDistancia = Infinity;
      pontosIndex.forEach((p) => {
        const el = chartMpMotivosMensal.getDatasetMeta(p.datasetIndex).data[p.index];
        const distancia = Math.abs((el.x ?? el.base ?? 0) - ev.offsetX);
        if (distancia < menorDistancia) { menorDistancia = distancia; segmentoClicado = p; }
      });
    }
    if (!segmentoClicado) return;
    const motivo = dados.motivos[segmentoClicado.datasetIndex];
    const filtroMotivo = motivo === "Outros" ? dados.motivos_agrupados_em_outros.join(",") : motivo;
    abrirModalPassivosItens(
      { mes, motivo: filtroMotivo, excluir_categoria_mapeamento: "inventario_mensal", status_fluxo: "APROVADA" },
      `${motivo} em ${mes}`
    );
  };
}

function renderMpFluxoInventario(dados) {
  dadosMpFluxoInventario = dados;
  // "Mapeamento de grana de todos os inventários": Total de Entradas (sobra encontrada no
  // fechamento) - Total de Saídas (falta) = Resultado do mês, somando TODOS os almoxarifados.
  // Saídas entram como valor NEGATIVO no dataset só pra desenhar a barra pra baixo (visão de
  // fluxo de caixa) - o valor em R$ mostrado no rótulo/tooltip usa o módulo (Math.abs).
  // O ponto da linha de Resultado fica, por definição, ENTRE as pontas das barras de Entrada e
  // Saída daquele mês (resultado = entrada - saída) - então um rótulo fixo em cada barra colide com
  // o rótulo do ponto da linha bem ali perto (testado visualmente e ficou ilegível). Pra não repetir
  // o mesmo erro do primeiro Mapeamento de Passivos (rótulos se sobrepondo), as barras de
  // Entrada/Saída não desenham texto no gráfico - o valor exato aparece no tooltip ao passar o
  // mouse. Só a linha de Resultado (o número que o Maurício pediu: "Resultado Total Mês") recebe
  // rótulo direto no gráfico, e só quando é grande o bastante pra não virar poluição visual nos
  // meses de resultado quase zero.
  const maiorResultadoAbs = Math.max(1, ...dados.map((d) => Math.abs(d.resultado_valor)));
  const rotuloResultado = (v) => (v && Math.abs(v) / maiorResultadoAbs >= 0.08 ? formatarMoeda(v) : "");

  const ctx = document.getElementById("mp-chart-fluxo-inventario");
  if (chartMpFluxoInventario) chartMpFluxoInventario.destroy();
  chartMpFluxoInventario = new Chart(ctx, {
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        {
          type: "bar", label: "Entradas (R$)", data: dados.map((d) => d.entradas_valor),
          backgroundColor: CORES_FLUXO_INVENTARIO.entrada, borderRadius: 3, order: 2,
        },
        {
          type: "bar", label: "Saídas (R$)", data: dados.map((d) => -d.saidas_valor),
          backgroundColor: CORES_FLUXO_INVENTARIO.saida, borderRadius: 3, order: 2,
        },
        {
          type: "line", label: "Resultado do Mês (Entradas − Saídas)", data: dados.map((d) => d.resultado_valor),
          borderColor: CORES_FLUXO_INVENTARIO.resultado, backgroundColor: "color-mix(in srgb, #5b75ac 25%, transparent)",
          fill: false, borderWidth: 3, pointRadius: 5, pointBackgroundColor: CORES_FLUXO_INVENTARIO.resultado, tension: 0.25, order: 1,
          formatarRotulo: rotuloResultado, corRotulo: CORES_FLUXO_INVENTARIO.resultado,
        },
      ],
    },
    options: {
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3", font: { size: 10 } } },
        tooltip: { callbacks: { label: (ctx2) => `${ctx2.dataset.label}: ${formatarMoeda(Math.abs(ctx2.raw))}` } },
      },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: {
          ticks: { color: "#8ca0a3", callback: (v) => formatarMoeda(v) }, grid: { color: "#2e3a40" },
          title: { display: true, text: "R$ (Entradas acima de zero · Saídas abaixo)", color: "#8ca0a3", font: { size: 10 } },
        },
      },
    },
  });
  ctx.onclick = (ev) => {
    // "index"+intersect:false acha o MÊS clicado de forma confiável mesmo fora de uma barra exata,
    // e devolve TODOS os datasets daquele índice juntos (não necessariamente na ordem de posição -
    // o Chart.js pode ordenar pelo "order" de desenho) - então pra saber QUAL série (entrada/saída/
    // linha) o usuário realmente clicou, comparamos manualmente a posição Y de cada elemento com a
    // posição Y do próprio clique (ev.offsetY, relativo ao canvas - mesmo espaço de coordenadas que
    // getDatasetMeta().data[i].y), e usamos a mais próxima.
    const pontosIndex = chartMpFluxoInventario.getElementsAtEventForMode(ev, "index", { intersect: false }, true);
    if (!pontosIndex.length) return;
    const d = dadosMpFluxoInventario[pontosIndex[0].index];
    let maisProximo = null, menorDistancia = Infinity;
    pontosIndex.forEach((p) => {
      const el = chartMpFluxoInventario.getDatasetMeta(p.datasetIndex).data[p.index];
      const distancia = Math.abs((el.y ?? el.base ?? 0) - ev.offsetY);
      if (distancia < menorDistancia) { menorDistancia = distancia; maisProximo = p; }
    });
    const datasetIndex = maisProximo ? maisProximo.datasetIndex : null;
    const direcao = datasetIndex === 0 ? "entrada" : datasetIndex === 1 ? "saida" : null;
    const sufixo = direcao === "entrada" ? " — Entradas" : direcao === "saida" ? " — Saídas" : " — Entradas e Saídas";
    abrirModalFluxoInventarioItens({ mes: d.mes, ...(direcao ? { direcao } : {}) }, `Fluxo de Inventário em ${d.mes}${sufixo}`);
  };
}

const CORES_RESULTADO_ALMOX = { passivos: "#e5534b", inventario: "#5b75ac" };

function renderMpResultadoPorAlmoxarifado(dados) {
  // Segundo indicador (13/08/2026): a mesma quebra Passivos x Resultado de Inventário do Resumo
  // Executivo, só que por ALMOXARIFADO em vez de por mês - pra achar onde estão concentradas as
  // maiores perdas. Barra horizontal empilhada (Passivos + Resultado de Inventário em valor
  // absoluto), já vem ordenada do backend do maior pro menor "valor acumulado do período".
  dadosMpResultadoAlmoxarifado = dados;
  const maiorAcumulado = Math.max(1, ...dados.map((d) => d.valor_acumulado));

  const ctx = document.getElementById("mp-chart-resultado-almoxarifado");
  if (chartMpResultadoAlmoxarifado) chartMpResultadoAlmoxarifado.destroy();
  chartMpResultadoAlmoxarifado = new Chart(ctx, {
    type: "bar",
    data: {
      labels: dados.map((d) => d.almoxarifado),
      datasets: [
        {
          label: "Passivos (R$)", data: dados.map((d) => d.passivos_valor),
          backgroundColor: CORES_RESULTADO_ALMOX.passivos, stack: "total", borderRadius: 2,
          formatarRotulo: (v) => (v && v / maiorAcumulado >= 0.08 ? formatarMoeda(v) : ""), corRotulo: "#eef2f3",
        },
        {
          label: "Resultado de Inventário (valor absoluto, R$)", data: dados.map((d) => d.inventario_valor_abs),
          backgroundColor: CORES_RESULTADO_ALMOX.inventario, stack: "total", borderRadius: 2,
          formatarRotulo: (v) => (v && v / maiorAcumulado >= 0.08 ? formatarMoeda(v) : ""), corRotulo: "#eef2f3",
        },
      ],
    },
    options: {
      indexAxis: "y",
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3" } },
        tooltip: {
          callbacks: {
            footer: (items) => {
              const d = dados[items[0].dataIndex];
              return [
                `Resultado de Inventário (com sinal): ${formatarMoeda(d.resultado_inventario_valor)}`,
                `Valor acumulado do período: ${formatarMoeda(d.valor_acumulado)}`,
              ];
            },
          },
        },
      },
      scales: {
        x: { stacked: true, beginAtZero: true, ticks: { color: "#8ca0a3", callback: (v) => formatarMoeda(v) }, grid: { color: "#2e3a40" } },
        y: { stacked: true, ticks: { color: "#8ca0a3" }, grid: { display: false } },
      },
    },
  });

  // reaproveita o clique-para-filtrar padrão (Power BI-like): clicar numa barra joga o
  // almoxarifado no filtro do próprio painel (recarregando tudo) e mostra o resumo do ponto.
  ativarCliqueParaFiltrar(
    chartMpResultadoAlmoxarifado, ctx, dados,
    (linha) => linha.almoxarifado,
    "mp-filtro-almoxarifado",
    (linha) => ({
      titulo: `Almoxarifado ${linha.almoxarifado}`,
      resumo:
        `No almoxarifado ${linha.almoxarifado}, neste recorte: Passivos de ${formatarMoeda(linha.passivos_valor)} e ` +
        `Resultado de Inventário de ${formatarMoeda(linha.resultado_inventario_valor)} ` +
        `(${linha.resultado_inventario_valor >= 0 ? "sobra líquida" : "perda líquida"}). ` +
        `Valor acumulado do período (Passivos + Resultado de Inventário em valor absoluto): ${formatarMoeda(linha.valor_acumulado)}.`,
    })
  );
}

function renderMpEvolucaoMensal(dados) {
  dadosMpEvolucaoMensal = dados;
  // Empilhado mês a mês, como pediu o Maurício: resultado do inventário (em valor
  // POSITIVO/absoluto - aqui é sobre tamanho do movimento, não sobre sinal) +
  // passivos do período, uma barra só por mês. A curva de evolução acompanha
  // essa mesma soma empilhada (não só o valor de baixas como antes), acumulada
  // mês a mês - é a "história completa" olhando as duas fontes juntas.
  const resultadoInvAbs = dados.map((d) => Math.abs(d.resultado_inventario_mes || 0));
  const passivosValor = dados.map((d) => d.valor || 0);
  let acumulado = 0;
  const totalAcumulado = dados.map((d, i) => (acumulado += resultadoInvAbs[i] + passivosValor[i]));

  // mesmo cuidado de sempre: só rotula direto na barra quando o valor é grande o bastante
  // (>= 8% do maior total empilhado do período) - evita colidir os dois rótulos numa
  // barra empilhada estreita.
  const maiorTotalEmpilhado = Math.max(1, ...dados.map((d, i) => resultadoInvAbs[i] + passivosValor[i]));
  const INDICE_LINHA = 2;

  const ctx = document.getElementById("mp-chart-evolucao-mensal");
  if (chartMpEvolucaoMensal) chartMpEvolucaoMensal.destroy();
  chartMpEvolucaoMensal = new Chart(ctx, {
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        {
          type: "bar", label: "Resultado do Fluxo de Inventário no mês (valor absoluto)", data: resultadoInvAbs,
          backgroundColor: CORES_FLUXO_INVENTARIO.resultado, borderRadius: 3, yAxisID: "y1", order: 2, stack: "total",
          formatarRotulo: (v) => (v && v / maiorTotalEmpilhado >= 0.08 ? formatarMoeda(v) : ""), corRotulo: "#c9d4d6",
        },
        {
          type: "bar", label: "Passivos do mês (R$)", data: passivosValor,
          backgroundColor: "#e5534b", borderRadius: 3, yAxisID: "y1", order: 2, stack: "total",
          formatarRotulo: (v) => (v && v / maiorTotalEmpilhado >= 0.08 ? formatarMoeda(v) : ""), corRotulo: "#c9d4d6",
        },
        {
          type: "line", label: "Curva de evolução (valor acumulado)", data: totalAcumulado,
          borderColor: "#f9a825", backgroundColor: "color-mix(in srgb, #f9a825 25%, transparent)", fill: false,
          borderWidth: 3, pointRadius: 5, pointBackgroundColor: "#f9a825", tension: 0.25, yAxisID: "y1", order: 1,
          formatarRotulo: (v) => formatarMoeda(v), corRotulo: "#f9a825",
        },
      ],
    },
    options: {
      onHover: (evt, elementos) => { evt.native.target.style.cursor = elementos.length ? "pointer" : "default"; },
      plugins: {
        legend: { position: "bottom", labels: { color: "#8ca0a3" } },
        tooltip: {
          callbacks: {
            afterBody: (items) => [
              `Resultado do fluxo de inventário no mês: ${formatarMoeda(dados[items[0].dataIndex].resultado_inventario_mes || 0)} (valor absoluto na barra)`,
              `Passivos no mês: ${formatarMoeda(dados[items[0].dataIndex].valor)}`,
              `Total empilhado no mês: ${formatarMoeda(resultadoInvAbs[items[0].dataIndex] + passivosValor[items[0].dataIndex])}`,
            ],
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false }, stacked: true },
        y1: {
          position: "left", stacked: true, beginAtZero: true,
          ticks: { color: "#8ca0a3", callback: (v) => formatarMoeda(v) }, grid: { color: "#2e3a40" },
          title: { display: true, text: "R$ (resultado do inventário + passivos do mês)", color: "#8ca0a3", font: { size: 10 } },
        },
      },
    },
  });
  ctx.onclick = (ev) => {
    // "index" acha o MÊS de forma confiável. Pra saber qual SEGMENTO da barra empilhada foi
    // clicado (fluxo de inventário x passivos - cada um abre uma modal diferente), testamos se
    // ev.offsetY cai dentro da faixa vertical (base..y) daquele segmento específico; a linha
    // (curva) é ignorada aqui, ela não abre modal própria.
    const pontosIndex = chartMpEvolucaoMensal.getElementsAtEventForMode(ev, "index", { intersect: false }, true);
    if (!pontosIndex.length) return;
    const d = dadosMpEvolucaoMensal[pontosIndex[0].index];
    const candidatosBarras = pontosIndex.filter((p) => p.datasetIndex !== INDICE_LINHA);
    if (!candidatosBarras.length) return;
    let maisProximo = candidatosBarras.find((p) => {
      const el = chartMpEvolucaoMensal.getDatasetMeta(p.datasetIndex).data[p.index];
      const topo = Math.min(el.y, el.base ?? el.y), base = Math.max(el.y, el.base ?? el.y);
      return ev.offsetY >= topo && ev.offsetY <= base;
    });
    if (!maisProximo) {
      let menorDistancia = Infinity;
      candidatosBarras.forEach((p) => {
        const el = chartMpEvolucaoMensal.getDatasetMeta(p.datasetIndex).data[p.index];
        const distancia = Math.abs((el.y ?? el.base ?? 0) - ev.offsetY);
        if (distancia < menorDistancia) { menorDistancia = distancia; maisProximo = p; }
      });
    }
    const clicouResultadoInventario = maisProximo && maisProximo.datasetIndex === 0;
    if (clicouResultadoInventario) {
      abrirModalFluxoInventarioItens({ mes: d.mes }, `Fluxo de Inventário em ${d.mes}`);
    } else {
      abrirModalPassivosItens({ mes: d.mes }, `Baixas aplicadas em ${d.mes}`);
    }
  };
}

function renderMpTabelaTop(idTabela, lista) {
  document.querySelector(`#${idTabela} tbody`).innerHTML = lista
    .map((i) => `<tr data-sku="${i.sku}" style="cursor:pointer"><td>${i.sku}</td><td class="col-descricao">${i.descricao_produto || "—"}</td><td>${i.quantidade}</td><td>${formatarMoeda(i.valor)}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhuma baixa aprovada ainda.</td></tr>`;

  document.querySelectorAll(`#${idTabela} tbody tr[data-sku]`).forEach((tr) =>
    tr.addEventListener("click", () => abrirModalPassivosItens({ sku: tr.dataset.sku }, `Baixas do SKU ${tr.dataset.sku}`))
  );

  definirLinhaTotal(
    idTabela,
    lista.length
      ? `<td colspan="2">Total (Top ${lista.length})</td><td>${lista.reduce((s, i) => s + (i.quantidade || 0), 0)}</td><td>${formatarMoeda(lista.reduce((s, i) => s + (i.valor || 0), 0))}</td>`
      : null
  );
}

// Converte o filtro do painel (montarParamsResumoExecutivoMp: {ano, mes, data_inicio, data_fim,
// almoxarifado, motivo}) pro formato que os endpoints de drill-down (/dashboard/itens,
// /dashboard/itens-fluxo-inventario) esperam - `mes` (1-12) vira `mes_numero`, porque nesses
// endpoints `mes` já significa outra coisa (o mês exato "YYYY-MM" de um clique específico).
function paramsRecorteParaItens() {
  const base = montarParamsResumoExecutivoMp();
  const { mes, ...resto } = base;
  return mes ? { ...resto, mes_numero: mes } : resto;
}

// ---------- Top 10 Maiores Movimentações do Período (13/08/2026) ----------
// Combina Passivos aprovados e Ajustes de Inventário numa lista só, ordenada por valor absoluto -
// complementa o "Resultado por Almoxarifado" (que soma por almoxarifado) com o detalhe linha a
// linha das maiores movimentações específicas. Cada linha abre a mesma justificativa usada pelo
// Fluxo de Inventário, agora também estendida a Passivos (ver abrirModalJustificativaPorItem).
function renderMpTop10Movimentos(dados) {
  const tbody = document.querySelector("#mp-tabela-top-10-movimentos tbody");
  tbody.innerHTML = dados
    .map((item, idx) => {
      const detalhe = item.tipo === "passivo"
        ? `${item.motivo || "—"} · ${badgeStatusBaixa(item.status_fluxo)}`
        : `Lote ${item.id_lote || "—"} · <span style="color:${item.direcao === "entrada" ? "var(--ok)" : "var(--critico)"}">${item.direcao === "entrada" ? "Entrada" : "Saída"}</span>`;
      const corTipo = item.tipo === "passivo" ? CORES_RESULTADO_ALMOX.passivos : CORES_RESULTADO_ALMOX.inventario;
      const badgeInvestigacao = item.tem_justificativa
        ? `<span class="badge badge-sim">Sim</span>`
        : `<span class="badge badge-nao">Não</span>`;
      return `<tr data-idx="${idx}" style="cursor:pointer" title="Clique pra abrir/editar a justificativa deste item">
        <td><span class="badge-status" style="background:color-mix(in srgb, ${corTipo} 20%, transparent); color:${corTipo}">${item.tipo === "passivo" ? "Passivo" : "Inventário"}</span></td>
        <td>${item.sku}</td>
        <td class="col-descricao">${item.descricao_produto || "—"}</td>
        <td>${item.almoxarifado || "—"}</td>
        <td>${item.data ? formatarDataCurta(item.data) : "—"}</td>
        <td>${detalhe}</td>
        <td>${item.quantidade ?? "—"}</td>
        <td>${formatarMoeda(item.valor_com_sinal ?? item.valor)}</td>
        <td>${badgeInvestigacao}</td>
        <td><button class="btn-secundario btn-justificar-top10" data-idx="${idx}">Justificar</button></td>
      </tr>`;
    })
    .join("") || `<tr><td colspan="10" style="color:var(--muted)">Nenhuma movimentação encontrada nesse recorte.</td></tr>`;

  definirLinhaTotal(
    "mp-tabela-top-10-movimentos",
    dados.length
      ? `<td colspan="7">Total (${dados.length} ${dados.length === 1 ? "item exibido" : "itens exibidos"})</td><td>${formatarMoeda(dados.reduce((s, i) => s + (i.valor_com_sinal ?? i.valor ?? 0), 0))}</td><td colspan="2"></td>`
      : null
  );

  const abrirJustificativaDoItem = (idx) => {
    const item = dados[idx];
    if (item) abrirModalJustificativaPorItem(item, item.tipo);
  };
  document.querySelectorAll("#mp-tabela-top-10-movimentos tbody tr[data-idx]").forEach((tr) =>
    tr.addEventListener("click", () => abrirJustificativaDoItem(parseInt(tr.dataset.idx)))
  );
  document.querySelectorAll(".btn-justificar-top10").forEach((btn) =>
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      abrirJustificativaDoItem(parseInt(btn.dataset.idx));
    })
  );
}

document.getElementById("btn-ver-todos-passivos").addEventListener("click", () =>
  abrirModalPassivosItens({ ...paramsRecorteParaItens(), status_fluxo: "APROVADA" }, "Todos os Passivos do período")
);
document.getElementById("btn-ver-todos-inventario").addEventListener("click", () => {
  const { motivo, ...params } = paramsRecorteParaItens(); // motivo não existe em Ajuste de Inventário
  abrirModalFluxoInventarioItens(params, "Todos os Ajustes de Inventário do período");
});

async function abrirModalPassivosItens(filtros, titulo) {
  const params = new URLSearchParams(filtros);
  const dados = await apiFetch(`${API}/baixas-operacionais/dashboard/itens?${params.toString()}`).then((r) => r.json());

  document.getElementById("modal-passivos-itens-titulo").textContent = `${titulo} (${dados.total})`;
  document.getElementById("modal-passivos-itens-resumo").textContent = `Valor total: ${formatarMoeda(dados.valor_total)}`;
  document.querySelector("#tabela-modal-passivos-itens tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr>
        <td>${i.sku}</td><td class="col-descricao">${i.descricao_produto || "—"}</td><td>${i.almoxarifado || "—"}</td>
        <td>${i.motivo || "—"}</td><td>${i.quantidade ?? "—"}</td><td>${formatarMoeda(i.valor_total)}</td>
        <td>${badgeStatusBaixa(i.status_fluxo)}</td><td>${i.data_baixa ? formatarDataCurta(i.data_baixa) : "—"}</td>
        <td>${i.divergencia_vinculada_id ? "#" + i.divergencia_vinculada_id : "—"}</td>
        <td>${i.divergencia_vinculada_id ? `<button class="btn-secundario btn-ver-divergencia-passivo" data-id="${i.divergencia_vinculada_id}">Ver</button>` : ""}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="10" style="color:var(--muted)">Nenhuma baixa encontrada nessa categoria.</td></tr>`;

  document.querySelectorAll(".btn-ver-divergencia-passivo").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.getElementById("modal-passivos-itens-overlay").classList.add("hidden");
      mostrarView("lista");
      abrirDetalhe(parseInt(btn.dataset.id));
    })
  );

  document.getElementById("modal-passivos-itens-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-passivos-itens").addEventListener("click", () => {
  document.getElementById("modal-passivos-itens-overlay").classList.add("hidden");
});
document.getElementById("modal-passivos-itens-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-passivos-itens-overlay") document.getElementById("modal-passivos-itens-overlay").classList.add("hidden");
});

async function abrirModalFluxoInventarioItens(filtros, titulo) {
  const params = new URLSearchParams(filtros);
  const dados = await apiFetch(`${API}/baixas-operacionais/dashboard/itens-fluxo-inventario?${params.toString()}`).then((r) => r.json());

  document.getElementById("modal-fluxo-inventario-itens-titulo").textContent = `${titulo} (${dados.total})`;
  document.getElementById("modal-fluxo-inventario-itens-resumo").textContent =
    `Entradas: ${formatarMoeda(dados.entradas_valor)} · Saídas: ${formatarMoeda(dados.saidas_valor)} · ` +
    `Resultado: ${formatarMoeda(dados.entradas_valor - dados.saidas_valor)}`;
  document.querySelector("#tabela-modal-fluxo-inventario-itens tbody").innerHTML = dados.itens
    .map(
      (i) => `<tr data-id="${i.id}" class="linha-clicavel">
        <td>${i.sku}</td><td class="col-descricao">${i.descricao_produto || "—"}</td><td>${i.almoxarifado || "—"}</td>
        <td>${i.id_lote || "—"}</td>
        <td>${i.qtd_sistema ?? "—"}</td><td>${i.qtd_contagem ?? "—"}</td><td>${i.divergencia_qtd ?? "—"}</td>
        <td style="color:${i.direcao === "entrada" ? "var(--ok)" : "var(--critico)"}">${i.direcao === "entrada" ? "Entrada" : "Saída"}</td>
        <td>${formatarMoeda(i.valor_estimado)}</td><td>${i.data_fechamento ? formatarDataCurta(i.data_fechamento) : "—"}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="10" style="color:var(--muted)">Nenhum ajuste de inventário encontrado.</td></tr>`;

  document.querySelectorAll("#tabela-modal-fluxo-inventario-itens tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => {
      const item = dados.itens.find((i) => String(i.id) === tr.dataset.id);
      if (item) abrirModalJustificativaPorItem(item, "inventario");
    })
  );

  document.getElementById("modal-fluxo-inventario-itens-overlay").classList.remove("hidden");
}

document.getElementById("btn-fechar-modal-fluxo-inventario-itens").addEventListener("click", () => {
  document.getElementById("modal-fluxo-inventario-itens-overlay").classList.add("hidden");
});
document.getElementById("modal-fluxo-inventario-itens-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-fluxo-inventario-itens-overlay") document.getElementById("modal-fluxo-inventario-itens-overlay").classList.add("hidden");
});

// ---------- modal de justificativa de ajuste de inventário ----------
// Espelha o modal de Ação Pós-Inventário (abrirModalComAcao etc.) - mesma ideia de
// responsável/prazo/status/checklist, mas aplicada a um ajuste já conciliado na tabela
// oficial (Ace4), aberto a partir do modal "Itens do fluxo de inventário". Mantém o painel
// "Acompanhamento do item" igual ao da Ação Pós-Inventário e adiciona, embaixo, um
// mini-gráfico Qtd. Sistema x Qtd. Contagem x Diferença específico daquele ajuste.
let justificativaModalAtual = null;
let justificativaModalAoSalvar = null;
let checklistJustificativaModalAtual = [];
let chartJustificativaModalHistorico;
let chartJustificativaModalComparativo;
// Anexos da justificativa (14/08/2026) - existentesModalJustificativa vem do servidor (metadados,
// sem o binário) quando a justificativa já tem id; pendentes são File[] escolhidos no <input
// type=file> que ainda não foram enviados - só sobem de fato no clique de "Salvar" (ver
// btn-salvar-modal-justificativa), porque uma justificativa nova só ganha id depois de salva.
let anexosExistentesModalJustificativa = [];
let anexosPendentesModalJustificativa = [];
const MAX_ANEXO_BYTES_FRONT = 15 * 1024 * 1024;

// `tipo` distingue de onde a justificativa foi aberta - "inventario" (linha de um ajuste
// oficial, ver AjusteInventarioOficial) ou "passivo" (linha de uma baixa aprovada, ver
// BaixaOperacional) - 13/08/2026, estendido a partir do Top 10 Maiores Movimentações e das
// listas completas de Passivos/Ajustes de Inventário, que agora também abrem justificativa.
async function abrirModalJustificativaPorItem(item, tipo) {
  const paramFiltro = tipo === "passivo" ? `baixa_operacional_id=${item.id}` : `ajuste_id=${item.id}`;
  let existente = null;
  try {
    const lista = await apiFetch(`${API}/ajustes-inventario/justificativas?${paramFiltro}`).then((r) => r.json());
    existente = lista[0] || null;
  } catch (erro) {
    console.error("Falha ao buscar justificativa existente:", erro);
  }
  if (existente) {
    abrirModalComJustificativa(existente, () => carregarJustificativasAjusteInventario());
  } else if (tipo === "passivo") {
    abrirModalComJustificativa(
      {
        baixa_operacional_id: item.id, sku: item.sku, descricao_produto: item.descricao_produto, almoxarifado: item.almoxarifado,
        id_lote: null, qtd_sistema: null, qtd_contagem: null,
        divergencia_qtd: item.quantidade, valor_estimado: item.valor ?? item.valor_total,
        justificativa: "", solucao_aplicada: null, responsavel: null, prazo: null, status: "Pendente", checklist: [],
      },
      () => carregarJustificativasAjusteInventario()
    );
  } else {
    abrirModalComJustificativa(
      {
        ajuste_id: item.id, sku: item.sku, descricao_produto: item.descricao_produto, almoxarifado: item.almoxarifado,
        id_lote: item.id_lote, qtd_sistema: item.qtd_sistema, qtd_contagem: item.qtd_contagem,
        divergencia_qtd: item.divergencia_qtd ?? item.quantidade, valor_estimado: item.valor_estimado ?? item.valor,
        justificativa: "", solucao_aplicada: null, responsavel: null, prazo: null, status: "Pendente", checklist: [],
      },
      () => carregarJustificativasAjusteInventario()
    );
  }
}

function abrirModalComJustificativa(justificativa, aoSalvar) {
  justificativaModalAtual = justificativa; // se não tiver .id, o modal está em modo "criar nova"
  justificativaModalAoSalvar = aoSalvar;
  checklistJustificativaModalAtual = Array.isArray(justificativa.checklist) ? [...justificativa.checklist] : [];
  const ehPassivo = !!justificativa.baixa_operacional_id; // deriva o tipo dos campos - ver abrirModalJustificativaPorItem

  document.getElementById("modal-justificativa-titulo").textContent =
    `${justificativa.sku} — ${justificativa.descricao_produto || "sem descrição"}${justificativa.id ? "" : " (nova justificativa)"}${ehPassivo ? " (Passivo)" : " (Ajuste de Inventário)"}`;
  document.getElementById("modal-justificativa-texto").value = justificativa.justificativa || "";
  document.getElementById("modal-justificativa-solucao").value = justificativa.solucao_aplicada || "";
  document.getElementById("modal-justificativa-responsavel").value = justificativa.responsavel || "";
  document.getElementById("modal-justificativa-prazo").value = justificativa.prazo || "";
  document.getElementById("modal-justificativa-status").value = justificativa.status || "Pendente";
  renderChecklistModalJustificativa();
  renderComparativoModalJustificativa(justificativa, ehPassivo);

  anexosPendentesModalJustificativa = [];
  anexosExistentesModalJustificativa = [];
  renderAnexosModalJustificativa();
  if (justificativa.id) {
    (async () => {
      try {
        anexosExistentesModalJustificativa = await apiFetch(`${API}/ajustes-inventario/justificativas/${justificativa.id}/anexos`).then((r) => r.json());
      } catch (erro) {
        console.error("Falha ao carregar anexos da justificativa:", erro);
      }
      renderAnexosModalJustificativa();
    })();
  }

  document.getElementById("modal-justificativa-overlay").classList.remove("hidden");

  document.getElementById("modal-justificativa-acompanhamento-kpis").innerHTML = `<p class="hint" style="grid-column:1/-1">Carregando...</p>`;
  document.getElementById("modal-justificativa-linha-do-tempo").innerHTML = "";
  (async () => {
    try {
      const params = justificativa.almoxarifado ? `?almoxarifado=${encodeURIComponent(justificativa.almoxarifado)}` : "";
      const historico = await apiFetch(`${API}/fechamentos/historico-sku/${encodeURIComponent(justificativa.sku)}${params}`).then((r) => r.json());
      renderAcompanhamentoModalJustificativa(historico);
    } catch (erro) {
      document.getElementById("modal-justificativa-acompanhamento-kpis").innerHTML = `<p class="hint" style="grid-column:1/-1">Não foi possível carregar o histórico.</p>`;
    }
  })();
}

function renderChecklistModalJustificativa() {
  document.getElementById("modal-justificativa-checklist-itens").innerHTML = checklistJustificativaModalAtual
    .map(
      (item, idx) => `<div class="checklist-item ${item.concluido ? "concluido" : ""}">
        <input type="checkbox" data-idx="${idx}" class="checklist-toggle-justificativa" ${item.concluido ? "checked" : ""}>
        <span>${item.descricao}</span>
        <button data-idx="${idx}" class="checklist-remover-justificativa">remover</button>
      </div>`
    )
    .join("") || "<p class='hint'>Nenhum item no checklist ainda.</p>";

  document.querySelectorAll(".checklist-toggle-justificativa").forEach((chk) =>
    chk.addEventListener("change", () => {
      checklistJustificativaModalAtual[parseInt(chk.dataset.idx)].concluido = chk.checked;
      renderChecklistModalJustificativa();
    })
  );
  document.querySelectorAll(".checklist-remover-justificativa").forEach((btn) =>
    btn.addEventListener("click", () => {
      checklistJustificativaModalAtual.splice(parseInt(btn.dataset.idx), 1);
      renderChecklistModalJustificativa();
    })
  );
}

document.getElementById("btn-add-checklist-justificativa").addEventListener("click", () => {
  const input = document.getElementById("modal-justificativa-checklist-novo");
  const texto = input.value.trim();
  if (!texto) return;
  checklistJustificativaModalAtual.push({ descricao: texto, concluido: false });
  input.value = "";
  renderChecklistModalJustificativa();
});

function formatarTamanhoArquivo(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderAnexosModalJustificativa() {
  const wrap = document.getElementById("modal-justificativa-anexos-lista");
  const linhasExistentes = anexosExistentesModalJustificativa
    .map(
      (a) => `<div class="anexo-item">
        <span class="anexo-nome" title="${a.nome_arquivo}">${a.nome_arquivo}</span>
        <span class="anexo-tamanho">${formatarTamanhoArquivo(a.tamanho_bytes)}</span>
        <button class="btn-secundario anexo-baixar" data-anexo-id="${a.id}" data-anexo-nome="${a.nome_arquivo}">Baixar</button>
        <button class="anexo-excluir" data-anexo-id="${a.id}">remover</button>
      </div>`
    )
    .join("");
  const linhasPendentes = anexosPendentesModalJustificativa
    .map(
      (f, idx) => `<div class="anexo-item anexo-pendente">
        <span class="anexo-nome" title="${f.name}">${f.name}</span>
        <span class="anexo-tamanho">${formatarTamanhoArquivo(f.size)}</span>
        <span class="badge badge-nao" style="margin-left:auto" title='Só sobe de fato ao clicar em "Salvar"'>Não enviado</span>
        <button class="anexo-remover-pendente" data-idx="${idx}">remover</button>
      </div>`
    )
    .join("");
  wrap.innerHTML = linhasExistentes + linhasPendentes || "<p class='hint'>Nenhum anexo ainda.</p>";

  document.querySelectorAll(".anexo-baixar").forEach((btn) =>
    btn.addEventListener("click", () => baixarAnexoJustificativa(parseInt(btn.dataset.anexoId), btn.dataset.anexoNome))
  );
  document.querySelectorAll(".anexo-excluir").forEach((btn) =>
    btn.addEventListener("click", () => excluirAnexoJustificativaExistente(parseInt(btn.dataset.anexoId)))
  );
  document.querySelectorAll(".anexo-remover-pendente").forEach((btn) =>
    btn.addEventListener("click", () => {
      anexosPendentesModalJustificativa.splice(parseInt(btn.dataset.idx), 1);
      renderAnexosModalJustificativa();
    })
  );
}

document.getElementById("modal-justificativa-anexo-input").addEventListener("change", (ev) => {
  const arquivos = Array.from(ev.target.files || []);
  const grandesDemais = arquivos.filter((f) => f.size > MAX_ANEXO_BYTES_FRONT);
  const validos = arquivos.filter((f) => f.size <= MAX_ANEXO_BYTES_FRONT);
  if (grandesDemais.length) {
    alert(`${grandesDemais.length} arquivo(s) maiores que 15 MB não foram adicionados: ${grandesDemais.map((f) => f.name).join(", ")}`);
  }
  anexosPendentesModalJustificativa.push(...validos);
  ev.target.value = ""; // permite selecionar o mesmo arquivo de novo depois, se remover e quiser readicionar
  renderAnexosModalJustificativa();
});

async function baixarAnexoJustificativa(anexoId, nomeArquivo) {
  try {
    const resp = await apiFetch(`${API}/ajustes-inventario/justificativas/anexos/${anexoId}/download`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nomeArquivo || "anexo";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (erro) {
    alert("Não consegui baixar o anexo: " + erro.message);
  }
}

async function excluirAnexoJustificativaExistente(anexoId) {
  if (!confirm("Excluir este anexo?")) return;
  const res = await apiFetch(`${API}/ajustes-inventario/justificativas/anexos/${anexoId}`, { method: "DELETE" });
  if (!res.ok) {
    alert("Não foi possível excluir o anexo.");
    return;
  }
  anexosExistentesModalJustificativa = anexosExistentesModalJustificativa.filter((a) => a.id !== anexoId);
  renderAnexosModalJustificativa();
}

function renderAcompanhamentoModalJustificativa(historico) {
  const kpis = [
    { rotulo: "Dias movimentados", valor: historico.dias_movimentados },
    { rotulo: "Dias pendente", valor: historico.dias_pendente, cor: "var(--critico)" },
    { rotulo: "Dias resolvido", valor: historico.dias_resolvido, cor: "var(--ok)" },
  ];
  document.getElementById("modal-justificativa-acompanhamento-kpis").innerHTML = kpis
    .map((k) => `<div class="kpi-mini"><div class="valor" style="${k.cor ? "color:" + k.cor : ""}">${k.valor}</div><div class="rotulo">${k.rotulo}</div></div>`)
    .join("");

  const linha = historico.linha_do_tempo || [];
  const ctx = document.getElementById("modal-justificativa-chart-historico");
  if (chartJustificativaModalHistorico) chartJustificativaModalHistorico.destroy();
  if (linha.length) {
    chartJustificativaModalHistorico = new Chart(ctx, {
      type: "line",
      data: {
        labels: linha.map((p) => formatarDataCurta(p.data)),
        datasets: [{
          label: "Divergente",
          data: linha.map((p) => (p.divergente ? 1 : 0)),
          borderColor: "#e5534b",
          backgroundColor: "#e5534b",
          pointBackgroundColor: linha.map((p) => (p.divergente ? "#e5534b" : "#4caf50")),
          pointRadius: 5,
          stepped: true,
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { min: 0, max: 1, ticks: { stepSize: 1, color: "#8ca0a3", callback: (v) => (v === 1 ? "Divergente" : "OK") }, grid: { color: "#2e3a40" } },
          x: { ticks: { color: "#8ca0a3", font: { size: 9 } }, grid: { display: false } },
        },
      },
    });
  }

  document.getElementById("modal-justificativa-linha-do-tempo").innerHTML = linha
    .slice()
    .reverse()
    .map((p) => `<div class="linha-tempo-item"><span>${formatarDataCurta(p.data)} · ${p.almoxarifado}</span><span style="color:${p.divergente ? "var(--critico)" : "var(--ok)"}">${p.divergente ? "Divergente" : "OK"}</span></div>`)
    .join("");
}

function renderComparativoModalJustificativa(item, ehPassivo) {
  // Passivo não tem Qtd. Sistema/Contagem (não é um ajuste conciliado) - mostra um resumo
  // simples (quantidade baixada + valor) no lugar do mini-gráfico comparativo, que só faz
  // sentido pra ajuste de inventário (13/08/2026).
  document.getElementById("modal-justificativa-comparativo-inventario").classList.toggle("hidden", !!ehPassivo);
  document.getElementById("modal-justificativa-comparativo-passivo").classList.toggle("hidden", !ehPassivo);
  if (ehPassivo) {
    document.getElementById("modal-justificativa-resumo-passivo").innerHTML = `
      <div class="kpi-mini"><div class="valor">${item.divergencia_qtd ?? "—"}</div><div class="rotulo">Quantidade baixada</div></div>
      <div class="kpi-mini"><div class="valor">${formatarMoeda(item.valor_estimado)}</div><div class="rotulo">Valor</div></div>
    `;
    return;
  }

  const ctx = document.getElementById("modal-justificativa-chart-comparativo");
  if (chartJustificativaModalComparativo) chartJustificativaModalComparativo.destroy();
  const qtdSistema = item.qtd_sistema ?? 0;
  const qtdContagem = item.qtd_contagem ?? 0;
  const diferenca = item.divergencia_qtd ?? qtdContagem - qtdSistema;
  chartJustificativaModalComparativo = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Qtd. Sistema", "Qtd. Contagem", "Diferença"],
      datasets: [{
        data: [qtdSistema, qtdContagem, diferenca],
        backgroundColor: ["#5b75ac", "#4caf50", diferenca < 0 ? "#e5534b" : "#4caf50"],
        borderRadius: 4,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { ticks: { color: "#8ca0a3" }, grid: { color: "#2e3a40" } },
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
      },
    },
  });
}

document.getElementById("btn-fechar-modal-justificativa").addEventListener("click", () => {
  document.getElementById("modal-justificativa-overlay").classList.add("hidden");
});
document.getElementById("modal-justificativa-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-justificativa-overlay") document.getElementById("modal-justificativa-overlay").classList.add("hidden");
});

document.getElementById("btn-salvar-modal-justificativa").addEventListener("click", async () => {
  if (!justificativaModalAtual) return;
  const textoJustificativa = document.getElementById("modal-justificativa-texto").value.trim();
  if (!textoJustificativa) {
    alert("Descreva a justificativa antes de salvar.");
    return;
  }
  const camposComuns = {
    justificativa: textoJustificativa,
    solucao_aplicada: document.getElementById("modal-justificativa-solucao").value.trim() || null,
    responsavel: document.getElementById("modal-justificativa-responsavel").value.trim() || null,
    prazo: document.getElementById("modal-justificativa-prazo").value || null,
    status: document.getElementById("modal-justificativa-status").value,
    checklist: checklistJustificativaModalAtual,
  };
  let res;
  if (justificativaModalAtual.id) {
    res = await apiFetch(`${API}/ajustes-inventario/justificativas/${justificativaModalAtual.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(camposComuns),
    });
  } else {
    res = await apiFetch(`${API}/ajustes-inventario/justificativas`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ajuste_id: justificativaModalAtual.ajuste_id || null, baixa_operacional_id: justificativaModalAtual.baixa_operacional_id || null,
        sku: justificativaModalAtual.sku,
        descricao_produto: justificativaModalAtual.descricao_produto, almoxarifado: justificativaModalAtual.almoxarifado,
        id_lote: justificativaModalAtual.id_lote, qtd_sistema: justificativaModalAtual.qtd_sistema,
        qtd_contagem: justificativaModalAtual.qtd_contagem, divergencia_qtd: justificativaModalAtual.divergencia_qtd,
        valor_estimado: justificativaModalAtual.valor_estimado, ...camposComuns,
      }),
    });
    // a criação (POST) já aceita status/checklist direto no payload (diferente da Ação
    // Pós-Inventário, que só aceita os campos básicos) - não precisa de um PATCH complementar.
  }
  if (!res.ok) {
    alert("Não foi possível salvar a justificativa.");
    return;
  }
  const justificativaSalva = await res.json();

  // Sobe os anexos escolhidos antes de salvar (uma justificativa nova só ganha id agora) - se
  // algum falhar, avisa mas não desfaz a justificativa (que já foi salva com sucesso).
  if (anexosPendentesModalJustificativa.length) {
    const btnSalvar = document.getElementById("btn-salvar-modal-justificativa");
    const textoOriginalBtn = btnSalvar.textContent;
    btnSalvar.disabled = true;
    let falhas = 0;
    for (const arquivo of anexosPendentesModalJustificativa) {
      btnSalvar.textContent = `Enviando ${arquivo.name}...`;
      const formData = new FormData();
      formData.append("arquivo", arquivo);
      try {
        const respAnexo = await apiFetch(`${API}/ajustes-inventario/justificativas/${justificativaSalva.id}/anexos`, {
          method: "POST", body: formData,
        });
        if (!respAnexo.ok) falhas++;
      } catch (erro) {
        falhas++;
      }
    }
    btnSalvar.disabled = false;
    btnSalvar.textContent = textoOriginalBtn;
    anexosPendentesModalJustificativa = [];
    if (falhas) alert(`A justificativa foi salva, mas ${falhas} anexo(s) não foram enviados. Abra a justificativa de novo pra tentar reenviar.`);
  }

  document.getElementById("modal-justificativa-overlay").classList.add("hidden");
  if (justificativaModalAoSalvar) justificativaModalAoSalvar();
});

async function carregarJustificativasAjusteInventario() {
  const tbody = document.querySelector("#mp-tabela-justificativas tbody");
  if (!tbody) return;
  let lista = [];
  try {
    lista = await apiFetch(`${API}/ajustes-inventario/justificativas`).then((r) => r.json());
  } catch (erro) {
    console.error("Falha ao carregar justificativas de ajuste de inventário:", erro);
    tbody.innerHTML = `<tr><td colspan="11" style="color:var(--muted)">Não foi possível carregar as justificativas agora.</td></tr>`;
    return;
  }
  tbody.innerHTML = lista
    .map(
      (j) => `<tr data-id="${j.id}" class="linha-clicavel">
        <td>${j.baixa_operacional_id ? "Passivo" : "Inventário"}</td>
        <td>${j.sku}</td><td class="col-descricao">${j.descricao_produto || "—"}</td><td>${j.id_lote || "—"}</td>
        <td>${j.qtd_sistema ?? "—"}</td><td>${j.qtd_contagem ?? "—"}</td><td>${j.divergencia_qtd ?? "—"}</td>
        <td class="col-descricao">${j.justificativa || "—"}</td><td class="col-descricao">${j.solucao_aplicada || "—"}</td>
        <td><span class="badge-status ${j.status}">${j.status.replace("_", " ")}</span></td>
        <td>${j.responsavel || "—"}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="11" style="color:var(--muted)">Nenhuma justificativa registrada ainda.</td></tr>`;

  document.querySelectorAll("#mp-tabela-justificativas tbody tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => {
      const justificativa = lista.find((j) => String(j.id) === tr.dataset.id);
      if (!justificativa) return;
      abrirModalComJustificativa(justificativa, () => carregarJustificativasAjusteInventario());
    })
  );
}

// ---------- mapa de demandas de gestão (painel fixo da tela Início) ----------
async function carregarMapaDemandas() {
  const painel = document.getElementById("painel-mapa-demandas");
  if (!painel) return;
  let dados;
  try {
    const res = await apiFetch(`${API}/dashboard/mapa-demandas`);
    if (!res.ok) throw new Error("resposta não-ok");
    dados = await res.json();
  } catch (erro) {
    console.error("Falha ao carregar o mapa de demandas:", erro);
    document.getElementById("md-kpi-row").innerHTML = `<p class="hint">Não foi possível carregar o mapa de demandas agora.</p>`;
    return;
  }

  const baixas = dados.baixas_pendentes || { total: 0, valor_total: 0, por_motivo: [] };
  const obsol = dados.obsolescencia || { resumo: { "30": { quantidade: 0, valor: 0 }, "60": { quantidade: 0, valor: 0 }, "90": { quantidade: 0, valor: 0 } } };
  const r = obsol.resumo;
  const shelf = dados.shelf_life;

  document.getElementById("md-kpi-row").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">Baixas pendentes (passivo)</div><div class="kpi-value accent">${baixas.total}</div></div>
    <div class="kpi-card"><div class="kpi-label">Valor em baixas pendentes</div><div class="kpi-value">${formatarMoeda(baixas.valor_total)}</div></div>
    <div class="kpi-card"><div class="kpi-label">SKUs em risco de obsolescência</div><div class="kpi-value">${(r["30"].quantidade + r["60"].quantidade + r["90"].quantidade)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Valor total em risco de obsolescência</div><div class="kpi-value" style="color:var(--alto)">${formatarMoeda(r["30"].valor + r["60"].valor + r["90"].valor)}</div></div>
    <div class="kpi-card"><div class="kpi-label">Lotes em risco de validade</div><div class="kpi-value" style="color:var(--critico)">${shelf ? shelf.total_lotes_em_risco : "—"}</div></div>
    <div class="kpi-card"><div class="kpi-label">Valor total em risco de validade</div><div class="kpi-value" style="color:var(--critico)">${shelf ? formatarMoeda(shelf.valor_total) : "—"}</div></div>
  `;

  document.getElementById("md-baixas-por-motivo").innerHTML = baixas.total
    ? baixas.por_motivo
        .map(
          (m) => `<div class="evidencia-item sim"><span>${m.motivo}</span><span>${m.quantidade} · ${formatarMoeda(m.valor)}</span></div>`
        )
        .join("")
    : `<p class="hint">Nenhuma baixa pendente no momento — tudo que foi solicitado já foi aprovado ou reprovado.</p>`;

  const linhaFarol = (cor, label, faixa) =>
    `<div class="evidencia-item sim"><span><span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:${cor}; margin-right:8px"></span>${label}</span><span>${faixa.quantidade} SKU(s) · ${formatarMoeda(faixa.valor)}</span></div>`;
  document.getElementById("md-obsolescencia-farol").innerHTML =
    linhaFarol("var(--medio)", "30-59 dias sem giro", r["30"]) +
    linhaFarol("var(--alto)", "60-89 dias sem giro", r["60"]) +
    linhaFarol("var(--critico)", "90+ dias sem giro", r["90"]);

  if (shelf) {
    const rs = shelf.resumo;
    const linhaFarolShelf = (cor, label, faixa) =>
      faixa
        ? `<div class="evidencia-item sim"><span><span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:${cor}; margin-right:8px"></span>${label}</span><span>${faixa.quantidade} lote(s) · ${formatarMoeda(faixa.valor)}</span></div>`
        : "";
    document.getElementById("md-shelf-life").innerHTML = `
      <h3 style="font-family:var(--display); font-size:14px; margin:16px 0 10px">Risco de validade (Shelf Life)</h3>
      ${linhaFarolShelf("var(--critico)", "Vencidos", rs.vencido)}
      ${linhaFarolShelf("var(--critico)", "Risco em 30 dias", rs["30"])}
      ${linhaFarolShelf("var(--alto)", "Risco em 60 dias", rs["60"])}
      ${linhaFarolShelf("var(--medio)", "Risco em 90 dias", rs["90"])}
      ${linhaFarolShelf("var(--muted)", "Pendente de validade (sem data cadastrada)", rs.sem_validade)}
      <button id="btn-ir-shelf-life" class="btn-secundario" style="margin-top:10px">Abrir tela Shelf Life →</button>
    `;
    const btnIrShelfLife = document.getElementById("btn-ir-shelf-life");
    if (btnIrShelfLife) btnIrShelfLife.addEventListener("click", () => mostrarView("shelf-life"));
  } else {
    document.getElementById("md-shelf-life").innerHTML = `📋 Risco de validade (Shelf Life): não foi possível carregar agora.`;
  }
}

// ---------- tela dedicada Shelf Life (risco de validade) ----------
const FAROL_LABEL_SHELF_LIFE = {
  vencido: "Vencido", "30": "Risco 30 dias", "60": "Risco 60 dias", "90": "Risco 90 dias", sem_validade: "Pendente de validade",
};
const FAROL_COR_SHELF_LIFE = {
  vencido: "var(--critico)", "30": "var(--critico)", "60": "var(--alto)", "90": "var(--medio)", sem_validade: "var(--muted)",
};

function badgeFarolShelfLife(farol) {
  const cor = FAROL_COR_SHELF_LIFE[farol] || "var(--muted)";
  const label = FAROL_LABEL_SHELF_LIFE[farol] || farol;
  return `<span style="display:inline-flex; align-items:center; gap:6px"><span style="width:9px; height:9px; border-radius:50%; background:${cor}; display:inline-block"></span>${label}</span>`;
}

async function atualizarSelectAlmoxarifadoShelfLife() {
  const lista = await apiFetch(`${API}/importar/almoxarifados`).then((r) => r.json());
  const opcoes = lista.map((a) => `<option value="${a.codigo}">${a.nome} (${a.codigo})</option>`).join("");
  const selFiltro = document.getElementById("sl-filtro-almoxarifado");
  const selForm = document.getElementById("sl-almoxarifado");
  if (selFiltro.options.length <= 1) selFiltro.insertAdjacentHTML("beforeend", opcoes);
  if (selForm && !selForm.options.length) selForm.innerHTML = `<option value="">(nenhum)</option>` + opcoes;
}

async function carregarShelfLife() {
  await atualizarSelectAlmoxarifadoShelfLife();

  const resumo = await apiFetch(`${API}/shelf-life/resumo`).then((r) => r.json());
  const rs = resumo.resumo;
  document.getElementById("sl-kpi-row").innerHTML = [
    { label: "Vencidos", value: rs.vencido.quantidade, valor: rs.vencido.valor, cor: "var(--critico)" },
    { label: "Risco 30 dias", value: rs["30"].quantidade, valor: rs["30"].valor, cor: "var(--critico)" },
    { label: "Risco 60 dias", value: rs["60"].quantidade, valor: rs["60"].valor, cor: "var(--alto)" },
    { label: "Risco 90 dias", value: rs["90"].quantidade, valor: rs["90"].valor, cor: "var(--medio)" },
    { label: "Pendente de validade", value: rs.sem_validade.quantidade, valor: rs.sem_validade.valor, cor: "var(--muted)" },
  ]
    .map((c) => `<div class="kpi-card"><div class="kpi-label">${c.label}</div><div class="kpi-value" style="color:${c.cor}">${c.value}</div><div class="hint" style="margin:2px 0 0">${formatarMoeda(c.valor)}</div></div>`)
    .join("");

  const farol = document.getElementById("sl-filtro-farol").value;
  const almoxarifado = document.getElementById("sl-filtro-almoxarifado").value;
  const busca = document.getElementById("sl-filtro-busca").value.trim();
  const params = new URLSearchParams();
  if (farol) params.set("farol", farol);
  if (almoxarifado) params.set("almoxarifado", almoxarifado);
  if (busca) params.set("busca", busca);

  const lotes = await apiFetch(`${API}/shelf-life/lotes?${params.toString()}`).then((r) => r.json());
  document.querySelector("#tabela-shelf-life tbody").innerHTML = lotes.length
    ? lotes
        .map(
          (l) => `<tr data-id="${l.id}">
            <td>${l.sku}</td><td class="col-descricao">${l.descricao_produto || "—"}</td><td>${l.lote || "—"}</td>
            <td>${l.almoxarifado || "—"}</td><td>${l.quantidade ?? "—"} ${l.unidade || ""}</td>
            <td>${l.data_validade ? formatarDataCurta(l.data_validade) : "—"}</td>
            <td>${l.dias_para_vencer != null ? l.dias_para_vencer : "—"}</td>
            <td>${formatarMoeda(l.valor_estimado)}</td>
            <td>${badgeFarolShelfLife(l.farol)}</td>
            <td><button class="btn-secundario btn-excluir-lote-shelf-life" data-id="${l.id}" style="padding:4px 10px">Excluir</button></td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="10" style="color:var(--muted)">Nenhum lote encontrado com esses filtros.</td></tr>`;

  document.querySelectorAll(".btn-excluir-lote-shelf-life").forEach((btn) =>
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Excluir este lote?")) return;
      const res = await apiFetch(`${API}/shelf-life/lotes/${btn.dataset.id}`, { method: "DELETE" });
      if (res.ok) carregarShelfLife();
    })
  );
}

document.getElementById("sl-filtro-farol").addEventListener("change", carregarShelfLife);
document.getElementById("sl-filtro-almoxarifado").addEventListener("change", carregarShelfLife);
let _timeoutBuscaShelfLife = null;
document.getElementById("sl-filtro-busca").addEventListener("input", () => {
  clearTimeout(_timeoutBuscaShelfLife);
  _timeoutBuscaShelfLife = setTimeout(carregarShelfLife, 400);
});

document.getElementById("btn-criar-lote-shelf-life").addEventListener("click", async () => {
  const msg = document.getElementById("sl-msg");
  const payload = {
    sku: document.getElementById("sl-sku").value.trim(),
    descricao_produto: document.getElementById("sl-descricao").value.trim() || null,
    lote: document.getElementById("sl-lote").value.trim() || null,
    almoxarifado: document.getElementById("sl-almoxarifado").value || null,
    quantidade: parseFloat(document.getElementById("sl-quantidade").value),
    unidade: document.getElementById("sl-unidade").value.trim() || null,
    data_validade: document.getElementById("sl-data-validade").value || null,
    custo_unitario: document.getElementById("sl-custo").value ? parseFloat(document.getElementById("sl-custo").value) : null,
  };
  if (!payload.sku || isNaN(payload.quantidade)) {
    msg.textContent = "Informe pelo menos SKU e quantidade.";
    return;
  }
  const res = await apiFetch(`${API}/shelf-life/lotes`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Erro ao criar lote."; return; }
  msg.textContent = "Lote adicionado.";
  ["sl-sku", "sl-descricao", "sl-lote", "sl-quantidade", "sl-unidade", "sl-data-validade", "sl-custo"].forEach((id) => (document.getElementById(id).value = ""));
  carregarShelfLife();
});

document.getElementById("btn-importar-shelf-life").addEventListener("click", async () => {
  const input = document.getElementById("sl-input-arquivo");
  const resultado = document.getElementById("sl-resultado-importacao");
  if (!input.files.length) {
    resultado.textContent = "Selecione um arquivo primeiro.";
    return;
  }
  const form = new FormData();
  form.append("arquivo", input.files[0]);
  form.append("aba", document.getElementById("sl-input-aba").value || "Lote_Sistema");
  resultado.textContent = "Importando...";
  try {
    const res = await apiFetch(`${API}/shelf-life/importar-planilha`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      resultado.textContent = `Erro (${res.status}): ${data.detail || JSON.stringify(data)}`;
      return;
    }
    resultado.textContent = JSON.stringify(data, null, 2);
    carregarShelfLife();
  } catch (erro) {
    resultado.textContent = "Falha ao importar: " + erro.message;
  }
});

// ---------- hub orbital (tela inicial) ----------
function renderizarHub() {
  const container = document.getElementById("hub-nodes");
  // usa os mesmos itens do menu lateral que estão visíveis pro usuário
  // (respeita permissão - Cadastros/Auditoria/Usuários só aparecem pra quem tem acesso)
  const itens = Array.from(document.querySelectorAll(".rail-item"))
    .filter((b) => b.dataset.view !== "hub" && !b.classList.contains("hidden"))
    .map((b) => ({ view: b.dataset.view, label: b.querySelector(".rail-label").textContent }));

  if (!itens.length) { container.innerHTML = ""; return; }

  const wrapEl = container.closest(".hub-wrap") || container.parentElement;
  const wrapRect = wrapEl.getBoundingClientRect();
  const centroX = wrapRect.left + wrapRect.width / 2;
  const centroY = wrapRect.top + wrapRect.height / 2;

  // ---- geometria real da tela, não estimativa de CSS ----
  // Em vez de confiar em %/vmin do CSS pra adivinhar quanto espaço existe
  // (o que já causou nós cortados em monitores largos/baixos e rótulos
  // sobrepostos em monitores menores), medimos a posição REAL do centro
  // do hub e as bordas REAIS da viewport e dos textos vizinhos (status de
  // voz / dica), e calculamos um raio máximo que NUNCA pode ser violado -
  // isso garante os módulos sempre dentro da área visível, em qualquer
  // monitor em que o Atlas for aberto.
  const margem = 14;
  const statusEl = document.getElementById("hub-voice-status");
  const hintEl = document.querySelector("#view-hub .hint");
  let limiteInferior = window.innerHeight - margem;
  [statusEl, hintEl].forEach((el) => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top > 0 && r.top < limiteInferior) limiteInferior = r.top;
  });

  const espacoEsquerda = centroX - margem;
  const espacoDireita = window.innerWidth - margem - centroX;
  const espacoAcima = centroY - margem;
  const espacoAbaixo = limiteInferior - margem - centroY;

  // "metade" de segurança de um nó (não é só um ponto - tem largura e
  // altura reais que também precisam caber dentro da área calculada acima)
  const METADE_LARGURA_MIN = 32; // metade da largura mínima aceitável de um nó (64px)
  const METADE_ALTURA_NODE = 50; // cobre ícone + até ~3 linhas de rótulo + padding

  const raioMaxEsquerda = espacoEsquerda - METADE_LARGURA_MIN;
  const raioMaxDireita = espacoDireita - METADE_LARGURA_MIN;
  const raioMaxAcima = espacoAcima - METADE_ALTURA_NODE;
  const raioMaxAbaixo = espacoAbaixo - METADE_ALTURA_NODE;

  // raio "ideal" pro visual pretendido (módulos flutuando fora do anel
  // externo) - só é usado se a tela tiver espaço de sobra pra isso
  const tamanhoBase = Math.min(wrapRect.width, wrapRect.height) || 320;
  const fracaoExpandida = itens.length > 9 ? 0.52 : 0.5;
  const raioIdeal = (tamanhoBase / 2) * (1 + fracaoExpandida);
  const RAIO_MINIMO_ALVO = 150; // espalhamento mínimo desejado, quando cabe

  // teto por direção - cada lado da tela tem seu próprio limite real (a
  // barra lateral come espaço à esquerda, o texto de voz/dica come espaço
  // abaixo etc.) então o alvo de cada direção nunca passa do que é seguro
  // NAQUELA direção especificamente, mas também não passa do "ideal" só
  // porque sobra espaço - isso evita um formato espichado sem necessidade
  // em monitores muito largos.
  // nunca deixa o raio-alvo ficar menor que o próprio núcleo "buraco
  // negro" (senão os nós flutuantes ficam por baixo do brilho do núcleo,
  // pouco legíveis) - mas isso ainda respeita o teto de segurança acima
  const hubCenterEl = wrapEl.querySelector(".hub-center");
  const raioNucleo = hubCenterEl
    ? Math.max(hubCenterEl.getBoundingClientRect().width, hubCenterEl.getBoundingClientRect().height) / 2
    : 0;
  const raioAlvo = (limiteDaDirecao) => Math.min(limiteDaDirecao, Math.max(raioIdeal, RAIO_MINIMO_ALVO, raioNucleo + 10));
  const raioDir = Math.max(60, raioAlvo(raioMaxDireita));
  const raioEsq = Math.max(60, raioAlvo(raioMaxEsquerda));
  const raioBaixo = Math.max(60, raioAlvo(raioMaxAbaixo));
  const raioCima = Math.max(60, raioAlvo(raioMaxAcima));

  const anguloInicial = -Math.PI / 2; // primeiro nó no topo
  container.innerHTML = "";

  // paleta de cores da marca ciclada nos nós - cada módulo com uma cor,
  // visual mais tecnológico/vibrante do que um único tom uniforme
  const CORES_NODOS = ["--accent", "--info", "--teal", "--support", "--critico", "--medio"];

  // ---- distribuição por comprimento de arco real, não por ângulo ----
  // Espaçar os nós por ângulo bruto ao redor de uma curva assimétrica (o
  // caso comum, já que o espaço disponível não é igual nos 4 lados) faz
  // com que eles se espremam bem nos pontos onde a curva "anda pouco por
  // grau" - foi exatamente aí que a colisão de rótulos apareceu nos
  // testes. Por isso amostramos a curva e distribuímos os nós por FRAÇÃO
  // REAL DE DISTÂNCIA percorrida, o que os mantém uniformemente espaçados
  // de verdade, seja qual for o formato resultante da tela.
  function raioNaDirecao(ang) {
    const cx = Math.cos(ang);
    const sy = Math.sin(ang);
    return { rx: cx >= 0 ? raioDir : raioEsq, ry: sy >= 0 ? raioBaixo : raioCima };
  }
  const N_AMOSTRAS = 480;
  const amostras = [];
  for (let k = 0; k <= N_AMOSTRAS; k++) {
    const ang = anguloInicial + (k / N_AMOSTRAS) * 2 * Math.PI;
    const { rx, ry } = raioNaDirecao(ang);
    amostras.push({ x: Math.cos(ang) * rx, y: Math.sin(ang) * ry });
  }
  const acumulado = [0];
  for (let k = 1; k <= N_AMOSTRAS; k++) {
    const dx = amostras[k].x - amostras[k - 1].x;
    const dy = amostras[k].y - amostras[k - 1].y;
    acumulado.push(acumulado[k - 1] + Math.sqrt(dx * dx + dy * dy));
  }
  const comprimentoTotal = acumulado[N_AMOSTRAS] || 1;
  function posicaoPorFracao(fracao) {
    const alvo = fracao * comprimentoTotal;
    let lo = 0, hi = N_AMOSTRAS;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (acumulado[mid] < alvo) lo = mid + 1; else hi = mid;
    }
    return amostras[lo];
  }
  const posicoes = itens.map((_, i) => posicaoPorFracao(i / itens.length));

  // largura do rótulo baseada na MENOR distância real entre nós vizinhos
  // (garante que nenhum par colide, seja qual for o formato da curva)
  let distanciaMinima = Infinity;
  for (let i = 0; i < posicoes.length; i++) {
    const a = posicoes[i];
    const b = posicoes[(i + 1) % posicoes.length];
    const d = Math.hypot(b.x - a.x, b.y - a.y);
    if (d < distanciaMinima) distanciaMinima = d;
  }
  const larguraNode = Math.max(64, Math.min(150, distanciaMinima * 0.82));
  const fonteNode = Math.max(9.5, Math.min(14, larguraNode / 9));

  itens.forEach((item, i) => {
    const { x, y } = posicoes[i];
    const angulo = (Math.atan2(y, x) * 180) / Math.PI;

    const linha = document.createElement("div");
    linha.className = "hub-node-line";
    const comprimento = Math.sqrt(x * x + y * y);
    linha.style.width = comprimento + "px";
    linha.style.transform = `rotate(${angulo}deg)`;
    linha.style.setProperty("--node-cor", `var(${CORES_NODOS[i % CORES_NODOS.length]})`);
    container.appendChild(linha);

    const node = document.createElement("button");
    node.className = "hub-node";
    node.style.setProperty("--node-cor", `var(${CORES_NODOS[i % CORES_NODOS.length]})`);
    node.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
    node.style.width = larguraNode + "px";
    node.innerHTML = `<span class="hub-node-dot"></span><span class="hub-node-label" style="font-size:${fonteNode}px">${item.label}</span>`;
    node.addEventListener("click", () => mostrarView(item.view));
    container.appendChild(node);
  });
}

// recalcula o raio dos nós quando a janela é redimensionada, só se o hub
// estiver visível agora (evita trabalho desnecessário nas outras telas)
let _atlasHubResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(_atlasHubResizeTimer);
  _atlasHubResizeTimer = setTimeout(() => {
    const viewHub = document.getElementById("view-hub");
    if (viewHub && !viewHub.classList.contains("hidden")) renderizarHub();
  }, 150);
});

// ---------- apresentação formal dos módulos (voz do "J.A.R.V.I.S.", trocado
// do tom "Exterminador do Futuro" a pedido do Maurício em 13/08/2026 - uma
// única vez por sessão de navegador - sessionStorage some ao fechar a aba)
// ----------
const ATLAS_APRESENTACAO_MODULOS = {
  dashboard: { frase: "Painel principal ativado. Todos os indicadores à sua disposição, senhor.", resumo: "Visão consolidada dos principais indicadores do sistema em tempo real." },
  lista: { frase: "Localizei as divergências, senhor. Já tenho os detalhes prontos para análise.", resumo: "Lista e trata inconsistências encontradas entre registros e contagens." },
  "cobertura-conferencia": { frase: "A cobertura da conferência está sob controle, como sempre.", resumo: "Percentual de itens já conferidos no processo de inventário." },
  importar: { frase: "Dados recebidos e processados com sucesso, senhor.", resumo: "Envia planilhas e arquivos externos para dentro do sistema Atlas." },
  "fechamento-dashboard": { frase: "Acompanhando o fechamento do inventário de perto.", resumo: "Painel com o status geral do inventário em andamento." },
  "acuracia-ponderada": { frase: "Calculando a precisão com toda a atenção que o senhor exige.", resumo: "Mede a exatidão do inventário considerando o peso de cada item." },
  compras: { frase: "Pedidos de compra sob monitoramento constante, senhor.", resumo: "Acompanha pedidos, entradas e status das compras." },
  fechamentos: { frase: "Fechamento consolidado. Tudo em ordem, senhor.", resumo: "Consolida e encerra oficialmente o ciclo de inventário atual." },
  "pos-inventario": { frase: "A análise não termina na contagem, senhor - eu cuido do que vem depois.", resumo: "Análises e ações realizadas após o encerramento do inventário." },
  cadastros: { frase: "As bases de dados estão organizadas e sob meus cuidados.", resumo: "Cadastro e manutenção das informações base do sistema." },
  auditoria: { frase: "Todo registro devidamente arquivado. Nada escapa à auditoria, senhor.", resumo: "Histórico completo de ações e alterações realizadas no sistema." },
  usuarios: { frase: "Acessos e permissões, tudo sob controle, senhor.", resumo: "Gestão de contas, permissões e acessos dos usuários do sistema." },
  "relatorio-baixa": { frase: "Baixas rastreadas com precisão. Nenhum descarte passa sem registro.", resumo: "Baixas operacionais importadas do Lovable e seu cruzamento com divergências." },
};

function _atlasModulosJaApresentados() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem("atlas_modulos_apresentados") || "[]"));
  } catch (e) {
    return new Set();
  }
}

// escolhe, entre as vozes disponíveis no navegador, uma em português - a
// lista de vozes carrega de forma assíncrona em alguns navegadores, então
// isso pode retornar vazio na primeiríssima chamada (nesse caso o
// utterance ainda funciona, só usa a voz padrão do sistema pro lang pt-BR)
//
// (13/08/2026) Antes esta função só pegava a PRIMEIRA voz pt-* encontrada -
// isso significa que, se o navegador só expõe uma única voz em português
// (o caso mais comum no Chrome, que normalmente só traz "Google português
// do Brasil"), ajustar pitch/rate no falarResumoModulo() não muda o timbre
// de verdade: o Chrome ignora o parâmetro "pitch" pras vozes de rede do
// Google (limitação conhecida do navegador, não um bug daqui) - então a voz
// continuava parecendo a mesma de antes, por mais que a fala/pitch/rate no
// código tivessem mudado. Agora a função tenta ativamente achar uma voz
// DIFERENTE da primeira (de preferência masculina/mais grave, no clima
// "mordomo educado" do J.A.R.V.I.S.) quando o navegador tiver mais de uma
// opção em português - e loga no console quantas vozes existem, pra dar
// pra confirmar rapidamente (F12 → Console) se a limitação é essa.
const _NOMES_VOZ_PREFERIDOS = [
  "jarvis", "daniel", "antonio", "antônio", "ricardo", "felipe", "fabio", "fábio",
  "duarte", "male", "homem", "masculin",
];

function _atlasEscolherVoz() {
  if (!("speechSynthesis" in window)) return null;
  const vozes = window.speechSynthesis.getVoices();
  const vozesPt = vozes.filter((v) => v.lang && v.lang.toLowerCase().startsWith("pt"));
  if (!vozesPt.length) return null;

  if (!window.__atlasVozesLogadas) {
    window.__atlasVozesLogadas = true;
    console.info(
      `Atlas: ${vozesPt.length} voz(es) em português encontrada(s) neste navegador -`,
      vozesPt.map((v) => `${v.name} (${v.lang}${v.localService ? ", local" : ", rede"})`)
    );
    if (vozesPt.length === 1) {
      console.info(
        "Atlas: como só há uma voz em português disponível, a troca de timbre fica limitada ao que pitch/rate conseguem mudar - " +
        "e o Chrome costuma ignorar 'pitch' em vozes de rede do Google. Pra uma voz de fato diferente, seria preciso um serviço de TTS externo."
      );
    }
  }

  // (13/08/2026) reordenado pra priorizar SEMPRE uma voz LOCAL primeiro -
  // é a única forma de o ajuste de pitch (tom mais grave, ver
  // falarResumoModulo) realmente funcionar; nas vozes DE REDE do Google o
  // Chrome ignora "pitch" por completo, então escolher uma delas mesmo que
  // o nome combine (ex: "Google português - Ricardo") não ajuda em nada.
  const combina = (v) => _NOMES_VOZ_PREFERIDOS.some((nome) => v.name.toLowerCase().includes(nome));

  const localComNome = vozesPt.find((v) => v.localService && combina(v));
  if (localComNome) return localComNome;

  const local = vozesPt.find((v) => v.localService);
  if (local) return local;

  const redeComNome = vozesPt.find(combina);
  if (redeComNome) return redeComNome;

  return vozesPt[0];
}

// ---------- conversão de valores em R$ pro extenso, em português (13/08/2026) ----------
// O SpeechSynthesis do navegador lê "R$ 114752.69" caractere a caractere (a
// letra R, o nome "cifrão", cada dígito solto, e o ponto decimal como se
// fosse vírgula) em vez de como um valor em dinheiro. Esta função troca todo
// trecho "R$ <número>" do texto por extenso ANTES de mandar pra fala, ex:
// "R$ 114752.69" -> "cento e quatorze mil, setecentos e cinquenta e dois
// reais e sessenta e nove centavos" - e "R$ -75.00" -> "menos setenta e
// cinco reais". Cobre tanto o formato puro do backend (":.2f", ponto como
// decimal, sem separador de milhar) quanto o formato de exibição
// pt-BR ("114.752,69", ponto como milhar e vírgula como decimal).
const _EXTENSO_UNIDADES = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"];
const _EXTENSO_DEZ_A_DEZENOVE = ["dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"];
const _EXTENSO_DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"];
const _EXTENSO_CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"];

function _extensoGrupo(n) {
  // n entre 0 e 999
  if (n === 0) return "";
  if (n === 100) return "cem";
  const centena = Math.floor(n / 100);
  const resto = n % 100;
  const partes = [];
  if (centena > 0) partes.push(_EXTENSO_CENTENAS[centena]);
  if (resto > 0) {
    if (resto < 10) partes.push(_EXTENSO_UNIDADES[resto]);
    else if (resto < 20) partes.push(_EXTENSO_DEZ_A_DEZENOVE[resto - 10]);
    else {
      const dezena = Math.floor(resto / 10);
      const unidade = resto % 10;
      partes.push(unidade === 0 ? _EXTENSO_DEZENAS[dezena] : `${_EXTENSO_DEZENAS[dezena]} e ${_EXTENSO_UNIDADES[unidade]}`);
    }
  }
  return partes.join(" e ");
}

function _numeroExtenso(nAbsoluto) {
  const n = Math.round(nAbsoluto);
  if (n === 0) return "zero";

  const bilhoes = Math.floor(n / 1e9);
  const milhoes = Math.floor((n % 1e9) / 1e6);
  const milhares = Math.floor((n % 1e6) / 1e3);
  const centena = n % 1000;

  const grupos = [];
  if (bilhoes > 0) grupos.push(`${_extensoGrupo(bilhoes)} ${bilhoes === 1 ? "bilhão" : "bilhões"}`);
  if (milhoes > 0) grupos.push(`${_extensoGrupo(milhoes)} ${milhoes === 1 ? "milhão" : "milhões"}`);
  if (milhares > 0) grupos.push(milhares === 1 ? "mil" : `${_extensoGrupo(milhares)} mil`);
  if (centena > 0) grupos.push(_extensoGrupo(centena));

  return grupos.join(", ");
}

function _parseValorMonetario(bruto) {
  let s = bruto.trim();
  let negativo = false;
  if (s.startsWith("-")) {
    negativo = true;
    s = s.slice(1);
  }
  // formato de exibição pt-BR ("114.752,69") - "." é milhar, "," é decimal
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  const valor = parseFloat(s);
  return negativo ? -valor : valor;
}

function _valorMonetarioExtenso(bruto) {
  const valor = _parseValorMonetario(bruto);
  if (Number.isNaN(valor)) return bruto; // não reconheceu o número - devolve como veio, sem quebrar a frase
  const negativo = valor < 0;
  const absValor = Math.abs(valor);
  const inteiro = Math.floor(absValor);
  const centavos = Math.round((absValor - inteiro) * 100);

  const inteiroExtenso = inteiro === 0 ? "zero" : _numeroExtenso(inteiro);
  const unidadeReal = inteiro === 1 ? "real" : "reais";
  let resultado = `${negativo ? "menos " : ""}${inteiroExtenso} ${unidadeReal}`;
  if (centavos > 0) {
    const unidadeCentavo = centavos === 1 ? "centavo" : "centavos";
    resultado += ` e ${_numeroExtenso(centavos)} ${unidadeCentavo}`;
  }
  return resultado;
}

function prepararTextoParaNarracao(texto) {
  // "-?\d+(?:[.,]\d+)*" - cada separador (. ou ,) só entra no número se for
  // seguido de dígito; assim um ponto final de frase logo depois do valor
  // (ex: "R$ 50.00. Das divergências...") não é engolido junto com o número.
  return texto.replace(/R\$\s?(-?\d+(?:[.,]\d+)*)/g, (_match, numero) => _valorMonetarioExtenso(numero));
}

// (13/08/2026) "voz mais robótica": quebra o texto em pedaços curtos (por
// vírgula/ponto/ponto-e-vírgula/travessão, sempre que vier seguido de
// espaço) e fala cada pedaço como uma frase SEPARADA, em sequência. O
// SpeechSynthesisUtterance não dá nenhum controle sobre a entonação
// (prosódia) DENTRO de uma fala longa - isso fica por conta do motor de voz
// do navegador, que naturalmente arredonda a curva melódica de uma frase
// inteira, soando "humano" demais mesmo com pitch baixo. Falando pedaço por
// pedaço, cada trecho sai com entonação mais "reta"/segmentada (sem a
// melodia de uma frase inteira), e a pausa curta entre eles reforça a
// cadência de robô lendo uma lista, em vez de alguém contando uma história.
// Evita quebrar em hífen simples de propósito (ex: "CD-01", "pós-inventário"
// não podem virar dois pedaços por engano).
function _dividirEmPedacosParaFala(texto) {
  return texto
    .split(/(?<=[.,;:—])\s+/)
    .map((p) => p.trim())
    .filter(Boolean);
}

// ---------- efeitos sonoros "tecnológicos" (13/08/2026) ----------
// Dois efeitos pedidos: um "pensamento tecnológico" (bipe de escaneamento
// antes de falar) e um eco. Os dois são sintetizados na hora via Web Audio
// API - sem precisar de nenhum arquivo .mp3/.wav - e o eco é um efeito de
// áudio DE VERDADE (delay com realimentação, não um truque visual).
//
// IMPORTANTE - por que o eco não é na VOZ em si: o SpeechSynthesis do
// navegador (usado pra falar os resumos) não expõe o áudio que produz pra
// nenhuma API - não tem como pegar esse som e passar por um efeito de eco/
// reverb, porque o navegador nunca entrega esse fluxo de áudio pra gente,
// só toca ele direto na saída de som. Por isso o eco aqui é aplicado a um
// SOM PRÓPRIO (um "tom de confirmação" tocado no fim da narração) em vez de
// ecoar as palavras faladas - tecnicamente honesto e ainda dá o clima
// desejado de "eco tecnológico" encerrando a fala. Pra ecoar a voz de
// verdade, a fala precisaria ser gerada no servidor (arquivo de áudio) em
// vez do navegador falar sozinho - mesma limitação já conversada sobre
// trocar a voz.
let _atlasAudioCtx = null;
function _obterAudioCtx() {
  const AudioContextClasse = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClasse) return null;
  if (!_atlasAudioCtx) _atlasAudioCtx = new AudioContextClasse();
  if (_atlasAudioCtx.state === "suspended") _atlasAudioCtx.resume().catch(() => {});
  return _atlasAudioCtx;
}

// monta uma "linha de eco" reutilizável (delay + realimentação, que é o que
// cria as repetições cada vez mais fracas) já ligada na saída de som -
// qualquer som conectado nela sai com cauda de eco.
function _criarLinhaDeEco(ctx, delaySegundos, realimentacaoGanho, volumeEco) {
  const delay = ctx.createDelay();
  delay.delayTime.value = delaySegundos;
  const realimentacao = ctx.createGain();
  realimentacao.gain.value = realimentacaoGanho; // < 1 sempre - senão o eco nunca se esvai (loop infinito)
  const wet = ctx.createGain();
  wet.gain.value = volumeEco;
  delay.connect(realimentacao);
  realimentacao.connect(delay);
  delay.connect(wet);
  wet.connect(ctx.destination);
  return delay;
}

// "pensamento tecnológico": 3 bipes curtos e ascendentes (clima de HUD/
// escaneamento, tipo Jarvis "processando") - tocado logo ANTES do Atlas
// começar a falar um resumo.
function tocarEfeitoPensamento() {
  const ctx = _obterAudioCtx();
  if (!ctx) return;
  const agora = ctx.currentTime;
  const linhaEco = _criarLinhaDeEco(ctx, 0.16, 0.32, 0.35);

  [420, 620, 900].forEach((freq, i) => {
    const inicio = agora + i * 0.09;
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, inicio);
    osc.frequency.exponentialRampToValueAtTime(freq * 1.4, inicio + 0.07);

    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0, inicio);
    envelope.gain.linearRampToValueAtTime(0.16, inicio + 0.012);
    envelope.gain.exponentialRampToValueAtTime(0.001, inicio + 0.11);

    osc.connect(envelope);
    envelope.connect(ctx.destination);
    envelope.connect(linhaEco);
    osc.start(inicio);
    osc.stop(inicio + 0.13);
  });
}

// "eco tecnológico": um tom único, descendente, tocado no FIM da narração -
// a cauda de eco (repetições cada vez mais fracas) é o que dá o efeito de
// eco pedido.
function tocarEfeitoEco() {
  const ctx = _obterAudioCtx();
  if (!ctx) return;
  const agora = ctx.currentTime;
  const linhaEco = _criarLinhaDeEco(ctx, 0.22, 0.45, 0.55);

  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(720, agora);
  osc.frequency.exponentialRampToValueAtTime(360, agora + 0.35);

  const envelope = ctx.createGain();
  envelope.gain.setValueAtTime(0, agora);
  envelope.gain.linearRampToValueAtTime(0.16, agora + 0.02);
  envelope.gain.exponentialRampToValueAtTime(0.001, agora + 0.4);

  osc.connect(envelope);
  envelope.connect(ctx.destination);
  envelope.connect(linhaEco);
  osc.start(agora);
  osc.stop(agora + 0.45);
}

function falarResumoModulo(texto) {
  if (!("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel(); // corta qualquer fala anterior em andamento
    tocarEfeitoPensamento();
    const voz = _atlasEscolherVoz();
    const pedacos = _dividirEmPedacosParaFala(prepararTextoParaNarracao(texto));
    if (!pedacos.length) return;

    let indice = 0;
    function falarProximoPedaco() {
      if (indice >= pedacos.length) {
        tocarEfeitoEco(); // eco de encerramento, só depois do ÚLTIMO pedaço
        return;
      }
      const fala = new SpeechSynthesisUtterance(pedacos[indice]);
      fala.lang = "pt-BR";
      // "rate" é respeitado por praticamente todas as vozes - já "pitch"
      // costuma ser IGNORADO pelo Chrome nas vozes de rede do Google (a mais
      // comum de existir em português), por isso _atlasEscolherVoz() acima
      // prioriza achar uma voz LOCAL do sistema (só nelas o pitch baixo
      // funciona de verdade - ver aviso no console/F12 se a voz do seu
      // navegador for só de rede). Cadência mais firme/constante (rate 1, em
      // vez do "mordomo lento" de antes) + tom BEM mais grave (pitch 0.6) -
      // clima de robô, não de mordomo educado.
      fala.rate = 1.0;
      fala.pitch = 0.6;
      if (voz) fala.voice = voz;
      fala.onend = () => {
        indice++;
        setTimeout(falarProximoPedaco, 80); // pausa curta entre pedaços - reforça a cadência mecânica/segmentada
      };
      fala.onerror = () => {
        indice++;
        falarProximoPedaco();
      };
      window.speechSynthesis.speak(fala);
    }
    setTimeout(falarProximoPedaco, 420); // dá tempo do efeito de "pensando" tocar antes da voz começar
  } catch (e) {
    console.warn("Atlas: não consegui falar o resumo do módulo.", e);
  }
}

function apresentarModuloSeNecessario(view) {
  const info = ATLAS_APRESENTACAO_MODULOS[view];
  if (!info) return;
  const apresentados = _atlasModulosJaApresentados();
  if (apresentados.has(view)) return; // já apresentado nesta sessão - não repete
  apresentados.add(view);
  sessionStorage.setItem("atlas_modulos_apresentados", JSON.stringify([...apresentados]));

  const secao = document.getElementById("view-" + view);
  if (!secao) return;
  const banner = document.createElement("div");
  banner.className = "atlas-apresentacao";
  banner.innerHTML = `<strong>ATLAS:</strong> "${info.frase}" <span class="atlas-apresentacao-resumo">${info.resumo}</span>`;
  secao.prepend(banner);
  setTimeout(() => banner.remove(), 9000);

  falarResumoModulo(`${info.frase} ${info.resumo}`);
}

// ---------- resumo executivo narrado (dashboards de análise) ----------
// Helper reutilizável: monta o painel de resumo executivo (título + botão de
// narração) dentro de um container já existente no HTML, usando texto
// construído a partir dos dados que o próprio loader da tela já buscou -
// sem endpoint novo no backend.
function renderizarResumoExecutivoNarrado(idContainer, textoNarrado) {
  const container = document.getElementById(idContainer);
  if (!container) return;
  container.innerHTML = "";

  const cabecalho = document.createElement("div");
  cabecalho.className = "panel-title-row";

  const titulo = document.createElement("h2");
  titulo.textContent = "📋 Resumo Executivo";

  const botao = document.createElement("button");
  botao.className = "btn-secundario";
  botao.textContent = "🔊 Narrar";
  botao.addEventListener("click", () => falarResumoModulo(textoNarrado));

  cabecalho.appendChild(titulo);
  cabecalho.appendChild(botao);

  const paragrafo = document.createElement("p");
  paragrafo.className = "panel-sub";
  paragrafo.style.lineHeight = "1.6";
  paragrafo.textContent = textoNarrado;

  container.appendChild(cabecalho);
  container.appendChild(paragrafo);
}

function construirResumoExecutivoDashboard(kpis, causas) {
  const abertas = kpis.divergencias_abertas || 0;
  const investigacao = kpis.em_investigacao || 0;
  const resolvidas = kpis.resolvidas || 0;
  const taxa = kpis.taxa_acerto_modelo_pct != null ? `${kpis.taxa_acerto_modelo_pct}%` : "ainda não calculada";
  const causaPrincipal = [...(causas || [])].sort((a, b) => b.quantidade - a.quantidade)[0];

  let texto = `No recorte atual, o Atlas está acompanhando ${abertas} divergência${abertas === 1 ? "" : "s"} em aberto, `;
  texto += `${investigacao} em investigação e ${resolvidas} já resolvida${resolvidas === 1 ? "" : "s"}. `;
  texto += `O valor total em aberto soma ${formatarMoeda(kpis.valor_total_em_aberto)}. `;
  texto += `A taxa de acerto do modelo de classificação está em ${taxa}. `;
  if (causaPrincipal) {
    texto += `A causa mais frequente identificada foi "${rotulo(causaPrincipal.hipotese)}", com ${causaPrincipal.quantidade} ocorrência${causaPrincipal.quantidade === 1 ? "" : "s"} registrada${causaPrincipal.quantidade === 1 ? "" : "s"}.`;
  }
  return texto.trim();
}

function construirResumoExecutivoCobertura(lista, coberturaMedia, semNenhumaConferencia, comFuroAtivo, maiorFuroGeral, semDadosCount) {
  const totalAlmox = lista.length;
  let texto = `Entre os ${totalAlmox} almoxarifado${totalAlmox === 1 ? "" : "s"} monitorados, a cobertura média de conferência está em ${coberturaMedia != null ? coberturaMedia + "%" : "ainda não calculada"}. `;
  texto += semNenhumaConferencia > 0
    ? `${semNenhumaConferencia} almoxarifado${semNenhumaConferencia === 1 ? "" : "s"} ainda não teve nenhuma conferência registrada. `
    : `Todos os almoxarifados com dados já tiveram ao menos uma conferência. `;
  if (comFuroAtivo > 0) {
    texto += `${comFuroAtivo} almoxarifado${comFuroAtivo === 1 ? "" : "s"} ${comFuroAtivo === 1 ? "está" : "estão"} com furo ativo agora, três dias ou mais sem conferência. `;
  }
  texto += `O maior furo já registrado foi de ${maiorFuroGeral} dia${maiorFuroGeral === 1 ? "" : "s"}. `;
  if (semDadosCount > 0) {
    texto += `${semDadosCount} almoxarifado${semDadosCount === 1 ? "" : "s"} ainda não ${semDadosCount === 1 ? "tem" : "têm"} dados suficientes de movimentação pra calcular a cobertura.`;
  }
  return texto.trim();
}

function construirResumoExecutivoFechamento(k) {
  const acuracia = k.acuracia_geral_pct != null ? k.acuracia_geral_pct + "%" : "ainda não calculada";
  const skusAcima95 = k.pct_skus_acima_95 != null ? k.pct_skus_acima_95 + "%" : "—";
  let texto = `O fechamento avaliou ${k.total_itens} ${k.total_itens === 1 ? "item" : "itens"}, dos quais ${k.total_divergentes} apresentaram divergência. `;
  texto += `A acurácia geral do período foi de ${acuracia}, com ${skusAcima95} dos SKUs acima de 95% de acerto. `;
  texto += `O déficit por faltas somou ${formatarMoeda(k.deficit_faltas)}, resultando num resultado líquido de ${formatarMoeda(k.resultado_liquido)}.`;
  return texto.trim();
}

function construirResumoExecutivoAcuraciaPonderada(c) {
  let texto = `A acurácia item a item está em ${c.item_a_item_pct != null ? c.item_a_item_pct + "%" : "—"}. `;
  texto += `Quando ponderada por quantidade, o IAQ resulta em ${c.iaq_pct != null ? c.iaq_pct + "%" : "—"}, `;
  texto += `e quando ponderada por valor financeiro, o IAP resulta em ${c.iap_pct != null ? c.iap_pct + "%" : "sem cobertura de custo suficiente para o cálculo"}. `;
  if (c.gap_item_vs_iap_pp != null) {
    const diferenca = Math.abs(c.gap_item_vs_iap_pp);
    const direcao = c.gap_item_vs_iap_pp > 0 ? "subestimava" : "sobrestimava";
    texto += `Isso mostra que o modelo item a item ${direcao} a real acurácia em ${diferenca} ${diferenca === 1 ? "ponto percentual" : "pontos percentuais"}, na comparação com o valor financeiro em risco.`;
  }
  return texto.trim();
}

function construirResumoExecutivoCompras(k) {
  let texto = `O Atlas está acompanhando ${k.total_pedidos} pedido${k.total_pedidos === 1 ? "" : "s"} de compra, sendo ${k.pedidos_abertos} em aberto. `;
  texto += k.pedidos_atrasados > 0
    ? `${k.pedidos_atrasados} pedido${k.pedidos_atrasados === 1 ? "" : "s"} ${k.pedidos_atrasados === 1 ? "está" : "estão"} atrasado${k.pedidos_atrasados === 1 ? "" : "s"} em relação ao prazo previsto. `
    : `Nenhum pedido está atrasado no momento. `;
  texto += `A quantidade pendente de recebimento soma ${(k.itens_pendentes_qtd || 0).toLocaleString("pt-BR")} unidades.`;
  return texto.trim();
}

function construirResumoExecutivoPosInventario(acoes) {
  const total = acoes.length;
  if (total === 0) return "Nenhuma ação de acompanhamento foi registrada ainda neste período.";

  const pendentes = acoes.filter((a) => a.status === "Pendente").length;
  const emAndamento = acoes.filter((a) => a.status === "Em_Andamento").length;
  const concluidas = acoes.filter((a) => a.status === "Concluida").length;
  const canceladas = acoes.filter((a) => a.status === "Cancelada").length;
  const automaticas = acoes.filter((a) => a.origem_automatica).length;
  const hoje = new Date().toISOString().slice(0, 10);
  const atrasadas = acoes.filter((a) => a.prazo && a.prazo < hoje && a.status !== "Concluida" && a.status !== "Cancelada").length;

  let texto = `Há ${total} ${total === 1 ? "ação" : "ações"} de acompanhamento registrada${total === 1 ? "" : "s"}, sendo ${pendentes} pendente${pendentes === 1 ? "" : "s"}, ${emAndamento} em andamento e ${concluidas} concluída${concluidas === 1 ? "" : "s"}`;
  texto += canceladas > 0 ? ` e ${canceladas} cancelada${canceladas === 1 ? "" : "s"}. ` : ". ";
  if (atrasadas > 0) {
    texto += `${atrasadas} ${atrasadas === 1 ? "ação está" : "ações estão"} com o prazo vencido. `;
  }
  if (automaticas > 0) {
    texto += `${automaticas} dessas ações ${automaticas === 1 ? "foi criada" : "foram criadas"} automaticamente pelo Atlas, a partir da reconciliação.`;
  }
  return texto.trim();
}

// ---------- comando de voz (navegação por fala) ----------
const HUB_PALAVRAS_CHAVE_POR_VIEW = {
  hub: ["início", "inicio", "hub", "home"],
  dashboard: ["painel de divergências", "painel", "divergências abertas"],
  lista: ["divergências", "lista de divergências", "divergência"],
  "cobertura-conferencia": ["cobertura de conferência", "cobertura", "conferência"],
  importar: ["importar", "importação", "importa"],
  "fechamento-dashboard": ["painel inventário", "painel de inventário", "painel do inventário"],
  "acuracia-ponderada": ["acurácia ponderada", "acurácia"],
  compras: ["controle de compras", "compras", "pedido de compra"],
  fechamentos: ["fechamento inventário", "fechamento de inventário", "fechamento"],
  "pos-inventario": ["pós-inventário", "pós inventário", "pos inventario"],
  cadastros: ["cadastros", "cadastro"],
  auditoria: ["auditoria"],
  usuarios: ["usuários", "usuarios"],
  "relatorio-baixa": ["relatório de baixa", "relatorio de baixa", "relatório de baixas", "baixas operacionais", "baixa operacional"],
};

function _normalizarTextoVoz(txt) {
  return txt
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

// remove a palavra de ativa\u00e7\u00e3o "atlas" do in\u00edcio da frase, se houver -
// permite comandos no formato "Atlas, cadastro" al\u00e9m de dizer s\u00f3 o nome
// do m\u00f3dulo direto (ex: "cadastro")
function _removerPalavraDeAtivacao(alvoNormalizado) {
  return alvoNormalizado.replace(/^(e[ai]?\s+)?atlas[,\s]*/, "").trim();
}

function _acharViewPorVoz(transcricao) {
  const alvo = _removerPalavraDeAtivacao(_normalizarTextoVoz(transcricao));
  let melhorView = null;
  let melhorTamanho = 0;
  for (const [view, palavras] of Object.entries(HUB_PALAVRAS_CHAVE_POR_VIEW)) {
    for (const palavra of palavras) {
      const p = _normalizarTextoVoz(palavra);
      if (alvo.includes(p) && p.length > melhorTamanho) {
        melhorView = view;
        melhorTamanho = p.length;
      }
    }
  }
  return melhorView;
}

// Chamado de dentro de mostrarApp() (depois do login) - não antes, pra não
// ligar o microfone ainda na tela de login. Definido fora da função de
// configuração pra existir mesmo se o navegador não suportar reconhecimento
// de voz (nesse caso é só um no-op).
window.ativarEscutaAtlasSeNecessario = function () {};

function configurarComandoDeVoz() {
  const btn = document.getElementById("hub-mic-btn");
  const status = document.getElementById("hub-voice-status");
  const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!Reconhecimento) {
    btn.disabled = true;
    btn.title = "Comando de voz não é suportado neste navegador (funciona no Chrome e Edge)";
    btn.style.opacity = "0.35";
    return;
  }

  // Modo "sempre ouvindo": LIGADO POR PADRÃO desde a primeira vez que o
  // Atlas é aberto (não precisa clicar no microfone pra ativar) - fica
  // escutando em qualquer tela e só age quando ouve a palavra de ativação
  // "Atlas" antes do nome do módulo (evita disparar sozinho numa conversa
  // qualquer perto do computador). O botão de microfone serve só pra
  // DESLIGAR, se alguém quiser - e essa preferência de desligado é que
  // fica salva entre visitas (o padrão é sempre ligado).
  const CHAVE_DESATIVADO = "atlas_voz_continua_desativada";
  let escutaContinuaDesejada = localStorage.getItem(CHAVE_DESATIVADO) !== "1";
  let reconhecimento = null;
  let paradaIntencional = false;
  let reiniciarTimer = null;

  function _criarReconhecimento() {
    const r = new Reconhecimento();
    r.lang = "pt-BR";
    r.continuous = true;
    r.interimResults = false;

    r.addEventListener("start", () => {
      btn.classList.add("escutando");
      btn.title = 'Sempre ouvindo - diga "Atlas, [nome do módulo]" (clique pra desligar)';
      status.textContent = '🎤 Sempre ouvindo... diga "Atlas" e o nome do módulo, em qualquer tela.';
    });

    r.addEventListener("end", () => {
      btn.classList.remove("escutando");
      // o navegador corta a escuta contínua de tempos em tempos (silêncio
      // prolongado, limite interno, etc) - reinicia sozinho pra manter
      // "sempre ouvindo" sem precisar clicar de novo, a menos que o
      // desligamento tenha sido intencional (clique no botão) ou a
      // permissão de microfone tenha sido negada.
      if (escutaContinuaDesejada && !paradaIntencional) {
        clearTimeout(reiniciarTimer);
        reiniciarTimer = setTimeout(_iniciar, 400);
      }
      paradaIntencional = false;
    });

    r.addEventListener("result", (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const resultado = ev.results[i];
        if (!resultado.isFinal) continue;
        const transcricao = resultado[0].transcript;
        const alvoNormalizado = _normalizarTextoVoz(transcricao);
        const ouviuPalavraDeAtivacao = _removerPalavraDeAtivacao(alvoNormalizado) !== alvoNormalizado;
        if (!ouviuPalavraDeAtivacao) continue; // ambiente/conversa normal, sem "Atlas" - ignora

        const view = _acharViewPorVoz(transcricao);
        if (view) {
          status.textContent = `✅ "${transcricao}" → abrindo ${document.querySelector(`.rail-item[data-view="${view}"] .rail-label`)?.textContent || view}`;
          setTimeout(() => mostrarView(view), 400);
        } else {
          status.textContent = `❓ Ouvi "Atlas", mas não reconheci "${transcricao}" como um módulo.`;
        }
        _registrarComandoDeVozNoBanco(transcricao, view);
      }
    });

    r.addEventListener("error", (ev) => {
      if (ev.error === "not-allowed") {
        escutaContinuaDesejada = false;
        localStorage.setItem(CHAVE_DESATIVADO, "1");
        btn.classList.remove("escutando");
        status.textContent = "⚠️ Permissão de microfone negada - autorize o microfone nas configurações do navegador e clique no ícone pra tentar de novo.";
      } else if (ev.error === "no-speech" || ev.error === "aborted") {
        // silêncio prolongado é normal em modo contínuo - o "end" que
        // segue este erro já cuida de reiniciar sozinho.
      } else {
        status.textContent = "⚠️ Erro no reconhecimento de voz: " + ev.error;
      }
    });

    return r;
  }

  function _iniciar() {
    reconhecimento = _criarReconhecimento();
    try {
      reconhecimento.start();
    } catch (e) {
      console.error("Atlas: falha ao iniciar reconhecimento de voz contínuo", e);
    }
  }

  function _parar() {
    paradaIntencional = true;
    clearTimeout(reiniciarTimer);
    if (reconhecimento) reconhecimento.stop();
    btn.classList.remove("escutando");
    btn.title = 'Escuta contínua desligada - clique pra ligar de novo ("Atlas, [módulo]")';
    status.textContent = "🔇 Escuta contínua desligada.";
  }

  btn.addEventListener("click", () => {
    escutaContinuaDesejada = !escutaContinuaDesejada;
    if (escutaContinuaDesejada) {
      localStorage.removeItem(CHAVE_DESATIVADO);
      _iniciar();
    } else {
      localStorage.setItem(CHAVE_DESATIVADO, "1");
      _parar();
    }
  });

  // grava no banco (auditoria) todo comando de voz reconhecido pela
  // palavra de ativação "Atlas" - reconhecido ou não - pra ter
  // rastreabilidade de como o pessoal navega por voz.
  async function _registrarComandoDeVozNoBanco(transcricao, viewDestino) {
    try {
      await apiFetch(`${API}/voz/comando`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcricao, view_destino: viewDestino || null, reconhecido: !!viewDestino }),
      });
    } catch (e) {
      console.warn("Atlas: não consegui registrar o comando de voz no banco.", e);
    }
  }

  // exposto pra mostrarApp() chamar depois do login - é ligado por padrão
  // (a menos que o usuário tenha desligado explicitamente antes).
  window.ativarEscutaAtlasSeNecessario = function () {
    if (escutaContinuaDesejada) _iniciar();
  };
}

configurarComandoDeVoz();

// ---------- PWA: registro do service worker (13/08/2026) ----------
// Só isso já é o suficiente pra Chrome/Android considerar o Atlas
// "instalável" (mostra o banner de instalação sozinho) - no Safari/iPhone
// não existe banner automático, mas o app funciona igual via "Compartilhar"
// → "Adicionar à Tela de Início" (o manifest.json/ícones cuidam da parte
// visual disso). Registra só depois do "load" pra não competir com o
// carregamento inicial da tela por rede/CPU.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((e) => console.warn("Atlas: falha ao registrar o service worker (app não fica instalável, mas continua funcionando normalmente):", e));
  });
}

// ---------- inicialização ----------
inicializarSessao();
