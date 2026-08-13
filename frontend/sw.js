// Atlas - service worker mínimo, só pra tornar o app instalável no celular
// (Chrome/Android e, via "Adicionar à Tela de Início", no Safari/iOS) e dar
// uma casca offline básica (a tela abre mesmo com internet ruim - mas os
// dados em si sempre exigem conexão; o Atlas não é um app offline "de
// verdade", só a casca visual funciona sem rede).
//
// Estratégia: "network-first" pros arquivos da casca (HTML/CSS/JS/vendor) -
// SEMPRE tenta buscar a versão mais nova da rede primeiro, e só usa o que
// está em cache se a rede falhar (offline ou servidor fora do ar). De
// propósito mais conservador que "cache-first": o Atlas está em
// desenvolvimento ativo (novas versões saem com frequência via
// atualizar.bat) e um cache desatualizado escondendo uma atualização nova
// seria pior do que não ter cache nenhum. Requisições de API (dados de
// verdade) NUNCA passam pelo cache, sempre vão direto pra rede.
//
// Bump o número da versão abaixo (CACHE_NOME) sempre que a LISTA de
// arquivos da casca mudar de verdade (raro) - não precisa mexer aqui só
// por causa do "?v=" do app.js/style.css, que já tem seu próprio
// cache-busting via query string.
const CACHE_NOME = "atlas-shell-v1";
const ARQUIVOS_CASCA = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./vendor/chart.umd.js",
  "./assets/logo.png",
  "./assets/icon-192.png",
  "./assets/icon-512.png",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches
      .open(CACHE_NOME)
      .then((cache) => cache.addAll(ARQUIVOS_CASCA))
      .catch((e) => console.warn("Atlas SW: falha ao pré-cachear a casca do app:", e))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys().then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE_NOME).map((n) => caches.delete(n))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);

  // nunca intercepta chamadas de API (dados sempre têm que vir da rede, ao
  // vivo) nem requisições que não sejam GET - só a casca estática do app
  // passa pelo cache.
  if (evento.request.method !== "GET" || url.pathname.includes("/api/")) return;

  evento.respondWith(
    fetch(evento.request)
      .then((resposta) => {
        const copia = resposta.clone();
        caches
          .open(CACHE_NOME)
          .then((cache) => cache.put(evento.request, copia))
          .catch(() => {});
        return resposta;
      })
      .catch(() => caches.match(evento.request))
  );
});
