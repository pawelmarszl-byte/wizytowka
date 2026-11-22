/* Motion on /off-the-clock:
 *   - lines from home (Warsaw) to every trip draw themselves on the map; hovering a trip lights its line,
 *   - the Istria loop is drawn along its route when it scrolls into view,
 *   - the luggage tag on each trip sways as the page scrolls (a damped pendulum per tag).
 *
 * Without JS there are no lines and the tags hang still. With prefers-reduced-motion the lines are there at once
 * and nothing sways.
 */
(function () {
  "use strict";
  var motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
  var NS = "http://www.w3.org/2000/svg";

  function onView(el, fn, threshold) {
    if (!motion || !("IntersectionObserver" in window)) { fn(); return; }
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) { io.disconnect(); fn(); }
    }, { threshold: threshold || 0.4 });
    io.observe(el);
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn(); else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    // ---------------------------------------------------------------- lines from home on the Europe map
    var map = document.querySelector(".map svg"), home = map && map.querySelector(".map-home");
    var pinsGroup = map && map.querySelector(".map-pins");
    if (home && pinsGroup) {
      var hx = +home.getAttribute("cx"), hy = +home.getAttribute("cy");
      var group = document.createElementNS(NS, "g");
      group.setAttribute("class", "map-arcs");
      group.setAttribute("aria-hidden", "true");
      var arcs = {};
      [].forEach.call(pinsGroup.querySelectorAll("a.map-pin"), function (pin, i) {
        var dot = pin.querySelector(".map-pin-dot");
        var ex = +dot.getAttribute("cx"), ey = +dot.getAttribute("cy");
        var mx = (hx + ex) / 2, my = (hy + ey) / 2, dx = ex - hx, dy = ey - hy, len = Math.sqrt(dx * dx + dy * dy);
        // bend every line the same way (towards the top of the map), more for longer flights
        var nx = dy / len, ny = -dx / len;
        if (ny > 0) { nx = -nx; ny = -ny; }
        var bend = Math.min(90, len * 0.22);
        var p = document.createElementNS(NS, "path");
        p.setAttribute("d", "M" + hx + " " + hy + " Q" + (mx + nx * bend).toFixed(1) + " " + (my + ny * bend).toFixed(1) + " " + ex + " " + ey);
        p.setAttribute("class", "map-arc");
        p.setAttribute("pathLength", "1");
        p.style.transitionDelay = motion ? (i * 0.12) + "s" : "0s";
        if (!motion) p.style.transition = "none";
        group.appendChild(p);
        arcs[pin.getAttribute("href")] = p;
        var on = function () { p.classList.add("is-lit"); }, off = function () { p.classList.remove("is-lit"); };
        pin.addEventListener("mouseenter", on); pin.addEventListener("mouseleave", off);
        pin.addEventListener("focus", on); pin.addEventListener("blur", off);
      });
      pinsGroup.parentNode.insertBefore(group, pinsGroup);
      // the trip log lights the same line as its pin
      [].forEach.call(document.querySelectorAll(".log a"), function (row) {
        var slug = row.getAttribute("href"), arc = arcs[slug] || arcs[slug.replace(/-\d+$/, "")];
        if (!arc) return;
        var on = function () { arc.classList.add("is-lit"); }, off = function () { arc.classList.remove("is-lit"); };
        row.addEventListener("mouseenter", on); row.addEventListener("focus", on);
        row.addEventListener("mouseleave", off); row.addEventListener("blur", off);
      });
      onView(map, function () {
        [].forEach.call(group.childNodes, function (p) { p.getBoundingClientRect(); });
        requestAnimationFrame(function () {
          group.classList.add("is-drawn");
          // once drawn, hovering should react at once, not after the staggered delay
          setTimeout(function () { [].forEach.call(group.childNodes, function (p) { p.style.transitionDelay = "0s"; }); }, 2500);
        });
      }, 0.3);
    }

    // ---------------------------------------------------------------- the Istria loop draws itself
    var route = document.querySelector(".frame.route .map-route");
    if (route && motion) {
      var svg = route.ownerSVGElement, defs = document.createElementNS(NS, "defs"), mask = document.createElementNS(NS, "mask");
      var vb = svg.viewBox.baseVal;
      mask.setAttribute("id", "route-reveal");
      mask.setAttribute("maskUnits", "userSpaceOnUse");
      ["x", "y", "width", "height"].forEach(function (k) { mask.setAttribute(k, vb[k]); });
      var pen = document.createElementNS(NS, "path");
      pen.setAttribute("d", route.getAttribute("d"));
      pen.setAttribute("pathLength", "1");
      pen.setAttribute("style", "fill:none;stroke:#fff;stroke-width:10;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1;" +
        "transition:stroke-dashoffset 3.2s cubic-bezier(.45,0,.25,1)");
      mask.appendChild(pen); defs.appendChild(mask); svg.insertBefore(defs, svg.firstChild);
      route.setAttribute("mask", "url(#route-reveal)");
      onView(route.closest(".frame"), function () {
        pen.getBoundingClientRect();
        requestAnimationFrame(function () { pen.style.strokeDashoffset = "0"; });
      }, 0.5);
    }

    // ---------------------------------------------------------------- swaying luggage tags
    if (!motion) return;
    var tags = [].map.call(document.querySelectorAll(".lug-swing"), function (el, i) {
      return { el: el, a: 0, v: 0, k: 0.75 + ((i * 37) % 50) / 100 }; // each tag reacts a little differently
    });
    if (!tags.length) return;
    var STIFF = 0.010, DAMP = 0.028, running = false, lastY = scrollY;
    function frame() {
      var busy = false;
      tags.forEach(function (t) {
        t.v += -STIFF * t.a - DAMP * t.v;
        t.a = Math.max(-0.7, Math.min(0.7, t.a + t.v));
        if (Math.abs(t.a) > 0.0008 || Math.abs(t.v) > 0.0004) busy = true;
        else { t.a = 0; t.v = 0; }
        t.el.style.rotate = t.a.toFixed(4) + "rad";
      });
      if (busy) requestAnimationFrame(frame); else running = false;
    }
    function go() { if (!running) { running = true; requestAnimationFrame(frame); } }
    addEventListener("scroll", function () {
      var dy = scrollY - lastY;
      lastY = scrollY;
      var kick = Math.max(-0.012, Math.min(0.012, dy * 0.00025));
      tags.forEach(function (t) { t.v = Math.max(-0.05, Math.min(0.05, t.v + kick * t.k)); });
      go();
    }, { passive: true });
    tags.forEach(function (t) {
      // brushing past a tag with the pointer flicks it in that direction
      t.el.addEventListener("pointerenter", function (e) {
        var r = t.el.getBoundingClientRect();
        t.v += (e.clientX < r.left + r.width / 2 ? -1 : 1) * 0.035; // rotate() is clockwise: from the left, swing the bottom right
        go();
      });
    });
  });
})();
