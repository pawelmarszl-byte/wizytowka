// Ledgerly front-end glue. Everything important happens on the server; this file only adds
// icons, toasts, the theme switch, chart hover, staged progress and small niceties.
(function () {
  "use strict";

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };

  function icons() {
    if (window.lucide) window.lucide.createIcons();
  }

  // ---------------------------------------------------------------- toasts
  const TOAST_ICONS = { success: "circle-check", warning: "triangle-alert", danger: "circle-x", info: "bell" };

  function toast(text, tone) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast tone-" + (tone || "info");
    const i = document.createElement("i");
    i.setAttribute("data-lucide", TOAST_ICONS[tone] || "bell");
    const span = document.createElement("span");
    span.textContent = text;
    el.append(i, span);
    box.appendChild(el);
    icons();
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 3800);
  }

  document.body.addEventListener("toast", (e) => toast(e.detail.text, e.detail.tone));

  // ---------------------------------------------------------------- theme
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-theme-toggle]")) {
      const root = document.documentElement;
      const dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      store.set("ledgerly-theme", root.dataset.theme);
    }
    if (e.target.closest("[data-open-welcome]")) document.getElementById("welcome").showModal();
  });

  // ---------------------------------------------------------------- welcome + missions
  function firstVisit() {
    if (!store.get("ledgerly-welcomed")) {
      const dlg = document.getElementById("welcome");
      if (dlg && dlg.showModal) dlg.showModal();
      store.set("ledgerly-welcomed", "1");
    }
  }

  function missionsState() {
    const card = document.querySelector(".missions-card");
    if (!card) return;
    const pref = store.get("ledgerly-missions");
    card.open = pref ? pref === "open" : card.hasAttribute("data-autoopen") && window.innerWidth > 860;
    card.addEventListener("toggle", () => store.set("ledgerly-missions", card.open ? "open" : "closed"));
  }

  // ---------------------------------------------------------------- relative times + countdown
  function ago() {
    const now = Date.now() / 1000;
    document.querySelectorAll("time[data-ago]").forEach((t) => {
      const s = Math.max(0, Math.round(now - Number(t.dataset.ago)));
      t.textContent = s < 10 ? "just now" : s < 60 ? s + "s ago" : Math.floor(s / 60) + " min ago";
    });
  }

  let countdownTimer;
  function countdown() {
    clearInterval(countdownTimer);
    const el = document.querySelector("[data-countdown] b");
    if (!el) return;
    let left = Number(el.parentElement.dataset.countdown);
    countdownTimer = setInterval(() => {
      left = Math.max(0, left - 1);
      el.textContent = left;
    }, 1000);
  }

  // ---------------------------------------------------------------- chart hover
  function bindChart(root) {
    root.querySelectorAll("svg[data-chart]").forEach((svg) => {
      if (svg.dataset.bound) return;
      svg.dataset.bound = "1";
      const wrap = svg.parentElement;
      const tip = wrap.querySelector("[data-tip]");
      const cross = svg.querySelector("[data-crosshair]");

      function show(hit) {
        const x = Number(hit.dataset.x);
        cross.setAttribute("x1", x);
        cross.setAttribute("x2", x);
        cross.style.opacity = ".5";
        tip.replaceChildren();
        const day = document.createElement("div");
        day.className = "tip-day";
        day.textContent = hit.dataset.day;
        tip.appendChild(day);
        [["Bank", hit.dataset.bank, "var(--series-bank)"], ["Ledger", hit.dataset.ledger, "var(--series-ledger)"]].forEach(([label, val, color]) => {
          const row = document.createElement("div");
          row.className = "row";
          const k = document.createElement("i");
          k.className = "k";
          k.style.background = color;
          const b = document.createElement("b");
          b.textContent = val;
          const span = document.createElement("span");
          span.textContent = label;
          row.append(k, span, b);
          tip.appendChild(row);
        });
        const ok = hit.dataset.ok === "1";
        const st = document.createElement("div");
        st.className = "tip-status " + (ok ? "ok" : "bad");
        st.textContent = ok ? "✓ Books match the bank" : "Difference " + hit.dataset.diff;
        tip.appendChild(st);
        tip.hidden = false;

        const box = svg.getBoundingClientRect();
        const scale = box.width / svg.viewBox.baseVal.width;
        const px = x * scale;
        const tw = tip.offsetWidth;
        const left = px + 14 + tw > box.width ? px - 14 - tw : px + 14;
        tip.style.left = Math.max(0, left) + "px";
        tip.style.top = "8px";
      }

      function hide() {
        tip.hidden = true;
        cross.style.opacity = "0";
      }

      svg.querySelectorAll(".hit").forEach((hit) => {
        hit.addEventListener("pointerenter", () => show(hit));
        hit.addEventListener("focus", () => show(hit));
        hit.addEventListener("blur", hide);
      });
      svg.addEventListener("pointerleave", hide);
    });
  }

  // ---------------------------------------------------------------- staged reconciliation progress
  let stageTimer;
  document.body.addEventListener("htmx:beforeRequest", (e) => {
    const btn = e.detail.elt;
    if (!btn.matches || !btn.matches("[data-run-recon]")) return;
    const steps = document.querySelectorAll("#recon-progress li");
    const bar = document.querySelector("#recon-progress .progress span");
    let i = 0;
    const advance = () => {
      steps.forEach((li, n) => { li.classList.toggle("done", n < i); li.classList.toggle("on", n === i); });
      if (bar) bar.style.width = Math.min(95, (i + 1) * 24) + "%";
      i = Math.min(i + 1, steps.length - 1);
    };
    advance();
    clearInterval(stageTimer);
    stageTimer = setInterval(advance, 380);
  });

  // ---------------------------------------------------------------- statement list helpers
  let knownStatements = null;

  function highlightArrivals(root) {
    const items = Array.from(document.querySelectorAll("#statement-list [data-stmt]"));
    if (!items.length) return;
    const ids = new Set(items.map((b) => b.dataset.stmt));
    if (knownStatements) {
      items.forEach((b) => { if (!knownStatements.has(b.dataset.stmt)) b.parentElement.classList.add("arrived"); });
    }
    knownStatements = ids;
  }

  function markSelected(number) {
    document.querySelectorAll("#statement-list .stmt").forEach((b) => {
      b.classList.toggle("selected", b.dataset.stmt === String(number));
    });
    const list = document.getElementById("statement-list");
    if (list) {
      const url = new URL(list.getAttribute("hx-get"), location.origin);
      url.searchParams.set("selected", number);
      list.setAttribute("hx-get", url.pathname + url.search);
      htmx.process(list);
    }
    if (location.pathname === "/statements") history.replaceState(null, "", "/statements?open=" + number);
  }

  window.Ledgerly = { toast, markSelected };

  // ---------------------------------------------------------------- lifecycle
  function refresh(root) {
    icons();
    ago();
    countdown();
    bindChart(root || document);
    highlightArrivals(root);
  }

  function syncNav() {
    const main = document.getElementById("main");
    if (!main) return;
    document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.nav === main.dataset.page));
  }

  document.body.addEventListener("htmx:afterSettle", (e) => {
    clearInterval(stageTimer);
    if (e.detail.elt && e.detail.elt.id === "main") {
      syncNav();
      htmx.trigger(document.body, "refresh-missions");
    }
    refresh(e.detail.elt);
    if (e.detail.elt && e.detail.elt.id === "missions") missionsState();
  });
  document.body.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.boosted) knownStatements = null;
  });
  document.body.addEventListener("htmx:sendError", () => toast("Can't reach the server - is it waking up? Try again in a few seconds.", "danger"));
  document.body.addEventListener("htmx:responseError", (e) => {
    if (e.detail.xhr.status >= 500) toast("Something went wrong on the server.", "danger");
  });

  refresh(document);
  missionsState();
  firstVisit();
  setInterval(ago, 15000);
})();
