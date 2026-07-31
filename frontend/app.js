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
  const res = await fetch(url, { ...options, headers });
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
  mostrarView("dashboard");
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
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(texto, pos.x + 6, pos.y);
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
  if (nome === "dashboard") carregarDashboard();
  if (nome === "lista") carregarLista();
  if (nome === "usuarios") carregarUsuarios();
  if (nome === "cadastros") carregarAbaCadastroAtiva();
  if (nome === "auditoria") carregarAuditoria();
  if (nome === "importar") carregarLotesImportacao();
  if (nome === "fechamentos") carregarFechamentos();
  if (nome === "fechamento-dashboard") carregarDashboardFechamento();
  if (nome === "acuracia-ponderada") carregarAcuraciaPonderada();
  if (nome === "compras") carregarPedidosCompra();
  if (nome === "pos-inventario") carregarAcoesPosInventario();
}

// ---------- dashboard ----------
let chartAcuraciaDia, chartCausas, chartTendencia, chartMom;

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

  const html = almoxs
    .map((a) => {
      const cells = hipoteses
        .map((h) => {
          const v = valor(a, h);
          const intensidade = v / max;
          const cor = v === 0 ? "#212b30" : mixColor(intensidade);
          return `<div class="heatmap-cell" style="background:${cor}" title="${a} × ${rotulo(h)}: ${v}">${v || ""}</div>`;
        })
        .join("");
      return `<div class="heatmap-row"><div class="row-label">${a}</div><div class="heatmap-cells">${cells}</div></div>`;
    })
    .join("");
  document.getElementById("heatmap").innerHTML = html || "<span style='color:var(--muted)'>Sem dados ainda.</span>";
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
    .map((r) => `<li>${r.almoxarifado} <span class="qtd">${r.quantidade}</span></li>`)
    .join("") || "<li>Sem dados</li>";
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
async function abrirDetalhe(id) {
  const [d, historico] = await Promise.all([
    apiFetch(`${API}/divergencias/${id}`).then((r) => r.json()),
    apiFetch(`${API}/divergencias/${id}/historico-sku`).then((r) => (r.ok ? r.json() : [])),
  ]);
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
        <h2>Histórico do SKU</h2>
        <p class="panel-sub">Quando divergiu e quando estabilizou, e por qual almoxarifado passou</p>
        <canvas id="chart-historico-sku" height="140"></canvas>
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
  mostrarView("detalhe");
}

let chartHistoricoSku;
function renderHistoricoSku(historico) {
  const ctx = document.getElementById("chart-historico-sku");
  if (!ctx) return;
  if (chartHistoricoSku) chartHistoricoSku.destroy();
  if (!historico.length) return;
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
}

const AP_MOM_ROTULOS = { iap_pct: "IAP (valor)", iaq_pct: "IAQ (quantidade)", item_a_item_pct: "Item a item" };
const AP_MOM_VARIACAO_CHAVE = { iap_pct: "variacao_iap_pp", iaq_pct: "variacao_iaq_pp", item_a_item_pct: "variacao_item_pp" };

function renderApMom(dados) {
  apEvolucaoCache = dados;
  const metrica = document.getElementById("ap-mom-metrica").value;
  const chaveVariacao = AP_MOM_VARIACAO_CHAVE[metrica];
  const ctx = document.getElementById("ap-chart-mom");
  if (apChartMom) apChartMom.destroy();
  apChartMom = new Chart(ctx, {
    data: {
      labels: dados.map((d) => d.mes),
      datasets: [
        {
          type: "bar", label: `Acurácia do mês — ${AP_MOM_ROTULOS[metrica]}`, data: dados.map((d) => d[metrica]),
          backgroundColor: dados.map((d) => corFarolAcuracia(d[metrica])), borderRadius: 3, yAxisID: "y",
          formatarRotulo: (v) => (v != null ? v + "%" : "—"),
        },
        {
          type: "line", label: "Variação MoM (pp)", data: dados.map((d) => d[chaveVariacao]), borderColor: "#f9a825",
          backgroundColor: "#f9a825", pointRadius: 4, yAxisID: "y1", spanGaps: true,
          formatarRotulo: (v) => (v == null ? "" : (v > 0 ? "+" : "") + v + " pp"), corRotulo: "#f9a825",
        },
      ],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { color: "#8ca0a3" } } },
      scales: {
        x: { ticks: { color: "#8ca0a3" }, grid: { display: false } },
        y: { position: "left", min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y1: { position: "right", ticks: { color: "#f9a825" }, grid: { display: false } },
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
      plugins: { legend: { display: false } },
      scales: {
        x: { min: 0, max: 112, ticks: { color: "#8ca0a3", callback: (v) => (v <= 100 ? v : "") }, grid: { color: "#2e3a40" } },
        y: { ticks: { color: "#8ca0a3", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
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
    .map((i) => `<tr><td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.ocorrencias}</td><td>${formatarMoeda(i.valor_total)}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhum item recorrente ainda.</td></tr>`;
}

function renderFdImpactoFinanceiro(lista) {
  document.querySelector("#fd-tabela-impacto-financeiro tbody").innerHTML = lista
    .map((i) => `<tr><td>${i.sku}</td><td class="col-descricao">${i.descricao || "—"}</td><td>${i.ocorrencias}</td><td>${formatarMoeda(i.valor_total)}</td></tr>`)
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhum passivo registrado ainda.</td></tr>`;
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
    .join("") || `<tr><td colspan="7" style="color:var(--muted)">Nenhum fechamento importado ainda.</td></tr>`;
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
      const res = await apiFetch(`${API}/fechamentos/${btn.dataset.id}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "Não foi possível excluir."); return; }
      alert(`Removidos: ${data.itens_removidos} item(ns), ${data.divergencias_removidas} divergência(s), ${data.acoes_removidas} ação(ões).`);
      carregarFechamentos();
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

async function carregarCiencia(fechamentoId) {
  const lista = await apiFetch(`${API}/fechamentos/${fechamentoId}/ciencia`).then((r) => r.json());
  document.querySelector("#tabela-ciencia tbody").innerHTML = lista
    .map(
      (c) => `<tr>
        <td>${new Date(c.data_assinatura).toLocaleString("pt-BR")}</td>
        <td>${c.gestor_nome || c.gestor_username}</td>
        <td>${c.total_itens_divergentes}</td>
        <td>${formatarMoeda(c.valor_total_divergente)}</td>
        <td class="col-descricao">${c.observacao || "—"}</td>
        <td><button class="btn-secundario btn-ver-pdf-ciencia" data-id="${c.id}">Ver PDF</button></td>
      </tr>`
    )
    .join("") || `<tr><td colspan="6" style="color:var(--muted)">Nenhuma confirmação de ciência registrada ainda para este fechamento.</td></tr>`;

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
  const btn = document.getElementById("btn-gerar-ciencia");
  const observacao = document.getElementById("ciencia-observacao").value.trim() || null;
  btn.disabled = true;
  btn.textContent = "Gerando...";
  try {
    const res = await apiFetch(`${API}/fechamentos/${fechamentoDetalheAtualId}/ciencia`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ observacao }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Não foi possível gerar a ciência.");
    } else {
      document.getElementById("ciencia-observacao").value = "";
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

document.getElementById("btn-fechar-modal-pedido").addEventListener("click", () => {
  document.getElementById("modal-pedido-overlay").classList.add("hidden");
});
document.getElementById("modal-pedido-overlay").addEventListener("click", (ev) => {
  if (ev.target.id === "modal-pedido-overlay") document.getElementById("modal-pedido-overlay").classList.add("hidden");
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
        <td>
          <button class="btn-secundario btn-editar-almox" data-codigo="${a.codigo}">Editar</button>
          <button class="btn-secundario btn-toggle-almox" data-codigo="${a.codigo}" data-ativo="${a.ativo}">${a.ativo ? "Desativar" : "Ativar"}</button>
          <button class="btn-secundario btn-excluir-almox" data-codigo="${a.codigo}">Excluir</button>
        </td>
      </tr>`
    )
    .join("") || `<tr><td colspan="4" style="color:var(--muted)">Nenhum almoxarifado cadastrado.</td></tr>`;

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

// ---------- inicialização ----------
inicializarSessao();
