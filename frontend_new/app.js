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
  return api("/students").catch(() => []);
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