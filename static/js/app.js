/* INTRINSIC - single-page frontend. Plain JavaScript, no external libraries. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ basics
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const app = $("#app");
  const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
  const DEMO = [
    { label: "Admin", email: "admin@intrinsic.io", note: "Full control" },
    { label: "Staff", email: "staff@intrinsic.io", note: "Day-to-day" },
    { label: "Customer", email: "customer@intrinsic.io", note: "Self-service" },
  ];
  const DEMO_PASSWORD = "Intrinsic@2026";
  const STEPS = ["draft", "quotation", "confirmed", "active", "closed"];
  const STEP_NAMES = { draft: "Draft", quotation: "Quotation", confirmed: "Confirmed", active: "Active", closed: "Closed" };
  const METHODS = { cash: "Cash", bank_transfer: "Bank transfer", card: "Card", upi: "UPI", cheque: "Cheque" };
  const PERIODS = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", yearly: "Yearly" };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => INR.format(Number(v || 0));
  const fdate = (s) => (s ? new Date(s + (s.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "-");
  const todayISO = () => new Date().toLocaleDateString("en-CA");
  const label = (s) => (s ? String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "");

  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem("intrinsic." + k)); } catch { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem("intrinsic." + k) : localStorage.setItem("intrinsic." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };

  const S = { token: store.get("token"), user: store.get("user"), cache: {}, filters: { subs: {}, invoices: {}, payments: {}, customers: {} } };
  const isInternal = () => S.user && S.user.role !== "customer";
  const isAdmin = () => S.user && S.user.role === "admin";

  // ------------------------------------------------------------------ API
  async function api(path, { method = "GET", body } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (S.token) headers.Authorization = "Bearer " + S.token;
    let res;
    try {
      res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new Error("Cannot reach the server. Check that it is still running.");
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && S.token && !path.startsWith("/api/auth/login")) {
      signOut(true);
      throw new Error(data.detail || "Your session has expired. Please sign in again.");
    }
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong.");
    return data;
  }

  const qs = (obj) => {
    const p = new URLSearchParams();
    Object.entries(obj).forEach(([k, v]) => { if (v !== "" && v != null) p.set(k, v); });
    const s = p.toString();
    return s ? "?" + s : "";
  };

  async function lookup(name) {
    if (!S.cache[name]) {
      const paths = { plans: "/api/plans", products: "/api/products", customers: "/api/customers", templates: "/api/templates", taxes: "/api/taxes", discounts: "/api/discounts" };
      S.cache[name] = await api(paths[name]);
    }
    return S.cache[name];
  }
  const forget = (...names) => names.forEach((n) => delete S.cache[n]);

  // ------------------------------------------------------------------ feedback
  function toast(msg, kind = "") {
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.textContent = msg;
    $("#toasts").append(t);
    setTimeout(() => t.remove(), kind === "error" ? 6000 : 3500);
  }

  async function run(btn, fn) {
    if (btn) btn.disabled = true;
    try { return await fn(); } catch (e) { toast(e.message, "error"); return undefined; } finally { if (btn) btn.disabled = false; }
  }

  // ------------------------------------------------------------------ modal & drawer
  function closeModal() { $("#modal-root").innerHTML = ""; }
  function openModal({ title, body, foot = "", wide = false, onOpen }) {
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal-backdrop" data-close></div>
      <section class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal-head"><h2>${esc(title)}</h2><button class="closebtn" data-close aria-label="Close">&times;</button></div>
        <div class="modal-body">${body}</div>
        ${foot ? `<div class="modal-foot">${foot}</div>` : ""}
      </section>`;
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", closeModal));
    const first = $("input:not([type=hidden]), select, textarea", root);
    if (first) first.focus();
    if (onOpen) onOpen($(".modal", root));
    return $(".modal", root);
  }

  function confirmBox(title, text, okLabel = "Confirm", danger = false) {
    return new Promise((resolve) => {
      const m = openModal({
        title, body: `<p style="margin:0">${esc(text)}</p>`,
        foot: `<button class="btn" data-no>Keep as is</button><button class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(okLabel)}</button>`,
      });
      $("[data-yes]", m).onclick = () => { closeModal(); resolve(true); };
      $("[data-no]", m).onclick = () => { closeModal(); resolve(false); };
      $$("[data-close]", $("#modal-root")).forEach((b) => b.addEventListener("click", () => resolve(false)));
    });
  }

  let drawerReload = null;
  function closeDrawer() { $("#drawer-root").innerHTML = ""; drawerReload = null; }
  function openDrawer(html, reload) {
    drawerReload = reload || null;
    $("#drawer-root").innerHTML = `<div class="overlay" data-close-drawer></div><aside class="drawer" role="dialog" aria-modal="true">${html}</aside>`;
    $$("[data-close-drawer]", $("#drawer-root")).forEach((b) => b.addEventListener("click", closeDrawer));
    return $(".drawer");
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if ($("#modal-root").innerHTML) closeModal(); else if ($("#drawer-root").innerHTML) closeDrawer();
  });

  // ------------------------------------------------------------------ forms
  function fieldHTML(f, v) {
    const id = "f_" + f.name;
    const req = f.required ? "required" : "";
    const val = v ?? f.default ?? "";
    if (f.type === "checkbox") {
      return `<label class="check"><input type="checkbox" name="${f.name}" ${val ? "checked" : ""}> ${esc(f.label)}</label>`;
    }
    let control;
    if (f.type === "select") {
      const opts = (f.options || []).map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(val) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
      control = `<select class="input" id="${id}" name="${f.name}" ${req}>${f.placeholder !== undefined ? `<option value="">${esc(f.placeholder)}</option>` : ""}${opts}</select>`;
    } else if (f.type === "textarea") {
      control = `<textarea class="input" id="${id}" name="${f.name}" ${req}>${esc(val)}</textarea>`;
    } else {
      const extra = [f.min !== undefined ? `min="${f.min}"` : "", f.step ? `step="${f.step}"` : "", f.autocomplete ? `autocomplete="${f.autocomplete}"` : "", f.readonly ? "readonly" : ""].join(" ");
      control = `<input class="input" id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(val)}" ${req} ${extra}>`;
    }
    return `<label class="field" for="${id}"><span>${esc(f.label)}</span>${control}${f.help ? `<small>${esc(f.help)}</small>` : ""}</label>`;
  }

  function rowsHTML(f, rows) {
    const cols = f.columns.length;
    const tpl = `grid-template-columns: ${f.columns.map((c) => c.width || "1fr").join(" ")} auto`;
    const line = (r = {}) => `<div class="row-line" style="${tpl}">${f.columns.map((c) => fieldHTML(c, r[c.name])).join("")}
        ${r.id ? `<input type="hidden" name="id" value="${esc(r.id)}">` : ""}
        <button type="button" class="btn ghost" data-remove-row aria-label="Remove line">&times;</button></div>`;
    return `<div class="rows" data-rows="${f.name}" data-cols="${cols}">
      <div class="rows-head"><span>${esc(f.label)}</span><button type="button" class="btn small" data-add-row>${esc(f.addLabel || "Add line")}</button></div>
      <div data-row-list>${(rows || []).map(line).join("") || ""}</div>
      ${f.help ? `<small class="muted">${esc(f.help)}</small>` : ""}
      <template>${line()}</template></div>`;
  }

  function formHTML(fields, values = {}) {
    return fields.map((f) => {
      if (Array.isArray(f)) return `<div class="grid-${f.length}">${f.map((x) => fieldHTML(x, values[x.name])).join("")}</div>`;
      if (f.type === "rows") return rowsHTML(f, values[f.name]);
      if (f.type === "html") return f.html;
      return fieldHTML(f, values[f.name]);
    }).join("");
  }

  function wireRows(root) {
    $$("[data-rows]", root).forEach((box) => {
      const list = $("[data-row-list]", box);
      $("[data-add-row]", box).onclick = () => { list.insertAdjacentHTML("beforeend", $("template", box).innerHTML); };
      box.addEventListener("click", (e) => { if (e.target.matches("[data-remove-row]")) e.target.closest(".row-line").remove(); });
    });
  }

  function readValue(f, el) {
    if (!el) return undefined;
    if (f.type === "checkbox") return el.checked;
    const v = el.value.trim();
    if (v === "") return null;
    if (f.type === "number") return Number(v);
    if (f.numeric) return Number(v);
    return v;
  }

  function readForm(root, fields) {
    const out = {};
    fields.flat().forEach((f) => {
      if (f.type === "html") return;
      if (f.type === "rows") {
        out[f.name] = $$(`[data-rows="${f.name}"] [data-row-list] .row-line`, root).map((line) => {
          const r = {};
          f.columns.forEach((c) => { r[c.name] = readValue(c, $(`[name="${c.name}"]`, line)); });
          const id = $('[name="id"]', line);
          if (id) r.id = Number(id.value);
          return r;
        });
        return;
      }
      out[f.name] = readValue(f, $(`[name="${f.name}"]`, root));
    });
    return out;
  }

  function formModal({ title, fields, values, submitLabel = "Save", wide = false, onSubmit, onOpen }) {
    const m = openModal({
      title, wide,
      body: `<form novalidate><div class="notice error hidden" data-err></div>${formHTML(fields, values)}<button type="submit" class="hidden"></button></form>`,
      foot: `<button class="btn" data-close>Cancel</button><button class="btn primary" data-submit>${esc(submitLabel)}</button>`,
    });
    const form = $("form", m);
    wireRows(form);
    if (onOpen) onOpen(form);
    const submit = async (e) => {
      e && e.preventDefault();
      const err = $("[data-err]", form);
      err.classList.add("hidden");
      const btn = $("[data-submit]", m);
      btn.disabled = true;
      try {
        await onSubmit(readForm(form, fields), form);
        closeModal();
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.remove("hidden");
        err.scrollIntoView({ block: "nearest" });
      } finally { btn.disabled = false; }
    };
    form.addEventListener("submit", submit);
    $("[data-submit]", m).addEventListener("click", submit);
  }

  // ------------------------------------------------------------------ small renderers
  function badge(status, text) { return `<span class="badge ${esc(status)}">${esc(text || label(status))}</span>`; }
  function subBadge(s) { return s.paused ? badge("paused", "Paused") : badge(s.status, STEP_NAMES[s.status]); }
  function invBadge(i) {
    if (i.display_status === "overdue") return badge("overdue", "Overdue");
    if (i.status === "confirmed") return badge(i.balance > 0 && i.amount_paid > 0 ? "outstanding" : "confirmed", i.amount_paid > 0 ? "Part paid" : "Confirmed");
    return badge(i.status);
  }
  function emptyRow(cols, title, hint = "") { return `<tr><td colspan="${cols}"><div class="empty"><strong>${esc(title)}</strong>${esc(hint)}</div></td></tr>`; }
  function pager(data, onPage) {
    if (!data.total) return "";
    const start = (data.page - 1) * data.page_size + 1;
    const end = Math.min(data.total, data.page * data.page_size);
    const id = "pg" + Math.random().toString(36).slice(2, 7);
    setTimeout(() => {
      const box = document.getElementById(id);
      if (!box) return;
      const prev = $("[data-prev]", box), next = $("[data-next]", box);
      if (prev) prev.onclick = () => onPage(data.page - 1);
      if (next) next.onclick = () => onPage(data.page + 1);
    });
    return `<div class="pager" id="${id}"><span>${start}-${end} of ${data.total}</span><span class="actions">
      <button class="btn small" data-prev ${data.page <= 1 ? "disabled" : ""}>Previous</button>
      <button class="btn small" data-next ${end >= data.total ? "disabled" : ""}>Next</button></span></div>`;
  }
  function track(status, counts) {
    return `<div class="track">${STEPS.map((st, i) => {
      const idx = STEPS.indexOf(status);
      let cls = "";
      if (counts) cls = "";
      else if (status === "closed") cls = st === "closed" ? "current closed-state" : "done";
      else if (i < idx) cls = "done";
      else if (i === idx) cls = "current";
      const tag = counts ? "button" : "div";
      return `<${tag} class="track-step ${cls}" ${counts ? `data-status="${st}" type="button" aria-label="Show ${STEP_NAMES[st]} subscriptions"` : ""}>
        <span class="track-node">${counts ? i + 1 : i < idx || (status === "closed" && st !== "closed") ? "&#10003;" : i + 1}</span>
        <span class="track-name">${STEP_NAMES[st]}</span>
        ${counts ? `<span class="track-count">${counts[st] ?? 0}</span>` : ""}</${tag}>`;
    }).join("")}</div>`;
  }

  // ------------------------------------------------------------------ icons
  const ICON = {
    dashboard: '<path d="M3 13h7V3H3zM14 21h7v-8h-7zM14 3v6h7V3zM3 21h7v-4H3z"/>',
    subs: '<path d="M4 6h16M4 12h16M4 18h10"/><circle cx="19" cy="18" r="2"/>',
    invoices: '<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h7M9 17h5"/>',
    payments: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    customers: '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6M16 4a4 4 0 0 1 0 8M22 21c0-3-2-5-4-5.6"/>',
    catalog: '<path d="M3 7l9-4 9 4-9 4zM3 12l9 4 9-4M3 17l9 4 9-4"/>',
    team: '<path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/>',
    profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/>',
  };
  const icon = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;
  const LOGO = `<svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#7C93E0"/><path d="M9 22h14M9 16h9M9 10h14" stroke="#18212B" stroke-width="3" stroke-linecap="round"/></svg>`;

  // ------------------------------------------------------------------ auth screens
  function rulesHTML() {
    return `<ul class="rules" data-rules>
      <li data-rule="len">More than 8 characters</li><li data-rule="up">An uppercase letter</li>
      <li data-rule="low">A lowercase letter</li><li data-rule="sp">A special character</li></ul>`;
  }
  function wireRules(input) {
    const box = input.closest("form").querySelector("[data-rules]");
    const check = () => {
      const v = input.value;
      const ok = { len: v.length > 8, up: /[A-Z]/.test(v), low: /[a-z]/.test(v), sp: /[^A-Za-z0-9\s]/.test(v) };
      Object.entries(ok).forEach(([k, good]) => box.querySelector(`[data-rule="${k}"]`).classList.toggle("ok", good));
    };
    input.addEventListener("input", check);
    check();
  }

  function renderAuth(mode, params = {}) {
    const story = `<div class="auth-story">
      <div class="wordmark">${LOGO} INTRINSIC</div>
      <div>
        <h1>Every subscription, from first quote to final invoice.</h1>
        <p>Brightloop Software's plans, renewals, invoices and payments, kept in one place instead of a spreadsheet.</p>
      </div>
      <div class="story-track" aria-hidden="true">
        ${[["Draft", "A rep prepares the offer"], ["Quotation", "Sent from a ready-made template"], ["Confirmed", "The customer accepts online"], ["Active", "Invoices go out on their own"], ["Closed", "Ended on time, nothing missed"]]
          .map(([t, d], i) => `<div class="story-step ${i === 3 ? "on" : ""}"><span class="story-dot">${i + 1}</span><div><strong>${t}</strong><span>${d}</span></div></div>`).join("")}
      </div>
    </div>`;

    let card = "";
    if (mode === "login" || mode === "register") {
      card = `<div class="tabs-inline" role="tablist">
          <button role="tab" aria-selected="${mode === "login"}" data-go="login">Sign in</button>
          <button role="tab" aria-selected="${mode === "register"}" data-go="register">Create account</button></div>`;
    }
    if (mode === "login") {
      card += `<h2>Welcome back</h2><p class="sub">Sign in to manage subscriptions and invoices.</p>
        <form data-form="login"><div class="notice error hidden" data-err></div>
          ${fieldHTML({ name: "email", label: "Email", type: "email", required: true, autocomplete: "username" })}
          ${fieldHTML({ name: "password", label: "Password", type: "password", required: true, autocomplete: "current-password" })}
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
            <button class="link" type="button" data-go="forgot">Forgot password?</button>
            <button class="btn primary" type="submit">Sign in</button></div>
        </form>
        <div class="personas"><p>Try a demo account (password ${DEMO_PASSWORD})</p><div class="persona-row">
          ${DEMO.map((d) => `<button class="btn" type="button" data-demo="${d.email}">${d.label}<small>${d.note}</small></button>`).join("")}</div></div>`;
    } else if (mode === "register") {
      card += `<h2>Create your account</h2><p class="sub">See and manage your own subscriptions and invoices.</p>
        <form data-form="register"><div class="notice error hidden" data-err></div>
          ${fieldHTML({ name: "name", label: "Your name", required: true, autocomplete: "name" })}
          ${fieldHTML({ name: "company", label: "Company (optional)", autocomplete: "organization" })}
          ${fieldHTML({ name: "email", label: "Email", type: "email", required: true, autocomplete: "email" })}
          <label class="field"><span>Password</span><input class="input" type="password" name="password" required autocomplete="new-password">${rulesHTML()}</label>
          <button class="btn primary" type="submit" style="width:100%">Create account</button>
        </form>`;
    } else if (mode === "forgot") {
      card = `<h2>Reset your password</h2><p class="sub">Enter the email you signed up with and we will send you a reset link.</p>
        <form data-form="forgot"><div class="notice error hidden" data-err></div><div data-done></div>
          ${fieldHTML({ name: "email", label: "Email", type: "email", required: true })}
          <div style="display:flex;justify-content:space-between;align-items:center">
            <button class="link" type="button" data-go="login">Back to sign in</button>
            <button class="btn primary" type="submit">Send reset link</button></div></form>`;
    } else if (mode === "reset") {
      card = `<h2>Choose a new password</h2><p class="sub">The link works once and expires after 30 minutes.</p>
        <form data-form="reset"><div class="notice error hidden" data-err></div>
          <label class="field"><span>New password</span><input class="input" type="password" name="password" required autocomplete="new-password">${rulesHTML()}</label>
          ${fieldHTML({ name: "confirm", label: "Repeat new password", type: "password", required: true, autocomplete: "new-password" })}
          <button class="btn primary" type="submit" style="width:100%">Save new password</button></form>`;
    }

    app.innerHTML = `<div class="auth">${story}<div class="auth-panel"><div class="auth-card">${card}</div></div></div>`;
    $$("[data-go]").forEach((b) => (b.onclick = () => (location.hash = b.dataset.go)));
    const pw = $('input[name="password"][autocomplete="new-password"]');
    if (pw) wireRules(pw);
    const form = $("form");
    const err = $("[data-err]", form);
    const fail = (e) => { err.textContent = e.message; err.classList.remove("hidden"); };

    $$("[data-demo]").forEach((b) => (b.onclick = () => {
      form.email.value = b.dataset.demo;
      form.password.value = DEMO_PASSWORD;
      form.requestSubmit();
    }));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.classList.add("hidden");
      const btn = $('button[type="submit"]', form);
      btn.disabled = true;
      try {
        const v = Object.fromEntries(new FormData(form));
        if (mode === "login") {
          signIn(await api("/api/auth/login", { method: "POST", body: { email: v.email, password: v.password } }));
        } else if (mode === "register") {
          signIn(await api("/api/auth/register", { method: "POST", body: { name: v.name, email: v.email, password: v.password, company: v.company || null } }));
          toast("Your account is ready.", "good");
        } else if (mode === "forgot") {
          const r = await api("/api/auth/forgot-password", { method: "POST", body: { email: v.email } });
          $("[data-done]", form).innerHTML = `<div class="notice good">${esc(r.message)}</div>` +
            (r.demo_reset_link ? `<div class="notice info">Demo mode, no mail server is set up. Your reset link:<br><a href="${esc(r.demo_reset_link)}">${esc(r.demo_reset_link)}</a></div>` : "");
        } else if (mode === "reset") {
          if (v.password !== v.confirm) throw new Error("The two passwords do not match.");
          const r = await api("/api/auth/reset-password", { method: "POST", body: { token: params.token || "", password: v.password } });
          toast(r.message, "good");
          location.hash = "login";
        }
      } catch (ex) { fail(ex); } finally { btn.disabled = false; }
    });
  }

  function signIn(data) {
    S.token = data.token; S.user = data.user; S.cache = {};
    store.set("token", S.token); store.set("user", S.user);
    location.hash = "dashboard";
    route();
  }

  async function signOut(expired = false) {
    if (!expired && S.token) { try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ } }
    S.token = null; S.user = null; S.cache = {};
    store.set("token", null); store.set("user", null);
    closeDrawer(); closeModal();
    location.hash = "login";
    route();
  }

  // ------------------------------------------------------------------ shell
  function navItems() {
    if (isInternal()) {
      const items = [
        ["dashboard", "Overview", "dashboard"], ["subscriptions", "Subscriptions", "subs"], ["invoices", "Invoices", "invoices"],
        ["payments", "Payments", "payments"], ["customers", "Customers", "customers"],
        ["group", "Setup"], ["catalog", "Products & plans", "catalog"],
      ];
      if (isAdmin()) items.push(["team", "Team", "team"]);
      return items;
    }
    return [["dashboard", "Overview", "dashboard"], ["subscriptions", "My subscriptions", "subs"], ["invoices", "My invoices", "invoices"],
      ["payments", "Payment history", "payments"], ["profile", "My details", "profile"]];
  }

  function renderShell(current) {
    if ($(".shell") && $(".shell").dataset.user === String(S.user.id)) {
      $$(".nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.page === current ? "page" : "false"));
      $(".side").classList.remove("open");
      return $("main");
    }
    app.innerHTML = `<div class="shell" data-user="${S.user.id}">
      <div class="topbar"><div class="wordmark">${LOGO} INTRINSIC</div><button class="btn small" data-menu aria-label="Open menu">Menu</button></div>
      <aside class="side">
        <div class="wordmark">${LOGO} INTRINSIC</div>
        <nav class="nav" aria-label="Main">${navItems().map((n) => n[0] === "group" ? `<div class="nav-group">${n[1]}</div>` :
          `<a href="#${n[0]}" data-page="${n[0]}" aria-current="${n[0] === current ? "page" : "false"}">${icon(n[2])}${n[1]}</a>`).join("")}</nav>
        <div class="side-foot">
          <div class="who"><strong>${esc(S.user.name)}</strong>${esc(S.user.email)}<br><span class="role-pill">${label(S.user.role)}</span></div>
          ${isInternal() ? `<a class="btn small" href="#profile">My details</a>` : ""}
          <button class="btn small" data-signout>Sign out</button>
        </div>
      </aside>
      <main id="main" tabindex="-1"></main></div>`;
    $("[data-signout]").onclick = () => signOut();
    $("[data-menu]").onclick = () => $(".side").classList.toggle("open");
    return $("main");
  }

  // ------------------------------------------------------------------ router
  const ROUTES = {
    dashboard: (main) => (isInternal() ? viewDashboard(main) : viewCustomerHome(main)),
    subscriptions: viewSubscriptions, invoices: viewInvoices, payments: viewPayments,
    customers: viewCustomers, catalog: viewCatalog, team: viewTeam, profile: viewProfile,
  };

  function parseHash() {
    const raw = location.hash.replace(/^#/, "");
    const [path, query] = raw.split("?");
    const [page, sub] = (path || "").split("/");
    return { page, sub, params: Object.fromEntries(new URLSearchParams(query || "")) };
  }

  async function route() {
    const { page, sub, params } = parseHash();
    if (page === "reset") return renderAuth("reset", params);
    if (!S.token || !S.user) {
      return renderAuth(["register", "forgot"].includes(page) ? page : "login");
    }
    if (["login", "register", "forgot", ""].includes(page) || !ROUTES[page]) { location.hash = "dashboard"; return; }
    if ((page === "customers" || page === "catalog") && !isInternal()) { location.hash = "dashboard"; return; }
    if (page === "team" && !isAdmin()) { location.hash = "dashboard"; return; }
    closeDrawer();
    const main = renderShell(page);
    main.innerHTML = `<div class="loading">Loading...</div>`;
    try { await ROUTES[page](main, sub, params); } catch (e) { main.innerHTML = `<div class="notice error">${esc(e.message)}</div>`; }
  }
  window.addEventListener("hashchange", route);

  // ------------------------------------------------------------------ dashboard (team)
  async function viewDashboard(main) {
    const f = S.filters.dashboard || (S.filters.dashboard = { date_from: todayISO().slice(0, 8) + "01", date_to: todayISO(), plan_id: "" });
    const [r, plans] = await Promise.all([api("/api/reports/summary" + qs(f)), lookup("plans")]);
    const maxBar = Math.max(1, ...r.collected_by_month.map((m) => m.collected));
    main.innerHTML = `
      <div class="page-head">
        <div><h1>Billing overview</h1><p>${fdate(r.range.date_from)} to ${fdate(r.range.date_to)}</p></div>
        <div class="actions">
          ${r.draft_invoices ? `<button class="btn" data-confirm-drafts>Confirm ${r.draft_invoices} draft invoice${r.draft_invoices > 1 ? "s" : ""}</button>` : ""}
          <button class="btn primary" data-run-billing>Run billing now</button>
        </div>
      </div>
      <form class="panel toolbar" style="margin-bottom:18px;border-radius:10px" data-range>
        <label class="sr" for="df">From</label><input class="input" type="date" id="df" name="date_from" value="${esc(f.date_from)}">
        <span class="muted">to</span>
        <label class="sr" for="dt">To</label><input class="input" type="date" id="dt" name="date_to" value="${esc(f.date_to)}">
        <label class="sr" for="dp">Plan</label><select class="input" id="dp" name="plan_id"><option value="">All plans</option>
          ${plans.map((p) => `<option value="${p.id}" ${String(p.id) === String(f.plan_id) ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
        <button class="btn" type="submit">Apply</button>
      </form>
      <section class="ledger" aria-label="Key figures">
        <div><div class="label">Active subscriptions</div><div class="value">${r.active_subscriptions}</div><div class="hint">${r.paused_subscriptions} paused</div></div>
        <div><div class="label">Monthly recurring revenue</div><div class="value">${money(r.mrr)}</div><div class="hint">Before tax</div></div>
        <div><div class="label">Collected in range</div><div class="value good">${money(r.collected)}</div><div class="hint">Invoiced ${money(r.invoiced)}</div></div>
        <div><div class="label">Still owed</div><div class="value">${money(r.outstanding)}</div><div class="hint">All confirmed invoices</div></div>
        <div><div class="label">Overdue</div><div class="value ${r.overdue_count ? "bad" : ""}">${money(r.overdue_amount)}</div><div class="hint">${r.overdue_count} invoice${r.overdue_count === 1 ? "" : "s"} past due</div></div>
      </section>
      <section class="panel" style="margin-top:18px">
        <div class="panel-head"><h2>Where every subscription stands</h2><span class="muted" style="font-size:13px">Select a stage to see its subscriptions</span></div>
        <div class="panel-body">${track(null, r.subscriptions_by_status)}</div>
      </section>
      <div class="split">
        <section class="panel"><div class="panel-head"><h2>Money collected, last 6 months</h2></div>
          <div class="panel-body"><div class="bars">${r.collected_by_month.map((m) => `<div class="bar" title="${esc(m.month)}: ${money(m.collected)}">
            <span class="amt">${m.collected ? money(m.collected).replace(/\.\d+$/, "") : "-"}</span>
            <div class="bar-fill-wrap"><div class="bar-fill" style="height:${Math.round((m.collected / maxBar) * 100)}%"></div></div>
            <small>${esc(m.month)}</small></div>`).join("")}</div></div></section>
        <section class="panel"><div class="panel-head"><h2>Most popular plans</h2></div>
          <div class="table-wrap"><table class="data"><thead><tr><th>Plan</th><th class="n">Active</th></tr></thead><tbody>
          ${r.top_plans.map((p) => `<tr><td>${esc(p.plan)}</td><td class="n">${p.active}</td></tr>`).join("") || emptyRow(2, "No active subscriptions yet.")}</tbody></table></div></section>
      </div>
      <div class="split">
        <section class="panel"><div class="panel-head"><h2>Overdue invoices to chase</h2><a href="#invoices" data-overdue class="link">See all</a></div>
          <div class="table-wrap"><table class="data"><thead><tr><th>Invoice</th><th>Due</th><th class="n">Owed</th></tr></thead><tbody>
          ${r.overdue_invoices.map((i) => `<tr class="clickable" data-inv="${i.id}"><td><span class="strong">${esc(i.number)}</span><span class="sub">${esc(i.customer)}</span></td>
            <td>${fdate(i.due_date)}</td><td class="n">${money(i.balance)}</td></tr>`).join("") || emptyRow(3, "Nothing overdue.", " Every confirmed invoice is within its payment terms.")}</tbody></table></div></section>
        <section class="panel"><div class="panel-head"><h2>Latest payments</h2><a href="#payments" class="link">See all</a></div>
          <div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>From</th><th class="n">Amount</th></tr></thead><tbody>
          ${r.recent_payments.map((p) => `<tr class="clickable" data-inv="${p.invoice_id}"><td>${fdate(p.payment_date)}</td><td>${esc(p.customer)}<span class="sub">${esc(p.invoice)} · ${esc(METHODS[p.method])}</span></td><td class="n">${money(p.amount)}</td></tr>`).join("") || emptyRow(3, "No payments recorded yet.")}</tbody></table></div></section>
      </div>`;

    $("[data-range]", main).onsubmit = (e) => {
      e.preventDefault();
      S.filters.dashboard = Object.fromEntries(new FormData(e.target));
      viewDashboard(main);
    };
    $$("[data-status]", main).forEach((b) => (b.onclick = () => { S.filters.subs = { status: b.dataset.status }; location.hash = "subscriptions"; }));
    $$("[data-inv]", main).forEach((row) => (row.onclick = () => openInvoice(row.dataset.inv, () => viewDashboard(main))));
    $("[data-overdue]", main).onclick = () => { S.filters.invoices = { status: "overdue" }; };
    $("[data-run-billing]", main).onclick = (e) => runBilling(e.target, () => viewDashboard(main));
    const cd = $("[data-confirm-drafts]", main);
    if (cd) cd.onclick = (e) => confirmDrafts(e.target, () => viewDashboard(main));
  }

  async function runBilling(btn, after) {
    const r = await run(btn, () => api("/api/billing/run", { method: "POST" }));
    if (!r) return;
    toast(r.invoices_created
      ? `Billing done: ${r.invoices_created} draft invoice${r.invoices_created > 1 ? "s" : ""} created for ${money(r.amount_invoiced)}.`
      : "Billing done: nothing is due today. No invoice was created twice.", "good");
    if (r.subscriptions_closed) toast(`${r.subscriptions_closed} subscription(s) reached the end of their term and were closed.`);
    after && after();
  }

  async function confirmDrafts(btn, after) {
    const r = await run(btn, () => api("/api/invoices/confirm-drafts", { method: "POST" }));
    if (r) { toast(`${r.confirmed} invoice${r.confirmed === 1 ? "" : "s"} confirmed.`, "good"); after && after(); }
  }

  // ------------------------------------------------------------------ customer home
  async function viewCustomerHome(main) {
    const [r, subs, open] = await Promise.all([
      api("/api/reports/summary"), api("/api/subscriptions?page_size=10"), api("/api/invoices?status=outstanding&page_size=20"),
    ]);
    main.innerHTML = `
      <div class="page-head"><div><h1>Hello, ${esc(S.user.name.split(" ")[0])}</h1><p>Your subscriptions and invoices at a glance.</p></div>
        <div class="actions"><button class="btn primary" data-new>Request a subscription</button></div></div>
      <section class="ledger" style="grid-template-columns:repeat(4,minmax(0,1fr))">
        <div><div class="label">Active subscriptions</div><div class="value">${r.active_subscriptions}</div><div class="hint">${r.paused_subscriptions} paused</div></div>
        <div><div class="label">You owe</div><div class="value">${money(r.outstanding)}</div><div class="hint">Across confirmed invoices</div></div>
        <div><div class="label">Overdue</div><div class="value ${r.overdue_count ? "bad" : ""}">${money(r.overdue_amount)}</div><div class="hint">${r.overdue_count} invoice${r.overdue_count === 1 ? "" : "s"}</div></div>
        <div><div class="label">Paid this month</div><div class="value good">${money(r.collected)}</div><div class="hint">Thank you</div></div>
      </section>
      <div class="split">
        <section class="panel"><div class="panel-head"><h2>Invoices to pay</h2></div>
          <div class="table-wrap"><table class="data"><thead><tr><th>Invoice</th><th>Due</th><th>Status</th><th class="n">Owed</th><th></th></tr></thead><tbody>
          ${open.items.map((i) => `<tr class="clickable" data-inv="${i.id}"><td><span class="strong">${esc(i.number)}</span><span class="sub">${fdate(i.period_start)} to ${fdate(i.period_end)}</span></td>
            <td>${fdate(i.due_date)}</td><td>${invBadge(i)}</td><td class="n">${money(i.balance)}</td>
            <td class="n"><button class="btn small good" data-pay="${i.id}" data-amount="${i.balance}">Pay now</button></td></tr>`).join("") || emptyRow(5, "You are all paid up.", " New invoices will appear here.")}</tbody></table></div></section>
        <section class="panel"><div class="panel-head"><h2>Your subscriptions</h2><a class="link" href="#subscriptions">See all</a></div>
          <div class="table-wrap"><table class="data"><tbody>
          ${subs.items.map((s) => `<tr class="clickable" data-sub="${s.id}"><td><span class="strong">${esc(s.plan)}</span><span class="sub">${esc(s.number)}${s.next_invoice_date && s.status === "active" ? ` · next invoice ${fdate(s.next_invoice_date)}` : ""}</span></td>
            <td>${subBadge(s)}</td><td class="n">${money(s.total)}</td></tr>`).join("") || emptyRow(3, "No subscriptions yet.", " Request one to get started.")}</tbody></table></div></section>
      </div>`;
    const reload = () => viewCustomerHome(main);
    $("[data-new]", main).onclick = () => subscriptionForm(null, reload);
    $$("[data-sub]", main).forEach((r2) => (r2.onclick = () => openSubscription(r2.dataset.sub, reload)));
    $$("[data-inv]", main).forEach((r2) => (r2.onclick = (e) => { if (!e.target.closest("[data-pay]")) openInvoice(r2.dataset.inv, reload); }));
    $$("[data-pay]", main).forEach((b) => (b.onclick = () => payNow(b.dataset.pay, Number(b.dataset.amount), reload)));
  }

  // ------------------------------------------------------------------ subscriptions
  async function viewSubscriptions(main) {
    const f = S.filters.subs;
    f.page = f.page || 1;
    const [data, plans] = await Promise.all([api("/api/subscriptions" + qs(f)), lookup("plans")]);
    const internal = isInternal();
    main.innerHTML = `
      <div class="page-head"><div><h1>${internal ? "Subscriptions" : "My subscriptions"}</h1>
        <p>${internal ? "Quotes, running contracts and closed ones, with their full history." : "Accept quotations, pause, renew or close your subscriptions."}</p></div>
        <div class="actions"><button class="btn primary" data-new>${internal ? "New subscription" : "Request a subscription"}</button></div></div>
      <section class="panel">
        <form class="toolbar" data-filter>
          ${internal ? `<label class="sr" for="sq">Search</label><input class="input search" id="sq" name="q" type="search" placeholder="Search number, customer or email" value="${esc(f.q || "")}">` : ""}
          <label class="sr" for="ss">Status</label><select class="input" id="ss" name="status"><option value="">Every status</option>
            ${[...STEPS, "paused"].map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${label(s)}</option>`).join("")}</select>
          <label class="sr" for="sp">Plan</label><select class="input" id="sp" name="plan_id"><option value="">Every plan</option>
            ${plans.map((p) => `<option value="${p.id}" ${String(f.plan_id) === String(p.id) ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
          ${f.customer_id ? `<span class="chip">Customer: ${esc(f.customer_name || f.customer_id)} <button type="button" class="link" data-clear-customer aria-label="Clear customer filter">&times;</button></span>` : ""}
          <button class="btn" type="submit">Filter</button>
        </form>
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Subscription</th><th>Plan</th><th>Status</th><th>Started</th><th>Next invoice</th><th class="n">Per period</th></tr></thead><tbody>
          ${data.items.map((s) => `<tr class="clickable" data-sub="${s.id}">
            <td><span class="strong">${esc(s.number)}</span><span class="sub">${internal ? esc(s.customer) : esc(PERIODS[s.billing_period])}</span></td>
            <td>${esc(s.plan)}</td><td>${subBadge(s)}</td><td>${fdate(s.start_date)}</td>
            <td>${s.status === "active" && !s.paused ? fdate(s.next_invoice_date) : "-"}</td><td class="n">${money(s.total)}</td></tr>`).join("")
            || emptyRow(6, "No subscriptions match these filters.", internal ? " Clear a filter or create a new subscription." : " Request a subscription to get started.")}
        </tbody></table></div>
        ${pager(data, (p) => { f.page = p; viewSubscriptions(main); })}
      </section>`;
    const reload = () => viewSubscriptions(main);
    $("[data-filter]", main).onsubmit = (e) => {
      e.preventDefault();
      Object.assign(f, Object.fromEntries(new FormData(e.target)), { page: 1 });
      reload();
    };
    const cc = $("[data-clear-customer]", main);
    if (cc) cc.onclick = () => { delete f.customer_id; delete f.customer_name; reload(); };
    $("[data-new]", main).onclick = () => subscriptionForm(null, reload);
    $$("[data-sub]", main).forEach((r) => (r.onclick = () => openSubscription(r.dataset.sub, reload)));
  }

  async function itemOptions() {
    const products = await lookup("products");
    const opts = [];
    products.filter((p) => p.is_active).forEach((p) => {
      if (p.variants.length) p.variants.forEach((v) => opts.push({ value: `${p.id}:${v.id}`, label: `${p.name} - ${v.attribute}: ${v.value} (${money(p.sales_price + v.extra_price)})` }));
      else opts.push({ value: `${p.id}:`, label: `${p.name} (${money(p.sales_price)})` });
    });
    return opts;
  }

  async function subscriptionForm(existing, after) {
    const internal = isInternal();
    const [plans, items, customers, templates] = await Promise.all([
      lookup("plans"), itemOptions(), internal ? lookup("customers") : [], internal ? lookup("templates") : [],
    ]);
    const lineCols = [{ name: "item", label: "Product or add-on", type: "select", options: items, placeholder: "Choose...", width: "3fr" },
      { name: "quantity", label: "Qty", type: "number", min: 1, default: 1, width: "90px" }];
    const fields = [
      ...(internal ? [{ name: "customer_id", label: "Customer", type: "select", required: true, numeric: true, placeholder: "Choose a customer",
        options: customers.filter((c) => c.is_active).map((c) => ({ value: c.id, label: `${c.name}${c.company ? " - " + c.company : ""}` })) }] : []),
      ...(internal && !existing ? [{ name: "template_id", label: "Start from a quotation template (optional)", type: "select", numeric: true, placeholder: "No template",
        options: templates.filter((t) => t.is_active).map((t) => ({ value: t.id, label: `${t.name} (valid ${t.validity_days} days)` })) }] : []),
      [{ name: "plan_id", label: "Plan", type: "select", required: true, numeric: true, placeholder: "Choose a plan",
         options: plans.filter((p) => p.is_active).map((p) => ({ value: p.id, label: `${p.name} - ${money(p.price)} ${p.billing_period}${p.min_quantity > 1 ? `, min ${p.min_quantity}` : ""}` })) },
       { name: "plan_quantity", label: "Plan quantity (seats or units)", type: "number", min: 1, default: 1 }],
      [{ name: "start_date", label: "Start date", type: "date", default: todayISO() },
       { name: "expiry_date", label: "Expiry date (optional)", type: "date", help: "Leave empty to run until closed." },
       { name: "payment_terms_days", label: "Payment terms (days)", type: "number", min: 0, default: 15 }],
      { name: "lines", type: "rows", label: "Extra products and add-ons", addLabel: "Add product", columns: lineCols },
      { name: "discount_code", label: "Discount code (optional)", help: "Applied automatically to each invoice while it is valid." },
      { name: "notes", label: "Notes", type: "textarea" },
    ];
    const values = existing ? {
      customer_id: existing.customer_id, plan_id: existing.plan_id, plan_quantity: existing.plan_quantity,
      start_date: existing.start_date, expiry_date: existing.expiry_date, payment_terms_days: existing.payment_terms_days,
      discount_code: existing.discount_code, notes: existing.notes,
      lines: existing.lines.filter((l) => l.product_id).map((l) => ({ item: `${l.product_id}:${l.variant_id || ""}`, quantity: l.quantity })),
    } : { lines: [] };

    formModal({
      title: existing ? `Edit ${existing.number}` : internal ? "New subscription" : "Request a subscription",
      submitLabel: existing ? "Save changes" : internal ? "Create draft" : "Send request",
      wide: true, fields, values,
      onOpen: (form) => {
        const tpl = form.template_id;
        if (!tpl) return;
        tpl.addEventListener("change", () => {
          const t = templates.find((x) => String(x.id) === tpl.value);
          if (!t) return;
          form.plan_id.value = t.plan_id;
          form.plan_quantity.value = t.plan_quantity;
          const box = $('[data-rows="lines"]', form);
          const list = $("[data-row-list]", box);
          list.innerHTML = "";
          t.lines.forEach((l) => {
            list.insertAdjacentHTML("beforeend", $("template", box).innerHTML);
            const row = list.lastElementChild;
            row.querySelector('[name="item"]').value = `${l.product_id}:${l.variant_id || ""}`;
            row.querySelector('[name="quantity"]').value = l.quantity;
          });
          toast(`Filled from "${t.name}". Adjust anything before saving.`);
        });
      },
      onSubmit: async (v) => {
        const body = {
          customer_id: v.customer_id, plan_id: v.plan_id, template_id: v.template_id || null, plan_quantity: v.plan_quantity || 1,
          start_date: v.start_date, expiry_date: v.expiry_date, payment_terms_days: v.payment_terms_days ?? 15,
          discount_code: v.discount_code, notes: v.notes,
          lines: v.lines.filter((l) => l.item).map((l) => { const [p, vr] = l.item.split(":"); return { product_id: Number(p), variant_id: vr ? Number(vr) : null, quantity: l.quantity || 1 }; }),
        };
        const saved = existing
          ? await api(`/api/subscriptions/${existing.id}`, { method: "PUT", body })
          : await api("/api/subscriptions", { method: "POST", body });
        toast(existing ? "Changes saved." : internal ? `${saved.number} created as a draft.` : "Request sent. The team will prepare your quotation.", "good");
        after && after();
        openSubscription(saved.id, after);
      },
    });
  }

  function subActions(s) {
    const a = [];
    const add = (action, text, cls = "") => a.push(`<button class="btn ${cls}" data-act="${action}">${text}</button>`);
    const r = s.plan_rules;
    if (isInternal()) {
      if (s.status === "draft") { add("edit", "Edit"); add("to:quotation", "Send quotation", "primary"); add("to:closed", "Cancel", "danger"); }
      if (s.status === "quotation") { add("edit", "Edit"); add("to:confirmed", "Mark as accepted", "primary"); add("to:closed", "Cancel", "danger"); }
      if (s.status === "confirmed") { add("to:active", "Activate and start billing", "primary"); add("to:closed", "Cancel", "danger"); }
    } else {
      if (s.status === "draft") { add("edit", "Edit request"); add("to:closed", "Withdraw request", "danger"); }
      if (s.status === "quotation") { add("to:confirmed", "Accept quotation", "primary"); add("to:closed", "Decline", "danger"); }
    }
    if (s.status === "active") {
      if (r.pausable) s.paused ? add("resume", "Resume billing", "primary") : add("pause", "Pause");
      if (r.renewable && s.expiry_date) add("renew", "Renew for another term");
      if (r.closable || isAdmin() || (s.expiry_date && s.expiry_date <= todayISO())) add("to:closed", "Close subscription", "danger");
    }
    return a.join("");
  }

  async function openSubscription(id, after) {
    const s = await run(null, () => api(`/api/subscriptions/${id}`));
    if (!s) return;
    const reload = () => { openSubscription(id, after); after && after(); };
    const invs = s.status === "active" || s.status === "closed" ? await api(`/api/invoices?subscription_id=${id}&page_size=12`) : { items: [] };
    const rules = s.plan_rules;
    const d = openDrawer(`
      <div class="drawer-head"><div><h2>${esc(s.number)} ${subBadge(s)}</h2><p>${esc(s.customer)} · ${esc(s.plan)} (${esc(PERIODS[s.billing_period])})</p></div>
        <button class="closebtn" data-close-drawer aria-label="Close">&times;</button></div>
      <div class="drawer-body">
        ${track(s.status)}
        ${s.status === "quotation" && s.quote_valid_until ? `<div class="notice info" style="margin-top:18px">This quotation is valid until ${fdate(s.quote_valid_until)}.</div>` : ""}
        ${s.paused ? `<div class="notice info" style="margin-top:18px">Billing is paused. No invoices are created until it is resumed.</div>` : ""}
        <div class="facts">
          <div><span>Customer</span><strong>${esc(s.customer)}</strong><br><small class="muted">${esc(s.customer_email)}</small></div>
          <div><span>Start date</span><strong>${fdate(s.start_date)}</strong></div>
          <div><span>Expiry date</span><strong>${s.expiry_date ? fdate(s.expiry_date) : "Runs until closed"}</strong></div>
          <div><span>Next invoice</span><strong>${s.status === "active" && !s.paused ? fdate(s.next_invoice_date) : "-"}</strong></div>
          <div><span>Payment terms</span><strong>${s.payment_terms_days ? s.payment_terms_days + " days" : "Due on receipt"}</strong></div>
          <div><span>Plan rules</span><strong style="font-weight:500;font-size:13px">${[rules.pausable && "Can pause", rules.renewable && "Renewable", rules.closable ? "Can close early" : "No early close", rules.auto_close && "Auto-closes at expiry"].filter(Boolean).join(", ")}</strong></div>
        </div>
        <h3 class="section-title">Order lines</h3>
        <div class="table-wrap"><table class="data"><thead><tr><th>Product</th><th class="n">Qty</th><th class="n">Unit price</th><th class="n">Discount</th><th class="n">Tax</th><th class="n">Amount</th></tr></thead><tbody>
          ${s.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="n">${l.quantity}</td><td class="n">${money(l.unit_price)}</td>
            <td class="n">${l.discount_amount ? "-" + money(l.discount_amount) : "-"}</td><td class="n">${l.tax_name ? esc(l.tax_name) : "-"}</td><td class="n">${money(l.total)}</td></tr>`).join("")}
        </tbody></table></div>
        <div class="totals">
          <div><span>Subtotal</span><span>${money(s.subtotal)}</span></div>
          <div><span>Discount${s.discount_code ? ` (${esc(s.discount_code)})` : ""}</span><span>-${money(s.discount_total)}</span></div>
          <div><span>Tax</span><span>${money(s.tax_total)}</span></div>
          <div class="grand"><span>Each ${esc(s.billing_period.replace("ly", "").replace("dai", "day"))}</span><span>${money(s.total)}</span></div>
        </div>
        ${s.discount_code && !s.discount_applied ? `<div class="notice error" style="margin-top:12px">Code ${esc(s.discount_code)} is not applied: ${esc(s.discount_note)}</div>` : ""}
        ${s.notes ? `<h3 class="section-title">Notes</h3><p style="margin:0">${esc(s.notes)}</p>` : ""}
        ${invs.items.length ? `<h3 class="section-title">Invoices</h3><div class="table-wrap"><table class="data"><tbody>
          ${invs.items.map((i) => `<tr class="clickable" data-inv="${i.id}"><td><span class="strong">${esc(i.number)}</span><span class="sub">${fdate(i.period_start)} to ${fdate(i.period_end)}</span></td>
            <td>${invBadge(i)}</td><td class="n">${money(i.total)}</td></tr>`).join("")}</tbody></table></div>` : ""}
        <h3 class="section-title">History</h3>
        <ol class="timeline">${s.history.slice().reverse().map((h) => `<li><strong>${h.action === "status" ? `${STEP_NAMES[h.from] || "New"} to ${STEP_NAMES[h.to]}` : label(h.action)}</strong> by ${esc(h.by)}
          ${h.note ? `<br>${esc(h.note)}` : ""}<time>${esc(h.at.replace("T", " "))}</time></li>`).join("")}</ol>
      </div>
      ${subActions(s) ? `<div class="drawer-actions">${subActions(s)}</div>` : ""}`, reload);

    $$("[data-inv]", d).forEach((r) => (r.onclick = () => openInvoice(r.dataset.inv, reload)));
    $$("[data-act]", d).forEach((b) => (b.onclick = async () => {
      const act = b.dataset.act;
      if (act === "edit") return subscriptionForm(s, after);
      if (act.startsWith("to:")) {
        const to = act.slice(3);
        const texts = {
          quotation: ["Send this quotation?", "The customer can then accept it from their portal."],
          confirmed: ["Accept this quotation?", "The subscription will be confirmed and the team will activate it."],
          active: ["Activate this subscription?", "Billing starts from the start date. The first invoice is created straight away if it is due."],
          closed: [s.status === "active" ? "Close this subscription?" : "Cancel this subscription?", "No more invoices will be created. This cannot be undone."],
        };
        if (!(await confirmBox(texts[to][0], texts[to][1], b.textContent, to === "closed"))) return;
        const r = await run(b, () => api(`/api/subscriptions/${id}/transition`, { method: "POST", body: { to } }));
        if (r) { toast(`${r.number} is now ${STEP_NAMES[r.status].toLowerCase()}.`, "good"); reload(); }
        return;
      }
      const r = await run(b, () => api(`/api/subscriptions/${id}/${act}`, { method: "POST" }));
      if (r) { toast({ pause: "Billing paused.", resume: "Billing resumed.", renew: `Renewed until ${fdate(r.expiry_date)}.` }[act], "good"); reload(); }
    }));
  }

  // ------------------------------------------------------------------ invoices
  async function viewInvoices(main) {
    const f = S.filters.invoices;
    f.page = f.page || 1;
    const data = await api("/api/invoices" + qs(f));
    const internal = isInternal();
    const statuses = internal ? ["draft", "confirmed", "outstanding", "overdue", "paid", "cancelled"] : ["outstanding", "overdue", "paid", "cancelled"];
    main.innerHTML = `
      <div class="page-head"><div><h1>${internal ? "Invoices" : "My invoices"}</h1>
        <p>${internal ? "Created from subscriptions on billing day. Confirm, send, print and record payments." : "View, print and pay your invoices."}</p></div>
        ${internal ? `<div class="actions"><button class="btn" data-confirm-drafts>Confirm all drafts</button><button class="btn primary" data-run-billing>Run billing now</button></div>` : ""}</div>
      <section class="panel">
        <form class="toolbar" data-filter>
          <label class="sr" for="iq">Search</label><input class="input search" id="iq" name="q" type="search" placeholder="Search invoice number${internal ? " or customer" : ""}" value="${esc(f.q || "")}">
          <label class="sr" for="is">Status</label><select class="input" id="is" name="status"><option value="">Every status</option>
            ${statuses.map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${label(s)}</option>`).join("")}</select>
          <label class="sr" for="if">Issued from</label><input class="input" type="date" id="if" name="date_from" value="${esc(f.date_from || "")}" title="Issued from">
          <label class="sr" for="it">Issued to</label><input class="input" type="date" id="it" name="date_to" value="${esc(f.date_to || "")}" title="Issued to">
          <button class="btn" type="submit">Filter</button>
        </form>
        <div class="table-wrap"><table class="data"><thead><tr>
          <th>Invoice</th><th>Period</th><th>Issued</th><th>Due</th><th>Status</th><th class="n">Total</th><th class="n">Still owed</th></tr></thead><tbody>
          ${data.items.map((i) => `<tr class="clickable" data-inv="${i.id}">
            <td><span class="strong">${esc(i.number)}</span><span class="sub">${internal ? esc(i.customer) + " · " : ""}${esc(i.subscription)}</span></td>
            <td>${fdate(i.period_start)} to ${fdate(i.period_end)}</td><td>${fdate(i.issue_date)}</td><td>${fdate(i.due_date)}</td>
            <td>${invBadge(i)}</td><td class="n">${money(i.total)}</td><td class="n">${i.balance > 0 && i.status !== "cancelled" ? money(i.balance) : "-"}</td></tr>`).join("")
            || emptyRow(7, "No invoices match these filters.", internal ? " Run billing to create the invoices that are due." : "")}
        </tbody></table></div>
        ${pager(data, (p) => { f.page = p; viewInvoices(main); })}
      </section>`;
    const reload = () => viewInvoices(main);
    $("[data-filter]", main).onsubmit = (e) => { e.preventDefault(); Object.assign(f, Object.fromEntries(new FormData(e.target)), { page: 1 }); reload(); };
    $$("[data-inv]", main).forEach((r) => (r.onclick = () => openInvoice(r.dataset.inv, reload)));
    if (internal) {
      $("[data-run-billing]", main).onclick = (e) => runBilling(e.target, reload);
      $("[data-confirm-drafts]", main).onclick = (e) => confirmDrafts(e.target, reload);
    }
  }

  async function printInvoice(id) {
    const w = window.open("", "_blank");
    try {
      const res = await fetch(`/api/invoices/${id}/print`, { headers: { Authorization: "Bearer " + S.token } });
      if (!res.ok) throw new Error("Could not load the printable invoice.");
      const html = await res.text();
      if (!w) { toast("Allow pop-ups for this site to print invoices.", "error"); return; }
      w.document.open(); w.document.write(html); w.document.close();
    } catch (e) { if (w) w.close(); toast(e.message, "error"); }
  }

  function payNow(id, amount, after) {
    formModal({
      title: "Pay invoice", submitLabel: `Pay ${money(amount)}`,
      fields: [{ type: "html", html: `<p style="margin-top:0">You are paying the full amount still owed, <strong>${money(amount)}</strong>. This demo records the payment straight away.</p>` },
        { name: "method", label: "Payment method", type: "select", default: "card", options: [{ value: "card", label: "Card" }, { value: "upi", label: "UPI" }, { value: "bank_transfer", label: "Bank transfer" }] }],
      onSubmit: async (v) => {
        const inv = await api(`/api/invoices/${id}/pay`, { method: "POST", body: { method: v.method } });
        toast(`Payment received. ${inv.number} is paid.`, "good");
        after && after();
      },
    });
  }

  async function openInvoice(id, after) {
    const i = await run(null, () => api(`/api/invoices/${id}`));
    if (!i) return;
    const reload = () => { openInvoice(id, after); after && after(); };
    const internal = isInternal();
    const acts = [];
    if (internal && i.status === "draft") acts.push(`<button class="btn primary" data-a="confirm">Confirm invoice</button>`);
    if (internal && i.status === "confirmed") acts.push(`<button class="btn primary" data-a="payment">Record payment</button>`);
    if (!internal && i.status === "confirmed" && i.balance > 0) acts.push(`<button class="btn good" data-a="paynow">Pay ${money(i.balance)}</button>`);
    if (internal && ["confirmed", "paid"].includes(i.status)) acts.push(`<button class="btn" data-a="send">${i.sent_at ? "Send again" : "Send to customer"}</button>`);
    acts.push(`<button class="btn" data-a="print">Print or save PDF</button>`);
    if (internal && ["draft", "confirmed"].includes(i.status) && !i.amount_paid) acts.push(`<button class="btn danger" data-a="cancel">Cancel invoice</button>`);
    const c = i.customer_details;
    const d = openDrawer(`
      <div class="drawer-head"><div><h2>${esc(i.number)} ${invBadge(i)}</h2><p>${esc(i.customer)} · ${esc(i.subscription)}</p></div>
        <button class="closebtn" data-close-drawer aria-label="Close">&times;</button></div>
      <div class="drawer-body">
        <div class="facts" style="margin-top:0">
          <div><span>Billed to</span><strong>${esc(c.name)}</strong><br><small class="muted">${esc(c.company || "")}${c.company ? "<br>" : ""}${esc(c.email)}</small></div>
          <div><span>Billing period</span><strong>${fdate(i.period_start)} to ${fdate(i.period_end)}</strong></div>
          <div><span>Issued / due</span><strong>${fdate(i.issue_date)} / ${fdate(i.due_date)}</strong></div>
          <div><span>Subscription</span><strong><button class="link" data-sub="${i.subscription_id}">${esc(i.subscription)}</button></strong></div>
          <div><span>Sent to customer</span><strong>${i.sent_at ? esc(i.sent_at.replace("T", " ")) : "Not yet"}</strong></div>
          <div><span>Still owed</span><strong class="${i.overdue ? "" : ""}" style="${i.overdue ? "color:var(--overdue)" : ""}">${i.status === "cancelled" ? "-" : money(i.balance)}</strong></div>
        </div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Description</th><th class="n">Qty</th><th class="n">Unit price</th><th class="n">Discount</th><th class="n">Tax</th><th class="n">Amount</th></tr></thead><tbody>
          ${i.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="n">${l.quantity}</td><td class="n">${money(l.unit_price)}</td>
            <td class="n">${l.discount_amount ? "-" + money(l.discount_amount) : "-"}</td><td class="n">${l.tax_name ? `${money(l.tax_amount)}<span class="sub">${esc(l.tax_name)}</span>` : "-"}</td><td class="n">${money(l.total)}</td></tr>`).join("")}
        </tbody></table></div>
        <div class="totals">
          <div><span>Subtotal</span><span>${money(i.subtotal)}</span></div>
          <div><span>Discount${i.discount_code ? ` (${esc(i.discount_code)})` : ""}</span><span>-${money(i.discount_total)}</span></div>
          <div><span>Tax</span><span>${money(i.tax_total)}</span></div>
          <div class="grand"><span>Total</span><span>${money(i.total)}</span></div>
          <div><span>Paid</span><span>${money(i.amount_paid)}</span></div>
          <div><strong>Still owed</strong><strong>${money(i.balance)}</strong></div>
        </div>
        <h3 class="section-title">Payments</h3>
        <div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Method</th><th>Note</th><th class="n">Amount</th></tr></thead><tbody>
          ${i.payments.map((p) => `<tr><td>${fdate(p.payment_date)}</td><td>${esc(METHODS[p.method])}</td><td>${esc(p.note || "")}<span class="sub">Recorded by ${esc(p.recorded_by)}</span></td><td class="n">${money(p.amount)}</td></tr>`).join("")
            || emptyRow(4, "No payments yet.")}</tbody></table></div>
      </div>
      <div class="drawer-actions">${acts.join("")}</div>`, reload);

    const sb = $("[data-sub]", d);
    if (sb) sb.onclick = () => openSubscription(i.subscription_id, after);
    $$("[data-a]", d).forEach((b) => (b.onclick = async () => {
      const a = b.dataset.a;
      if (a === "print") return printInvoice(id);
      if (a === "paynow") return payNow(id, i.balance, reload);
      if (a === "payment") {
        return formModal({
          title: `Record a payment for ${i.number}`, submitLabel: "Record payment",
          fields: [[{ name: "amount", label: "Amount", type: "number", step: "0.01", min: 0.01, default: i.balance, required: true, help: `Still owed: ${money(i.balance)}` },
                    { name: "payment_date", label: "Payment date", type: "date", default: todayISO() }],
                   { name: "method", label: "Method", type: "select", default: "bank_transfer", options: Object.entries(METHODS).map(([value, l]) => ({ value, label: l })) },
                   { name: "note", label: "Note (reference, cheque number...)" }],
          onSubmit: async (v) => {
            const r = await api(`/api/invoices/${id}/payments`, { method: "POST", body: v });
            toast(r.status === "paid" ? `${r.number} is now fully paid.` : `Payment recorded. ${money(r.balance)} still owed.`, "good");
            reload();
          },
        });
      }
      if (a === "cancel" && !(await confirmBox("Cancel this invoice?", "It will no longer count as money owed. This cannot be undone.", "Cancel invoice", true))) return;
      const r = await run(b, () => api(`/api/invoices/${id}/${a}`, { method: "POST" }));
      if (!r) return;
      toast(r.message || { confirm: `${r.number} confirmed.`, cancel: `${r.number} cancelled.`, send: `${r.number} sent.` }[a], r.message && r.message.startsWith("Demo") ? "" : "good");
      reload();
    }));
  }

  // ------------------------------------------------------------------ payments
  async function viewPayments(main) {
    const f = S.filters.payments;
    f.page = f.page || 1;
    const data = await api("/api/payments" + qs(f));
    const internal = isInternal();
    const pageTotal = data.items.reduce((a, p) => a + p.amount, 0);
    main.innerHTML = `
      <div class="page-head"><div><h1>${internal ? "Payments" : "Payment history"}</h1>
        <p>${internal ? "Every payment received, by method and date, against its invoice." : "Payments you have made."}</p></div></div>
      <section class="panel">
        <form class="toolbar" data-filter>
          <label class="sr" for="pm">Method</label><select class="input" id="pm" name="method"><option value="">Every method</option>
            ${Object.entries(METHODS).map(([k, v]) => `<option value="${k}" ${f.method === k ? "selected" : ""}>${v}</option>`).join("")}</select>
          <label class="sr" for="pf">From</label><input class="input" type="date" id="pf" name="date_from" value="${esc(f.date_from || "")}" title="Paid from">
          <label class="sr" for="pt">To</label><input class="input" type="date" id="pt" name="date_to" value="${esc(f.date_to || "")}" title="Paid to">
          <button class="btn" type="submit">Filter</button>
          <span class="muted" style="margin-left:auto;font-size:13px">${data.total} payment${data.total === 1 ? "" : "s"}, ${money(pageTotal)} on this page</span>
        </form>
        <div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Invoice</th>${internal ? "<th>Customer</th>" : ""}<th>Method</th><th>Note</th><th class="n">Amount</th></tr></thead><tbody>
          ${data.items.map((p) => `<tr class="clickable" data-inv="${p.invoice_id}"><td>${fdate(p.payment_date)}</td><td class="strong">${esc(p.invoice)}</td>
            ${internal ? `<td>${esc(p.customer)}</td>` : ""}<td>${esc(METHODS[p.method])}</td><td>${esc(p.note || "")}</td><td class="n">${money(p.amount)}</td></tr>`).join("")
            || emptyRow(internal ? 6 : 5, "No payments match these filters.")}
        </tbody></table></div>
        ${pager(data, (p) => { f.page = p; viewPayments(main); })}
      </section>`;
    const reload = () => viewPayments(main);
    $("[data-filter]", main).onsubmit = (e) => { e.preventDefault(); Object.assign(f, Object.fromEntries(new FormData(e.target)), { page: 1 }); reload(); };
    $$("[data-inv]", main).forEach((r) => (r.onclick = () => openInvoice(r.dataset.inv, reload)));
  }

  // ------------------------------------------------------------------ customers
  async function viewCustomers(main) {
    const f = S.filters.customers;
    const list = await api("/api/customers" + qs({ q: f.q }));
    main.innerHTML = `
      <div class="page-head"><div><h1>Customers</h1><p>Everyone who buys from Brightloop. Select a customer to see their subscriptions.</p></div>
        <div class="actions"><button class="btn primary" data-new>Add customer</button></div></div>
      <section class="panel">
        <form class="toolbar" data-filter><label class="sr" for="cq">Search</label>
          <input class="input search" id="cq" name="q" type="search" placeholder="Search name, email or company" value="${esc(f.q || "")}"><button class="btn" type="submit">Search</button></form>
        <div class="table-wrap"><table class="data"><thead><tr><th>Customer</th><th>Company</th><th>Phone</th><th class="n">Active subscriptions</th><th>Joined</th></tr></thead><tbody>
          ${list.map((c) => `<tr class="clickable" data-cust="${c.id}" data-name="${esc(c.name)}"><td><span class="strong">${esc(c.name)}</span><span class="sub">${esc(c.email)}</span></td>
            <td>${esc(c.company || "-")}</td><td>${esc(c.phone || "-")}</td><td class="n">${c.active_subscriptions}</td><td>${fdate(c.created_at)}</td></tr>`).join("")
            || emptyRow(5, "No customers found.", " Try a different search or add a customer.")}</tbody></table></div>
      </section>`;
    $("[data-filter]", main).onsubmit = (e) => { e.preventDefault(); f.q = new FormData(e.target).get("q"); viewCustomers(main); };
    $$("[data-cust]", main).forEach((r) => (r.onclick = () => { S.filters.subs = { customer_id: r.dataset.cust, customer_name: r.dataset.name }; location.hash = "subscriptions"; }));
    $("[data-new]", main).onclick = () => formModal({
      title: "Add customer", submitLabel: "Add customer",
      fields: [[{ name: "name", label: "Name", required: true }, { name: "company", label: "Company" }],
        [{ name: "email", label: "Email", type: "email", required: true }, { name: "phone", label: "Phone" }],
        { name: "address", label: "Billing address", type: "textarea" },
        { name: "password", label: "Temporary password", type: "text", required: true, help: "More than 8 characters with an uppercase letter, a lowercase letter and a special character. Share it with the customer, or ask them to use 'Forgot password'." }],
      onSubmit: async (v) => { await api("/api/customers", { method: "POST", body: v }); forget("customers"); toast(`${v.name} added.`, "good"); viewCustomers(main); },
    });
  }

  // ------------------------------------------------------------------ catalog
  const CATALOG_TABS = [["products", "Products"], ["plans", "Plans"], ["discounts", "Discounts"], ["taxes", "Taxes"], ["templates", "Quotation templates"]];

  async function viewCatalog(main, tab) {
    tab = CATALOG_TABS.some((t) => t[0] === tab) ? tab : "products";
    const admin = isAdmin();
    const [taxes, products, plans] = await Promise.all([lookup("taxes"), lookup("products"), lookup("plans")]);
    const taxOpts = taxes.filter((t) => t.is_active).map((t) => ({ value: t.id, label: `${t.name}` }));
    const reload = () => viewCatalog(main, tab);
    let head = "", body = "", fields = [], toBody = (v) => v, path = "", noun = "";

    if (tab === "products") {
      const rows = await lookup("products");
      noun = "product"; path = "/api/products";
      head = `<th>Product</th><th>Type</th><th>Variants</th><th>Tax</th><th class="n">Cost price</th><th class="n">Sales price</th><th>Status</th>`;
      body = rows.map((p) => `<tr class="${admin ? "clickable" : ""}" data-id="${p.id}"><td><span class="strong">${esc(p.name)}</span><span class="sub">${esc(p.notes || "")}</span></td>
        <td>${label(p.product_type)}</td><td><div class="chips">${p.variants.map((v) => `<span class="chip">${esc(v.attribute)}: ${esc(v.value)}${v.extra_price ? " +" + money(v.extra_price) : ""}</span>`).join("") || "-"}</div></td>
        <td>${esc(p.tax ? p.tax.name : "-")}</td><td class="n">${money(p.cost_price)}</td><td class="n">${money(p.sales_price)}</td><td>${p.is_active ? badge("active", "Available") : badge("closed", "Archived")}</td></tr>`).join("");
      fields = [[{ name: "name", label: "Name", required: true }, { name: "product_type", label: "Type", type: "select", default: "service", options: [{ value: "service", label: "Service" }, { value: "addon", label: "Add-on" }, { value: "goods", label: "Goods" }] }],
        [{ name: "sales_price", label: "Sales price", type: "number", step: "0.01", min: 0, required: true }, { name: "cost_price", label: "Cost price", type: "number", step: "0.01", min: 0, default: 0 },
         { name: "tax_id", label: "Tax", type: "select", numeric: true, placeholder: "No tax", options: taxOpts }],
        { name: "variants", type: "rows", label: "Variants", addLabel: "Add variant", help: "Example: Brand / Odoo / 560 adds 560 to the price when that variant is chosen.",
          columns: [{ name: "attribute", label: "Attribute", default: "Brand" }, { name: "value", label: "Value" }, { name: "extra_price", label: "Extra price", type: "number", step: "0.01", min: 0, default: 0 }] },
        { name: "notes", label: "Notes", type: "textarea" }, { name: "is_active", label: "Available for new subscriptions", type: "checkbox", default: true }];
      toBody = (v) => ({ ...v, cost_price: v.cost_price || 0, variants: v.variants.filter((x) => x.value).map((x) => ({ ...x, extra_price: x.extra_price || 0, attribute: x.attribute || "Variant" })) });
    } else if (tab === "plans") {
      noun = "plan"; path = "/api/plans";
      head = `<th>Plan</th><th>Billing</th><th class="n">Min qty</th><th>Available</th><th>Rules</th><th class="n">Price</th><th>Status</th>`;
      body = plans.map((p) => `<tr class="${admin ? "clickable" : ""}" data-id="${p.id}"><td><span class="strong">${esc(p.name)}</span><span class="sub">${esc(p.description || "")}</span></td>
        <td>${PERIODS[p.billing_period]}</td><td class="n">${p.min_quantity}</td><td>${fdate(p.start_date)}${p.end_date ? " to " + fdate(p.end_date) : " onwards"}</td>
        <td><div class="chips">${[p.auto_close && "Auto-close", p.closable && "Close early", p.pausable && "Pause", p.renewable && "Renew"].filter(Boolean).map((x) => `<span class="chip">${x}</span>`).join("")}</div></td>
        <td class="n">${money(p.price)}</td><td>${p.is_active ? badge("active", "Offered") : badge("closed", "Withdrawn")}</td></tr>`).join("");
      fields = [[{ name: "name", label: "Name", required: true }, { name: "price", label: "Price per period", type: "number", step: "0.01", min: 0, required: true }],
        [{ name: "billing_period", label: "Bills every", type: "select", default: "monthly", options: Object.entries(PERIODS).map(([value, l]) => ({ value, label: l })) },
         { name: "min_quantity", label: "Minimum quantity", type: "number", min: 1, default: 1 }, { name: "tax_id", label: "Tax", type: "select", numeric: true, placeholder: "No tax", options: taxOpts }],
        [{ name: "start_date", label: "Available from", type: "date", default: todayISO(), required: true }, { name: "end_date", label: "Available until (optional)", type: "date" }],
        { name: "description", label: "Description", type: "textarea" },
        { type: "html", html: `<p class="muted" style="margin:4px 0 8px;font-size:13px">What can happen to subscriptions on this plan</p>` },
        [{ name: "auto_close", label: "Close on its own at expiry", type: "checkbox" }, { name: "closable", label: "Can be closed early", type: "checkbox", default: true }],
        [{ name: "pausable", label: "Can be paused", type: "checkbox" }, { name: "renewable", label: "Can be renewed", type: "checkbox", default: true }],
        { name: "is_active", label: "Offered to new subscriptions", type: "checkbox", default: true }];
    } else if (tab === "discounts") {
      const rows = await lookup("discounts");
      noun = "discount rule"; path = "/api/discounts";
      head = `<th>Code</th><th>Gives</th><th>Conditions</th><th>Valid</th><th class="n">Used</th><th>Status</th>`;
      body = rows.map((d) => `<tr class="${admin ? "clickable" : ""}" data-id="${d.id}"><td><span class="strong">${esc(d.code)}</span><span class="sub">${esc(d.name)}</span></td>
        <td>${d.discount_type === "percentage" ? `${d.value}% off` : `${money(d.value)} off`}<span class="sub">${d.applies_to === "product" ? "On " + esc(d.product) : "Whole subscription"}</span></td>
        <td>${[d.min_amount ? "Min " + money(d.min_amount) : "", d.min_quantity ? "Min qty " + d.min_quantity : ""].filter(Boolean).join(", ") || "None"}</td>
        <td>${fdate(d.start_date)}${d.end_date ? " to " + fdate(d.end_date) : " onwards"}</td><td class="n">${d.used_count}${d.usage_limit ? " / " + d.usage_limit : ""}</td>
        <td>${d.usable ? badge("active", "Usable") : badge("closed", d.status_note.replace("This discount ", "").replace(/\.$/, ""))}</td></tr>`).join("");
      fields = [[{ name: "code", label: "Code", required: true, help: "Customers type this, e.g. SEATS15" }, { name: "name", label: "Name", required: true }],
        [{ name: "discount_type", label: "Type", type: "select", default: "percentage", options: [{ value: "percentage", label: "Percentage" }, { value: "fixed", label: "Fixed amount" }] },
         { name: "value", label: "Value", type: "number", step: "0.01", min: 0.01, required: true }],
        [{ name: "min_amount", label: "Minimum purchase", type: "number", step: "0.01", min: 0, default: 0 }, { name: "min_quantity", label: "Minimum quantity", type: "number", min: 0, default: 0 },
         { name: "usage_limit", label: "Usage limit", type: "number", min: 1, help: "Empty = unlimited" }],
        [{ name: "start_date", label: "Starts", type: "date", default: todayISO(), required: true }, { name: "end_date", label: "Ends (optional)", type: "date" }],
        [{ name: "applies_to", label: "Applies to", type: "select", default: "subscription", options: [{ value: "subscription", label: "Whole subscription" }, { value: "product", label: "One product" }] },
         { name: "product_id", label: "Product (if one product)", type: "select", numeric: true, placeholder: "-", options: products.map((p) => ({ value: p.id, label: p.name })) }],
        { name: "is_active", label: "Active", type: "checkbox", default: true }];
      toBody = (v) => ({ ...v, min_amount: v.min_amount || 0, min_quantity: v.min_quantity || 0 });
    } else if (tab === "taxes") {
      noun = "tax"; path = "/api/taxes";
      head = `<th>Tax</th><th class="n">Rate</th><th>Status</th>`;
      body = taxes.map((t) => `<tr class="${admin ? "clickable" : ""}" data-id="${t.id}"><td class="strong">${esc(t.name)}</td><td class="n">${t.rate}%</td><td>${t.is_active ? badge("active", "In use") : badge("closed", "Retired")}</td></tr>`).join("");
      fields = [[{ name: "name", label: "Name", required: true }, { name: "rate", label: "Rate (%)", type: "number", step: "0.01", min: 0, required: true }],
        { name: "is_active", label: "Active", type: "checkbox", default: true }];
    } else {
      const rows = await lookup("templates");
      const items = await itemOptions();
      noun = "quotation template"; path = "/api/templates";
      head = `<th>Template</th><th>Plan</th><th>Products</th><th class="n">Valid for</th><th>Status</th>`;
      body = rows.map((t) => `<tr class="${admin ? "clickable" : ""}" data-id="${t.id}"><td><span class="strong">${esc(t.name)}</span><span class="sub">${esc(t.notes || "")}</span></td>
        <td>${esc(t.plan)} x ${t.plan_quantity}</td><td><div class="chips">${t.lines.map((l) => `<span class="chip">${esc(l.product)}${l.variant ? " (" + esc(l.variant) + ")" : ""} x ${l.quantity}</span>`).join("") || "-"}</div></td>
        <td class="n">${t.validity_days} days</td><td>${t.is_active ? badge("active", "Active") : badge("closed", "Archived")}</td></tr>`).join("");
      fields = [{ name: "name", label: "Name", required: true },
        [{ name: "plan_id", label: "Plan", type: "select", numeric: true, required: true, placeholder: "Choose a plan", options: plans.map((p) => ({ value: p.id, label: p.name })) },
         { name: "plan_quantity", label: "Plan quantity", type: "number", min: 1, default: 1 }, { name: "validity_days", label: "Valid for (days)", type: "number", min: 1, default: 30 }],
        { name: "lines", type: "rows", label: "Product lines", addLabel: "Add product", columns: [{ name: "item", label: "Product", type: "select", options: items, placeholder: "Choose...", width: "3fr" }, { name: "quantity", label: "Qty", type: "number", min: 1, default: 1, width: "90px" }] },
        { name: "notes", label: "Notes", type: "textarea" }, { name: "is_active", label: "Active", type: "checkbox", default: true }];
      toBody = (v) => ({ ...v, lines: v.lines.filter((l) => l.item).map((l) => { const [p, vr] = l.item.split(":"); return { product_id: Number(p), variant_id: vr ? Number(vr) : null, quantity: l.quantity || 1 }; }) });
    }

    main.innerHTML = `
      <div class="page-head"><div><h1>Products & plans</h1><p>${admin ? "Set up what Brightloop sells, how it is billed, taxed and discounted." : "Read-only for staff. Only the admin can change the catalog."}</p></div>
        ${admin ? `<div class="actions"><button class="btn primary" data-new>Add ${noun}</button></div>` : ""}</div>
      <nav class="tabs" aria-label="Catalog sections">${CATALOG_TABS.map(([k, v]) => `<a href="#catalog/${k}" aria-current="${k === tab ? "page" : "false"}">${v}</a>`).join("")}</nav>
      <section class="panel"><div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body || emptyRow(8, `No ${noun}s yet.`, admin ? ` Add the first ${noun}.` : "")}</tbody></table></div></section>`;

    const all = { products, plans, taxes, discounts: S.cache.discounts, templates: S.cache.templates }[tab] || [];
    const save = (item) => formModal({
      title: item ? `Edit ${noun}` : `Add ${noun}`, wide: ["products", "plans", "discounts", "templates"].includes(tab), fields,
      values: item ? (tab === "templates" ? { ...item, lines: item.lines.map((l) => ({ item: `${l.product_id}:${l.variant_id || ""}`, quantity: l.quantity })) } : item) : {},
      submitLabel: item ? "Save changes" : `Add ${noun}`,
      onSubmit: async (v) => {
        await api(item ? `${path}/${item.id}` : path, { method: item ? "PUT" : "POST", body: toBody(v) });
        forget(tab, "products", "plans", "templates");
        toast(item ? "Changes saved." : `${label(noun)} added.`, "good");
        reload();
      },
    });
    if (admin) {
      $("[data-new]", main).onclick = () => save(null);
      $$("tr[data-id]", main).forEach((r) => (r.onclick = () => save(all.find((x) => String(x.id) === r.dataset.id))));
    }
  }

  // ------------------------------------------------------------------ team
  async function viewTeam(main) {
    const team = await api("/api/users");
    main.innerHTML = `
      <div class="page-head"><div><h1>Team</h1><p>Only an admin can add staff. Staff handle customers, subscriptions and invoices, but cannot change the catalog.</p></div>
        <div class="actions"><button class="btn primary" data-new>Add team member</button></div></div>
      <section class="panel"><div class="table-wrap"><table class="data"><thead><tr><th>Name</th><th>Role</th><th>Department</th><th>Status</th><th></th></tr></thead><tbody>
        ${team.map((u) => `<tr><td><span class="strong">${esc(u.name)}</span><span class="sub">${esc(u.email)}</span></td><td>${label(u.role)}</td><td>${esc(u.department || "-")}</td>
          <td>${u.is_active ? badge("active", "Active") : badge("closed", "Deactivated")}</td>
          <td class="n">${u.id === S.user.id ? '<span class="muted">You</span>' : `<button class="btn small ${u.is_active ? "danger" : ""}" data-toggle="${u.id}">${u.is_active ? "Deactivate" : "Reactivate"}</button>`}</td></tr>`).join("")}
      </tbody></table></div></section>`;
    $$("[data-toggle]", main).forEach((b) => (b.onclick = async () => {
      const r = await run(b, () => api(`/api/users/${b.dataset.toggle}/toggle-active`, { method: "POST" }));
      if (r) { toast(`${r.name} ${r.is_active ? "reactivated" : "deactivated and signed out"}.`, "good"); viewTeam(main); }
    }));
    $("[data-new]", main).onclick = () => formModal({
      title: "Add team member", submitLabel: "Add team member",
      fields: [[{ name: "name", label: "Name", required: true }, { name: "email", label: "Email", type: "email", required: true }],
        [{ name: "role", label: "Role", type: "select", default: "staff", options: [{ value: "staff", label: "Staff" }, { value: "admin", label: "Admin" }] }, { name: "department", label: "Department" }],
        { name: "password", label: "Temporary password", required: true, help: "More than 8 characters with an uppercase letter, a lowercase letter and a special character." }],
      onSubmit: async (v) => { await api("/api/users", { method: "POST", body: v }); toast(`${v.name} added to the team.`, "good"); viewTeam(main); },
    });
  }

  // ------------------------------------------------------------------ profile
  async function viewProfile(main) {
    const me = await api("/api/auth/me");
    const fields = [[{ name: "name", label: "Name", required: true }, { name: "company", label: "Company" }],
      [{ name: "email", label: "Email", readonly: true, help: "Your email cannot be changed." }, { name: "phone", label: "Phone" }],
      { name: "address", label: "Billing address", type: "textarea" }];
    main.innerHTML = `<div class="page-head"><div><h1>My details</h1><p>Used on your invoices.</p></div></div>
      <section class="panel" style="max-width:680px"><form class="panel-body" data-form>${formHTML(fields, me)}
        <div class="actions" style="justify-content:space-between"><a class="link" href="#forgot" data-reset>Change password</a><button class="btn primary" type="submit">Save details</button></div></form></section>`;
    $("[data-reset]", main).onclick = async (e) => {
      e.preventDefault();
      const r = await run(null, () => api("/api/auth/forgot-password", { method: "POST", body: { email: me.email } }));
      if (!r) return;
      if (r.demo_reset_link) openModal({ title: "Change password", body: `<div class="notice info">Demo mode, no mail server is set up. Open this link to choose a new password:<br><a href="${esc(r.demo_reset_link)}">${esc(r.demo_reset_link)}</a></div>` });
      else toast("We emailed you a link to change your password.", "good");
    };
    $("[data-form]", main).onsubmit = async (e) => {
      e.preventDefault();
      const v = readForm(e.target, fields);
      const r = await run($('button[type="submit"]', e.target), () => api("/api/auth/me", { method: "PUT", body: { name: v.name, company: v.company, phone: v.phone, address: v.address } }));
      if (r) { S.user = r; store.set("user", r); $(".who strong").textContent = r.name; toast("Details saved.", "good"); }
    };
  }

  // ------------------------------------------------------------------ start
  route();
})();
