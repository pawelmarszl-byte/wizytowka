/* Scroll-driven touches on the home page, all on the accounting theme:
 *   - the figures strip rolls its numbers in like an old adding machine,
 *   - each role in "The path" gets a POSTED stamp as it scrolls in, and the total row balances when all are in,
 *   - the bank-vs-ledger chart draws itself, then fixes its three mistakes until the difference is 0.00,
 *   - copying the email address prints a little receipt (window.printReceipt, called from home.html).
 *
 * Without JS everything is simply shown in its final state; with prefers-reduced-motion the receipt still
 * appears (it confirms the copy) but nothing else moves.
 */
(function () {
  "use strict";
  var motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;

  // Run fn once, the first time el is well inside the viewport.
  function onView(el, fn, threshold) {
    if (!("IntersectionObserver" in window)) { fn(); return; }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { io.unobserve(e.target); fn(e.target); } });
    }, { threshold: threshold || 0.35 });
    io.observe(el);
  }

  // ---------------------------------------------------------------- receipt (also without motion)
  var receipt = document.getElementById("receipt"), receiptNo = document.getElementById("receipt-no"), copies = 0, rT = 0;
  window.printReceipt = function () {
    if (!receipt) return;
    copies++;
    receiptNo.textContent = "#" + String(copies).padStart(4, "0");
    clearTimeout(rT);
    receipt.classList.remove("is-printing", "is-torn");
    void receipt.offsetWidth; // restart the animation on a second copy
    receipt.classList.add("is-printing");
    rT = setTimeout(function () {
      receipt.classList.remove("is-printing"); receipt.classList.add("is-torn");
      rT = setTimeout(function () { receipt.classList.remove("is-torn"); }, 800);
    }, 3200);
  };

  if (!motion) return;

  // ---------------------------------------------------------------- odometer figures
  [].forEach.call(document.querySelectorAll("[data-roll]"), function (b, k) {
    var text = b.textContent, strips = [];
    b.textContent = "";
    var sr = document.createElement("span"); sr.className = "sr-only"; sr.textContent = text; b.appendChild(sr);
    var vis = document.createElement("span"); vis.setAttribute("aria-hidden", "true"); b.appendChild(vis);
    text.split("").forEach(function (ch, i) {
      if (!/\d/.test(ch)) { vis.appendChild(document.createTextNode(ch)); return; }
      var roll = document.createElement("span"), strip = document.createElement("span");
      roll.className = "roll"; strip.className = "roll-strip";
      for (var d = 0; d <= 19; d++) { var s = document.createElement("span"); s.textContent = d % 10; strip.appendChild(s); }
      strip.style.transitionDelay = (k * 140 + i * 90) + "ms";
      roll.appendChild(strip); vis.appendChild(roll);
      strips.push({ el: strip, target: 10 + +ch });
    });
    onView(b, function () {
      strips.forEach(function (s) { s.el.style.translate = "0 " + (-1.1 * s.target) + "em"; });
    }, 0.6);
  });

  // ---------------------------------------------------------------- posted stamps + balancing total
  var rows = [].slice.call(document.querySelectorAll(".ledger-row:not(.ledger-head):not(.ledger-total)"));
  var total = document.getElementById("ledger-total"), posted = 0;
  rows.forEach(function (row) {
    onView(row, function () {
      row.classList.add("is-posted");
      if (++posted === rows.length && total) setTimeout(function () { total.classList.add("is-balanced"); }, 500);
    }, 0.6);
  });

  // ---------------------------------------------------------------- the chart
  var chart = document.getElementById("recon");
  if (chart) {
    var data = JSON.parse(chart.dataset.chart);
    var svg = chart.querySelector("svg");
    var bankP = svg.querySelector(".recon-bank"), ledgerP = svg.querySelector(".recon-ledger"), gapP = svg.querySelector(".recon-gap");
    var marks = [].slice.call(svg.querySelectorAll(".recon-mark")), diffEl = document.getElementById("recon-diff");
    var n = data.bank.length, pad = data.pad, weights = data.mistakes.map(function () { return 1; });
    var X = function (i) { return pad[0] + (data.w - pad[0] - pad[1]) * i / (n - 1); };
    var Y = function (v) { return pad[2] + (data.h - pad[2] - pad[3]) * (1 - (v - data.lo) / (data.hi - data.lo)); };
    var fmt = function (v) { return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
    var ledger = function () {
      return data.bank.map(function (b, i) {
        var v = b;
        data.mistakes.forEach(function (m, k) { if (m.start <= i && i <= m.end) v += m.amount * weights[k]; });
        return v;
      });
    };
    var line = function (vals) {
      return "M" + vals.map(function (v, i) { return X(i).toFixed(1) + " " + Y(v).toFixed(1); }).join(" L");
    };
    var draw = function () {
      var l = ledger();
      ledgerP.setAttribute("d", line(l));
      var back = [];
      for (var i = n - 1; i >= 0; i--) back.push(X(i).toFixed(1) + " " + Y(data.bank[i]).toFixed(1));
      gapP.setAttribute("d", line(l) + " L" + back.join(" L") + " Z");
      var d = l[n - 1] - data.bank[n - 1];
      diffEl.textContent = Math.abs(d) < 0.005 ? "0.00" : fmt(d);
    };
    var tween = function (ms, fn, done) {
      var t0 = performance.now();
      (function tick(now) {
        var k = Math.min(1, (now - t0) / ms);
        fn(k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
        if (k < 1) requestAnimationFrame(tick); else if (done) done();
      })(t0);
    };
    var later = function (ms, fn) { setTimeout(fn, ms); };

    // the "before" state: lines not drawn yet, gap and labels hidden
    var hide = function () {
      [bankP, ledgerP].forEach(function (p) {
        var len = p.getTotalLength();
        p.style.transition = "none"; p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
      });
      gapP.style.transition = "none"; gapP.style.opacity = 0;
      marks.forEach(function (m) { m.style.opacity = 0; m.classList.remove("is-fixed"); });
    };
    var play = function () {
      weights = weights.map(function () { return 1; });
      chart.classList.remove("is-balanced");
      draw(); hide();
      void svg.getBoundingClientRect();
      [bankP, ledgerP].forEach(function (p, i) {
        p.style.transition = "stroke-dashoffset 1.4s cubic-bezier(.5, 0, .2, 1) " + (i * 0.25) + "s"; p.style.strokeDashoffset = 0;
      });
      later(1500, function () {
        [bankP, ledgerP].forEach(function (p) { p.style.strokeDasharray = "none"; });
        gapP.style.transition = "opacity .5s"; gapP.style.opacity = "";
        marks.forEach(function (m, i) { m.style.transition = "opacity .35s " + (i * 0.15) + "s"; m.style.opacity = ""; });
      });
      // fix the mistakes one at a time: the timing difference first, then the swapped digits, then the double payment
      var order = [1, 2, 0], at = 3000;
      order.forEach(function (k) {
        later(at, function () {
          marks[k].style.transition = ""; marks[k].classList.add("is-fixed");
          tween(800, function (e) { weights[k] = 1 - e; draw(); });
        });
        at += 1100;
      });
      later(at, function () { chart.classList.add("is-balanced"); replay.hidden = false; });
    };
    var replay = document.createElement("button");
    replay.type = "button"; replay.className = "recon-replay"; replay.textContent = "Replay ↺"; replay.hidden = true;
    replay.addEventListener("click", function () { replay.hidden = true; play(); });
    chart.querySelector(".recon-legend").appendChild(replay);
    hide();
    onView(chart, play, 0.55);
  }
})();
