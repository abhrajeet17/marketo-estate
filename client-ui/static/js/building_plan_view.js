/* Building Plan customer view: aerial -> tower -> floor -> unit, driven by one inlined tree. */
(function () {
    'use strict';

    var T = window.__BP_TREE__;
    if (!T || !T.maps || !T.maps[T.root]) return;
    var MAPS = T.maps;
    var BASE = '/building-plan/' + encodeURIComponent(T.token);

    var $ = function (id) { return document.getElementById(id); };
    var root = $('bp');
    var scene = $('bp-scene');
    var loader = $('bp-loader');
    var card = $('bp-hovercard');

    // ── Tree indexes ──────────────────────────────────────
    var parentOf = {};       // mapId -> { map, zone }
    Object.keys(MAPS).forEach(function (mid) {
        MAPS[mid].zones.forEach(function (z) {
            if (z.link === 'building_map' && z.target && z.target !== T.root && !parentOf[z.target]) {
                parentOf[z.target] = { map: mid, zone: z };
            }
        });
    });

    var zoneHome = {};      // zoneId -> mapId containing it
    Object.keys(MAPS).forEach(function (mid) {
        MAPS[mid].zones.forEach(function (z) { zoneHome[z.id] = mid; });
    });

    // A map can be opened from several zones (e.g. one typical floor map shared by many
    // floors), so the customer's actual path (zone ids from the root) drives breadcrumbs,
    // "up", siblings and the interest snapshot. parentOf is only the fallback for old links.
    function chainFor(via) {
        var out = [], m = T.root;
        for (var i = 0; i < via.length; i++) {
            var z = findZone(m, via[i]);
            if (!z || z.link !== 'building_map' || !MAPS[z.target]) return null;
            out.push({ map: m, zone: z });
            m = z.target;
        }
        return { chain: out, end: m };
    }
    function staticVia(mid) {
        var via = [], guard = 0;
        while (parentOf[mid] && guard++ < 30) { via.unshift(parentOf[mid].zone.id); mid = parentOf[mid].map; }
        return mid === T.root ? via : [];
    }
    function currentChain() {
        var c = chainFor(state.via || []);
        if (c && c.end === state.map) return c.chain;
        state.via = staticVia(state.map);
        c = chainFor(state.via);
        return c ? c.chain : [];
    }
    function parentFor(mid) {
        var ch = currentChain();
        for (var i = ch.length - 1; i >= 0; i--) if (ch[i].zone.target === mid) return ch[i];
        return parentOf[mid] || null;
    }
    function viaTo(mapId, viaZone) {
        if (mapId === T.root) return [];
        var ch = currentChain(), i;
        if (viaZone && viaZone.target === mapId) {
            var home = zoneHome[viaZone.id];
            if (home === state.map) return state.via.concat([viaZone.id]);
            for (i = 0; i < ch.length; i++) if (ch[i].map === home) return state.via.slice(0, i).concat([viaZone.id]);
        }
        if (mapId === state.map) return (state.via || []).slice();
        for (i = 0; i < ch.length; i++) if (ch[i].map === mapId) return state.via.slice(0, i);
        return staticVia(mapId);
    }

    // ── Status: apartments drive their floor ──────────────
    // A floor zone may override the statuses of the units in the (shared) map it opens
    // via meta.unit_status {unitId: status}. Floor colour: any available -> available,
    // else any hold -> hold, else all sold -> sold.
    function unitsOf(mapId) {
        return MAPS[mapId] ? MAPS[mapId].zones.filter(function (u) { return !u.link && u.meta && u.meta.status; }) : [];
    }
    function unitStatusOn(floorZone, unit) {
        var o = floorZone && floorZone.meta && floorZone.meta.unit_status;
        return (o && o[unit.id]) || (unit.meta && unit.meta.status) || '';
    }
    function rollup(statuses) {
        if (!statuses.length) return '';
        if (statuses.indexOf('available') >= 0) return 'available';
        if (statuses.indexOf('hold') >= 0) return 'hold';
        return 'sold';
    }
    function currentFloorZone() {
        var p = parentFor(state.map);
        return p && p.zone && p.zone.target === state.map ? p.zone : null;
    }
    function statusOf(z) {
        if (!z) return '';
        if (z.link === 'building_map') {
            var units = unitsOf(z.target);
            if (units.length) return rollup(units.map(function (u) { return unitStatusOn(z, u); }));
        }
        if (!z.link && zoneHome[z.id] === state.map) {
            var fz = currentFloorZone();
            if (fz) return unitStatusOn(fz, z);
        }
        return (z.meta && z.meta.status) || '';
    }
    function refreshStatuses() {
        if (!cur) return;
        var byId = {};
        cur.zones.forEach(function (z) { byId[z.id] = z; });
        cur.svg.querySelectorAll('.bp-zone').forEach(function (el) {
            var z = byId[el.dataset.zid];
            if (!z) return;
            ['available', 'sold', 'hold'].forEach(function (k) { el.classList.remove('st-' + k); });
            var st = statusOf(z);
            if (st) el.classList.add('st-' + st);
        });
    }

    function depth(mid) {
        if (mid === state.map) return currentChain().length;
        var d = 0;
        while (parentOf[mid] && d < 30) { mid = parentOf[mid].map; d++; }
        return d;
    }
    function hasChildMaps(mid) {
        return MAPS[mid].zones.some(function (z) { return z.link === 'building_map'; });
    }
    function levelOf(mid) {
        var m = MAPS[mid];
        if (m.level) return m.level;
        var d = depth(mid);
        if (d === 0) return hasChildMaps(mid) ? 'aerial' : 'tower';
        if (d === 1) return 'tower';
        return 'floor';
    }
    function findZone(mid, zid) {
        var m = MAPS[mid];
        if (!m || zid == null) return null;
        for (var i = 0; i < m.zones.length; i++) if (String(m.zones[i].id) === String(zid)) return m.zones[i];
        return null;
    }
    function zoneLabel(z) { return (z.meta && z.meta.label) || z.name; }
    // Human title: a bare floor number label reads as "Floor 12".
    function zoneTitle(z) {
        var l = zoneLabel(z);
        if (!/^\d+$/.test(l)) return l;
        // Twin towers share a map: keep the tower in the title ("T2 Floor 32").
        return /floor/i.test(z.name || '') ? z.name : 'Floor ' + l;
    }
    function isUnitZone(z) { return !z.link && z.meta && Object.keys(z.meta).length > 0; }
    function isOpenable(z) { return !!z.link || isUnitZone(z); }

    // ── State + URL ───────────────────────────────────────
    var state = { map: T.root, view: 0, zone: null, via: [] };

    function readUrl() {
        var p = new URLSearchParams(location.search);
        var m = p.get('m');
        var s = { map: (m && MAPS[m]) ? m : T.root, view: 0, zone: null,
            via: (p.get('p') || '').split('.').filter(Boolean).map(function (x) { return isNaN(+x) ? x : +x; }) };
        var z = p.get('z');
        if (z && findZone(s.map, z)) s.zone = z;
        var v = parseInt(p.get('v'), 10);
        if (v > 0 && v < MAPS[s.map].views.length) s.view = v;
        return s;
    }
    function writeUrl(replace) {
        // Keep params the view doesn't own (e.g. ref_user_id from a broker's share link).
        var p = new URLSearchParams(location.search);
        ['m', 'p', 'v', 'z'].forEach(function (k) { p.delete(k); });
        if (state.map !== T.root) p.set('m', state.map);
        if (state.via && state.via.length) p.set('p', state.via.join('.'));
        if (state.view) p.set('v', state.view);
        if (state.zone != null) p.set('z', state.zone);
        var url = BASE + (p.toString() ? '?' + p.toString() : '');
        if (url === location.pathname + location.search) return;
        history[replace ? 'replaceState' : 'pushState'](null, '', url);
    }

    // ── Image cache / preloading ──────────────────────────
    var imgCache = {};
    var imgCacheDone = {};
    function loadImage(url) {
        if (!url) return Promise.reject(new Error('no image'));
        if (imgCache[url]) return imgCache[url];
        imgCache[url] = new Promise(function (resolve, reject) {
            var im = new Image();
            im.decoding = 'async';
            im.onload = function () {
                var done = function () { resolve(im); };
                if (im.decode) im.decode().then(done, done); else done();
            };
            im.onerror = function () { delete imgCache[url]; reject(new Error('Image failed to load')); };
            im.src = url;
        });
        return imgCache[url];
    }
    var idle = window.requestIdleCallback || function (fn) { return setTimeout(fn, 200); };
    function prefetchAround(mid) {
        // Child maps / floor plans one level down, then siblings of the current map.
        var urls = [];
        MAPS[mid].zones.forEach(function (z) {
            if (z.link === 'building_map' && MAPS[z.target]) urls.push(MAPS[z.target].views[0].url);
            if (z.link === 'floor_plan' && z.floor_plan) urls.push(z.floor_plan.url);
        });
        MAPS[mid].views.forEach(function (v) { urls.push(v.url); });
        var p = parentFor(mid);
        if (p) MAPS[p.map].zones.forEach(function (z) {
            if (z.link === 'building_map' && MAPS[z.target]) urls.push(MAPS[z.target].views[0].url);
        });
        var i = 0;
        (function step() {
            var n = 0;
            while (i < urls.length && n < 3) { if (urls[i]) { loadImage(urls[i]).catch(function () {}); n++; } i++; }
            if (i < urls.length) idle(step);
        })();
    }

    // ── Stage / geometry ──────────────────────────────────
    var cur = null;        // { el, svg, w, h, mode, k, x, y }
    // Motion for the next stage swap: 'in' (into a zone), 'out' (up a level), 'next'/'prev' (siblings).
    var navMotion = null;  // { dir, focus: [screenX, screenY] }
    var REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Phones: panels start closed so the building/plan stays visible.
    var IS_PHONE = !!(window.matchMedia && window.matchMedia('(max-width: 760px)').matches);
    var loaderTimer = null;
    var navSeq = 0;

    function sceneSize() { return { w: scene.clientWidth || window.innerWidth, h: scene.clientHeight || window.innerHeight }; }

    // Area not covered by panels/buttons, so floor plans are never hidden behind UI.
    function freeRect() {
        var s = sceneSize();
        var r = { l: 16, t: 16, r: s.w - 16, b: s.h - 16 };
        if (s.w <= 760) {
            r.t = 64; r.b = s.h - 80;
            // Bottom sheets (details / floor list) own the lower part of the screen on phones.
            ['bp-details', 'bp-floorsel'].forEach(function (id) {
                var el = $(id);
                if (el && !el.hidden) r.b = Math.min(r.b, el.getBoundingClientRect().top - 8);
            });
            if (r.b - r.t < 120) r.b = r.t + 120;
            return r;
        }
        var vis = function (id) { var el = $(id); return el && !el.hidden && el.offsetParent !== null ? el.getBoundingClientRect() : null; };
        var cb = vis('bp-crumbbar'); if (cb) r.t = Math.max(r.t, cb.bottom + 12);
        ['bp-floorsel', 'bp-details', 'bp-filters', 'bp-floorsel-open'].forEach(function (id) {
            var b = vis(id); if (b && b.left < s.w * 0.45) r.l = Math.max(r.l, b.right + 16);
        });
        ['bp-legend', 'bp-zoom', 'bp-explore', 'bp-compass'].forEach(function (id) {
            var b = vis(id); if (b && b.right > s.w * 0.55) r.r = Math.min(r.r, b.left - 16);
        });
        var rb = vis('bp-return'); if (rb) r.b = Math.min(r.b, rb.top - 12);
        if (r.r - r.l < s.w * 0.35) { r.l = 16; r.r = s.w - 16; }
        return r;
    }

    function fitScale(st) {
        var s = sceneSize();
        if (st.mode === 'contain') {
            var fr = freeRect();
            st.free = fr;
            return Math.min((fr.r - fr.l) / st.w, (fr.b - fr.t) / st.h);
        }
        var cover = Math.max(s.w / st.w, s.h / st.h);
        var contain = Math.min(s.w / st.w, s.h / st.h);
        // Fill the screen, but never crop the drawn buildings/floors: shrink until their
        // bounds fit between the top bar and the bottom button (blurred backdrop fills the rest).
        var bb = st.bbox;
        if (!bb) return cover;
        var room = s.w > 760 ? 120 : 110;
        var need = Math.min((s.h - room) / (bb[3] - bb[1]), (s.w - 40) / (bb[2] - bb[0]));
        return Math.max(contain, Math.min(cover, need));
    }
    function clampPan(st) {
        var s = sceneSize();
        var S = st.base * st.k;
        var W = st.w * S, H = st.h * S;
        st.x = W <= s.w ? (s.w - W) / 2 : Math.min(0, Math.max(s.w - W, st.x));
        st.y = H <= s.h ? (s.h - H) / 2 : Math.min(0, Math.max(s.h - H, st.y));
    }
    function applyTransform(st) {
        st.el.style.transform = 'translate3d(' + st.x.toFixed(1) + 'px,' + st.y.toFixed(1) + 'px,0) scale(' + (st.base * st.k).toFixed(5) + ')';
    }
    function layout(st, focus) {
        st.base = fitScale(st);
        var s = sceneSize();
        var S = st.base * st.k;
        if (focus) {
            st.x = s.w / 2 - focus[0] * S;
            st.y = s.h / 2 - focus[1] * S;
        } else if (st.mode === 'contain' && st.free) {
            st.x = (st.free.l + st.free.r - st.w * S) / 2;
            st.y = (st.free.t + st.free.b - st.h * S) / 2;
        } else {
            st.x = (s.w - st.w * S) / 2;
            st.y = (s.h - st.h * S) / 2;
        }
        if (st.mode !== 'contain' || st.k > 1) clampPan(st);
        applyTransform(st);
    }
    function zoomBy(factor, cx, cy) {
        if (!cur) return;
        var s = sceneSize();
        if (cx == null) { cx = s.w / 2; cy = s.h / 2; }
        var oldS = cur.base * cur.k;
        var maxK = cur.mode === 'contain' ? 5 : 3;
        cur.k = Math.max(1, Math.min(maxK, cur.k * factor));
        var newS = cur.base * cur.k;
        cur.x = cx - (cx - cur.x) * (newS / oldS);
        cur.y = cy - (cy - cur.y) * (newS / oldS);
        clampPan(cur);
        applyTransform(cur);
        syncZoomButtons();
    }
    function syncZoomButtons() {
        if (!cur) return;
        $('bp-zoom-out').disabled = cur.k <= 1.001;
        $('bp-zoom-in').disabled = cur.k >= (cur.mode === 'contain' ? 5 : 3) - 0.001;
    }

    function zonesBBox(zones, sx, sy) {
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        zones.forEach(function (z) {
            (z.points || []).forEach(function (p) {
                var x = p[0] * sx, y = p[1] * sy;
                if (x < minX) minX = x; if (x > maxX) maxX = x;
                if (y < minY) minY = y; if (y > maxY) maxY = y;
            });
        });
        return isFinite(minX) && maxX > minX && maxY > minY ? [minX, minY, maxX, maxY] : null;
    }

    var SVGNS = 'http://www.w3.org/2000/svg';
    function buildStage(desc, img, src) {
        var w = desc.w || img.naturalWidth, h = desc.h || img.naturalHeight;
        // DB dimensions can drift from the stored file; trust the decoded image.
        if (!src && img.naturalWidth && img.naturalHeight) { w = img.naturalWidth; h = img.naturalHeight; }
        var el = document.createElement('div');
        el.className = 'bp-stage';
        el.style.width = w + 'px';
        el.style.height = h + 'px';
        var im = document.createElement('img');
        im.src = src || desc.url;
        im.alt = desc.alt || '';
        im.draggable = false;
        el.appendChild(im);
        var svg = document.createElementNS(SVGNS, 'svg');
        svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
        svg.setAttribute('class', 'lv-' + desc.level);
        var sx = desc.srcW ? w / desc.srcW : 1, sy = desc.srcH ? h / desc.srcH : 1;
        (desc.zones || []).forEach(function (z) {
            if (!z.points || z.points.length < 3) return;
            var poly = document.createElementNS(SVGNS, 'polygon');
            poly.setAttribute('points', z.points.map(function (p) { return (p[0] * sx).toFixed(1) + ',' + (p[1] * sy).toFixed(1); }).join(' '));
            var st = statusOf(z);
            poly.setAttribute('class', 'bp-zone' + (st ? ' st-' + st : '') + (isOpenable(z) ? '' : ' is-static'));
            poly.dataset.zid = z.id;
            svg.appendChild(poly);
        });
        el.appendChild(svg);
        return { key: desc.key, el: el, svg: svg, img: im, w: w, h: h, mode: desc.mode, k: 1, x: 0, y: 0, base: 1, zones: desc.zones || [], level: desc.level,
            url: desc.url, bbox: desc.mode === 'cover' ? zonesBBox(desc.zones || [], sx, sy) : null };
    }

    var backdrop = document.createElement('div');
    backdrop.className = 'bp-backdrop';
    scene.appendChild(backdrop);
    function setBackdrop(url) {
        backdrop.style.backgroundImage = url ? 'url("' + url.replace(/"/g, '%22') + '")' : 'none';
    }

    function transformAt(st, k, fx, fy, dx) {
        // Stage transform scaled by k around screen point (fx, fy), shifted by dx.
        var S = st.base * st.k;
        var x = fx - (fx - st.x) * k + (dx || 0);
        var y = fy - (fy - st.y) * k;
        return 'translate3d(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px,0) scale(' + (S * k).toFixed(5) + ')';
    }

    function animateSwap(old, st, motion) {
        var sz = sceneSize();
        var f = motion.focus || [sz.w / 2, sz.h / 2];
        var fromNew, toOld;
        if (motion.dir === 'in') {
            toOld = transformAt(old, 2.2, f[0], f[1]);           // dive into the clicked zone
            fromNew = transformAt(st, 0.86, sz.w / 2, sz.h / 2);  // next level rises up to meet it
        } else if (motion.dir === 'out') {
            toOld = transformAt(old, 0.72, sz.w / 2, sz.h / 2);
            fromNew = transformAt(st, 1.35, f[0], f[1]);          // parent settles back from the child
        } else {
            var d = motion.dir === 'next' ? -1 : 1;
            toOld = transformAt(old, 1, sz.w / 2, sz.h / 2, d * sz.w * 0.35);
            fromNew = transformAt(st, 1, sz.w / 2, sz.h / 2, -d * sz.w * 0.35);
        }
        st.el.style.transition = 'none';
        st.el.style.transform = fromNew;
        st.el.style.opacity = '0';
        old.el.classList.add('is-leaving');
        old.el.style.transform = toOld;
        void st.el.offsetWidth;
        requestAnimationFrame(function () {
            st.el.style.transition = '';
            st.el.style.opacity = '';
            st.el.classList.add('is-entering', 'is-in');
            applyTransform(st);
            setTimeout(function () { st.el.classList.remove('is-entering'); }, 720);
        });
    }

    function revealZones(st) {
        var polys = st.svg.querySelectorAll('.bp-zone');
        if (!polys.length || REDUCED) return;
        // Bottom-up wave: lower floors light up first.
        var items = Array.prototype.map.call(polys, function (el) {
            var bb = el.getBBox ? el.getBBox() : { y: 0, height: 0 };
            return { el: el, y: bb.y + bb.height };
        }).sort(function (a, b) { return b.y - a.y; });
        var step = Math.min(28, 700 / items.length);
        items.forEach(function (it, i) {
            it.el.style.animationDelay = Math.round(260 + i * step) + 'ms';
            it.el.classList.add('is-revealing');
        });
        setTimeout(function () { items.forEach(function (it) { it.el.classList.remove('is-revealing'); it.el.style.animationDelay = ''; }); }, 260 + items.length * step + 700);
    }

    function mountStage(st, desc, seq) {
        scene.appendChild(st.el);
        var focus = st.bbox ? [(st.bbox[0] + st.bbox[2]) / 2, (st.bbox[1] + st.bbox[3]) / 2] : null;
        layout(st, focus);
        setBackdrop(desc.mode === 'cover' ? (desc.lqip || desc.url) : '');
        var old = cur;
        cur = st;
        var motion = navMotion;
        navMotion = null;
        if (old && motion && !REDUCED) animateSwap(old, st, motion);
        else requestAnimationFrame(function () { st.el.classList.add('is-in'); });
        if (st.level === 'tower' || st.level === 'floor') revealZones(st);
        if (old) {
            old.el.classList.remove('is-in');
            old.el.style.pointerEvents = 'none';
            setTimeout(function () { if (old.el.parentNode) old.el.parentNode.removeChild(old.el); }, 700);
        }
        syncZoomButtons();
        applyFilters();
        markSelected();
    }

    function showStage(desc) {
        var seq = ++navSeq;
        clearTimeout(loaderTimer);
        $('bp-loader-text').textContent = 'Loading view…';
        loaderTimer = setTimeout(function () { if (seq === navSeq) loader.classList.add('is-on'); }, desc.lqip ? 600 : 120);
        var early = null;
        // Blurred preview first: the view and its zones are usable before the full render arrives.
        if (desc.lqip && desc.w && desc.h && !imgCacheDone[desc.url]) {
            early = buildStage(desc, { naturalWidth: desc.w, naturalHeight: desc.h }, desc.lqip);
            early.el.classList.add('is-lqip');
            mountStage(early, desc, seq);
        }
        return loadImage(desc.url).then(function (img) {
            imgCacheDone[desc.url] = true;
            if (seq !== navSeq) return null;
            clearTimeout(loaderTimer);
            loader.classList.remove('is-on');
            if (early) {
                early.img.src = desc.url;
                early.el.classList.remove('is-lqip');
                if (desc.mode === 'cover') setBackdrop(desc.url);
                return early;
            }
            var st = buildStage(desc, img);
            mountStage(st, desc, seq);
            return st;
        }).catch(function () {
            if (seq !== navSeq) return null;
            clearTimeout(loaderTimer);
            $('bp-loader-text').textContent = 'This view could not be loaded. Check your connection and try again.';
            loader.classList.add('is-on');
            return null;
        });
    }

    // ── Render ────────────────────────────────────────────
    var filters = { bhk: null, min: null, max: null, hideAll: false };
    var stageKey = '';

    function currentDescriptor() {
        var m = MAPS[state.map];
        var z = findZone(state.map, state.zone);
        if (z && z.link === 'floor_plan' && z.floor_plan) {
            return {
                key: 'plan:' + z.id, url: z.floor_plan.url, w: z.floor_plan.w, h: z.floor_plan.h,
                mode: 'contain', level: 'plan', zones: [], alt: z.floor_plan.name, plan: true,
            };
        }
        var v = m.views[state.view] || m.views[0];
        var lvl = levelOf(state.map);
        return {
            key: 'map:' + m.id + ':' + state.view, url: v.url, lqip: v.lqip || '', w: v.w, h: v.h, srcW: v.w, srcH: v.h,
            mode: lvl === 'floor' ? 'contain' : 'cover', level: lvl, alt: m.name,
            // Zones drawn before multi-view support have no image_id and belong to the first view.
            zones: m.zones.filter(function (zz) { return zz.image_id ? zz.image_id === v.id : state.view === 0 || !v.id; }),
        };
    }

    function render(opts) {
        opts = opts || {};
        var desc = currentDescriptor();
        var lvl = desc.plan ? 'plan' : desc.level;
        root.dataset.level = lvl === 'plan' ? 'floor' : lvl;
        root.dataset.mode = desc.plan ? 'plan' : 'map';
        hideCard();
        var sameStage = desc.key === stageKey && !!cur;
        if (sameStage) navMotion = null;  // e.g. selecting a unit: no stage swap to animate
        var p = sameStage ? Promise.resolve(cur) : showStage(desc);
        stageKey = desc.key;
        p.then(function (st) {
            if (!st) return;
            refreshStatuses();
            applyFilters();
            markSelected();
        });
        renderChrome(desc);
        // Panels opening/closing (details, floor list) change the free area: refit plans smoothly.
        if (cur && cur.mode === 'contain' && cur.k <= 1.001 && desc.key === (cur.key || '')) {
            cur.el.classList.add('is-animating');
            layout(cur, null);
            setTimeout(function () { if (cur) cur.el.classList.remove('is-animating'); }, 360);
        }
        prefetchAround(state.map);
        if (!opts.noUrl) writeUrl(opts.replace);
    }

    function markSelected() {
        if (!cur) return;
        cur.svg.querySelectorAll('.bp-zone').forEach(function (el) {
            el.classList.toggle('is-selected', state.zone != null && el.dataset.zid === String(state.zone));
        });
    }

    // ── Chrome (panels per level) ─────────────────────────
    function ancestry(mid) {
        if (mid === state.map) return currentChain().slice();
        var chain = [];
        var guard = 0;
        while (parentOf[mid] && guard++ < 30) { chain.unshift(parentOf[mid]); mid = parentOf[mid].map; }
        return chain; // [{map, zone}] root-first
    }

    function renderChrome(desc) {
        var zone = findZone(state.map, state.zone);
        var lvl = desc.plan ? 'plan' : desc.level;

        // Brand
        var brand = $('bp-brand');
        brand.textContent = T.project.brand || T.project.name || 'Project';

        // Crumbs
        var crumbs = [{ label: MAPS[T.root].name || T.project.name, go: { map: T.root } }];
        ancestry(state.map).forEach(function (a) {
            crumbs.push({ label: zoneTitle(a.zone), go: { map: a.zone.target } });
        });
        if (zone) crumbs.push({ label: zoneTitle(zone) || 'Apartment', go: null });
        var ol = $('bp-crumbs');
        ol.innerHTML = '';
        crumbs.forEach(function (c, i) {
            var li = document.createElement('li');
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = c.label;
            if (i < crumbs.length - 1 && c.go) b.addEventListener('click', function () { go(c.go.map, null); });
            li.appendChild(b);
            ol.appendChild(li);
        });
        ol.scrollLeft = ol.scrollWidth;
        $('bp-up').disabled = state.map === T.root && state.zone == null;

        // VR tour
        var vr = $('bp-vr');
        var vrUrl = T.vr_tour_url;
        if (zone && zone.link === 'panorama') vrUrl = '/customer/' + zone.panorama_id;
        vr.hidden = !vrUrl;
        if (vrUrl) vr.href = vrUrl;

        // RERA
        var rera = $('bp-rera');
        rera.hidden = !T.project.rera;
        rera.textContent = T.project.rera ? 'Rera Number : ' + T.project.rera : '';

        var mapZones = MAPS[state.map].zones;
        var hasStatus = mapZones.some(function (z) { return !!statusOf(z); });
        var isTower = lvl === 'tower';
        var isFloor = lvl === 'floor' || lvl === 'plan';

        $('bp-legend').hidden = !((isTower || lvl === 'floor') && hasStatus);
        $('bp-eye').hidden = !(isTower || lvl === 'floor');
        $('bp-zoom').hidden = !isFloor;

        renderFilters(isTower);
        renderExplore(lvl);
        renderFloorSelector(lvl);
        renderDetails(zone, lvl);
        renderArrows(lvl, zone);
        renderReturn(lvl, zone);
    }

    // Filters (tower level)
    function bhkTokens(z) {
        var s = ((z.meta && (z.meta.configurations || z.meta.unit_type)) || '').toUpperCase();
        var out = [];
        (s.match(/\d+(\.\d+)?\s*BHK/g) || []).forEach(function (t) { t = t.replace(/\s+/g, ''); if (out.indexOf(t) < 0) out.push(t); });
        return out;
    }
    function sizeRangeOf(z) {
        var m = z.meta || {};
        var lo = m.size_min, hi = m.size_max;
        if (lo == null && m.area) { var n = parseFloat(String(m.area).replace(/,/g, '')); if (!isNaN(n)) lo = hi = n; }
        if (lo == null) return null;
        return [lo, hi == null ? lo : hi];
    }
    var filterInfo = null;
    function renderFilters(show) {
        var panel = $('bp-filters');
        panel.hidden = !show;
        if (!show) { filterInfo = null; return; }
        var zones = MAPS[state.map].zones;
        var units = 0, bhk = [], lo = Infinity, hi = -Infinity;
        zones.forEach(function (z) {
            units += (z.meta && z.meta.units) ? z.meta.units : 1;
            bhkTokens(z).forEach(function (t) { if (bhk.indexOf(t) < 0) bhk.push(t); });
            var r = sizeRangeOf(z);
            if (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[1]); }
        });
        bhk.sort(function (a, b) { return parseFloat(a) - parseFloat(b); });
        var key = state.map;
        if (!filterInfo || filterInfo.key !== key) {
            filters = { bhk: bhk.slice(), min: isFinite(lo) ? lo : null, max: isFinite(hi) ? hi : null, hideAll: false };
        }
        filterInfo = { key: key, bhk: bhk, lo: lo, hi: hi };
        $('bp-units-total').textContent = units + ' Units Total';
        var chips = $('bp-bhk');
        chips.innerHTML = '';
        bhk.forEach(function (t) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'bp-chip' + (filters.bhk.indexOf(t) < 0 ? ' is-off' : '');
            b.textContent = t;
            b.setAttribute('aria-pressed', filters.bhk.indexOf(t) >= 0 ? 'true' : 'false');
            b.addEventListener('click', function () {
                var i = filters.bhk.indexOf(t);
                if (i >= 0) filters.bhk.splice(i, 1); else filters.bhk.push(t);
                b.classList.toggle('is-off', i >= 0);
                b.setAttribute('aria-pressed', i >= 0 ? 'false' : 'true');
                applyFilters();
            });
            chips.appendChild(b);
        });
        chips.hidden = !bhk.length;
        var sizeWrap = $('bp-size-wrap');
        sizeWrap.hidden = !isFinite(lo) || lo === hi;
        if (!sizeWrap.hidden) {
            var mn = $('bp-size-min'), mx = $('bp-size-max');
            [mn, mx].forEach(function (inp) { inp.min = lo; inp.max = hi; inp.step = 1; });
            mn.value = filters.min; mx.value = filters.max;
            syncRange();
        }
        $('bp-hide-all').textContent = filters.hideAll ? 'Show All' : 'Hide All';
    }
    function syncRange() {
        var mn = $('bp-size-min'), mx = $('bp-size-max');
        var lo = +mn.min, hi = +mn.max;
        var a = +mn.value, b = +mx.value;
        if (a > b) { var t = a; a = b; b = t; }
        filters.min = a; filters.max = b;
        $('bp-size-lo').textContent = Math.round(a);
        $('bp-size-hi').textContent = Math.round(b);
        var span = hi - lo || 1;
        var fill = $('bp-range-fill');
        fill.style.left = ((a - lo) / span * 100) + '%';
        fill.style.right = ((hi - b) / span * 100) + '%';
    }
    $('bp-size-min').addEventListener('input', function () { syncRange(); applyFilters(); });
    $('bp-size-max').addEventListener('input', function () { syncRange(); applyFilters(); });
    $('bp-hide-all').addEventListener('click', function () {
        filters.hideAll = !filters.hideAll;
        this.textContent = filters.hideAll ? 'Show All' : 'Hide All';
        applyFilters();
    });
    if (IS_PHONE) { $('bp-filters').classList.add('is-collapsed'); $('bp-filters-toggle').setAttribute('aria-expanded', 'false'); }
    $('bp-filters-toggle').addEventListener('click', function () {
        var p = $('bp-filters');
        var c = p.classList.toggle('is-collapsed');
        this.setAttribute('aria-expanded', c ? 'false' : 'true');
    });

    function zonePasses(z) {
        if (!filterInfo) return true;
        if (filters.hideAll) return false;
        var toks = bhkTokens(z);
        if (filterInfo.bhk.length && toks.length && !toks.some(function (t) { return filters.bhk.indexOf(t) >= 0; })) return false;
        var r = sizeRangeOf(z);
        if (r && filters.min != null && (r[1] < filters.min || r[0] > filters.max)) return false;
        return true;
    }
    function applyFilters() {
        if (!cur) return;
        var byId = {};
        cur.zones.forEach(function (z) { byId[z.id] = z; });
        cur.svg.querySelectorAll('.bp-zone').forEach(function (el) {
            var z = byId[el.dataset.zid];
            el.classList.toggle('is-filtered', !!z && !zonePasses(z));
        });
    }

    // Explore towers: siblings of the current tower inside its parent.
    function siblingMaps(mid) {
        var p = parentFor(mid);
        if (!p) return [];
        return MAPS[p.map].zones.filter(function (z) { return z.link === 'building_map' && MAPS[z.target]; });
    }
    function renderExplore(lvl) {
        var panel = $('bp-explore');
        var sibs = lvl === 'tower' ? siblingMaps(state.map) : [];
        panel.hidden = sibs.length < 2;
        if (panel.hidden) return;
        var list = $('bp-explore-list');
        list.innerHTML = '';
        sibs.forEach(function (z) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = zoneLabel(z);
            if (z.target === state.map) b.classList.add('is-active');
            b.addEventListener('click', function () { if (z.target !== state.map) go(z.target, null, { dir: 'next' }, z); });
            list.appendChild(b);
        });
    }

    // Floor selector: floors of the tower that owns the current floor.
    function floorContext() {
        // Returns { tower: mapId, current: zone } where `current` is the tower zone for this floor.
        var z = findZone(state.map, state.zone);
        if (z && z.link === 'floor_plan') return { tower: state.map, current: z };
        var p = parentFor(state.map);
        if (p && levelOf(state.map) === 'floor') return { tower: p.map, current: p.zone };
        return null;
    }
    var floorselOpen = !IS_PHONE;
    function renderFloorSelector(lvl) {
        var panel = $('bp-floorsel');
        var openBtn = $('bp-floorsel-open');
        var ctx = (lvl === 'floor' || lvl === 'plan') ? floorContext() : null;
        if (!ctx) { panel.hidden = true; openBtn.hidden = true; root.dataset.panelLeft = 'none'; return; }
        panel.hidden = !floorselOpen;
        openBtn.hidden = floorselOpen;
        root.dataset.panelLeft = floorselOpen ? 'floorsel' : 'none';
        var towerName = (towerKey(ctx.current) ? String(ctx.current.name).replace(/\s*floor\b.*$/i, '') : '') ||
            ancestry(ctx.tower).map(function (a) { return zoneLabel(a.zone); }).pop() || MAPS[ctx.tower].name;
        var fl = ctx.current.floor;
        $('bp-floorsel-title').textContent = towerName + ' ' + (fl ? ordinal(fl) + ' Floor' : zoneLabel(ctx.current));

        // Towers row
        var tw = siblingMaps(ctx.tower);
        $('bp-floorsel-towers-wrap').hidden = tw.length < 2;
        var tl = $('bp-floorsel-towers');
        tl.innerHTML = '';
        tw.forEach(function (z) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = zoneLabel(z);
            if (z.target === ctx.tower) b.classList.add('is-active');
            b.addEventListener('click', function () { if (z.target !== ctx.tower) go(z.target, null, { dir: 'next' }, z); });
            tl.appendChild(b);
        });

        // Floors grouped in tens
        var floors = MAPS[ctx.tower].zones.filter(function (z) { return z.link === 'floor_plan' || (z.link === 'building_map' && MAPS[z.target]); });
        // A building map can hold twin towers ("T5 Floor 32", "T6 Floor 32"): list the current tower's floors.
        var key = towerKey(ctx.current);
        if (key) {
            var mine = floors.filter(function (z) { return towerKey(z) === key; });
            if (mine.length) floors = mine;
        }
        floors.sort(function (a, b) { return a.floor - b.floor || String(a.name).localeCompare(String(b.name)); });
        var floorCount = {};
        floors.forEach(function (z) { floorCount[z.floor] = (floorCount[z.floor] || 0) + 1; });
        var groups = {};
        floors.forEach(function (z) {
            var g = Math.floor(Math.max(0, z.floor - 1) / 10);
            (groups[g] = groups[g] || []).push(z);
        });
        var host = $('bp-floorsel-floors');
        host.innerHTML = '';
        Object.keys(groups).map(Number).sort(function (a, b) { return a - b; }).forEach(function (g) {
            var row = document.createElement('div');
            row.className = 'bp-floor-group';
            var lab = document.createElement('span');
            var list = groups[g];
            lab.textContent = list[0].floor + ' - ' + list[list.length - 1].floor;
            var btns = document.createElement('div');
            btns.className = 'bp-grid-btns';
            list.forEach(function (z) {
                var b = document.createElement('button');
                b.type = 'button';
                // Several zones on one floor (e.g. wings) need their own label to be told apart.
                b.textContent = z.floor && floorCount[z.floor] === 1 ? z.floor : zoneLabel(z);
                if (b.textContent.length > 3) b.style.width = 'auto';
                b.title = zoneLabel(z);
                if (z === ctx.current) b.classList.add('is-active');
                b.addEventListener('click', function () { openTowerZone(ctx.tower, z); });
                btns.appendChild(b);
            });
            row.appendChild(lab);
            row.appendChild(btns);
            host.appendChild(row);
        });
        panel._floors = { tower: ctx.tower, list: floors };
        var active = host.querySelector('.is-active');
        var scroller = panel.querySelector('.bp-floorsel-scroll');
        if (active && scroller) {
            var top = active.offsetTop - scroller.offsetTop;
            if (top < scroller.scrollTop || top > scroller.scrollTop + scroller.clientHeight - 40) {
                scroller.scrollTop = Math.max(0, top - scroller.clientHeight / 2);
            }
        }
    }
    function towerKey(z) {
        var m = /^(.*?)\s*floor\b/i.exec(String((z && z.name) || ''));
        return m ? m[1].trim().toLowerCase() : '';
    }
    function ordinal(n) {
        var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
        return n + (s[(v - 20) % 10] || s[v] || s[0]);
    }
    function openTowerZone(towerId, z) {
        if (z.link === 'building_map') go(z.target, null, null, z);
        else go(towerId, z.id);
    }
    $('bp-floor-search').addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        var panel = $('bp-floorsel');
        var info = panel._floors;
        var q = this.value.trim().toLowerCase();
        if (!info || !q) return;
        var hit = info.list.find(function (z) { return String(z.floor) === q || zoneLabel(z).toLowerCase() === q; }) ||
            info.list.find(function (z) { return zoneLabel(z).toLowerCase().indexOf(q) >= 0; });
        if (hit) { this.value = ''; openTowerZone(info.tower, hit); }
        else { this.select(); }
    });
    $('bp-floorsel-close').addEventListener('click', function () { floorselOpen = false; render({ noUrl: true }); });
    $('bp-floorsel-open').addEventListener('click', function () { floorselOpen = true; render({ noUrl: true }); });

    // Details panel (unit or floor plan)
    var STATUS_LABEL = { available: 'AVAILABLE', sold: 'SOLD', hold: 'HOLD' };
    function detailRows(z) {
        var m = z.meta || {};
        var rows = [];
        var nm = zoneLabel(z);
        rows.push(['', z.link === 'floor_plan' || /^(unit|apartment|flat)\b/i.test(nm) ? zoneTitle(z) : 'Unit ' + nm]);
        if (m.unit_type || m.configurations) rows.push(['', m.unit_type || m.configurations]);
        var st = statusOf(z);
        if (st) rows.push(['Unit Status', STATUS_LABEL[st], 'st-' + st]);
        if (m.area) rows.push(['Total Area', m.area]);
        else if (m.size_min) rows.push(['Size', m.size_min + (m.size_max && m.size_max !== m.size_min ? ' - ' + m.size_max : '') + ' Sq. Ft.']);
        if (m.units) rows.push(['Apartments', String(m.units)]);
        if (m.price) rows.push(['Price', m.price]);
        return rows;
    }
    function renderDetails(zone, lvl) {
        var panel = $('bp-details');
        var show = !!zone && (zone.link === 'floor_plan' || isUnitZone(zone));
        panel.hidden = !show;
        if (!show) return;
        $('bp-details-title').textContent = zone.link === 'floor_plan' ? 'Floor Details' : 'Apartment Details';
        var host = $('bp-detail-rows');
        host.innerHTML = '';
        detailRows(zone).forEach(function (r) {
            var div = document.createElement('div');
            div.className = 'bp-detail-row';
            if (r[0]) {
                var a = document.createElement('span'); a.textContent = r[0];
                var b = document.createElement('b'); b.textContent = r[1]; if (r[2]) b.className = r[2];
                div.appendChild(a); div.appendChild(b);
            } else {
                div.textContent = r[1];
            }
            host.appendChild(div);
        });
        var btn = $('bp-interest-btn');
        var m = zone.meta || {};
        btn.hidden = !T.show_interest || !!m.hide_interest;
        var sold = statusOf(zone) === 'sold';
        btn.disabled = sold;
        btn.textContent = sold ? 'Sold Out' : 'Show Interest';
    }
    $('bp-interest-btn').addEventListener('click', function () { openInterest(); });

    // Prev / next
    var cycle = null;
    function renderArrows(lvl, zone) {
        cycle = null;
        var list = null, idx = -1, apply = null;
        if (zone) {
            if (zone.link === 'floor_plan') {
                list = MAPS[state.map].zones.filter(function (z) { return z.link === 'floor_plan'; });
                list.sort(function (a, b) { return a.floor - b.floor; });
            } else {
                list = MAPS[state.map].zones.filter(isUnitZone);
            }
            idx = list.indexOf(zone);
            apply = function (z) { go(state.map, z.id); };
        } else if (lvl === 'tower' || lvl === 'floor') {
            var sib = siblingMaps(state.map);
            var here = currentFloorZone();
            if (lvl === 'floor') {
                var key = towerKey(here);
                if (key) sib = sib.filter(function (z) { return towerKey(z) === key; });
                sib = sib.slice().sort(function (a, b) { return a.floor - b.floor; });
            }
            list = sib;
            idx = here ? sib.indexOf(here) : -1;
            if (idx < 0) idx = sib.findIndex(function (z) { return z.target === state.map; });
            apply = function (z) { go(z.target, null, null, z); };
        } else {
            var views = MAPS[state.map].views;
            if (views.length > 1) {
                list = views; idx = state.view;
                apply = function (_v, i) { state.view = i; state.zone = null; render(); };
            }
        }
        var ok = list && list.length > 1 && idx >= 0;
        $('bp-prev').hidden = !ok;
        $('bp-next').hidden = !ok;
        if (ok) cycle = { list: list, idx: idx, apply: apply };
    }
    function step(d) {
        if (!cycle) return;
        var n = cycle.list.length;
        var i = (cycle.idx + d + n) % n;
        navMotion = { dir: d > 0 ? 'next' : 'prev' };
        cycle.apply(cycle.list[i], i);
    }
    $('bp-prev').addEventListener('click', function () { step(-1); });
    $('bp-next').addEventListener('click', function () { step(1); });

    // Return button
    function renderReturn(lvl, zone) {
        var btn = $('bp-return');
        var label = '';
        if (zone) label = zone.link === 'floor_plan' ? 'Return To Tower' : 'Return To Floor Plan';
        else if (parentFor(state.map)) {
            var pl = levelOf(parentFor(state.map).map);
            label = pl === 'aerial' ? 'Return To Aerial View' : pl === 'tower' ? 'Return To Tower' : 'Return To Floor Plan';
        }
        btn.hidden = !label;
        $('bp-return-text').textContent = label;
    }
    $('bp-return').addEventListener('click', goUp);
    $('bp-up').addEventListener('click', goUp);
    $('bp-brand').addEventListener('click', function () { go(T.root, null); });
    $('bp-eye').addEventListener('click', function () { root.classList.toggle('overlays-off'); });

    // ── Navigation ────────────────────────────────────────
    function go(mapId, zoneId, motion, viaZone) {
        if (!MAPS[mapId]) return;
        if (motion) navMotion = motion;
        state.via = viaTo(mapId, viaZone);
        if (mapId !== state.map) state.view = 0;
        state.map = mapId;
        state.zone = zoneId == null ? null : zoneId;
        render();
    }
    function zoneScreenCenter(st, zone) {
        if (!st || !zone) return null;
        var el = st.svg.querySelector('[data-zid="' + zone.id + '"]');
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
    }
    function goUp() {
        var sz = sceneSize();
        if (state.zone != null) {
            var z = findZone(state.map, state.zone);
            go(state.map, null, z && z.link === 'floor_plan' ? { dir: 'out', focus: [sz.w / 2, sz.h / 2] } : null);
            return;
        }
        var p = parentFor(state.map);
        if (p) go(p.map, null, { dir: 'out', focus: [sz.w / 2, sz.h / 2] });
    }
    function openZone(z) {
        if (!z) return;
        var motion = { dir: 'in', focus: zoneScreenCenter(cur, z) };
        if (z.link === 'building_map') go(z.target, null, motion, z);
        else if (z.link === 'floor_plan') go(state.map, z.id, motion);
        else if (z.link === 'panorama') window.location.href = '/customer/' + z.panorama_id;
        else if (isUnitZone(z)) go(state.map, z.id);
    }
    window.addEventListener('popstate', function () {
        var s = readUrl();
        state.map = s.map; state.view = s.view; state.zone = s.zone; state.via = s.via;
        render({ noUrl: true });
    });

    // ── Pointer: pan, click, hover ────────────────────────
    var ptr = null;
    var pinch = null;
    var activePtrs = {};
    scene.addEventListener('pointerdown', function (e) {
        if (!cur || e.button > 0) return;
        activePtrs[e.pointerId] = { x: e.clientX, y: e.clientY };
        var ids = Object.keys(activePtrs);
        if (ids.length === 2) {
            var a = activePtrs[ids[0]], b = activePtrs[ids[1]];
            pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: cur.k };
            ptr = null;
            return;
        }
        ptr = { x: e.clientX, y: e.clientY, sx: cur.x, sy: cur.y, moved: false, id: e.pointerId };
    });
    window.addEventListener('pointermove', function (e) {
        if (activePtrs[e.pointerId]) activePtrs[e.pointerId] = { x: e.clientX, y: e.clientY };
        if (pinch && cur) {
            var ids = Object.keys(activePtrs);
            if (ids.length === 2) {
                var a = activePtrs[ids[0]], b = activePtrs[ids[1]];
                var d = Math.hypot(a.x - b.x, a.y - b.y);
                var target = pinch.k * d / pinch.d;
                zoomBy(target / cur.k, (a.x + b.x) / 2, (a.y + b.y) / 2);
            }
            return;
        }
        if (ptr && ptr.id === e.pointerId && cur) {
            var dx = e.clientX - ptr.x, dy = e.clientY - ptr.y;
            if (!ptr.moved && Math.hypot(dx, dy) > 6) { ptr.moved = true; scene.classList.add('is-panning'); hideCard(); }
            if (ptr.moved) {
                cur.x = ptr.sx + dx; cur.y = ptr.sy + dy;
                clampPan(cur); applyTransform(cur);
            }
        }
    });
    var suppressClick = false;
    function endPointer(e) {
        delete activePtrs[e.pointerId];
        if (pinch && Object.keys(activePtrs).length < 2) { pinch = null; suppressClick = true; return; }
        if (!ptr || ptr.id !== e.pointerId) return;
        suppressClick = ptr.moved;
        ptr = null;
        scene.classList.remove('is-panning');
    }
    window.addEventListener('pointerup', endPointer);
    window.addEventListener('pointercancel', endPointer);
    // Native click only fires when press and release land on the scene, so presses on
    // panels/buttons can never select a zone underneath them.
    scene.addEventListener('click', function (e) {
        if (suppressClick) { suppressClick = false; return; }
        var el = e.target;
        if (!cur || !el.classList || !el.classList.contains('bp-zone') || el.classList.contains('is-filtered')) return;
        var z = cur.zones.find(function (zz) { return String(zz.id) === el.dataset.zid; });
        if (!z) return;
        // Touch on aerial: first tap previews the card, second tap opens.
        if (lastPointerType === 'touch' && hotZone !== z && levelOf(state.map) === 'aerial' && window.innerWidth > 760) {
            hotZone = z; showCard(z, e.clientX, e.clientY); return;
        }
        openZone(z);
    });
    var lastPointerType = 'mouse';
    scene.addEventListener('pointerdown', function (e) { lastPointerType = e.pointerType; suppressClick = false; }, true);

    var hotZone = null;
    scene.addEventListener('pointerover', function (e) {
        if (ptr && ptr.moved) return;
        var el = e.target;
        if (!el.classList || !el.classList.contains('bp-zone') || !cur) return;
        var z = cur.zones.find(function (zz) { return String(zz.id) === el.dataset.zid; });
        if (!z) return;
        hotZone = z;
        if (e.pointerType !== 'touch') showCard(z, e.clientX, e.clientY);
        prefetchZone(z);
    });
    scene.addEventListener('pointermove', function (e) {
        if (!card.hidden && e.pointerType !== 'touch') positionCard(e.clientX, e.clientY);
    });
    scene.addEventListener('pointerout', function (e) {
        if (e.target.classList && e.target.classList.contains('bp-zone')) { hotZone = null; hideCard(); }
    });
    scene.addEventListener('wheel', function (e) {
        if (!cur || cur.mode !== 'contain') return;
        e.preventDefault();
        zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY);
    }, { passive: false });
    $('bp-zoom-in').addEventListener('click', function () { zoomBy(1.3); });
    $('bp-zoom-out').addEventListener('click', function () { zoomBy(1 / 1.3); });

    function prefetchZone(z) {
        if (z.link === 'building_map' && MAPS[z.target]) loadImage(MAPS[z.target].views[0].url).catch(function () {});
        if (z.link === 'floor_plan' && z.floor_plan) loadImage(z.floor_plan.url).catch(function () {});
    }

    // Hover card
    function cardRows(z) {
        var m = z.meta || {};
        var rows = [];
        if (m.subtitle) rows.push(esc(m.subtitle));
        else if (m.floors || m.units) rows.push([m.floors ? m.floors + ' Floors' : '', m.units ? m.units + ' Apartments' : ''].filter(Boolean).join(' | '));
        if (m.configurations) rows.push(esc(m.configurations));
        if (m.unit_type && m.unit_type !== m.configurations) rows.push(esc(m.unit_type));
        var st = statusOf(z);
        if (st) rows.push('<span class="st-' + st + '">' + STATUS_LABEL[st] + '</span>');
        if (m.size_min) rows.push(m.size_min + (m.size_max && m.size_max !== m.size_min ? ' - ' + m.size_max : '') + ' Sq.Ft');
        else if (m.area) rows.push(esc(m.area));
        if (m.price) rows.push(esc(m.price));
        return rows;
    }
    function showCard(z, x, y) {
        var rows = cardRows(z);
        var title = zoneTitle(z);
        card.innerHTML = '<div class="hc-title"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>' +
            esc(title) + '</div>' + rows.map(function (r) { return '<div class="hc-row">' + r + '</div>'; }).join('');
        card.hidden = false;
        positionCard(x, y);
    }
    function positionCard(x, y) {
        var s = sceneSize();
        var w = card.offsetWidth, h = card.offsetHeight;
        var left = x + 24, top = y - h / 2;
        if (left + w > s.w - 10) left = x - w - 24;
        top = Math.max(10, Math.min(s.h - h - 10, top));
        card.style.left = left + 'px';
        card.style.top = top + 'px';
    }
    function hideCard() { card.hidden = true; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // Keyboard
    document.addEventListener('keydown', function (e) {
        if (!$('bp-modal').hidden) { if (e.key === 'Escape') closeInterest(); return; }
        if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
        if (e.key === 'Escape') goUp();
        else if (e.key === 'ArrowLeft') step(-1);
        else if (e.key === 'ArrowRight') step(1);
    });

    // Fullscreen
    $('bp-fullscreen').addEventListener('click', function () {
        var d = document;
        if (d.fullscreenElement || d.webkitFullscreenElement) (d.exitFullscreen || d.webkitExitFullscreen).call(d);
        else { var el = d.documentElement; var fn = el.requestFullscreen || el.webkitRequestFullscreen; if (fn) fn.call(el); }
    });

    // Resize
    var resizeRaf = 0;
    window.addEventListener('resize', function () {
        cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(function () {
            if (!cur) return;
            var s = sceneSize();
            var c = [(s.w / 2 - cur.x) / (cur.base * cur.k), (s.h / 2 - cur.y) / (cur.base * cur.k)];
            layout(cur, c);
        });
    });

    // ── Show Interest ─────────────────────────────────────
    var form = $('bp-interest-form');
    var interestZone = null;
    function openInterest() {
        var z = findZone(state.map, state.zone);
        if (!z) return;
        interestZone = { map: state.map, zone: z };
        var trail = ancestry(state.map).map(function (a) { return zoneTitle(a.zone); }).concat([zoneTitle(z)]);
        var m = z.meta || {};
        var extra = [m.unit_type || m.configurations, m.area].filter(Boolean).join(' · ');
        $('bp-modal-unit').textContent = trail.join(' › ') + (extra ? ' — ' + extra : '');
        setMsg('');
        $('bp-modal-body').hidden = false;
        $('bp-modal-footer').hidden = false;
        form.querySelectorAll('.has-error').forEach(function (el) { el.classList.remove('has-error'); });
        $('bp-modal').hidden = false;
        loadReferences();
        setTimeout(function () { $('bpf-name').focus(); }, 30);
    }
    function closeInterest() { $('bp-modal').hidden = true; }

    // Reference dropdown (same behaviour as the plotted-development checkout):
    // a ?ref_user_id= link preselects and locks it; otherwise the customer may pick one.
    var referencePromise = null;
    var REQUESTED_REF = (function () {
        try { return String(new URLSearchParams(location.search).get('ref_user_id') || '').trim(); } catch (e) { return ''; }
    })();
    function requestedRef() { return REQUESTED_REF; }
    function referenceLabel(r) {
        var name = String(r.display_name || r.email || 'Reference').trim();
        var meta = [];
        if (r.member_role_label) meta.push(String(r.member_role_label));
        var groups = Array.isArray(r.client_group_names) ? r.client_group_names.filter(Boolean) : [];
        if (groups.length) meta.push(groups.join(', '));
        return meta.length ? name + ' (' + meta.join(' · ') + ')' : name;
    }
    function loadReferences() {
        if (referencePromise) return referencePromise;
        var sel = $('bpf-reference');
        referencePromise = fetch('/api/public/building-plan/' + encodeURIComponent(T.token) + '/reference-users')
            .then(function (r) { return r.ok ? r.json() : { reference_users: [] }; })
            .catch(function () { return { reference_users: [] }; })
            .then(function (d) {
                var users = Array.isArray(d.reference_users) ? d.reference_users : [];
                var want = requestedRef();
                sel.innerHTML = '';
                var none = document.createElement('option');
                none.value = '';
                none.textContent = users.length ? 'No reference' : 'No reference available';
                sel.appendChild(none);
                users.forEach(function (u) {
                    if (!u || !u.user_id) return;
                    var o = document.createElement('option');
                    o.value = String(u.user_id);
                    o.textContent = referenceLabel(u);
                    sel.appendChild(o);
                });
                if (want && !users.some(function (u) { return String(u.user_id) === want; })) {
                    var o = document.createElement('option');
                    o.value = want;
                    o.textContent = 'Reference from link';
                    sel.appendChild(o);
                }
                if (want) sel.value = want;
                sel.disabled = !!want || !users.length;
                return users;
            });
        return referencePromise;
    }
    function setMsg(text, ok) {
        var el = $('bp-modal-msg');
        el.hidden = !text;
        el.textContent = text || '';
        el.classList.toggle('is-ok', !!ok);
    }
    $('bp-modal-close').addEventListener('click', closeInterest);
    $('bp-modal-cancel').addEventListener('click', closeInterest);
    $('bp-modal').addEventListener('click', function (e) { if (e.target === this) closeInterest(); });

    var FIELD_MAP = { customer_name: 'bpf-name', customer_email: 'bpf-email', customer_phone: 'bpf-phone', reference_user_id: 'bpf-reference' };
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!interestZone) return;
        form.querySelectorAll('.has-error').forEach(function (el) { el.classList.remove('has-error'); });
        var missing = ['bpf-name', 'bpf-email', 'bpf-phone'].filter(function (id) { return !$(id).value.trim(); });
        var email = $('bpf-email').value.trim();
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) missing.push('bpf-email');
        if (missing.length) {
            missing.forEach(function (id) { $(id).parentNode.classList.add('has-error'); });
            setMsg(missing.indexOf('bpf-email') >= 0 && email ? 'Enter a valid email address.' : 'Name, email and phone are required.');
            $(missing[0]).focus();
            return;
        }
        var body = { map_id: interestZone.map, zone_id: interestZone.zone.id, path: (state.via || []).slice() };
        new FormData(form).forEach(function (v, k) { v = String(v).trim(); if (v) body[k] = v; });
        var refSel = $('bpf-reference');
        if (refSel && refSel.value) body.reference_user_id = refSel.value;
        var btn = $('bp-modal-submit');
        btn.disabled = true;
        btn.querySelector('.bp-btn-spin').hidden = false;
        btn.querySelector('.bp-btn-label').textContent = 'Sending…';
        setMsg('');
        fetch('/api/public/building-plan/' + encodeURIComponent(T.token) + '/interest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
        }).then(function (res) {
            if (!res.ok) {
                var id = FIELD_MAP[res.d && res.d.field];
                if (id) $(id).parentNode.classList.add('has-error');
                throw new Error((res.d && res.d.error) || ('Could not send (' + res.status + ')'));
            }
            var keepRef = $('bpf-reference').value;
            form.reset();
            $('bpf-reference').value = keepRef;
            $('bp-modal-body').hidden = true;
            $('bp-modal-footer').hidden = true;
            setMsg('Thank you! Your interest has been shared. Our team will contact you shortly.', true);
            setTimeout(closeInterest, 2600);
        }).catch(function (err) {
            setMsg(err && err.message ? err.message : 'Could not send. Please try again.');
        }).then(function () {
            btn.disabled = false;
            btn.querySelector('.bp-btn-spin').hidden = true;
            btn.querySelector('.bp-btn-label').textContent = 'Send Interest';
        });
    });

    // ── Boot ──────────────────────────────────────────────
    var s0 = readUrl();
    state.map = s0.map; state.view = s0.view; state.zone = s0.zone; state.via = s0.via;
    render({ replace: true });
})();
