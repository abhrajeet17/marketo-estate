(function () {
    'use strict';

    var BOOTSTRAP = window.__SRV_BOOTSTRAP__ || {};
    var MARKERS = Array.isArray(BOOTSTRAP.markers) ? BOOTSTRAP.markers.slice() : [];
    var ROUTES = Array.isArray(BOOTSTRAP.routes) ? BOOTSTRAP.routes.slice() : [];
    var HOVER_ROUTES = Array.isArray(BOOTSTRAP.hoverRoutes) ? BOOTSTRAP.hoverRoutes.slice() : [];
    var iconLibrary = window.salesRouteMapIcons || null;

    var stageEl = document.getElementById('srv-stage');
    var mapCanvasEl = document.getElementById('srv-map-canvas');
    var imageEl = document.getElementById('srv-image');
    var markersLayer = document.getElementById('srv-markers-layer');
    var routesSvg = document.getElementById('srv-routes-svg');
    var hoverRoutesSvg = document.getElementById('srv-hover-routes-svg');
    var hoverRoutesLayer = document.getElementById('srv-hover-routes-layer');
    var statusEl = document.getElementById('srv-status');
    var filterPanelEl = document.getElementById('srv-filter-panel');
    var typeFiltersEl = document.getElementById('srv-type-filters');
    var filterPanelCollapseBtn = document.getElementById('srv-filter-panel-collapse');
    var filterPanelExpandBtn = document.getElementById('srv-filter-panel-expand');
    var routeModalEl = document.getElementById('srv-route-modal');
    var routeModalMediaEl = routeModalEl ? routeModalEl.querySelector('.srv-route-modal-media') : null;
    var routeModalIconEl = document.getElementById('srv-route-modal-icon');
    var routeModalEyebrowEl = document.getElementById('srv-route-modal-eyebrow');
    var routeModalTitleEl = document.getElementById('srv-route-modal-title');
    var routeModalPointerTypeEl = document.getElementById('srv-route-modal-pointer-type');
    var routeModalDistanceEl = document.getElementById('srv-route-modal-distance');
    var PREVIEW_MOBILE = document.body && document.body.classList ? document.body.classList.contains('preview-mobile') : false;
    var activeMarkerId = null;
    var activeAnimationFrame = null;
    var activeTypeFilter = 'all';
    var activeHoverRouteId = null;
    var hoverRouteLocked = false;
    var INITIAL_MAP_SCALE = PREVIEW_MOBILE ? 1.08 : 1.32;
    var MIN_MAP_SCALE = 1;
    var MAX_MAP_SCALE = 4.5;
    var mapScale = INITIAL_MAP_SCALE;
    var mapTranslateX = 0;
    var mapTranslateY = 0;
    var mousePanActive = false;
    var touchPanActive = false;
    var touchPinchActive = false;
    var panStartClientX = 0;
    var panStartClientY = 0;
    var panStartTranslateX = 0;
    var panStartTranslateY = 0;
    var pinchStartDistance = 0;
    var pinchStartScale = INITIAL_MAP_SCALE;
    var pinchLastCenter = null;
    var suppressStageClickOnce = false;

    function clampRatio(value) {
        var num = Number(value);
        if (!Number.isFinite(num)) return 0;
        if (num < 0) return 0;
        if (num > 1) return 1;
        return num;
    }

    function clampLineWidth(value) {
        var num = Number(value);
        if (!Number.isFinite(num)) return 3;
        return Math.max(1, Math.min(12, Math.round(num)));
    }

    function normalizeHexColor(value, fallback) {
        var raw = String(value || '').trim();
        if (/^#[0-9a-fA-F]{3}$/.test(raw)) {
            return '#' + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3];
        }
        if (/^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toLowerCase();
        return fallback || '#162338';
    }

    function routeColor(route) {
        return normalizeHexColor(route && route.color, '#162338');
    }

    function routeLineWidth(route) {
        return clampLineWidth(route && route.line_width);
    }

    function routeStrokeWidthSvg(lineWidth) {
        return String(clampLineWidth(lineWidth) * 0.002);
    }

    function normalizeRouteLineStyle(value, fallback) {
        var style = String(value || '').trim().toLowerCase();
        if (style === 'continuous' || style === 'dashed' || style === 'dotted') return style;
        return fallback || 'dashed';
    }

    function routeStrokeDasharray(style) {
        var normalized = normalizeRouteLineStyle(style, 'dashed');
        if (normalized === 'continuous') return 'none';
        if (normalized === 'dotted') return '0.001 0.014';
        return '0.024 0.015';
    }

    function applyRouteLineStyle(polyline, style) {
        if (!polyline) return;
        polyline.style.strokeDasharray = routeStrokeDasharray(style);
    }

    function normalizeHoverRouteLineStyle(value, fallback) {
        return normalizeRouteLineStyle(value, fallback);
    }

    function applyHoverRouteLineStyle(polyline, style) {
        applyRouteLineStyle(polyline, style);
    }

    function normalizeDistanceKm(value) {
        if (value === null || value === undefined) return null;
        var raw = String(value).trim();
        if (!raw) return null;
        var num = Number(raw);
        if (!Number.isFinite(num) || num < 0) return null;
        return Math.round(num * 1000) / 1000;
    }

    function routeDistanceKm(route) {
        return normalizeDistanceKm(route && route.distance_km);
    }

    function formatDistanceKm(distanceKm) {
        var distance = normalizeDistanceKm(distanceKm);
        if (distance === null) return 'Distance not added';
        return distance + ' km';
    }

    function defaultStatusText() {
        if (HOVER_ROUTES.length) {
            return 'Click a normal pointer to view its route, or hover a highway label to preview an independent route.';
        }
        return 'Click a normal pointer to view its route.';
    }

    function isMobileViewport() {
        if (PREVIEW_MOBILE) return true;
        return window.matchMedia ? window.matchMedia('(max-width: 768px)').matches : window.innerWidth <= 768;
    }

    function isInteractiveUiTarget(target) {
        return !!(target && target.closest && target.closest('.srv-marker, .srv-hover-chip, .srv-route-modal, .srv-filter-panel'));
    }

    function clampMapScale(value) {
        var num = Number(value);
        if (!Number.isFinite(num)) return INITIAL_MAP_SCALE;
        return Math.max(MIN_MAP_SCALE, Math.min(MAX_MAP_SCALE, num));
    }

    function clampMapTranslation() {
        if (!stageEl || !mapCanvasEl) return;
        var stageWidth = stageEl.clientWidth || 0;
        var stageHeight = stageEl.clientHeight || 0;
        var canvasWidth = mapCanvasEl.offsetWidth || 0;
        var canvasHeight = mapCanvasEl.offsetHeight || 0;
        var scaledWidth = canvasWidth * mapScale;
        var scaledHeight = canvasHeight * mapScale;
        var maxX = Math.max(0, (scaledWidth - stageWidth) / 2);
        var maxY = Math.max(0, (scaledHeight - stageHeight) / 2);
        mapTranslateX = Math.max(-maxX, Math.min(maxX, mapTranslateX));
        mapTranslateY = Math.max(-maxY, Math.min(maxY, mapTranslateY));
    }

    function applyMapTransform() {
        if (!mapCanvasEl) return;
        clampMapTranslation();
        mapCanvasEl.style.transform = 'translate(' + mapTranslateX + 'px, ' + mapTranslateY + 'px) scale(' + mapScale + ')';
    }

    function zoomMapAroundPoint(nextScale, clientX, clientY) {
        if (!stageEl || !mapCanvasEl) return;
        var targetScale = clampMapScale(nextScale);
        var rect = stageEl.getBoundingClientRect();
        var localX = clientX - rect.left - (rect.width / 2);
        var localY = clientY - rect.top - (rect.height / 2);
        var ratio = targetScale / mapScale;
        mapTranslateX = localX - ((localX - mapTranslateX) * ratio);
        mapTranslateY = localY - ((localY - mapTranslateY) * ratio);
        mapScale = targetScale;
        applyMapTransform();
    }

    function resetMapView() {
        mapScale = clampMapScale(INITIAL_MAP_SCALE);
        mapTranslateX = 0;
        mapTranslateY = 0;
        applyMapTransform();
    }

    function touchDistance(touches) {
        if (!touches || touches.length < 2) return 0;
        var dx = touches[0].clientX - touches[1].clientX;
        var dy = touches[0].clientY - touches[1].clientY;
        return Math.sqrt((dx * dx) + (dy * dy));
    }

    function touchCenter(touches) {
        if (!touches || !touches.length) return null;
        if (touches.length === 1) {
            return { clientX: touches[0].clientX, clientY: touches[0].clientY };
        }
        return {
            clientX: (touches[0].clientX + touches[1].clientX) / 2,
            clientY: (touches[0].clientY + touches[1].clientY) / 2
        };
    }

    function releaseMapPointerState() {
        mousePanActive = false;
        touchPanActive = false;
        touchPinchActive = false;
        pinchLastCenter = null;
        if (mapCanvasEl) mapCanvasEl.classList.remove('is-dragging');
    }

    function setFilterPanelCollapsed(collapsed) {
        if (!filterPanelEl) return;
        var next = !!collapsed;
        filterPanelEl.classList.toggle('collapsed', next);
        if (filterPanelCollapseBtn) filterPanelCollapseBtn.setAttribute('aria-expanded', next ? 'false' : 'true');
        if (filterPanelExpandBtn) filterPanelExpandBtn.setAttribute('aria-expanded', next ? 'false' : 'true');
    }

    function applyMobileDefaultFilterPanelState() {
        if (!filterPanelEl || filterPanelEl.hidden || filterPanelEl.dataset.mobileDefaultApplied === '1' || !isMobileViewport()) return;
        filterPanelEl.dataset.mobileDefaultApplied = '1';
        setFilterPanelCollapsed(true);
    }

    function markerById(markerId) {
        return MARKERS.find(function (marker) { return String(marker.id) === String(markerId); }) || null;
    }

    function markerMeta(marker) {
        if (iconLibrary && typeof iconLibrary.resolveMarkerMeta === 'function') {
            return iconLibrary.resolveMarkerMeta(marker || {});
        }
        var markerType = marker && marker.marker_type ? marker.marker_type : 'normal';
        return {
            markerType: markerType,
            pointerType: markerType === 'main' ? 'project' : 'landmark',
            iconKey: marker && marker.icon_key ? marker.icon_key : (markerType === 'main' ? 'main-star' : 'plot-pin'),
            iconColor: iconLibrary && typeof iconLibrary.defaultColor === 'function'
                ? iconLibrary.defaultColor(markerType)
                : (markerType === 'main' ? '#f97316' : '#22d3ee'),
            iconLook: 'solid',
            appearance: {
                color: markerType === 'main' ? '#f97316' : '#22d3ee',
                look: 'solid'
            },
            typeMeta: { label: markerType === 'main' ? 'Project / Site' : 'Landmark', shortLabel: markerType === 'main' ? 'Project' : 'Landmark' }
        };
    }

    function markerPointerType(marker) {
        return markerMeta(marker).pointerType;
    }

    function markerPointerLabel(marker) {
        return markerMeta(marker).typeMeta.label;
    }

    function markerPointerShortLabel(marker) {
        return markerMeta(marker).typeMeta.shortLabel || markerPointerLabel(marker);
    }

    function markerLabel(marker) {
        if (!marker) return '';
        var label = String(marker.label || '').trim();
        if (label) return label;
        return markerPointerShortLabel(marker);
    }

    function markerIconKey(marker) {
        return markerMeta(marker).iconKey;
    }

    function applyMarkerAppearance(el, marker) {
        if (!el) return;
        if (iconLibrary && typeof iconLibrary.applyMarkerAppearance === 'function') {
            iconLibrary.applyMarkerAppearance(el, marker || {});
            return;
        }
        var meta = markerMeta(marker);
        if (meta && meta.iconColor) el.style.setProperty('--srm-marker-bg', meta.iconColor);
    }

    function markerIconSvg(marker) {
        var markerType = marker && marker.marker_type ? marker.marker_type : 'normal';
        var pointerType = marker && marker.pointer_type ? marker.pointer_type : (markerType === 'main' ? 'project' : 'landmark');
        var key = markerIconKey(marker);
        if (iconLibrary && typeof iconLibrary.renderSvg === 'function') {
            return iconLibrary.renderSvg(key, markerType, pointerType);
        }
        return '';
    }

    function getMainMarker() {
        return MARKERS.find(function (marker) { return marker.marker_type === 'main'; }) || null;
    }

    function normalizeRoutePoints(route, startMarker, endMarker, reverse) {
        var points = Array.isArray(route.path_points) ? route.path_points.filter(function (point) {
            return point && Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y));
        }).map(function (point) {
            return { x: clampRatio(point.x), y: clampRatio(point.y) };
        }) : [];
        if (reverse) points.reverse();
        if (!points.length) {
            return [
                { x: clampRatio(startMarker.x_ratio), y: clampRatio(startMarker.y_ratio) },
                { x: clampRatio(endMarker.x_ratio), y: clampRatio(endMarker.y_ratio) }
            ];
        }
        points[0] = { x: clampRatio(startMarker.x_ratio), y: clampRatio(startMarker.y_ratio) };
        points[points.length - 1] = { x: clampRatio(endMarker.x_ratio), y: clampRatio(endMarker.y_ratio) };
        return points;
    }

    function findRoute(mainMarker, targetMarker) {
        var direct = ROUTES.find(function (route) {
            return String(route.from_marker_id) === String(mainMarker.id) &&
                   String(route.to_marker_id) === String(targetMarker.id);
        });
        if (direct) return { route: direct, reverse: false };
        var reverse = ROUTES.find(function (route) {
            return String(route.from_marker_id) === String(targetMarker.id) &&
                   String(route.to_marker_id) === String(mainMarker.id);
        });
        if (reverse) return { route: reverse, reverse: true };
        return null;
    }

    function clearRouteLayer() {
        routesSvg.innerHTML = '';
        if (activeAnimationFrame) {
            cancelAnimationFrame(activeAnimationFrame);
            activeAnimationFrame = null;
        }
    }

    function clearHoverRouteLayer() {
        if (hoverRoutesSvg) hoverRoutesSvg.innerHTML = '';
    }

    function renderHoverRoutePath(route) {
        clearHoverRouteLayer();
        if (!hoverRoutesSvg || !route) return;
        var points = normalizeHoverRoutePoints(route);
        if (points.length < 2) return;
        var glow = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        glow.setAttribute('class', 'srv-hover-path-glow');
        glow.setAttribute('points', pointsToSvg(points));
        glow.style.strokeWidth = String(routeLineWidth(route) * 0.0036);
        hoverRoutesSvg.appendChild(glow);

        var line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        line.setAttribute('class', 'srv-hover-path');
        line.setAttribute('points', pointsToSvg(points));
        line.style.stroke = routeColor(route);
        line.style.strokeWidth = String(routeLineWidth(route) * 0.0022);
        applyHoverRouteLineStyle(line, route && route.line_style);
        hoverRoutesSvg.appendChild(line);
    }

    function markerLabelDirection(marker) {
        return clampRatio(marker.x_ratio) > 0.72 ? 'left' : 'right';
    }

    function markerVisible(marker) {
        if (!marker) return false;
        if (marker.marker_type === 'main') return true;
        if (activeTypeFilter === 'all') return true;
        return markerPointerType(marker) === activeTypeFilter;
    }

    function markerClass(marker) {
        var classes = ['srv-marker', marker.marker_type === 'main' ? 'main' : 'normal', 'label-' + markerLabelDirection(marker)];
        if (String(marker.id) === String(activeMarkerId)) classes.push('active');
        if (!markerVisible(marker)) classes.push('hidden');
        return classes.join(' ');
    }

    function renderMarkers() {
        markersLayer.innerHTML = '';
        MARKERS.forEach(function (marker) {
            if (!markerVisible(marker)) return;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = markerClass(marker);
            button.style.left = (clampRatio(marker.x_ratio) * 100) + '%';
            button.style.top = (clampRatio(marker.y_ratio) * 100) + '%';
            button.title = markerLabel(marker);
            button.innerHTML = '<span class="srv-marker-pin"><span class="srv-marker-icon">' + markerIconSvg(marker) + '</span></span><span class="srv-marker-label">' + markerLabel(marker) + '</span>';
            applyMarkerAppearance(button, marker);
            button.addEventListener('click', function () {
                handleMarkerClick(marker);
            });
            markersLayer.appendChild(button);
        });
    }

    function renderHoverRouteChips() {
        if (!hoverRoutesLayer) return;
        hoverRoutesLayer.innerHTML = '';
        HOVER_ROUTES.forEach(function (route, index) {
            var points = normalizeHoverRoutePoints(route);
            if (points.length < 2) return;
            var anchor = hoverRouteMidpoint(points);
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'srv-hover-chip';
            button.dataset.hoverRouteId = route.id;
            if (String(route.id) === String(activeHoverRouteId)) button.classList.add('active');
            button.style.left = (anchor.x * 100) + '%';
            button.style.top = (anchor.y * 100) + '%';
            button.textContent = hoverRouteLabel(route, index);
            button.title = hoverRouteLabel(route, index);
            button.addEventListener('mouseenter', function () {
                if (hoverRouteLocked && String(activeHoverRouteId) !== String(route.id)) return;
                activeHoverRouteId = route.id;
                hoverRouteLocked = false;
                renderHoverRoutePath(route);
                syncHoverRouteChipState();
                statusEl.textContent = 'Previewing independent route: ' + hoverRouteLabel(route, index);
            });
            button.addEventListener('mouseleave', function () {
                if (hoverRouteLocked && String(activeHoverRouteId) === String(route.id)) return;
                activeHoverRouteId = null;
                clearHoverRouteLayer();
                syncHoverRouteChipState();
                if (!activeMarkerId) statusEl.textContent = defaultStatusText();
            });
            button.addEventListener('focus', function () {
                activeHoverRouteId = route.id;
                hoverRouteLocked = false;
                renderHoverRoutePath(route);
                syncHoverRouteChipState();
                statusEl.textContent = 'Previewing independent route: ' + hoverRouteLabel(route, index);
            });
            button.addEventListener('blur', function () {
                if (hoverRouteLocked && String(activeHoverRouteId) === String(route.id)) return;
                activeHoverRouteId = null;
                clearHoverRouteLayer();
                syncHoverRouteChipState();
                if (!activeMarkerId) statusEl.textContent = defaultStatusText();
            });
            button.addEventListener('click', function () {
                if (hoverRouteLocked && String(activeHoverRouteId) === String(route.id)) {
                    hoverRouteLocked = false;
                    activeHoverRouteId = null;
                    clearHoverRouteLayer();
                    syncHoverRouteChipState();
                    if (!activeMarkerId) statusEl.textContent = defaultStatusText();
                    return;
                }
                activeHoverRouteId = route.id;
                hoverRouteLocked = true;
                renderHoverRoutePath(route);
                syncHoverRouteChipState();
                statusEl.textContent = 'Pinned independent route: ' + hoverRouteLabel(route, index);
            });
            hoverRoutesLayer.appendChild(button);
        });
    }

    function syncHoverRouteChipState() {
        if (!hoverRoutesLayer) return;
        hoverRoutesLayer.querySelectorAll('.srv-hover-chip[data-hover-route-id]').forEach(function (button) {
            button.classList.toggle('active', String(button.dataset.hoverRouteId || '') === String(activeHoverRouteId || ''));
        });
    }

    function pointsToSvg(points) {
        return points.map(function (point) { return point.x + ',' + point.y; }).join(' ');
    }

    function hoverRouteLabel(route, index) {
        var label = route && String(route.label || '').trim();
        if (label) return label;
        return 'Independent Route ' + (Number(index) + 1);
    }

    function normalizeHoverRoutePoints(route) {
        return Array.isArray(route && route.path_points) ? route.path_points.filter(function (point) {
            return point && Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y));
        }).map(function (point) {
            return { x: clampRatio(point.x), y: clampRatio(point.y) };
        }) : [];
    }

    function hoverRouteMidpoint(points) {
        if (!points.length) return { x: 0.5, y: 0.5 };
        if (points.length === 1) return points[0];
        var segments = [];
        var total = 0;
        for (var i = 1; i < points.length; i += 1) {
            var dx = points[i].x - points[i - 1].x;
            var dy = points[i].y - points[i - 1].y;
            var length = Math.sqrt((dx * dx) + (dy * dy));
            segments.push({ index: i, length: length });
            total += length;
        }
        if (!total) return points[Math.floor(points.length / 2)] || points[0];
        var halfway = total / 2;
        var walked = 0;
        for (var s = 0; s < segments.length; s += 1) {
            var segment = segments[s];
            if ((walked + segment.length) >= halfway) {
                var prev = points[segment.index - 1];
                var next = points[segment.index];
                var local = (halfway - walked) / (segment.length || 1);
                return {
                    x: clampRatio(prev.x + ((next.x - prev.x) * local)),
                    y: clampRatio(prev.y + ((next.y - prev.y) * local))
                };
            }
            walked += segment.length;
        }
        return points[points.length - 1];
    }

    function animateRoute(points, style) {
        clearRouteLayer();
        var strokeColor = normalizeHexColor(style && style.color, '#162338');
        var strokeWidth = routeStrokeWidthSvg(style && style.line_width);
        var finalLineStyle = normalizeRouteLineStyle(style && style.line_style, 'dashed');

        var polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        polyline.setAttribute('class', 'srv-path');
        polyline.setAttribute('points', pointsToSvg(points));
        polyline.style.stroke = strokeColor;
        polyline.style.strokeWidth = strokeWidth;
        routesSvg.appendChild(polyline);

        var length = polyline.getTotalLength();
        polyline.style.strokeDasharray = String(length);
        polyline.style.strokeDashoffset = String(length);
        polyline.getBoundingClientRect();
        polyline.style.transition = 'stroke-dashoffset 900ms ease';
        polyline.style.strokeDashoffset = '0';

        var routeStrokeFinalized = false;
        function finalizeRouteStroke() {
            if (routeStrokeFinalized) return;
            routeStrokeFinalized = true;
            polyline.style.transition = '';
            polyline.style.strokeDashoffset = '0';
            applyRouteLineStyle(polyline, finalLineStyle);
        }
        polyline.addEventListener('transitionend', finalizeRouteStroke, { once: true });
        window.setTimeout(finalizeRouteStroke, 980);

        var dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('class', 'srv-dot');
        dot.setAttribute('r', '0.01');
        dot.style.fill = strokeColor;
        routesSvg.appendChild(dot);

        var startedAt = null;
        var duration = 900;
        function tick(timestamp) {
            if (!startedAt) startedAt = timestamp;
            var progress = Math.min(1, (timestamp - startedAt) / duration);
            var point = polyline.getPointAtLength(length * progress);
            dot.setAttribute('cx', point.x);
            dot.setAttribute('cy', point.y);
            if (progress < 1) {
                activeAnimationFrame = requestAnimationFrame(tick);
            } else {
                activeAnimationFrame = null;
            }
        }
        activeAnimationFrame = requestAnimationFrame(tick);
    }

    function showRouteModal(fromMarker, toMarker, distanceKm) {
        if (!routeModalEl) return;
        routeModalIconEl.innerHTML = markerIconSvg(toMarker);
        applyMarkerAppearance(routeModalEl, toMarker);
        if (routeModalMediaEl) applyMarkerAppearance(routeModalMediaEl, toMarker);
        if (routeModalIconEl) applyMarkerAppearance(routeModalIconEl, toMarker);
        routeModalEyebrowEl.textContent = markerLabel(fromMarker) + ' -> Route';
        routeModalTitleEl.textContent = markerLabel(toMarker);
        routeModalPointerTypeEl.textContent = markerPointerLabel(toMarker);
        routeModalDistanceEl.textContent = formatDistanceKm(distanceKm);
        routeModalEl.hidden = false;
    }

    function hideRouteModal() {
        if (routeModalEl) routeModalEl.hidden = true;
    }

    function clearActiveMarkerSelection(shouldResetStatus) {
        var hadActiveMarker = !!activeMarkerId;
        activeMarkerId = null;
        if (hadActiveMarker) {
            renderMarkers();
        }
        clearRouteLayer();
        hideRouteModal();
        if (shouldResetStatus && !activeHoverRouteId) {
            statusEl.textContent = defaultStatusText();
        }
    }

    function distinctPointerTypes() {
        var seen = {};
        var types = [];
        MARKERS.forEach(function (marker) {
            if (marker.marker_type === 'main') return;
            var typeKey = markerPointerType(marker);
            if (!typeKey || seen[typeKey]) return;
            seen[typeKey] = true;
            types.push({ key: typeKey, label: markerPointerShortLabel(marker) });
        });
        return types.sort(function (a, b) {
            return a.label.localeCompare(b.label);
        });
    }

    function renderTypeFilters() {
        if (!typeFiltersEl || !filterPanelEl) return;
        var types = distinctPointerTypes();
        if (!types.length) {
            typeFiltersEl.innerHTML = '';
            filterPanelEl.hidden = true;
            return;
        }
        filterPanelEl.hidden = false;
        var allTypes = [{ key: 'all', label: 'All' }].concat(types);
        typeFiltersEl.innerHTML = allTypes.map(function (typeMeta) {
            var cls = 'srv-filter-chip';
            if (typeMeta.key === activeTypeFilter) cls += ' active';
            return '<button type="button" class="' + cls + '" data-pointer-type="' + typeMeta.key + '">' + typeMeta.label + '</button>';
        }).join('');
        typeFiltersEl.querySelectorAll('[data-pointer-type]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                activeTypeFilter = btn.dataset.pointerType || 'all';
                if (activeMarkerId) {
                    var activeMarker = markerById(activeMarkerId);
                    if (activeMarker && !markerVisible(activeMarker)) {
                        clearActiveMarkerSelection(false);
                    }
                }
                renderTypeFilters();
                renderMarkers();
                if (!activeHoverRouteId) {
                    statusEl.textContent = activeTypeFilter === 'all'
                        ? defaultStatusText()
                        : ('Showing only ' + btn.textContent + ' pointers.');
                }
            });
        });
        applyMobileDefaultFilterPanelState();
    }

    function handleMarkerClick(targetMarker) {
        if (!targetMarker || targetMarker.marker_type === 'main') return;
        if (String(activeMarkerId || '') === String(targetMarker.id || '')) {
            clearActiveMarkerSelection(true);
            return;
        }
        hoverRouteLocked = false;
        activeHoverRouteId = null;
        clearHoverRouteLayer();
        syncHoverRouteChipState();
        var mainMarker = getMainMarker();
        if (!mainMarker) {
            statusEl.textContent = 'No main pointer is configured on this map yet.';
            return;
        }
        activeMarkerId = targetMarker.id;
        renderMarkers();

        var routeMatch = findRoute(mainMarker, targetMarker);
        var points;
        var style = { color: '#162338', line_width: 3 };
        var distanceKm = null;
        if (routeMatch) {
            points = normalizeRoutePoints(routeMatch.route, mainMarker, targetMarker, routeMatch.reverse);
            style = { color: routeColor(routeMatch.route), line_width: routeLineWidth(routeMatch.route) };
            distanceKm = routeDistanceKm(routeMatch.route);
            statusEl.textContent = 'Showing route: ' + markerLabel(mainMarker) + ' -> ' + markerLabel(targetMarker);
        } else {
            points = [
                { x: clampRatio(mainMarker.x_ratio), y: clampRatio(mainMarker.y_ratio) },
                { x: clampRatio(targetMarker.x_ratio), y: clampRatio(targetMarker.y_ratio) }
            ];
            statusEl.textContent = 'Direct route shown (custom route not configured).';
        }
        showRouteModal(mainMarker, targetMarker, distanceKm);
        animateRoute(points, style);
    }

    function handleStageClick(event) {
        if (!stageEl) return;
        if (suppressStageClickOnce) {
            suppressStageClickOnce = false;
            return;
        }
        if (event.target && event.target.closest && event.target.closest('.srv-marker, .srv-hover-chip, .srv-route-modal, .srv-filter-panel')) {
            return;
        }
        clearActiveMarkerSelection(true);
    }

    function bindFilterPanelControls() {
        if (filterPanelCollapseBtn) {
            filterPanelCollapseBtn.addEventListener('click', function () {
                setFilterPanelCollapsed(true);
            });
        }
        if (filterPanelExpandBtn) {
            filterPanelExpandBtn.addEventListener('click', function () {
                setFilterPanelCollapsed(false);
            });
        }
    }

    function bindMapInteractions() {
        if (!stageEl || !mapCanvasEl) return;

        stageEl.addEventListener('wheel', function (event) {
            if (isInteractiveUiTarget(event.target)) return;
            event.preventDefault();
            var delta = event.deltaY > 0 ? 0.9 : 1.1;
            zoomMapAroundPoint(mapScale * delta, event.clientX, event.clientY);
        }, { passive: false });

        stageEl.addEventListener('mousedown', function (event) {
            if (event.button !== 0 || isInteractiveUiTarget(event.target)) return;
            mousePanActive = true;
            panStartClientX = event.clientX;
            panStartClientY = event.clientY;
            panStartTranslateX = mapTranslateX;
            panStartTranslateY = mapTranslateY;
            mapCanvasEl.classList.add('is-dragging');
            event.preventDefault();
        });

        window.addEventListener('mousemove', function (event) {
            if (!mousePanActive) return;
            var deltaX = event.clientX - panStartClientX;
            var deltaY = event.clientY - panStartClientY;
            if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) suppressStageClickOnce = true;
            mapTranslateX = panStartTranslateX + deltaX;
            mapTranslateY = panStartTranslateY + deltaY;
            applyMapTransform();
        });

        window.addEventListener('mouseup', function () {
            if (!mousePanActive) return;
            mousePanActive = false;
            if (mapCanvasEl) mapCanvasEl.classList.remove('is-dragging');
        });

        stageEl.addEventListener('touchstart', function (event) {
            if (isInteractiveUiTarget(event.target)) return;
            if (event.touches.length >= 2) {
                touchPinchActive = true;
                touchPanActive = false;
                pinchStartDistance = touchDistance(event.touches);
                pinchStartScale = mapScale;
                pinchLastCenter = touchCenter(event.touches);
                if (mapCanvasEl) mapCanvasEl.classList.add('is-dragging');
                return;
            }
            if (event.touches.length === 1) {
                touchPanActive = true;
                touchPinchActive = false;
                panStartClientX = event.touches[0].clientX;
                panStartClientY = event.touches[0].clientY;
                panStartTranslateX = mapTranslateX;
                panStartTranslateY = mapTranslateY;
                if (mapCanvasEl) mapCanvasEl.classList.add('is-dragging');
            }
        }, { passive: true });

        stageEl.addEventListener('touchmove', function (event) {
            if (touchPinchActive && event.touches.length >= 2) {
                event.preventDefault();
                var nextDistance = touchDistance(event.touches);
                var center = touchCenter(event.touches);
                if (pinchLastCenter && center) {
                    mapTranslateX += center.clientX - pinchLastCenter.clientX;
                    mapTranslateY += center.clientY - pinchLastCenter.clientY;
                }
                pinchLastCenter = center;
                suppressStageClickOnce = true;
                zoomMapAroundPoint((pinchStartScale * nextDistance) / (pinchStartDistance || 1), center.clientX, center.clientY);
                return;
            }
            if (touchPanActive && event.touches.length === 1) {
                event.preventDefault();
                var deltaX = event.touches[0].clientX - panStartClientX;
                var deltaY = event.touches[0].clientY - panStartClientY;
                if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) suppressStageClickOnce = true;
                mapTranslateX = panStartTranslateX + deltaX;
                mapTranslateY = panStartTranslateY + deltaY;
                applyMapTransform();
            }
        }, { passive: false });

        function endTouchInteraction(event) {
            if (touchPinchActive && event.touches && event.touches.length === 1) {
                touchPinchActive = false;
                touchPanActive = true;
                panStartClientX = event.touches[0].clientX;
                panStartClientY = event.touches[0].clientY;
                panStartTranslateX = mapTranslateX;
                panStartTranslateY = mapTranslateY;
                pinchLastCenter = null;
                return;
            }
            if (event.touches && event.touches.length >= 2) return;
            releaseMapPointerState();
        }

        stageEl.addEventListener('touchend', endTouchInteraction, { passive: true });
        stageEl.addEventListener('touchcancel', endTouchInteraction, { passive: true });
    }

    function init() {
        var mainMarker = getMainMarker();
        if (!mainMarker) {
            statusEl.textContent = 'Main pointer missing. Please ask your builder to configure one.';
        } else {
            statusEl.textContent = defaultStatusText();
        }
        bindFilterPanelControls();
        bindMapInteractions();
        if (stageEl) stageEl.addEventListener('click', handleStageClick);
        if (imageEl) {
            if (imageEl.complete) resetMapView();
            else imageEl.addEventListener('load', resetMapView, { once: true });
        }
        window.addEventListener('resize', function () {
            applyMapTransform();
            applyMobileDefaultFilterPanelState();
        });
        renderTypeFilters();
        renderMarkers();
        renderHoverRouteChips();
    }

    init();
})();
