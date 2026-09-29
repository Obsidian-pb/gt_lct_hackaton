/* ============================================================================
 * Тренажёр оператора ДДС «Система-112» — элементарный веб-клиент (прототип)
 * Чистый JS без зависимостей. Общается с REST API backend_new по /api/v1.
 * Открывается как статический HTML даже при погашенном бэкенде:
 * в этом случае страницы показывают сообщение «Сервер недоступен».
 * ========================================================================== */

const DEFAULT_API = "http://127.0.0.1:8000/api/v1";

/* ---------- конфигурация адреса API (хранится в localStorage) ------------- */
function getApiBase() {
  return localStorage.getItem("api_base") || DEFAULT_API;
}
function setApiBase(url) {
  localStorage.setItem("api_base", String(url).replace(/\/+$/, ""));
}

/* ---------- токены и текущий пользователь --------------------------------- */
function getToken() { return localStorage.getItem("access_token"); }
function saveTokens(t) {
  localStorage.setItem("access_token", t.access_token);
  localStorage.setItem("refresh_token", t.refresh_token);
}
function clearAuth() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("me");
}

/* Универсальный вызов REST API. throw Error с человекочитаемым текстом.
 * Если передан json и не указан method — используется POST. */
async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (opts.json !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let res;
  try {
    res = await fetch(getApiBase() + path, {
      ...opts,
      method: opts.method || (opts.json !== undefined ? "POST" : "GET"),
      headers,
      body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
    });
  } catch (e) {
    throw new Error("Сервер недоступен: " + getApiBase() + " (" + (e && e.name ? e.name : e) + ": " + (e && e.message ? e.message : "") + "). Запустите бэкенд и обновите страницу.");
  }
  if (res.status === 401) {
    clearAuth();
    if (!location.pathname.endsWith("index.html")) location.href = "index.html";
    throw new Error("Требуется вход в систему");
  }
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    if (data && typeof data === "object" && data.detail !== undefined) {
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
    throw new Error(detail);
  }
  return data;
}

/* Текущий пользователь (кэш + запрос /auth/me). */
async function me(force = false) {
  const cached = localStorage.getItem("me");
  if (cached && !force) return JSON.parse(cached);
  const user = await api("/auth/me");
  localStorage.setItem("me", JSON.stringify(user));
  return user;
}
function roleCodes(user) {
  return (user.roles || []).map(r => r.code);
}
function hasAny(user, codes) {
  return roleCodes(user).some(c => codes.includes(c));
}
const STAFF = ["system_admin", "admin", "teacher"];
const EDITORS = ["system_admin", "admin", "teacher"];

/* ---------- утилиты отображения ------------------------------------------ */
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c =>
    c === "&" ? "&" + "amp;" :
    c === "<" ? "&" + "lt;" :
    c === ">" ? "&" + "gt;" :
    c === '"' ? "&" + "quot;" : "&#" + "39;");
}
function fmtDate(v) {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d) ? esc(v) : d.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}
function fmtNum(v, digits = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(digits);
}
function fmtJson(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return esc(v);
  return "<pre class=\"json\">" + esc(JSON.stringify(v, null, 2)) + "</pre>";
}
function trunc(s, n = 90) {
  s = String(s ?? "");
  return s.length > n ? esc(s.slice(0, n)) + "…" : esc(s);
}

/* Toast-уведомления */
function toast(msg, kind = "info") {
  let box = document.getElementById("toastBox");
  if (!box) {
    box = document.createElement("div");
    box.id = "toastBox";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

/* Заглушка на время запроса */
let _busyCount = 0;
function busy(on) {
  _busyCount = Math.max(0, _busyCount + (on ? 1 : -1));
  let el = document.getElementById("busy");
  if (!el) {
    el = document.createElement("div");
    el.id = "busy";
    document.body.appendChild(el);
  }
  el.style.display = _busyCount ? "flex" : "none";
}

/* Оборачивает async-действие: busy + обработка ошибок + опциональный success-toast */
async function act(fn, okMsg) {
  busy(true);
  try {
    const r = await fn();
    if (okMsg) toast(okMsg, "ok");
    return r;
  } catch (e) {
    toast(e.message, "err");
    throw e;
  } finally {
    busy(false);
  }
}

/* Построение таблицы из данных. cols: [{key,label,fmt?}] */
function tableEl(cols, rows, emptyText = "Нет данных") {
  const wrap = document.createElement("div");
  wrap.className = "tbl-wrap";
  if (!rows.length) {
    wrap.innerHTML = "<div class='empty'>" + esc(emptyText) + "</div>";
    return wrap;
  }
  let html = "<table><thead><tr>";
  for (const c of cols) html += "<th>" + esc(c.label) + "</th>";
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    for (const c of cols) {
      const v = row[c.key];
      html += "<td>" + (c.fmt ? c.fmt(v, row) : esc(v)) + "</td>";
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
  return wrap;
}

/* Карточка с заголовком и содержимым */
function cardEl(title, body) {
  const div = document.createElement("div");
  div.className = "card";
  div.innerHTML = "<h3>" + esc(title) + "</h3>";
  div.appendChild(body);
  return div;
}

/* Фильтры для списков: одна строка с полями */
function filterBar(fields) {
  const bar = document.createElement("div");
  bar.className = "filter-bar";
  for (const f of fields) {
    const label = document.createElement("span");
    label.textContent = f.label + ": ";
    bar.appendChild(label);
    bar.appendChild(f.el);
  }
  return bar;
}

/* Селект из массива {id,name} с пустым вариантом */
function selectEl(items, placeholder = "— не выбрано —", selected = "") {
  const sel = document.createElement("select");
  sel.innerHTML = "<option value=''>" + esc(placeholder) + "</option>";
  for (const it of items || []) {
    sel.innerHTML += "<option value='" + esc(it.id) + "'" + (String(it.id) === String(selected) ? " selected" : "") + ">" + esc(it.name || it.label || it.title || it.code) + "</option>";
  }
  return sel;
}

/* Список справочников, которые нужны многим страницам */
async function loadDicts() {
  const [services, applicantStatuses, scenarioStatuses, trainingRoles, eventGroups,
         eventTypes, features1, features2, features3] = await Promise.all([
    api("/services").catch(() => []),
    api("/applicant-statuses").catch(() => []),
    api("/scenario-statuses").catch(() => []),
    api("/training-roles").catch(() => []),
    api("/event-groups").catch(() => []),
    api("/classifier/event-types").catch(() => []),
    api("/classifier/features-1").catch(() => []),
    api("/classifier/features-2").catch(() => []),
    api("/classifier/features-3").catch(() => []),
  ]);
  return { services, applicantStatuses, scenarioStatuses, trainingRoles, eventGroups,
           eventTypes, features1, features2, features3 };
}
async function loadUsers() {
  return api("/users").catch(() => []);
}
/* Список обучающихся (роль student): доступен admin и teacher (окно 9 ТЗ) */
async function loadStudents() {
  return api("/users/students").catch(() => []);
}

/* Статусы тренировок/карточек на русском */
const STATUS_LABELS = {
  prepared: "Подготовлена", active: "Активна", finished: "Завершена",
  draft: "Черновик", submitted: "Отправлена", accepted: "Принята",
  routed: "Направлена", processed: "Отработана",
  approved: "Утверждена", pending: "На проверке",
};
function statusLabel(s) { return STATUS_LABELS[s] || s || "—"; }

/* Вставка блока «пользователь + выход» в шапку */
async function renderHeader(activeNav) {
  const nav = document.getElementById("nav");
  if (!nav) return;
  let user = null;
  try { user = await me(); } catch (e) { /* без токена */ }
  const isStaff = user && hasAny(user, STAFF);
  const isAdmin = user && hasAny(user, ["system_admin", "admin"]);

  const links = [
    ["dashboard.html", "Кабинет"],
    isAdmin ? ["users.html", "Пользователи"] : null,
    isAdmin ? ["reference.html", "Справочники"] : null,
    isStaff ? ["tasks.html", "Учебные задачи"] : null,
    isStaff ? ["scenarios.html", "Сценарии"] : null,
    ["trainings.html", "Тренировки"],
    isStaff ? ["cards.html", "Карточки"] : null,
    isStaff ? ["reports.html", "Отчёты"] : null,
    ["materials.html", "Материалы"],
    user && hasAny(user, ["system_admin"]) ? ["system.html", "Система"] : null,
  ].filter(Boolean);

  nav.innerHTML = "<a class='brand' href='index.html'>Тренажёр 112</a>"
    + links.map(([href, label]) =>
        "<a href='" + href + "'" + (href === activeNav ? " class='active'" : "") + ">" + label + "</a>").join("");

  const who = document.getElementById("who");
  if (who) {
    if (user) {
      who.innerHTML = "<span>" + esc(user.last_name + " " + user.first_name)
        + " <small>(" + esc(roleCodes(user).join(", ")) + ")</small></span>"
        + "<button onclick='logout()'>Выход</button>";
    } else {
      who.innerHTML = "<a href='index.html'>Войти</a>";
    }
  }
}

function logout() {
  clearAuth();
  location.href = "index.html";
}

/* Показать ошибку вместо содержимого секции */
function showError(el, err) {
  el.innerHTML = "<div class='err-box'>⚠ " + esc(err && err.message ? err.message : err) + "</div>";
}

/* ============================================================================
 * ИИ-интеграция frontend_new с endpoints backend_new /api/v1 (пункт 2 плана №2)
 * Контракт: backend_new/app/api/v1/ai.py + schemas/ai.py. Ключ провайдера живёт
 * только в ai_service; браузер работает через backend_new.
 * ========================================================================== */

/* Проверка доступности ИИ (мониторинг, system.html) */
async function aiStatus() {
  return api("/system/ai/status");
}

/* Генерация содержимого учебной задачи (tasks.html). Заполняет типизированные
 * поля задачи: сообщение заявителя, адрес, телефоны, флаги. */
async function aiGenerate(taskId, opts = {}) {
  return api("/study-tasks/" + taskId + "/generate", { method: "POST", json: opts });
}

/* Превью эталона: ИИ формирует expected_fields и ЗАПИСЫВАЕТ эталон в задачу.
 * Возвращает {task_id, etalon_content, field_schema, reference}. */
async function aiReferencePreview(taskId, opts = {}) {
  return api("/study-tasks/" + taskId + "/reference-preview", { method: "POST", json: opts });
}

/* Реплика заявителя в мастерской преподавателя (tasks.html). */
async function aiCallerReplyTask(taskId, payload) {
  return api("/study-tasks/" + taskId + "/caller-reply", { method: "POST", json: payload });
}

/* Реплика заявителя в симуляторе обучающегося (simulator.html, карточка). */
async function aiCallerReplyCard(cardId, payload) {
  return api("/cards/" + cardId + "/caller-reply", { method: "POST", json: payload });
}

/* Реплика службы ДДС (исходящий звонок, simulator.html). */
async function aiServiceReply(cardId, payload) {
  return api("/cards/" + cardId + "/service-reply", { method: "POST", json: payload });
}

/* Предварительная оценка ИИ карточки (cards.html, simulator.html). */
async function aiEval(cardId, payload = {}) {
  return api("/cards/" + cardId + "/ai-eval", { method: "POST", json: payload });
}

/* Локальная валидация полей карточки в ИИ-формате (мастерская). */
async function aiValidateFields(taskId, content) {
  return api("/study-tasks/" + taskId + "/validate-fields", { method: "POST", json: { content } });
}

/* ============================================================================
 * Клиентские виджеты (пункт 6 плана №2): голос, баннеры, адрес/карта.
 * Без внешних библиотек; данные — статика в frontend_new/geo и banners/.
 * ========================================================================== */

/* ---------- голосовой ввод (SpeechRecognition) и озвучивание (TTS) ---------- */
function speechSupported() {
  return typeof window !== "undefined" && !!window.speechSynthesis;
}
function recognitionSupported() {
  return typeof window !== "undefined" && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

/* Озвучить текст реплики заявителя/службы (ru-RU). Возвращает true, если озвучено. */
function speak(text) {
  if (!speechSupported()) return false;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(String(text || ""));
    u.lang = "ru-RU";
    u.rate = 1.02;
    u.pitch = 1;
    speechSynthesis.speak(u);
    return true;
  } catch (e) {
    return false;
  }
}
function stopSpeak() {
  if (speechSupported()) { try { speechSynthesis.cancel(); } catch (e) { /* ignore */ } }
}

/* Распознавание речи: onResult(text), onEnd(ok). Возвращает объект rec (null, если не поддержано). */
function listen(onResult, onEnd) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    if (onEnd) onEnd(false);
    return null;
  }
  let rec;
  try { rec = new SR(); } catch (e) { if (onEnd) onEnd(false); return null; }
  rec.lang = "ru-RU";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = ev => {
    const t = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : "";
    if (t) onResult(t);
  };
  rec.onerror = () => { if (onEnd) onEnd(false); };
  rec.onend = () => { if (onEnd) onEnd(true); };
  try { rec.start(); } catch (e) { if (onEnd) onEnd(false); return null; }
  return rec;
}

/* ---------- баннеры происшествий (banners/banner-map.json + PNG) ---------- */
let BANNER_MAP = null;
async function loadBannerMap() {
  if (BANNER_MAP) return BANNER_MAP;
  try {
    const r = await fetch("banners/banner-map.json");
    BANNER_MAP = await r.json();
  } catch (e) {
    BANNER_MAP = { categories: {}, title_keywords: {}, group_keywords: {}, default: "general" };
  }
  return BANNER_MAP;
}

/* Подбор баннера: точные ключевые слова сообщения → группа → категория → default. */
function pickBanner(map, opts) {
  map = map || { categories: {}, title_keywords: {}, group_keywords: {}, default: "general" };
  opts = opts || {};
  const text = String((opts.text || "") + " " + (opts.className || "") + " " + (opts.groupName || "")).toLowerCase();
  for (const [kw, img] of Object.entries(map.title_keywords || {})) {
    if (text.includes(kw)) return img;
  }
  for (const [kw, img] of Object.entries(map.group_keywords || {})) {
    if (text.includes(kw)) return img;
  }
  if (opts.categoryCode && map.categories && map.categories[opts.categoryCode]) {
    return map.categories[opts.categoryCode];
  }
  return map.default || "general";
}
function bannerHtml(img) {
  return "<div class='banner'><img src='banners/" + esc(img) + ".png' alt='Баннер происшествия' loading='lazy'></div>";
}

/* ---------- адрес/карта: локальный поиск по geo/addresses.json ---------- */
let GEO_ADDRESSES = null;
async function loadGeoAddresses() {
  if (GEO_ADDRESSES) return GEO_ADDRESSES;
  try {
    const r = await fetch("geo/addresses.json");
    GEO_ADDRESSES = await r.json();
  } catch (e) {
    GEO_ADDRESSES = { version: 1, city: "", region: "", country: "", addresses: [] };
  }
  return GEO_ADDRESSES;
}
function geoSearch(query, limit) {
  const q = String(query || "").trim().toLowerCase();
  if (q.length < 3) return [];
  const out = [];
  for (const item of (GEO_ADDRESSES && GEO_ADDRESSES.addresses) || []) {
    const street = String(item.street || "").toLowerCase();
    const house = String(item.house || "").toLowerCase();
    if (street.includes(q) || (house && (street + " " + house).includes(q))) {
      out.push({ id: item.id, label: item.street + ", " + item.house, point: item.point });
      if (out.length >= (limit || 8)) break;
    }
  }
  return out;
}
function geoLabel(item) {
  return item && item.street ? item.street + ", " + (item.house || "") : (item ? item.id : "");
}

/* Схематичная карта-виджет без внешних сервисов: сетка + маркер + ссылка OSM.
 * el — DOM-контейнер; lat/lng — координаты точки. */
function renderMiniMap(el, lat, lng, label) {
  if (!el) return;
  const L = Number(lat), G = Number(lng);
  if (isNaN(L) || isNaN(G)) {
    el.innerHTML = "<div class='map-panel'><p class='muted'>Координаты не заданы — карта недоступна.</p></div>";
    return;
  }
  const size = 280, c = size / 2, span = 0.004;
  const x = c + (G - G) * 0; // маркер в центре; сетка — локальная
  const grid = [];
  for (let i = 1; i < 6; i++) {
    const off = Math.round(size * i / 6);
    grid.push("<line x1='0' y1='" + off + "' x2='" + size + "' y2='" + off + "' stroke='#d7dfe6'/>");
    grid.push("<line x1='" + off + "' y1='0' x2='" + off + "' y2='" + size + "' stroke='#d7dfe6'/>");
  }
  el.innerHTML =
    "<div class='map-panel'>" +
      "<svg viewBox='0 0 " + size + " " + size + "' role='img' aria-label='Схема местности'>" +
        "<rect width='" + size + "' height='" + size + "' fill='#eef4f0'/>" +
        grid.join("") +
        "<circle cx='" + c + "' cy='" + c + "' r='9' fill='#c0392b' stroke='#fff' stroke-width='2'/>" +
        "<text x='" + c + "' y='" + (c + 26) + "' text-anchor='middle' font-size='11' fill='#30383f'>" + esc(label || "Точка вызова") + "</text>" +
      "</svg>" +
      "<p class='muted mono'>lat " + L.toFixed(6) + " · lng " + G.toFixed(6) +
      " · <a href='https://www.openstreetmap.org/?mlat=" + L + "&mlon=" + G + "#map=17/" + L + "/" + G + "' target='_blank' rel='noopener'>открыть в OSM ↗</a></p>" +
    "</div>";
  void x; void span;
}