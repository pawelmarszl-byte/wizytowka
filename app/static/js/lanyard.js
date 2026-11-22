/* ID badge on a lanyard for the home page hero.
 *
 * Verlet physics in 2D, no libraries. The strap is a chain of points that can go slack but not stretch much;
 * the card is a rigid stick of two heavier points (top of the clip, bottom of the card) hanging from its end.
 * On load the card drops from above the page, bounces on the strap and swings to rest; visitors can grab
 * it and throw it around. The loop sleeps once everything is still and while the hero is off screen.
 *
 * Without JS or with prefers-reduced-motion the card simply hangs still (see .hero-badge in home.css).
 */
(function (root) {
  "use strict";

  var G = 2400;          // gravity, px/s²
  var STEP = 1 / 120;    // fixed physics step, s
  var DAMP = 0.993;      // velocity kept per step (air drag)
  var ITER = 14;         // constraint passes per step
  var ROPE_K = 0.7;      // strap stiffness per pass; < 1 gives the drop a little bounce
  var CARD_W = 0.3;      // inverse mass of the card points (strap points are 1): the card is heavier
  var MAX_V = 60;        // px per step, caps a throw
  var ANCHOR_UP = 260;   // how far above the top of the page the strap is fixed, px

  // ---------------------------------------------------------------- simulation (pure, testable in Node)
  function createSim(g) {
    // g: { ax, ay } anchor, { rx, ry } rest position of the clip top, cardLen
    var len = Math.max(20, g.ry - g.ay);
    var n = Math.max(6, Math.round(len / 26));
    var seg = len / n;
    var pts = [];
    for (var i = 0; i <= n + 1; i++) {
      var y = i <= n ? g.ay + seg * i : g.ry + g.cardLen;
      var x = i <= n ? g.ax + (g.rx - g.ax) * (i / n) : g.rx;
      pts.push({ x: x, y: y, px: x, py: y, w: i === 0 ? 0 : i >= n ? CARD_W : 1 });
    }
    var sim = { pts: pts, n: n, seg: seg, len: len, cardLen: g.cardLen, ax: g.ax, ay: g.ay, pin: -1, tx: 0, ty: 0 };
    // The strap gives a little under the card's weight; shorten it so the card comes to rest exactly where
    // the layout put it.
    var rest = pts.map(function (q) { return { x: q.x, y: q.y }; });
    for (var pass = 0; pass < 3; pass++) {
      for (var k = 0; k < 240; k++) step(sim, STEP);
      sim.seg -= (pts[n].y - g.ry) / n;
      reset(sim, rest);
    }
    return sim;
  }

  // Put the clip at (ax + dx, clipY) with the strap loose between it and the anchor, ready to fall.
  // dx tilts the start so the fall turns into a swing.
  function stageDrop(sim, clipY, dx) {
    var p = sim.pts, n = sim.n;
    for (var i = 1; i <= n; i++) {
      var k = i / n;
      var x = sim.ax + dx * k + Math.sin(k * Math.PI) * 40, y = sim.ay + (clipY - sim.ay) * k;
      p[i].x = p[i].px = x; p[i].y = p[i].py = y;
    }
    p[n + 1].x = p[n + 1].px = p[n].x + 8; p[n + 1].y = p[n + 1].py = p[n].y + sim.cardLen;
  }

  function reset(sim, rest) {
    sim.pts.forEach(function (q, i) { q.x = q.px = rest[i].x; q.y = q.py = rest[i].y; });
  }

  function satisfy(sim, a, b, len, k, slack) {
    var dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1e-6;
    if (slack && d <= len) return;
    var wa = a.w, wb = b.w, wsum = wa + wb;
    if (!wsum) return;
    var f = ((d - len) / d) * k / wsum;
    a.x += dx * f * wa; a.y += dy * f * wa;
    b.x -= dx * f * wb; b.y -= dy * f * wb;
  }

  function step(sim, dt) {
    var p = sim.pts, n = sim.n, i, q;
    for (i = 1; i < p.length; i++) {
      q = p[i];
      var vx = (q.x - q.px) * DAMP, vy = (q.y - q.py) * DAMP;
      q.px = q.x; q.py = q.y;
      q.x += vx; q.y += vy + G * dt * dt;
    }
    var pinned = sim.pin >= 0 ? p[sim.pin] : null, w0;
    if (pinned) { w0 = pinned.w; pinned.w = 0; }
    for (var it = 0; it < ITER; it++) {
      if (pinned) { pinned.x = sim.tx; pinned.y = sim.ty; }
      for (i = 0; i < n; i++) satisfy(sim, p[i], p[i + 1], sim.seg, ROPE_K, true);
      satisfy(sim, p[n], p[n + 1], sim.cardLen, 1, false);
    }
    if (pinned) { pinned.x = sim.tx; pinned.y = sim.ty; pinned.w = w0; }
  }

  function energy(sim) {
    var e = 0, p = sim.pts;
    for (var i = 1; i < p.length; i++) {
      var vx = p[i].x - p[i].px, vy = p[i].y - p[i].py;
      e = Math.max(e, vx * vx + vy * vy);
    }
    return e;
  }

  // Clip-top position and card angle (radians, 0 = hanging straight down, positive = swung to the right at the bottom)
  function pose(sim) {
    var a = sim.pts[sim.n], b = sim.pts[sim.n + 1];
    return { x: a.x, y: a.y, angle: Math.atan2(b.x - a.x, b.y - a.y) };
  }

  var api = { createSim: createSim, stageDrop: stageDrop, step: step, energy: energy, pose: pose, STEP: STEP };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  // ---------------------------------------------------------------- page wiring
  var stage = document.getElementById("badge-stage");
  var card = document.getElementById("badge");
  var path = document.getElementById("strap-path");
  var strapSvg = document.getElementById("strap");
  if (!stage || !card || !path || !strapSvg) return;
  if (!matchMedia("(prefers-reduced-motion: no-preference)").matches) return;

  var narrow = matchMedia("(max-width: 860px)");
  var sim = null, geo = null, running = false, visible = true, last = 0, acc = 0, calm = 0;

  // Geometry in stage-local px, measured with the card at rest (no transform).
  function measure() {
    card.style.transform = "";
    var s = stage.getBoundingClientRect(), c = card.getBoundingClientRect();
    var clipH = parseFloat(getComputedStyle(stage).getPropertyValue("--clip-h")) || 30;
    var rx = c.left - s.left + c.width / 2, ry = c.top - s.top - clipH;
    var pageTop = -(s.top + scrollY);
    // The strap is fixed well above the page, so the card can start its fall out of sight.
    // On phones the strap is only drawn below the navigation, so it never runs through the links.
    var cut = pageTop;
    if (narrow.matches) {
      var nav = document.querySelector(".topnav");
      if (nav) cut = nav.getBoundingClientRect().bottom - s.top;
    }
    strapSvg.style.clipPath = "polygon(-5000px " + cut + "px, 5000px " + cut + "px, 5000px 9000px, -5000px 9000px)";
    return { ax: rx, ay: pageTop - ANCHOR_UP, rx: rx, ry: ry, cardLen: c.height + clipH, pageTop: pageTop };
  }

  function render() {
    var p = sim.pts, n = sim.n, pz = pose(sim);
    card.style.transform = "translate(" + (pz.x - geo.rx).toFixed(2) + "px," + (pz.y - geo.ry).toFixed(2) + "px) rotate(" +
      (-pz.angle * 180 / Math.PI).toFixed(3) + "deg)";
    // smooth strap through the midpoints; it ends a few px into the clip ring so the join is hidden
    var d = "M" + p[0].x.toFixed(1) + " " + p[0].y.toFixed(1);
    for (var i = 1; i < n; i++) {
      var mx = (p[i].x + p[i + 1].x) / 2, my = (p[i].y + p[i + 1].y) / 2;
      d += "Q" + p[i].x.toFixed(1) + " " + p[i].y.toFixed(1) + " " + mx.toFixed(1) + " " + my.toFixed(1);
    }
    d += "L" + p[n].x.toFixed(1) + " " + (p[n].y + 4).toFixed(1);
    path.setAttribute("d", d);
  }

  function frame(now) {
    if (!running) return;
    var dt = Math.min(0.05, (now - last) / 1000 || 0);
    last = now; acc += dt;
    while (acc >= STEP) { step(sim, STEP); acc -= STEP; }
    render();
    // sleep once still for a moment (and not held)
    if (sim.pin < 0 && energy(sim) < 0.002) calm++; else calm = 0;
    if (calm > 90) { running = false; return; }
    requestAnimationFrame(frame);
  }

  function wake() {
    calm = 0;
    if (running || !visible || !sim) return;
    running = true; last = performance.now(); acc = 0;
    requestAnimationFrame(frame);
  }

  function build(drop) {
    geo = measure();
    sim = createSim(geo);
    if (drop) stageDrop(sim, geo.pageTop - geo.cardLen - 40, 90);
    stage.classList.add("is-live");
    render();
    wake();
  }

  // ---- dragging
  var grabOff = { x: 0, y: 0 };
  function local(e) {
    var s = stage.getBoundingClientRect();
    return { x: e.clientX - s.left, y: e.clientY - s.top };
  }
  function clampTarget(x, y) {
    var reach = sim.len * 1.04 + (sim.pin === sim.n + 1 ? sim.cardLen : 0);
    var dx = x - sim.ax, dy = y - sim.ay, d = Math.sqrt(dx * dx + dy * dy);
    if (d > reach) { x = sim.ax + dx / d * reach; y = sim.ay + dy / d * reach; }
    sim.tx = x; sim.ty = y;
  }
  card.addEventListener("pointerdown", function (e) {
    if (!sim || e.button > 0) return;
    var m = local(e), a = sim.pts[sim.n], b = sim.pts[sim.n + 1];
    var ux = (b.x - a.x) / sim.cardLen, uy = (b.y - a.y) / sim.cardLen;
    var along = ((m.x - a.x) * ux + (m.y - a.y) * uy) / sim.cardLen;
    sim.pin = along < 0.45 ? sim.n : sim.n + 1; // held near the top: the card dangles; near the bottom: it hangs from the hand
    var q = sim.pts[sim.pin];
    grabOff.x = m.x - q.x; grabOff.y = m.y - q.y;
    clampTarget(q.x, q.y);
    card.setPointerCapture(e.pointerId);
    card.classList.add("is-dragging");
    e.preventDefault();
    wake();
  });
  card.addEventListener("pointermove", function (e) {
    if (!sim || sim.pin < 0) return;
    var m = local(e);
    clampTarget(m.x - grabOff.x, m.y - grabOff.y);
    wake();
  });
  function release() {
    if (!sim || sim.pin < 0) return;
    var q = sim.pts[sim.pin];
    var vx = q.x - q.px, vy = q.y - q.py, v = Math.sqrt(vx * vx + vy * vy);
    if (v > MAX_V) { q.px = q.x - vx / v * MAX_V; q.py = q.y - vy / v * MAX_V; }
    sim.pin = -1;
    card.classList.remove("is-dragging");
    wake();
  }
  card.addEventListener("pointerup", release);
  card.addEventListener("pointercancel", release);
  card.addEventListener("lostpointercapture", release);

  // ---- lifecycle
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (es) {
      visible = es[0].isIntersecting;
      if (visible) wake(); else running = false;
    }, { rootMargin: "200px 0px" }).observe(stage);
  }
  // Scrolling nudges the card: the page moves and the card lags a little behind, so it sways.
  var lastY = scrollY;
  addEventListener("scroll", function () {
    var dy = scrollY - lastY;
    lastY = scrollY;
    if (!sim || sim.pin >= 0 || !visible) return;
    var b = sim.pts[sim.n + 1];
    var vx = (b.x - b.px) + Math.max(-4, Math.min(4, dy * 0.08));
    vx = Math.max(-9, Math.min(9, vx)); // a fast scroll shouldn't fling it around
    b.px = b.x - vx;
    wake();
  }, { passive: true });

  var lastW = innerWidth, rT = 0;
  addEventListener("resize", function () {
    if (innerWidth === lastW) return; // phones fire resize when the address bar hides; ignore height-only changes
    lastW = innerWidth;
    clearTimeout(rT);
    rT = setTimeout(function () { if (sim) build(false); }, 150);
  });

  function start() {
    if (sim) return;
    var r = stage.getBoundingClientRect();
    build(r.bottom > 0 && r.top < innerHeight); // only drop if the hero is on screen; otherwise just hang
  }
  // the card's height depends on the web fonts, so measure after they're in (but don't wait forever)
  if (document.fonts && document.fonts.ready) {
    var t = setTimeout(start, 1200);
    document.fonts.ready.then(function () { clearTimeout(t); start(); });
  } else start();
})(this);
