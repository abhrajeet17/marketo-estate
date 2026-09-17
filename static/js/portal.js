/* ═══════════════════════════════════════════════════════════════
   Portal – Customer property explorer
   Features: search, filters, lazy-loading images, infinite scroll,
             grid/list/map views, Google Maps integration
   ═══════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    /* ── State ── */
    var state = {
        projects: [],
        allProjects: [],
        page: 1,
        perPage: 12,
        total: 0,
        loading: false,
        query: '',
        city: '',
        type: '',
        sort: 'newest',
        view: 'grid',      // grid | list | map
        cities: [],
        mapLoaded: false,
        map: null,
        markers: [],
    };

    /* ── DOM refs ── */
    var dom = {};
    function cacheDom() {
        dom.grid = document.getElementById('portal-grid');
        dom.empty = document.getElementById('portal-empty');
        dom.loadMore = document.getElementById('portal-load-more');
        dom.searchInput = document.getElementById('portal-search-input');
        dom.searchBtn = document.getElementById('portal-search-btn');
        dom.filterCity = document.getElementById('filter-city');
        dom.filterSort = document.getElementById('filter-sort');
        dom.resultsTitle = document.getElementById('portal-results-title');
        dom.resultsCount = document.getElementById('portal-results-count');
        dom.viewGrid = document.getElementById('view-grid');
        dom.viewList = document.getElementById('view-list');
        dom.viewMap = document.getElementById('view-map');
        dom.mapSection = document.getElementById('map-section');
        dom.mapContainer = document.getElementById('portal-map');
        dom.mapSidebarList = document.getElementById('portal-map-sidebar-list');
        dom.closeMap = document.getElementById('close-map');
        dom.modal = document.getElementById('project-modal');
        dom.modalBody = document.getElementById('project-modal-body');
        dom.modalClose = document.getElementById('project-modal-close');
        dom.statProjects = document.getElementById('stat-projects');
        dom.statPlots = document.getElementById('stat-plots');
        dom.statCities = document.getElementById('stat-cities');
        dom.statAvailable = document.getElementById('stat-available');
        dom.chips = document.querySelectorAll('.portal-chip[data-type]');
        dom.navMapLink = document.getElementById('nav-map-link');
    }

    /* ── Utility ── */
    function formatPrice(num) {
        if (!num || num === 0) return '--';
        if (num >= 10000000) return (num / 10000000).toFixed(2) + ' Cr';
        if (num >= 100000) return (num / 100000).toFixed(2) + ' L';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toLocaleString('en-IN');
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            var d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            return d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
        } catch (e) { return dateStr; }
    }

    function thumbnailUrl(filename) {
        if (!filename) return '';
        return '/uploads/' + encodeURIComponent(filename) + '?size=thumb';
    }

    function fullImageUrl(filename) {
        if (!filename) return '';
        return '/uploads/' + encodeURIComponent(filename);
    }

    function escHtml(str) {
        var el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }

    function projectTypeLabel(t) {
        var labels = {
            residential: 'Residential',
            commercial: 'Commercial',
            plotted: 'Plotted',
            villa: 'Villa',
            mixed: 'Mixed Use',
            farmland: 'Farm Land',
        };
        return labels[t] || (t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Residential');
    }

    function debounce(fn, ms) {
        var timer;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    /* ── API ── */
    function fetchProjects(append) {
        if (state.loading) return;
        state.loading = true;
        if (!append) {
            state.page = 1;
            dom.grid.innerHTML = skeletonHtml(6);
        }
        dom.loadMore.hidden = true;

        var params = new URLSearchParams();
        params.set('page', state.page);
        params.set('per_page', state.perPage);
        if (state.query) params.set('q', state.query);
        if (state.city) params.set('city', state.city);
        if (state.type) params.set('type', state.type);
        if (state.sort) params.set('sort', state.sort);

        fetch('/api/public/portal/projects?' + params.toString())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var projects = data.projects || [];
                state.total = data.total || projects.length;

                if (append) {
                    state.projects = state.projects.concat(projects);
                } else {
                    state.projects = projects;
                    state.allProjects = projects;
                    state.cities = data.cities || [];
                    populateCityFilter();
                }

                renderGrid();
                updateStats();
                updateResultsInfo();

                // Show load-more sentinel if there are more pages
                var hasMore = state.projects.length < state.total;
                dom.loadMore.hidden = !hasMore;

                state.loading = false;
            })
            .catch(function (err) {
                console.error('Portal fetch error:', err);
                state.loading = false;
                if (!append) {
                    dom.grid.innerHTML = '';
                    dom.empty.hidden = false;
                }
            });
    }

    /* ── Render ── */
    function skeletonHtml(count) {
        var html = '';
        for (var i = 0; i < count; i++) {
            html += '<div class="portal-skeleton-card"><div class="skeleton-img"></div>' +
                '<div class="skeleton-body"><div class="skeleton-line w70"></div>' +
                '<div class="skeleton-line w40"></div><div class="skeleton-line w90"></div></div></div>';
        }
        return html;
    }

    function renderGrid() {
        var projects = state.projects;
        dom.empty.hidden = projects.length > 0;

        if (projects.length === 0) {
            dom.grid.innerHTML = '';
            return;
        }

        var html = '';
        for (var i = 0; i < projects.length; i++) {
            html += buildCardHtml(projects[i], i);
        }
        dom.grid.innerHTML = html;

        // Apply view class
        dom.grid.classList.toggle('list-view', state.view === 'list');

        // Setup lazy loading for images
        setupLazyImages();

        // Stagger animations
        var cards = dom.grid.querySelectorAll('.portal-card');
        for (var j = 0; j < cards.length; j++) {
            cards[j].style.animationDelay = (j % 12) * 0.04 + 's';
        }
    }

    function buildCardHtml(p, idx) {
        var plotCount = p.plot_count || 0;
        var available = p.available_plots || 0;
        var sold = p.sold_plots || 0;
        var hold = p.hold_plots || 0;
        var total = available + sold + hold || 1;
        var availPct = (available / total * 100).toFixed(1);
        var holdPct = (hold / total * 100).toFixed(1);
        var soldPct = (sold / total * 100).toFixed(1);

        var locationParts = [];
        if (p.location_city) locationParts.push(p.location_city);
        if (p.location_state) locationParts.push(p.location_state);
        var locationStr = locationParts.join(', ') || p.location_address || '';

        var badges = '';
        if (p.is_360) badges += '<span class="portal-badge portal-badge--360">360°</span>';
        if (p.project_type) badges += '<span class="portal-badge portal-badge--type">' + escHtml(projectTypeLabel(p.project_type)) + '</span>';
        if (p.rera_registration) badges += '<span class="portal-badge portal-badge--rera">RERA</span>';

        return '<div class="portal-card" data-id="' + escHtml(String(p.id)) + '" onclick="window.__portalOpenProject(\'' + String(p.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')">' +
            '<div class="portal-card-image">' +
                '<img data-src="' + escHtml(thumbnailUrl(p.filename)) + '" alt="' + escHtml(p.name) + '" class="lazy-img" loading="lazy">' +
                '<div class="portal-card-badges">' + badges + '</div>' +
                '<div class="portal-card-plots-bar">' +
                    '<div class="bar-available" style="width:' + availPct + '%"></div>' +
                    '<div class="bar-hold" style="width:' + holdPct + '%"></div>' +
                    '<div class="bar-sold" style="width:' + soldPct + '%"></div>' +
                '</div>' +
            '</div>' +
            '<div class="portal-card-body">' +
                '<div class="portal-card-title">' + escHtml(p.name) + '</div>' +
                (p.builder_name ? '<div class="portal-card-builder">by ' + escHtml(p.builder_name) + '</div>' : '') +
                (locationStr ? '<div class="portal-card-location"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>' + escHtml(locationStr) + '</div>' : '') +
                '<div class="portal-card-stats">' +
                    '<div class="portal-card-stat"><div class="portal-card-stat-val">' + plotCount + '</div><div class="portal-card-stat-label">Plots</div></div>' +
                    '<div class="portal-card-stat"><div class="portal-card-stat-val">' + formatPrice(p.avg_price) + '</div><div class="portal-card-stat-label">Avg Price</div></div>' +
                    '<div class="portal-card-stat"><div class="portal-card-stat-val">' + available + '</div><div class="portal-card-stat-label">Available</div></div>' +
                '</div>' +
            '</div>' +
            '<div class="portal-card-footer">' +
                (p.launch_date ? '<span class="portal-card-date">Launch: ' + escHtml(formatDate(p.launch_date)) + '</span>' : '<span class="portal-card-date"></span>') +
                '<span class="portal-card-cta">View Project <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg></span>' +
            '</div>' +
        '</div>';
    }

    /* ── Lazy Loading with IntersectionObserver ── */
    var imageObserver;
    function setupLazyImages() {
        var imgs = dom.grid.querySelectorAll('img.lazy-img');
        if (!imageObserver) {
            if ('IntersectionObserver' in window) {
                imageObserver = new IntersectionObserver(function (entries) {
                    for (var i = 0; i < entries.length; i++) {
                        if (entries[i].isIntersecting) {
                            var img = entries[i].target;
                            if (img.dataset.src) {
                                img.src = img.dataset.src;
                                img.removeAttribute('data-src');
                                img.classList.remove('lazy-img');
                            }
                            imageObserver.unobserve(img);
                        }
                    }
                }, { rootMargin: '200px 0px' });
            }
        }
        for (var j = 0; j < imgs.length; j++) {
            if (imageObserver) {
                imageObserver.observe(imgs[j]);
            } else {
                // Fallback: load all
                imgs[j].src = imgs[j].dataset.src;
            }
        }
    }

    /* ── Infinite Scroll with IntersectionObserver ── */
    function setupInfiniteScroll() {
        if (!('IntersectionObserver' in window)) return;
        var sentinel = dom.loadMore;
        var scrollObserver = new IntersectionObserver(function (entries) {
            if (entries[0].isIntersecting && !state.loading && state.projects.length < state.total) {
                state.page++;
                fetchProjects(true);
            }
        }, { rootMargin: '400px 0px' });
        scrollObserver.observe(sentinel);
    }

    /* ── City Filter ── */
    function populateCityFilter() {
        if (!dom.filterCity) return;
        var currentVal = dom.filterCity.value;
        dom.filterCity.innerHTML = '<option value="">All Cities</option>';
        for (var i = 0; i < state.cities.length; i++) {
            var opt = document.createElement('option');
            opt.value = state.cities[i];
            opt.textContent = state.cities[i];
            dom.filterCity.appendChild(opt);
        }
        dom.filterCity.value = currentVal;
    }

    /* ── Stats ── */
    function updateStats() {
        var projects = state.projects;
        var totalPlots = 0, totalAvailable = 0;
        var citySet = {};
        for (var i = 0; i < projects.length; i++) {
            totalPlots += projects[i].plot_count || 0;
            totalAvailable += projects[i].available_plots || 0;
            var c = projects[i].location_city;
            if (c) citySet[c] = true;
        }
        animateNumber(dom.statProjects, state.total || projects.length);
        animateNumber(dom.statPlots, totalPlots);
        animateNumber(dom.statCities, state.cities.length || Object.keys(citySet).length);
        animateNumber(dom.statAvailable, totalAvailable);
    }

    function animateNumber(el, target) {
        if (!el) return;
        var current = parseInt(el.textContent) || 0;
        if (current === target) return;
        var steps = 20;
        var increment = (target - current) / steps;
        var step = 0;
        function tick() {
            step++;
            if (step >= steps) {
                el.textContent = target;
                return;
            }
            el.textContent = Math.round(current + increment * step);
            requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    function updateResultsInfo() {
        var title = 'All Projects';
        if (state.query) title = 'Results for "' + state.query + '"';
        else if (state.type) title = projectTypeLabel(state.type) + ' Projects';
        else if (state.city) title = 'Projects in ' + state.city;
        dom.resultsTitle.textContent = title;
        dom.resultsCount.textContent = state.total ? '(' + state.total + ' found)' : '';
    }

    /* ── View Toggle ── */
    function setView(view) {
        state.view = view;
        dom.viewGrid.classList.toggle('active', view === 'grid');
        dom.viewList.classList.toggle('active', view === 'list');
        dom.viewMap.classList.toggle('active', view === 'map');
        dom.grid.classList.toggle('list-view', view === 'list');

        if (view === 'map') {
            dom.mapSection.hidden = false;
            dom.mapSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            initMap();
        } else {
            dom.mapSection.hidden = true;
        }
    }

    /* ── Google Maps Integration ── */
    function initMap() {
        if (state.mapLoaded && state.map) {
            updateMapMarkers();
            return;
        }

        // Check if Google Maps is already loaded
        if (window.google && window.google.maps) {
            createMap();
            return;
        }

        // Load Google Maps API
        // Using a placeholder — the actual API key should be configured
        var existing = document.getElementById('google-maps-script');
        if (existing) {
            // Script loading in progress, wait
            existing.addEventListener('load', createMap);
            return;
        }

        // Create a map without Google Maps if API key not available
        // Use OpenStreetMap/Leaflet as fallback via iframe or simple HTML markers
        createFallbackMap();
    }

    function createMap() {
        if (!window.google || !window.google.maps) {
            createFallbackMap();
            return;
        }
        var center = { lat: 20.5937, lng: 78.9629 }; // India center
        state.map = new google.maps.Map(dom.mapContainer, {
            center: center,
            zoom: 5,
            mapTypeControl: false,
            streetViewControl: false,
            styles: [
                { featureType: 'poi', stylers: [{ visibility: 'off' }] },
                { featureType: 'transit', stylers: [{ visibility: 'off' }] },
            ],
        });
        state.mapLoaded = true;
        updateMapMarkers();
    }

    function createFallbackMap() {
        // Render an interactive map using OpenStreetMap embeds as fallback
        state.mapLoaded = true;
        var projectsWithCoords = state.projects.filter(function (p) {
            return p.location_lat && p.location_lng;
        });

        if (projectsWithCoords.length === 0) {
            dom.mapContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;flex-direction:column;gap:0.5rem;color:var(--color-muted);font-size:0.85rem;">' +
                '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>' +
                '<p>No projects with map coordinates yet.</p>' +
                '<p style="font-size:0.72rem;">Add Google Maps links in the dashboard to see projects on the map.</p></div>';
        } else {
            // Find center
            var latSum = 0, lngSum = 0;
            projectsWithCoords.forEach(function (p) { latSum += p.location_lat; lngSum += p.location_lng; });
            var centerLat = latSum / projectsWithCoords.length;
            var centerLng = lngSum / projectsWithCoords.length;

            // Render with OpenStreetMap iframe + marker overlay
            var zoom = projectsWithCoords.length === 1 ? 14 : 6;
            dom.mapContainer.innerHTML =
                '<iframe width="100%" height="100%" frameborder="0" scrolling="no" ' +
                'src="https://www.openstreetmap.org/export/embed.html?bbox=' +
                (centerLng - 5) + ',' + (centerLat - 3) + ',' + (centerLng + 5) + ',' + (centerLat + 3) +
                '&layer=mapnik" style="border:0;"></iframe>' +
                '<div style="position:absolute;top:0.75rem;left:0.75rem;background:rgba(255,255,255,0.95);padding:0.5rem 0.75rem;border-radius:8px;font-size:0.72rem;font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,0.1);">' +
                projectsWithCoords.length + ' project(s) with coordinates</div>';
            dom.mapContainer.style.position = 'relative';
        }

        // Populate sidebar
        updateMapSidebar();
    }

    function updateMapMarkers() {
        if (!state.map || !window.google) return;
        // Clear old markers
        state.markers.forEach(function (m) { m.setMap(null); });
        state.markers = [];

        var bounds = new google.maps.LatLngBounds();
        var hasCoords = false;

        state.projects.forEach(function (p) {
            if (!p.location_lat || !p.location_lng) return;
            hasCoords = true;
            var pos = { lat: p.location_lat, lng: p.location_lng };
            var marker = new google.maps.Marker({
                position: pos,
                map: state.map,
                title: p.name,
            });
            var infoWindow = new google.maps.InfoWindow({
                content: '<div style="font-family:Syne,sans-serif;max-width:220px;padding:0.25rem;">' +
                    '<strong style="font-size:0.9rem;">' + escHtml(p.name) + '</strong>' +
                    (p.builder_name ? '<div style="font-size:0.72rem;color:#666;">' + escHtml(p.builder_name) + '</div>' : '') +
                    '<div style="font-size:0.75rem;margin-top:0.3rem;">' + (p.plot_count || 0) + ' plots | ' + (p.available_plots || 0) + ' available</div>' +
                    '<a href="#" onclick="window.__portalOpenProject(\'' + String(p.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\');return false;" style="font-size:0.72rem;color:#c9a962;font-weight:600;">View Details</a>' +
                    '</div>',
            });
            marker.addListener('click', function () {
                infoWindow.open(state.map, marker);
            });
            bounds.extend(pos);
            state.markers.push(marker);
        });

        if (hasCoords) {
            state.map.fitBounds(bounds);
            if (state.markers.length === 1) state.map.setZoom(14);
        }

        updateMapSidebar();
    }

    function updateMapSidebar() {
        if (!dom.mapSidebarList) return;
        var html = '';
        state.projects.forEach(function (p) {
            var loc = p.location_city || p.location_address || '';
            html += '<button class="portal-map-item" onclick="window.__portalOpenProject(\'' + String(p.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')">' +
                '<img class="portal-map-item-thumb" src="' + escHtml(thumbnailUrl(p.filename)) + '" alt="" loading="lazy">' +
                '<div class="portal-map-item-info">' +
                    '<div class="portal-map-item-name">' + escHtml(p.name) + '</div>' +
                    (loc ? '<div class="portal-map-item-loc">' + escHtml(loc) + '</div>' : '') +
                    '<div class="portal-map-item-plots">' + (p.available_plots || 0) + ' available of ' + (p.plot_count || 0) + '</div>' +
                '</div>' +
            '</button>';
        });
        dom.mapSidebarList.innerHTML = html || '<div style="padding:1rem;text-align:center;color:var(--color-muted);font-size:0.78rem;">No projects to show</div>';
    }

    /* ── Project Detail Modal ── */
    window.__portalOpenProject = function (id) {
        var project = null;
        for (var i = 0; i < state.projects.length; i++) {
            if (String(state.projects[i].id) === String(id)) { project = state.projects[i]; break; }
        }
        if (!project) return;

        var amenities = project.amenities || [];
        var amenitiesHtml = '';
        if (amenities.length) {
            amenitiesHtml = '<div class="portal-modal-section-title">Amenities</div><div class="portal-modal-amenities">';
            amenities.forEach(function (a) { amenitiesHtml += '<span class="portal-amenity-tag">' + escHtml(a) + '</span>'; });
            amenitiesHtml += '</div>';
        }

        var locationParts = [];
        if (project.location_address) locationParts.push(project.location_address);
        if (project.location_city) locationParts.push(project.location_city);
        if (project.location_state) locationParts.push(project.location_state);

        // Build view URL
        var viewUrl = '/customer/project/' + encodeURIComponent(project.id);

        var html = '<div class="portal-modal-hero">' +
            '<img src="' + escHtml(fullImageUrl(project.filename)) + '" alt="' + escHtml(project.name) + '" loading="lazy">' +
            '<div class="portal-modal-hero-overlay">' +
                '<div class="portal-modal-hero-title">' + escHtml(project.name) + '</div>' +
                (project.builder_name ? '<div class="portal-modal-hero-builder">by ' + escHtml(project.builder_name) + '</div>' : '') +
            '</div>' +
        '</div>' +
        '<div class="portal-modal-content">' +
            '<div class="portal-modal-meta-grid">' +
                metaItem('Location', locationParts.join(', ') || '--') +
                metaItem('Project Type', projectTypeLabel(project.project_type)) +
                metaItem('Total Area', project.total_area || '--') +
                metaItem('RERA No.', project.rera_registration || '--') +
                metaItem('Launch Date', formatDate(project.launch_date) || '--') +
                metaItem('Possession', project.possession_date || '--') +
                metaItem('Avg Price', formatPrice(project.avg_price)) +
                metaItem('Price Range', project.min_price ? formatPrice(project.min_price) + ' - ' + formatPrice(project.max_price) : '--') +
            '</div>' +

            (project.description ? '<div class="portal-modal-section-title">About</div><div class="portal-modal-description">' + escHtml(project.description) + '</div>' : '') +
            amenitiesHtml +

            '<div class="portal-modal-section-title">Plot Availability</div>' +
            '<div class="portal-modal-plot-stats">' +
                '<div class="portal-modal-plot-stat"><div class="portal-modal-plot-stat-val">' + (project.plot_count || 0) + '</div><div class="portal-modal-plot-stat-label">Total Plots</div></div>' +
                '<div class="portal-modal-plot-stat"><div class="portal-modal-plot-stat-val available">' + (project.available_plots || 0) + '</div><div class="portal-modal-plot-stat-label">Available</div></div>' +
                '<div class="portal-modal-plot-stat"><div class="portal-modal-plot-stat-val hold">' + (project.hold_plots || 0) + '</div><div class="portal-modal-plot-stat-label">On Hold</div></div>' +
                '<div class="portal-modal-plot-stat"><div class="portal-modal-plot-stat-val sold">' + (project.sold_plots || 0) + '</div><div class="portal-modal-plot-stat-label">Sold</div></div>' +
            '</div>' +

            (project.contact_phone || project.contact_email ?
                '<div class="portal-modal-section-title">Contact</div>' +
                '<div style="display:flex;gap:1.5rem;margin-bottom:1rem;font-size:0.85rem;">' +
                    (project.contact_phone ? '<span>' + escHtml(project.contact_phone) + '</span>' : '') +
                    (project.contact_email ? '<span>' + escHtml(project.contact_email) + '</span>' : '') +
                '</div>'
            : '') +

            (project.google_maps_link ?
                '<div style="margin-bottom:1rem;">' +
                    '<a href="' + escHtml(project.google_maps_link) + '" target="_blank" rel="noopener" style="font-size:0.78rem;color:var(--color-muted);text-decoration:underline;">View on Google Maps</a>' +
                '</div>'
            : '') +

            '<div class="portal-modal-actions">' +
                '<a href="' + viewUrl + '" class="portal-btn portal-btn--primary" target="_blank" rel="noopener">Explore 360° View</a>' +
            '</div>' +
        '</div>';

        dom.modalBody.innerHTML = html;
        dom.modal.classList.add('visible');
        document.body.style.overflow = 'hidden';
    };

    function metaItem(label, value) {
        return '<div class="portal-modal-meta-item">' +
            '<div class="portal-modal-meta-label">' + escHtml(label) + '</div>' +
            '<div class="portal-modal-meta-value">' + escHtml(value) + '</div>' +
        '</div>';
    }

    function closeModal() {
        dom.modal.classList.remove('visible');
        document.body.style.overflow = '';
    }

    /* ── Event Bindings ── */
    function bindEvents() {
        // Search
        var debouncedSearch = debounce(function () {
            state.query = dom.searchInput.value.trim();
            fetchProjects(false);
        }, 350);

        dom.searchInput.addEventListener('input', debouncedSearch);
        dom.searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                state.query = dom.searchInput.value.trim();
                fetchProjects(false);
            }
        });
        dom.searchBtn.addEventListener('click', function () {
            state.query = dom.searchInput.value.trim();
            fetchProjects(false);
        });

        // City filter
        dom.filterCity.addEventListener('change', function () {
            state.city = this.value;
            fetchProjects(false);
        });

        // Sort
        dom.filterSort.addEventListener('change', function () {
            state.sort = this.value;
            fetchProjects(false);
        });

        // Type chips
        dom.chips.forEach(function (chip) {
            chip.addEventListener('click', function () {
                dom.chips.forEach(function (c) { c.classList.remove('active'); });
                this.classList.add('active');
                state.type = this.dataset.type;
                fetchProjects(false);
            });
        });

        // View toggle
        dom.viewGrid.addEventListener('click', function () { setView('grid'); });
        dom.viewList.addEventListener('click', function () { setView('list'); });
        dom.viewMap.addEventListener('click', function () { setView('map'); });

        // Map nav link
        if (dom.navMapLink) {
            dom.navMapLink.addEventListener('click', function (e) {
                e.preventDefault();
                setView('map');
            });
        }

        // Close map
        if (dom.closeMap) {
            dom.closeMap.addEventListener('click', function () {
                setView('grid');
            });
        }

        // Modal
        dom.modalClose.addEventListener('click', closeModal);
        dom.modal.addEventListener('click', function (e) {
            if (e.target === dom.modal) closeModal();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && dom.modal.classList.contains('visible')) closeModal();
        });

        // Sticky nav on scroll
        var nav = document.getElementById('portal-nav');
        var lastScroll = 0;
        window.addEventListener('scroll', function () {
            var st = window.pageYOffset;
            if (st > 60) {
                nav.style.boxShadow = '0 2px 12px rgba(22,35,56,0.06)';
            } else {
                nav.style.boxShadow = 'none';
            }
            lastScroll = st;
        }, { passive: true });

        // Mobile hamburger
        var hamburger = document.getElementById('portal-hamburger');
        if (hamburger) {
            hamburger.addEventListener('click', function () {
                var links = document.querySelector('.portal-nav-links');
                var actions = document.querySelector('.portal-nav-actions');
                if (links) links.style.display = links.style.display === 'flex' ? 'none' : 'flex';
                if (actions) actions.style.display = actions.style.display === 'flex' ? 'none' : 'flex';
            });
        }
    }

    /* ── Init ── */
    function init() {
        cacheDom();
        bindEvents();
        fetchProjects(false);
        setupInfiniteScroll();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
