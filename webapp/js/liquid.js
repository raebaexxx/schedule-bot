/*
 * liquid.js — движок «liquid glass» (стиль Apple iOS 26/27) для Mini App.
 *
 * Уровни:
 *   1. frost-база — чистый CSS (backdrop-filter blur+saturate), работает
 *      во всех WebView, включая Telegram iOS (WKWebView). См. style.css.
 *   2. «Жидкая» рефракция кромки — прогрессивное усиление ТОЛЬКО для
 *      Chromium (Telegram Android, десктоп Chrome): карта смещений
 *      генерируется на canvas из SDF скруглённого прямоугольника
 *      (метод shuding/liquid-glass) и подаётся в backdrop-filter
 *      через feImage + feDisplacementMap.
 *
 * Отличия от базовой версии (ближе к Apple):
 *   - смещение вдоль НОРМАЛИ края (градиент SDF), а не радиус-вектора:
 *     плоские грани преломляют перпендикулярно, углы — по диагонали;
 *   - узкая линза (EDGE_BAND ~17% меньшего полудиапазона) со степенным
 *     профилем: сильный изгиб у самой кромки, чистый центр;
 *   - хроматическая дисперсия (ENABLE_CHROMA): R/G/B каналы смещаются
 *     с чуть разными масштабами — цветной fringing на кромке;
 *   - SDF-прямоугольник = видимая площадь стекла (хост без overscan).
 *
 * ВАЖНО: CSS @supports лжёт в Safari — детект через navigator.userAgentData.
 */
(function () {
  "use strict";

  /* ---------- тюнинг эффекта ---------- */

  var ENABLE_CHROMA = true;  // хроматическая дисперсия (3 прохода)
  var MAX_SCALE = 24;        // макс. смещение пикселей у кромки
  var EDGE_BAND = 0.17;      // ширина линзы, доля меньшего полудиапазона
  var BAND_POWER = 0.75;     // профиль: <1 — резче у кромки
  var CHROMA_SPREAD = 0.08;  // разброс масштабов R/G/B (±8%)
  var overscan = 24;         // запас слоя под смещение (>= MAX_SCALE)

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

  /* нормаль края = градиент SDF (конечная разность) */
  function sdfNormal(x, y, hx, hy, r) {
    var e = 0.5;
    var dx = roundedRectSDF(x + e, y, hx, hy, r) -
             roundedRectSDF(x - e, y, hx, hy, r);
    var dy = roundedRectSDF(x, y + e, hx, hy, r) -
             roundedRectSDF(x, y - e, hx, hy, r);
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    return [dx / len, dy / len];
  }

  /* Карта смещений: R = сдвиг по X, G = по Y, 128 — нейтраль */
  function buildDisplacementMap(w, h, glassHx, glassHy, radius) {
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(2, Math.round(w));
    canvas.height = Math.max(2, Math.round(h));
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(canvas.width, canvas.height);
    var data = img.data;
    var cx = canvas.width / 2;
    var cy = canvas.height / 2;
    var r = Math.max(0, Math.min(radius, glassHx, glassHy));
    var band = EDGE_BAND * Math.min(glassHx, glassHy);

    for (var y = 0; y < canvas.height; y++) {
      for (var x = 0; x < canvas.width; x++) {
        var ix = x + 0.5 - cx;
        var iy = y + 0.5 - cy;
        var dist = Math.abs(roundedRectSDF(ix, iy, glassHx, glassHy, r));
        var t = Math.pow(smoothStep(band, 0, dist), BAND_POWER);
        var dx = 0, dy = 0;
        if (t > 0.002) {
          var n = sdfNormal(ix, iy, glassHx, glassHy, r);
          dx = n[0] * t * MAX_SCALE;
          dy = n[1] * t * MAX_SCALE;
        }
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

  function svgEl(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  /* матрицы выделения одного цветового канала (для дисперсии) */
  var CHROMA_MATRIX = {
    r: "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0",
    g: "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0",
    b: "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0",
  };

  function applyDisplacement(el) {
    var host = el.parentElement || el;
    var hostRect = host.getBoundingClientRect();
    var w = Math.ceil(hostRect.width) + overscan * 2;
    var h = Math.ceil(hostRect.height) + overscan * 2;
    if (w < 8 || h < 8) return;

    var radius = parseFloat(getComputedStyle(host).borderTopLeftRadius) || 20;
    /* SDF-прямоугольник = видимая площадь стекла (слой шире на overscan) */
    var glassHx = Math.ceil(hostRect.width) / 2 - 1;
    var glassHy = Math.ceil(hostRect.height) / 2 - 1;
    var mapHref = buildDisplacementMap(w, h, glassHx, glassHy, radius);

    var id = "lg" + (++seq);
    var svg = svgEl("svg", {
      "class": "lg-defs", "aria-hidden": "true", width: "0", height: "0",
    });
    svg.style.position = "absolute";

    var filter = svgEl("filter", {
      id: id, filterUnits: "userSpaceOnUse",
      colorInterpolationFilters: "sRGB",
      x: "0", y: "0", width: String(w), height: String(h),
    });

    var feImage = svgEl("feImage", {
      href: mapHref, x: "0", y: "0",
      width: String(w), height: String(h), result: "map",
    });
    feImage.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", mapHref);
    filter.appendChild(feImage);

    if (ENABLE_CHROMA) {
      /* R/G/B смещаются с чуть разными масштабами -> fringing на кромке */
      var scales = [
        MAX_SCALE * (1 - CHROMA_SPREAD),
        MAX_SCALE,
        MAX_SCALE * (1 + CHROMA_SPREAD),
      ];
      var chans = ["r", "g", "b"];
      var prev = null;
      for (var i = 0; i < 3; i++) {
        filter.appendChild(svgEl("feColorMatrix", {
          in: "SourceGraphic", type: "matrix",
          values: CHROMA_MATRIX[chans[i]], result: "c" + i,
        }));
        filter.appendChild(svgEl("feDisplacementMap", {
          in: "c" + i, in2: "map", scale: String(scales[i]),
          xChannelSelector: "R", yChannelSelector: "G", result: "d" + i,
        }));
        if (prev === null) {
          prev = "d0";
        } else {
          filter.appendChild(svgEl("feComposite", {
            in: prev, in2: "d" + i, operator: "arithmetic",
            k1: "0", k2: "1", k3: "1", k4: "0", result: "m" + i,
          }));
          prev = "m" + i;
        }
      }
    } else {
      filter.appendChild(svgEl("feDisplacementMap", {
        in: "SourceGraphic", in2: "map", scale: String(MAX_SCALE),
        xChannelSelector: "R", yChannelSelector: "G",
      }));
    }

    svg.appendChild(filter);

    /* старый SVG фильтра убираем — иначе при каждом resize копится мусор */
    if (el.__lgSvg) el.__lgSvg.remove();
    el.appendChild(svg);
    el.__lgSvg = svg;

    /* frost (blur+saturate) уже даёт ::before в style.css — здесь только
       смещение и лёгкое сглаживание, без двойной насыщенности */
    var fx = "url(#" + id + ") blur(1px)";
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
