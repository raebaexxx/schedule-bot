/*
 * liquid.js — движок «liquid glass» (стиль Apple iOS 26) для Mini App.
 *
 * Уровни:
 *   1. frost-база — чистый CSS (backdrop-filter blur+saturate), работает
 *      во всех WebView, включая Telegram iOS (WKWebView). См. style.css.
 *   2. «Жидкая» рефракция краёв — прогрессивное усиление ТОЛЬКО для
 *      Chromium (Telegram Android, десктоп Chrome): карта смещений
 *      генерируется на canvas из SDF скруглённого прямоугольника
 *      (метод shuding/liquid-glass) и подаётся в backdrop-filter
 *      через feImage + feDisplacementMap.
 *
 * ВАЖНО: CSS @supports лжёт в Safari — детект через navigator.userAgentData.
 */
(function () {
  "use strict";

  function isChromium() {
    try {
      if (!navigator.userAgentData || !navigator.userAgentData.brands) return false;
      return navigator.userAgentData.brands.some(function (b) {
        return /Chromium|Google Chrome/i.test(b.brand);
      });
    } catch (e) {
      return false;
    }
  }

  var MAX_SCALE = 34;          // макс. смещение пикселей у края (сила стекла)
  var EDGE_BAND = 0.42;        // доля половины размера, занимаемая зоной изгиба
  var overscan = 24;           // запас под displacement, чтобы не резать края

  function smoothStep(a, b, t) {
    t = Math.max(0, Math.min(1, (t - a) / (b - a)));
    return t * t * (3 - 2 * t);
  }

  /* SDF скруглённого прямоугольника с центром в (0,0); отрицательное — внутри */
  function roundedRectSDF(x, y, hx, hy, r) {
    var qx = Math.abs(x) - hx + r;
    var qy = Math.abs(y) - hy + r;
    return Math.min(Math.max(qx, qy), 0) +
      Math.sqrt(Math.max(qx, 0) * Math.max(qx, 0) +
                Math.max(qy, 0) * Math.max(qy, 0)) - r;
  }

  /* Карта смещений: R = сдвиг по X, G = по Y, 128 — нейтраль */
  function buildDisplacementMap(w, h, radius) {
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(2, Math.round(w));
    canvas.height = Math.max(2, Math.round(h));
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(canvas.width, canvas.height);
    var data = img.data;
    var cx = canvas.width / 2;
    var cy = canvas.height / 2;
    var hx = cx - 1.5;
    var hy = cy - 1.5;
    var r = Math.min(radius, hx, hy);

    for (var y = 0; y < canvas.height; y++) {
      for (var x = 0; x < canvas.width; x++) {
        var ix = x + 0.5 - cx;
        var iy = y + 0.5 - cy;
        var dist = roundedRectSDF(ix, iy, hx, hy, r);
        /* смещение только в узкой полосе у края: у кромки max, в центре 0 */
        var t = smoothStep(hx * EDGE_BAND, 0, Math.abs(dist));
        var dx = ix * t;
        var dy = iy * t;
        var i = (y * canvas.width + x) * 4;
        data[i]     = Math.round(128 + (dx / MAX_SCALE) * 127);
        data[i + 1] = Math.round(128 + (dy / MAX_SCALE) * 127);
        data[i + 2] = 128;
        data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL("image/png");
  }

  var seq = 0;

  function applyDisplacement(el) {
    var rect = el.getBoundingClientRect();
    var w = Math.ceil(rect.width) + overscan * 2;
    var h = Math.ceil(rect.height) + overscan * 2;
    if (w < 8 || h < 8) return;

    var styles = getComputedStyle(el);
    var radius = parseFloat(styles.borderTopLeftRadius) || 20;

    var id = "lg" + (++seq);
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "lg-defs");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.position = "absolute";

    var filter = document.createElementNS("http://www.w3.org/2000/svg", "filter");
    filter.setAttribute("id", id);
    filter.setAttribute("filterUnits", "userSpaceOnUse");
    filter.setAttribute("colorInterpolationFilters", "sRGB");
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", String(w));
    filter.setAttribute("height", String(h));

    var mapHref = buildDisplacementMap(w, h, radius);
    var feImage = document.createElementNS("http://www.w3.org/2000/svg", "feImage");
    feImage.setAttribute("href", mapHref);
    feImage.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", mapHref);
    feImage.setAttribute("x", "0");
    feImage.setAttribute("y", "0");
    feImage.setAttribute("width", String(w));
    feImage.setAttribute("height", String(h));
    feImage.setAttribute("result", "map");

    var feDisp = document.createElementNS("http://www.w3.org/2000/svg", "feDisplacementMap");
    feDisp.setAttribute("in", "SourceGraphic");
    feDisp.setAttribute("in2", "map");
    feDisp.setAttribute("scale", String(MAX_SCALE));
    feDisp.setAttribute("xChannelSelector", "R");
    feDisp.setAttribute("yChannelSelector", "G");

    filter.appendChild(feImage);
    filter.appendChild(feDisp);
    svg.appendChild(filter);

    /* старый SVG фильтра убираем — иначе при каждом resize копится мусор */
    if (el.__lgSvg) el.__lgSvg.remove();
    el.appendChild(svg);
    el.__lgSvg = svg;

    var fx = "url(#" + id + ") blur(2px) saturate(175%) brightness(1.05)";
    el.style.backdropFilter = fx;
    el.style.webkitBackdropFilter = fx;
    /* слой стекла чуть выступает за границы — запас под смещение пикселей */
    el.style.setProperty("--lg-overscan", overscan + "px");
  }

  function init(root) {
    if (!isChromium()) return;   // Safari/Firefox/старые WebView — остаётся frost
    var scope = root || document;
    var targets = scope.querySelectorAll(".liquid:not([data-liquid-done])");
    targets.forEach(function (el) {
      el.setAttribute("data-liquid-done", "1");
      var inner = document.createElement("div");
      /* слой-«стекло»: сам размывает фон и искажает его; контент выше */
      inner.className = "liquid-layer";
      applyDisplacement(inner);

      /* displacement-слой кладём ПОД контентом внутри glass-обёртки */
      el.insertBefore(inner, el.firstChild);
      var ro = new ResizeObserver(function () {
        /* пересборка карты при изменении размера (дебаунс) */
        clearTimeout(el.__lgTimer);
        el.__lgTimer = setTimeout(function () {
          if (inner.__lgSvg) inner.__lgSvg.remove();
          applyDisplacement(inner);
        }, 120);
      });
      ro.observe(el);
    });
  }

  var style = document.createElement("style");
  style.textContent =
    ".lg-defs{position:absolute;width:0;height:0}" +
    ".liquid-layer{position:absolute;inset:-24px;z-index:-1;pointer-events:none}" +
    ".liquid-layer > svg{position:absolute;visibility:hidden}";
  document.head.appendChild(style);

  window.LiquidGlass = { init: init, supported: isChromium() };

  /* шапка и табы статичны — включаем рефракцию сразу после загрузки */
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      try { init(); } catch (e) { /* остаётся frost-фоллбэк */ }
    });
  } else {
    try { init(); } catch (e) { /* остаётся frost-фоллбэк */ }
  }
})();
