/**
 * Charm charts — tiny SVG donut + bar charts with draw-in animation and
 * hover tooltips. Replaces ApexCharts for the dashboard (~5 KB vs ~570 KB).
 *
 *   CharmCharts.donut(el, { segments: [{ label, value, color }], centerLabel })
 *   CharmCharts.bars(el,  { labels: [], values: [], color, tooltip(i) })
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var reduce = !!(global.Charm && global.Charm.reduceMotion);

  function svgEl(tag, attrs) {
    var el = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  function tooltipFor(host) {
    var tip = host.querySelector('.ui-chart-tip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'ui-chart-tip';
      tip.setAttribute('role', 'presentation');
      host.appendChild(tip);
    }
    return {
      show: function (html, x, y) {
        tip.innerHTML = html;
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
        tip.classList.add('is-visible');
      },
      hide: function () { tip.classList.remove('is-visible'); }
    };
  }

  function donut(host, opts) {
    var o = opts || {};
    var segments = (o.segments || []).filter(function (s) { return Number(s.value) > 0; });
    var total = segments.reduce(function (sum, s) { return sum + Number(s.value || 0); }, 0);
    host.textContent = '';
    host.classList.add('ui-chart');
    var size = 220;
    var r = 82;
    var stroke = 22;
    var c = 2 * Math.PI * r;
    var svg = svgEl('svg', { viewBox: '0 0 ' + size + ' ' + size, class: 'ui-donut', role: 'img', 'aria-label': o.ariaLabel || 'Donut chart' });
    svg.appendChild(svgEl('circle', { cx: size / 2, cy: size / 2, r: r, fill: 'none', stroke: 'var(--ui-panel-sunken)', 'stroke-width': stroke }));
    var g = svgEl('g', { transform: 'rotate(-90 ' + size / 2 + ' ' + size / 2 + ')' });
    svg.appendChild(g);
    var tip = tooltipFor(host);
    var offset = 0;
    var gap = segments.length > 1 ? 3 : 0;
    segments.forEach(function (s, i) {
      var len = Math.max(0, (Number(s.value) / total) * c - gap);
      var arc = svgEl('circle', {
        cx: size / 2, cy: size / 2, r: r, fill: 'none',
        stroke: s.color, 'stroke-width': stroke, 'stroke-linecap': 'butt',
        'stroke-dasharray': len + ' ' + (c - len),
        'stroke-dashoffset': String(-offset),
        class: 'ui-donut__arc'
      });
      if (!reduce) {
        arc.style.strokeDasharray = '0 ' + c;
        arc.style.transition = 'stroke-dasharray 700ms cubic-bezier(.22,1,.36,1) ' + (i * 70) + 'ms';
        requestAnimationFrame(function () { requestAnimationFrame(function () { arc.style.strokeDasharray = len + ' ' + (c - len); }); });
      }
      arc.addEventListener('mousemove', function (e) {
        var box = host.getBoundingClientRect();
        var pct = total ? Math.round((s.value / total) * 100) : 0;
        tip.show('<span class="ui-chart-tip__dot" style="background:' + s.color + '"></span><strong>' + s.value + '</strong><span>' + global.Charm.esc(s.label) + ' · ' + pct + '%</span>', e.clientX - box.left, e.clientY - box.top);
      });
      arc.addEventListener('mouseleave', tip.hide);
      g.appendChild(arc);
      offset += len + gap;
    });
    var center = svgEl('text', { x: size / 2, y: size / 2 - 2, 'text-anchor': 'middle', class: 'ui-donut__value' });
    center.textContent = String(total);
    var label = svgEl('text', { x: size / 2, y: size / 2 + 22, 'text-anchor': 'middle', class: 'ui-donut__label' });
    label.textContent = o.centerLabel || 'Total';
    svg.appendChild(center);
    svg.appendChild(label);
    host.appendChild(svg);
  }

  function niceMax(peak, ticks) {
    if (peak <= ticks) return ticks;
    var step = Math.ceil(peak / ticks);
    var mag = Math.pow(10, Math.floor(Math.log10(step)));
    var norm = step / mag;
    var nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
    return nice * mag * ticks;
  }

  function bars(host, opts) {
    var o = opts || {};
    var values = (o.values || []).map(function (v) { return Number(v || 0); });
    var labels = o.labels || [];
    host.textContent = '';
    host.classList.add('ui-chart');
    var width = Math.max(260, host.clientWidth || 600);
    var height = o.height || 240;
    var pad = { top: 12, right: 8, bottom: 28, left: 32 };
    var innerW = width - pad.left - pad.right;
    var innerH = height - pad.top - pad.bottom;
    var ticks = 4;
    var max = niceMax(Math.max.apply(null, values.concat([0])), ticks);
    var svg = svgEl('svg', { viewBox: '0 0 ' + width + ' ' + height, width: '100%', height: height, class: 'ui-bars', role: 'img', 'aria-label': o.ariaLabel || 'Bar chart' });

    for (var t = 0; t <= ticks; t += 1) {
      var y = pad.top + innerH - (innerH * t) / ticks;
      svg.appendChild(svgEl('line', { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: t === 0 ? 'ui-bars__base' : 'ui-bars__grid' }));
      var lbl = svgEl('text', { x: pad.left - 8, y: y + 4, 'text-anchor': 'end', class: 'ui-bars__axis' });
      lbl.textContent = String(Math.round((max * t) / ticks));
      svg.appendChild(lbl);
    }

    var n = values.length || 1;
    var slot = innerW / n;
    var barW = Math.max(4, Math.min(34, slot * (n <= 7 ? 0.42 : n <= 14 ? 0.56 : 0.66)));
    var labelEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 64))));
    var tip = tooltipFor(host);

    values.forEach(function (v, i) {
      var h = max ? (innerH * v) / max : 0;
      var x = pad.left + slot * i + (slot - barW) / 2;
      var y0 = pad.top + innerH;
      var hit = svgEl('rect', { x: pad.left + slot * i, y: pad.top, width: slot, height: innerH, fill: 'transparent', class: 'ui-bars__hit' });
      var bar = svgEl('rect', { x: x, y: y0 - Math.max(h, v ? 2 : 0), width: barW, height: Math.max(h, v ? 2 : 0), rx: Math.min(6, barW / 2), fill: o.color || 'var(--ui-brand)', class: 'ui-bars__bar' });
      if (!reduce) {
        bar.style.transformOrigin = 'center ' + y0 + 'px';
        bar.style.transform = 'scaleY(0)';
        bar.style.transition = 'transform 620ms cubic-bezier(.22,1,.36,1) ' + Math.min(400, i * 18) + 'ms';
        requestAnimationFrame(function () { requestAnimationFrame(function () { bar.style.transform = 'scaleY(1)'; }); });
      }
      function show(e) {
        bar.classList.add('is-hover');
        var box = host.getBoundingClientRect();
        var html = typeof o.tooltip === 'function' ? o.tooltip(i, v) : '<strong>' + v + '</strong>';
        tip.show(html, e.clientX - box.left, e.clientY - box.top);
      }
      hit.addEventListener('mousemove', show);
      hit.addEventListener('mouseleave', function () { bar.classList.remove('is-hover'); tip.hide(); });
      svg.appendChild(bar);
      svg.appendChild(hit);
      if (i % labelEvery === 0 || (i === n - 1 && i % labelEvery >= labelEvery / 2)) {
        var xl = svgEl('text', { x: pad.left + slot * i + slot / 2, y: height - 8, 'text-anchor': 'middle', class: 'ui-bars__axis' });
        xl.textContent = typeof o.formatLabel === 'function' ? o.formatLabel(labels[i], i) : String(labels[i] || '');
        svg.appendChild(xl);
      }
    });
    host.appendChild(svg);
  }

  global.CharmCharts = { donut: donut, bars: bars };
})(window);
