(function () {
    'use strict';

    var ICONS = [
        { key: 'main-star', group: 'main', label: 'Star', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.9 5.86 6.47.94-4.68 4.56 1.1 6.44L12 17.6l-5.79 3.04 1.1-6.44-4.68-4.56 6.47-.94L12 2.8z"/></svg>' },
        { key: 'main-home', group: 'main', label: 'Home', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2l9 7.4v9.2h-6.2v-5.6H9.2v5.6H3V10.6l9-7.4z"/></svg>' },
        { key: 'main-flag', group: 'main', label: 'Flag', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2.5v19h2.2v-6.1h10.1l-1.9-3.5 1.9-3.5H8.2V2.5H6z"/></svg>' },
        { key: 'main-crown', group: 'main', label: 'Crown', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8.6l4.4 3.3L12 6.2l4.6 5.7L21 8.6l-2.1 10H5.1L3 8.6z"/></svg>' },
        { key: 'plot-pin', group: 'normal', label: 'Pin', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2c-3.6 0-6.6 2.8-6.6 6.3 0 4.7 6.6 13.3 6.6 13.3s6.6-8.6 6.6-13.3c0-3.5-3-6.3-6.6-6.3zm0 9a2.7 2.7 0 1 1 0-5.4 2.7 2.7 0 0 1 0 5.4z"/></svg>' },
        { key: 'plot-dot', group: 'normal', label: 'Dot', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="6.8"/></svg>' },
        { key: 'plot-square', group: 'normal', label: 'Square', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.8"/></svg>' },
        { key: 'plot-gate', group: 'normal', label: 'Gate', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V9.5h3.2V20H4zm12.8 0V9.5H20V20h-3.2zM8.8 20v-8h6.4v8H8.8zm-1-10.3L12 5.2l4.2 4.5H7.8z"/></svg>' },
        { key: 'plot-tree', group: 'normal', label: 'Tree', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2l4.6 6h-2.5l3.1 4h-3.1l2.3 3.1H7.6l2.3-3.1H6.8l3.1-4H7.4l4.6-6zm-1.3 13.1h2.6v4.5h-2.6v-4.5z"/></svg>' },
        { key: 'plot-office', group: 'normal', label: 'Office', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 20V5.2L13 3v17H4.5zm4.2-12h1.8v1.8H8.7V8zm0 3.4h1.8v1.8H8.7v-1.8zm0 3.4h1.8v1.8H8.7v-1.8zM14.3 20v-9H20V20h-5.7zm2-5.9h1.6v1.6h-1.6v-1.6z"/></svg>' },
        { key: 'poi-school', group: 'normal', label: 'School', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5L12 5l8 4.5-8 4.3-8-4.3zm2.1 1.9h2.1v5H6.1v-5zm4.9 0h2.1v5H11v-5zm4.8 0h2.1v5h-2.1v-5zM4.8 18h14.4v1.9H4.8z"/></svg>' },
        { key: 'poi-college', group: 'normal', label: 'College', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4l9 4.5-9 4.5-9-4.5L12 4zm-5.4 7.1v3.6c0 1.9 2.4 3.4 5.4 3.4s5.4-1.5 5.4-3.4v-3.6L12 13.8l-5.4-2.7zm11.5.2 2 .9v4.8h-2v-5.7z"/></svg>' },
        { key: 'poi-hospital', group: 'normal', label: 'Hospital', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h14a1 1 0 0 1 1 1V20H4V5.5a1 1 0 0 1 1-1zm5.2 2.7v2.5H7.7v2.6h2.5v2.5h2.6v-2.5h2.5V9.7h-2.5V7.2h-2.6zm6.3 11v-4.6h-3.2v4.6h3.2zm-9.2 0v-4.6H4v4.6h3.3z"/></svg>' },
        { key: 'poi-clinic', group: 'normal', label: 'Clinic', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.8a7.4 7.4 0 1 1 0 14.8 7.4 7.4 0 0 1 0-14.8zm-1.2 3.1v3H7.7v2.4h3.1v3h2.4v-3h3.1V9.9h-3.1v-3h-2.4zM8.3 19h7.4v1.8H8.3z"/></svg>' },
        { key: 'poi-pharmacy', group: 'normal', label: 'Pharmacy', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.2 5.2h11.6a1.2 1.2 0 0 1 1.2 1.2v11.4a1.2 1.2 0 0 1-1.2 1.2H6.2A1.2 1.2 0 0 1 5 17.8V6.4a1.2 1.2 0 0 1 1.2-1.2zm4.7 2.5v2.8H8.1V13h2.8v2.8h2.2V13h2.8v-2.5h-2.8V7.7h-2.2z"/></svg>' },
        { key: 'poi-airport', group: 'normal', label: 'Airport', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.2l-8.1 1.9-1.7 5.2-1.7-.5.7-4.6-3.6.9-1.6 2.4-1.3-.4.8-3-2.5.6-.6-1.8 2.5-.6-2-2.4 1.3-.4 2.4 1.5 3.6-.9-2.8-3.8.5-1.7 4.4 3.2 8.1-1.9 1.1 3.3z"/></svg>' },
        { key: 'poi-railway', group: 'normal', label: 'Railway', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4.6h8c2 0 3.2 1.3 3.2 3v6.8c0 1.4-.8 2.5-2.1 3.1l1.8 2.3H16l-1.2-1.7h-5.6L8 19.8H5.1l1.8-2.3A3.3 3.3 0 0 1 4.8 14.4V7.6c0-1.7 1.2-3 3.2-3zm0 2.3v3.1h8V6.9H8zm1 7.1a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8zm6 0a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8z"/></svg>' },
        { key: 'poi-metro', group: 'normal', label: 'Metro', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 4h9A3.5 3.5 0 0 1 20 7.5v6.8c0 1.2-.6 2.3-1.5 3l1.3 2H17l-.9-1.4h-8.2L7 19.3H4.2l1.3-2A3.7 3.7 0 0 1 4 14.3V7.5A3.5 3.5 0 0 1 7.5 4zm0 2.2v3.3h9V6.2h-9zm1.5 7a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4zm6 0a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4z"/></svg>' },
        { key: 'poi-bus', group: 'normal', label: 'Bus Stop', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.2 4.6h9.6c2.1 0 3.2 1.1 3.2 2.9v6.6c0 1.1-.4 2-1.2 2.7V19h-2.2v-1.3H7.4V19H5.2v-2.2A3.2 3.2 0 0 1 4 14.1V7.5c0-1.8 1.1-2.9 3.2-2.9zm-.1 2.2v3.1h9.8V6.8H7.1zm1 7a1.2 1.2 0 1 0 0-2.3 1.2 1.2 0 0 0 0 2.3zm7.8 0a1.2 1.2 0 1 0 0-2.3 1.2 1.2 0 0 0 0 2.3z"/></svg>' },
        { key: 'poi-petrol', group: 'normal', label: 'Fuel', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4.8h8.1A1.9 1.9 0 0 1 16 6.7V19H6V4.8zm2.1 2.1v4.1h5.8V6.9H8.1zm9.8 1.2 2.4 2.5v6.3c0 1.4-.9 2.3-2.3 2.3h-.7c-1.5 0-2.3-.9-2.3-2.3v-2.6h2.1v2.1c0 .5.2.7.7.7h.3c.5 0 .7-.2.7-.7v-4.9l-2.4-2.4 1.5-1z"/></svg>' },
        { key: 'poi-mall', group: 'normal', label: 'Mall', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.4 7.3h2l1-2.3h3.2l1 2.3h2a1.8 1.8 0 0 1 1.8 1.8V19H5.6V9.1a1.8 1.8 0 0 1 1.8-1.8zm2 2.2v7.3h5.2V9.5H9.4z"/></svg>' },
        { key: 'poi-market', group: 'normal', label: 'Market', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 7.2h13l-1.1 3a2.3 2.3 0 0 1-1.9 1.5 2.3 2.3 0 0 1-2-.9 2.3 2.3 0 0 1-3 0 2.3 2.3 0 0 1-2 .9 2.3 2.3 0 0 1-1.9-1.5l-1.1-3zm1.4 5.9h10.2v5.7H6.9v-5.7z"/></svg>' },
        { key: 'poi-bank', group: 'normal', label: 'Bank', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4l8.6 4.5v1.9H3.4V8.5L12 4zm-6.6 7.7H7v5.7H5.4v-5.7zm4 0H11v5.7H9.4v-5.7zm4 0H15v5.7h-1.6v-5.7zm4 0H19v5.7h-1.6v-5.7zM4.3 19h15.4v1.8H4.3z"/></svg>' },
        { key: 'poi-restaurant', group: 'normal', label: 'Restaurant', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5h1.4v6a1.9 1.9 0 0 1-1.5 1.9V20H4.7v-7.6a1.9 1.9 0 0 1-1.5-1.9v-6h1.4v4.2h1V4.5h1.4v4.2h1V4.5zm8.9 0h2.8c1.6 0 2.7 1.1 2.7 2.9 0 1.7-1.1 2.8-2.7 2.8h-.7V20h-2.1V4.5zm2.1 2.1v2h.6c.4 0 .7-.3.7-1s-.3-1-.7-1h-.6z"/></svg>' },
        { key: 'poi-hotel', group: 'normal', label: 'Hotel', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7.2h2.1v3.3h9.8c1.7 0 2.9 1.1 2.9 2.8V19h-2.1v-2.2H7.1V19H5V7.2zm4.2 0a1.9 1.9 0 1 1 0 3.8 1.9 1.9 0 0 1 0-3.8z"/></svg>' },
        { key: 'poi-gym', group: 'normal', label: 'Gym', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.4 9.4h2.2v5.2H4.4V9.4zm13 0h2.2v5.2h-2.2V9.4zm-9.7 1h1.8V8.6h4.9v1.8h1.8v3.2h-1.8v1.8H9.5v-1.8H7.7v-3.2z"/></svg>' },
        { key: 'poi-park', group: 'normal', label: 'Park', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.1c2.8 0 5 2 5 4.6 0 .5-.1 1-.3 1.5 1.6.7 2.7 2.1 2.7 3.8 0 2.4-2 4.4-4.5 4.4H9.1c-2.5 0-4.5-2-4.5-4.4 0-1.7 1.1-3.1 2.7-3.8-.2-.5-.3-1-.3-1.5 0-2.6 2.2-4.6 5-4.6zm-1.2 14.3h2.4V21h-2.4v-3.6z"/></svg>' },
        { key: 'poi-garden', group: 'normal', label: 'Garden', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 6.1c1.1-2.1 3.8-2.8 5.5-1.2 1.8 1.7 1.2 4.7-1.1 5.7 1.9.7 2.7 3.1 1.4 4.9-1.3 1.8-4 1.8-5.2 0-.9 2-3.8 2.6-5.4 1-1.7-1.6-1.1-4.6 1.1-5.6-2.2-1-2.8-4.1-1.1-5.7C8.8 3.3 11.1 4 12 6.1zm-1 10.3h2v4.6h-2v-4.6z"/></svg>' },
        { key: 'poi-stadium', group: 'normal', label: 'Stadium', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7.1h12a2 2 0 0 1 2 2V17H4V9.1a2 2 0 0 1 2-2zm0 2v1.6h12V9.1H6zm0 3.2v2h3.2v-2H6zm4.4 0v2H13v-2h-2.6zm3.8 0v2H18v-2h-4.2z"/></svg>' },
        { key: 'poi-temple', group: 'normal', label: 'Temple', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 3h2v2.1l2.7 1.7H8.3L11 5.1V3zm-5.2 5.5h12.4v1.8H5.8V8.5zm1.1 2.8h2v5.5h-2v-5.5zm4.1 0h2v5.5h-2v-5.5zm4.1 0h2v5.5h-2v-5.5zM4.6 18.2h14.8V20H4.6v-1.8z"/></svg>' },
        { key: 'poi-church', group: 'normal', label: 'Church', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 3h2v2h2v1.8h-2v2.1h4.1V20H6.9V8.9H11V6.8H9V5h2V3zm-1.8 8.3h5.6V18h-1.7v-3.3h-2.2V18H9.2v-6.7z"/></svg>' },
        { key: 'poi-mosque', group: 'normal', label: 'Mosque', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.2c2.7 0 4.7 1.9 4.7 4.2v1.2h1.8V20H5.5V9.6h1.8V8.4c0-2.3 2-4.2 4.7-4.2zm-2.6 7H11V18H9.4v-6.8zm3.6 0h1.6V18H13v-6.8z"/></svg>' },
        { key: 'poi-police', group: 'normal', label: 'Police', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.8l6 2v5.5c0 4.1-2.1 7.2-6 8.9-3.9-1.7-6-4.8-6-8.9V5.8l6-2zm0 4.3 1 2 2.2.3-1.6 1.5.4 2.2-2-1.1-2 1.1.4-2.2-1.6-1.5 2.2-.3 1-2z"/></svg>' },
        { key: 'poi-residence', group: 'normal', label: 'Residence', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.2l8.4 6.9V20H14v-5.2h-4V20H3.6v-8.9L12 4.2z"/></svg>' },
        { key: 'poi-industrial', group: 'normal', label: 'Industrial', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.2 19.8V8.7l5.4 2.7V8.1l5.2 2.6V4.8h5.1v15H4.2zm9.8-9.8h1.7v1.7H14v-1.7zm0 3.1h1.7v1.7H14v-1.7z"/></svg>' }
    ];

    var POINTER_TYPES = [
        { key: 'project', label: 'Project / Site', shortLabel: 'Project', markerType: 'main', iconKey: 'main-home' },
        { key: 'landmark', label: 'Landmark', shortLabel: 'Landmark', markerType: 'normal', iconKey: 'plot-pin' },
        { key: 'residence', label: 'Residence', shortLabel: 'Residence', markerType: 'normal', iconKey: 'poi-residence' },
        { key: 'school', label: 'School', shortLabel: 'School', markerType: 'normal', iconKey: 'poi-school' },
        { key: 'college', label: 'College / University', shortLabel: 'College', markerType: 'normal', iconKey: 'poi-college' },
        { key: 'hospital', label: 'Hospital', shortLabel: 'Hospital', markerType: 'normal', iconKey: 'poi-hospital' },
        { key: 'clinic', label: 'Clinic', shortLabel: 'Clinic', markerType: 'normal', iconKey: 'poi-clinic' },
        { key: 'pharmacy', label: 'Pharmacy', shortLabel: 'Pharmacy', markerType: 'normal', iconKey: 'poi-pharmacy' },
        { key: 'airport', label: 'Airport', shortLabel: 'Airport', markerType: 'normal', iconKey: 'poi-airport' },
        { key: 'railway_station', label: 'Railway Station', shortLabel: 'Railway', markerType: 'normal', iconKey: 'poi-railway' },
        { key: 'metro_station', label: 'Metro Station', shortLabel: 'Metro', markerType: 'normal', iconKey: 'poi-metro' },
        { key: 'bus_stop', label: 'Bus Stop', shortLabel: 'Bus Stop', markerType: 'normal', iconKey: 'poi-bus' },
        { key: 'petrol_pump', label: 'Petrol Pump', shortLabel: 'Fuel', markerType: 'normal', iconKey: 'poi-petrol' },
        { key: 'mall', label: 'Mall', shortLabel: 'Mall', markerType: 'normal', iconKey: 'poi-mall' },
        { key: 'market', label: 'Market', shortLabel: 'Market', markerType: 'normal', iconKey: 'poi-market' },
        { key: 'bank', label: 'Bank', shortLabel: 'Bank', markerType: 'normal', iconKey: 'poi-bank' },
        { key: 'office', label: 'Office', shortLabel: 'Office', markerType: 'normal', iconKey: 'plot-office' },
        { key: 'restaurant', label: 'Restaurant', shortLabel: 'Restaurant', markerType: 'normal', iconKey: 'poi-restaurant' },
        { key: 'hotel', label: 'Hotel', shortLabel: 'Hotel', markerType: 'normal', iconKey: 'poi-hotel' },
        { key: 'gym', label: 'Gym', shortLabel: 'Gym', markerType: 'normal', iconKey: 'poi-gym' },
        { key: 'park', label: 'Park', shortLabel: 'Park', markerType: 'normal', iconKey: 'poi-park' },
        { key: 'garden', label: 'Garden', shortLabel: 'Garden', markerType: 'normal', iconKey: 'poi-garden' },
        { key: 'stadium', label: 'Stadium', shortLabel: 'Stadium', markerType: 'normal', iconKey: 'poi-stadium' },
        { key: 'temple', label: 'Temple', shortLabel: 'Temple', markerType: 'normal', iconKey: 'poi-temple' },
        { key: 'church', label: 'Church', shortLabel: 'Church', markerType: 'normal', iconKey: 'poi-church' },
        { key: 'mosque', label: 'Mosque', shortLabel: 'Mosque', markerType: 'normal', iconKey: 'poi-mosque' },
        { key: 'police_station', label: 'Police Station', shortLabel: 'Police', markerType: 'normal', iconKey: 'poi-police' },
        { key: 'industrial_area', label: 'Industrial Area', shortLabel: 'Industrial', markerType: 'normal', iconKey: 'poi-industrial' }
    ];

    var MARKER_LOOKS = [
        { key: 'solid', label: 'Solid' },
        { key: 'soft', label: 'Soft Glow' },
        { key: 'outline', label: 'Outline' },
        { key: 'glass', label: 'Glass' },
        { key: 'light', label: 'Light' }
    ];

    var ICONS_BY_KEY = {};
    var POINTER_TYPES_BY_KEY = {};
    var MARKER_LOOKS_BY_KEY = {};

    ICONS.forEach(function (icon) {
        ICONS_BY_KEY[icon.key] = icon;
    });

    POINTER_TYPES.forEach(function (pointerType) {
        POINTER_TYPES_BY_KEY[pointerType.key] = pointerType;
    });

    MARKER_LOOKS.forEach(function (look) {
        MARKER_LOOKS_BY_KEY[look.key] = look;
    });

    function normalizeKey(value) {
        return String(value || '').trim().toLowerCase();
    }

    function normalizeHexColor(value, fallback) {
        var raw = String(value || '').trim().toLowerCase();
        if (/^#[0-9a-f]{3}$/.test(raw)) {
            return '#' + raw[1] + raw[1] + raw[2] + raw[2] + raw[3] + raw[3];
        }
        if (/^#[0-9a-f]{6}$/.test(raw)) return raw;
        return fallback || '#22d3ee';
    }

    function hexToRgb(hex) {
        var normalized = normalizeHexColor(hex, '#22d3ee');
        return {
            r: parseInt(normalized.slice(1, 3), 16),
            g: parseInt(normalized.slice(3, 5), 16),
            b: parseInt(normalized.slice(5, 7), 16)
        };
    }

    function rgba(hex, alpha) {
        var rgb = hexToRgb(hex);
        var safeAlpha = Number(alpha);
        if (!Number.isFinite(safeAlpha)) safeAlpha = 1;
        return 'rgba(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ', ' + safeAlpha + ')';
    }

    function defaultForType(markerType) {
        return normalizeKey(markerType) === 'main' ? 'main-star' : 'plot-pin';
    }

    function defaultPointerType(markerType) {
        return normalizeKey(markerType) === 'main' ? 'project' : 'landmark';
    }

    function defaultColor(markerType) {
        return normalizeKey(markerType) === 'main' ? '#f97316' : '#22d3ee';
    }

    function defaultMarkerSize() {
        return 1;
    }

    function normalizeMarkerSize(markerSize) {
        var size = Number(markerSize);
        if (!Number.isFinite(size)) return defaultMarkerSize();
        if (size < 0.6) size = 0.6;
        if (size > 2.4) size = 2.4;
        return Math.round(size * 100) / 100;
    }

    function getIcon(key) {
        return ICONS_BY_KEY[normalizeKey(key)] || null;
    }

    function isAllowed(key) {
        return !!getIcon(key);
    }

    function getPointerType(pointerType, markerType) {
        var normalized = normalizeKey(pointerType);
        if (normalizeKey(markerType) === 'main') return POINTER_TYPES_BY_KEY.project;
        return POINTER_TYPES_BY_KEY[normalized] || POINTER_TYPES_BY_KEY.landmark;
    }

    function pointerTypeOptions(markerType) {
        var normalizedMarkerType = normalizeKey(markerType);
        return POINTER_TYPES.filter(function (pointerType) {
            return pointerType.markerType === (normalizedMarkerType === 'main' ? 'main' : 'normal');
        });
    }

    function normalizePointerType(pointerType, markerType) {
        var pointerTypeMeta = getPointerType(pointerType, markerType);
        return pointerTypeMeta ? pointerTypeMeta.key : defaultPointerType(markerType);
    }

    function defaultIconForPointerType(pointerType, markerType) {
        var pointerTypeMeta = getPointerType(pointerType, markerType);
        return pointerTypeMeta && pointerTypeMeta.iconKey ? pointerTypeMeta.iconKey : defaultForType(markerType);
    }

    function markerLookOptions() {
        return MARKER_LOOKS.slice();
    }

    function normalizeMarkerLook(markerLook) {
        var normalized = normalizeKey(markerLook);
        return MARKER_LOOKS_BY_KEY[normalized] ? normalized : 'solid';
    }

    function normalizeIconKey(iconKey, markerType, pointerType) {
        var normalized = normalizeKey(iconKey);
        if (isAllowed(normalized)) return normalized;
        return defaultIconForPointerType(pointerType, markerType);
    }

    function renderSvg(iconKey, markerType, pointerType) {
        var normalized = normalizeIconKey(iconKey, markerType, pointerType);
        var icon = getIcon(normalized);
        return icon ? icon.svg : '';
    }

    function byGroup(group) {
        var normalizedGroup = normalizeKey(group);
        if (normalizedGroup === 'normal') {
            return ICONS.filter(function (icon) { return icon.group !== 'main'; });
        }
        return ICONS.filter(function (icon) { return icon.group === normalizedGroup; });
    }

    function pointerTypeLabel(pointerType, markerType) {
        return getPointerType(pointerType, markerType).label;
    }

    function pointerTypeShortLabel(pointerType, markerType) {
        return getPointerType(pointerType, markerType).shortLabel;
    }

    function appearancePalette(iconColor, markerLook) {
        var color = normalizeHexColor(iconColor, '#22d3ee');
        var look = normalizeMarkerLook(markerLook);
        if (look === 'outline') {
            return {
                color: color,
                look: look,
                bg: 'rgba(15, 23, 42, 0.56)',
                border: color,
                icon: color,
                shadow: '0 5px 14px rgba(0, 0, 0, 0.24)',
                cardBg: 'linear-gradient(160deg, ' + rgba(color, 0.74) + ', rgba(15, 23, 42, 0.9))',
                badgeBg: rgba(color, 0.22),
                badgeBorder: rgba(color, 0.46)
            };
        }
        if (look === 'glass') {
            return {
                color: color,
                look: look,
                bg: 'linear-gradient(180deg, rgba(255, 255, 255, 0.24), ' + rgba(color, 0.42) + ')',
                border: 'rgba(255, 255, 255, 0.68)',
                icon: '#ffffff',
                shadow: '0 10px 24px ' + rgba(color, 0.24),
                cardBg: 'linear-gradient(160deg, ' + rgba(color, 0.82) + ', rgba(15, 23, 42, 0.88))',
                badgeBg: 'rgba(255, 255, 255, 0.18)',
                badgeBorder: 'rgba(255, 255, 255, 0.28)'
            };
        }
        if (look === 'light') {
            return {
                color: color,
                look: look,
                bg: '#ffffff',
                border: rgba(color, 0.42),
                icon: color,
                shadow: '0 8px 20px ' + rgba(color, 0.16),
                cardBg: 'linear-gradient(160deg, ' + rgba(color, 0.78) + ', rgba(15, 23, 42, 0.88))',
                badgeBg: rgba(color, 0.18),
                badgeBorder: rgba(color, 0.34)
            };
        }
        if (look === 'soft') {
            return {
                color: color,
                look: look,
                bg: rgba(color, 0.22),
                border: rgba(color, 0.94),
                icon: '#ffffff',
                shadow: '0 0 0 1px rgba(255, 255, 255, 0.16), 0 10px 24px ' + rgba(color, 0.28),
                cardBg: 'linear-gradient(160deg, ' + rgba(color, 0.78) + ', rgba(15, 23, 42, 0.9))',
                badgeBg: rgba(color, 0.2),
                badgeBorder: rgba(color, 0.38)
            };
        }
        return {
            color: color,
            look: 'solid',
            bg: color,
            border: '#ffffff',
            icon: '#ffffff',
            shadow: '0 10px 24px ' + rgba(color, 0.28),
            cardBg: 'linear-gradient(160deg, ' + rgba(color, 0.84) + ', rgba(15, 23, 42, 0.88))',
            badgeBg: rgba(color, 0.2),
            badgeBorder: rgba(color, 0.36)
        };
    }

    function appearanceVars(marker) {
        var meta = resolveMarkerMeta(marker);
        return {
            '--srm-marker-accent': meta.appearance.color,
            '--srm-marker-bg': meta.appearance.bg,
            '--srm-marker-border': meta.appearance.border,
            '--srm-marker-icon': meta.appearance.icon,
            '--srm-marker-shadow': meta.appearance.shadow,
            '--srm-marker-scale': String(meta.markerSize),
            '--srv-marker-card-bg': meta.appearance.cardBg,
            '--srv-marker-badge-bg': meta.appearance.badgeBg,
            '--srv-marker-badge-border': meta.appearance.badgeBorder
        };
    }

    function styleAttr(vars) {
        return Object.keys(vars).map(function (key) {
            return key + ': ' + vars[key];
        }).join('; ');
    }

    function applyMarkerAppearance(el, marker) {
        if (!el) return;
        var vars = appearanceVars(marker);
        Object.keys(vars).forEach(function (key) {
            el.style.setProperty(key, vars[key]);
        });
        el.setAttribute('data-marker-look', resolveMarkerMeta(marker).iconLook);
    }

    function markerStyleAttr(marker) {
        return styleAttr(appearanceVars(marker));
    }

    function resolveMarkerMeta(marker) {
        var markerType = normalizeKey(marker && marker.marker_type ? marker.marker_type : 'normal') || 'normal';
        var pointerType = normalizePointerType(marker && marker.pointer_type, markerType);
        var iconKey = normalizeIconKey(marker && marker.icon_key, markerType, pointerType);
        var iconColor = normalizeHexColor(marker && marker.icon_color, defaultColor(markerType));
        var iconLook = normalizeMarkerLook(marker && marker.icon_look);
        var markerSize = normalizeMarkerSize(marker && marker.marker_size);
        return {
            markerType: markerType,
            pointerType: pointerType,
            iconKey: iconKey,
            typeMeta: getPointerType(pointerType, markerType),
            iconColor: iconColor,
            iconLook: iconLook,
            markerSize: markerSize,
            appearance: appearancePalette(iconColor, iconLook)
        };
    }

    window.salesRouteMapIcons = {
        list: ICONS,
        pointerTypes: POINTER_TYPES,
        markerLooks: MARKER_LOOKS,
        get: getIcon,
        byGroup: byGroup,
        normalizeKey: normalizeKey,
        normalizeHexColor: normalizeHexColor,
        defaultForType: defaultForType,
        defaultPointerType: defaultPointerType,
        defaultColor: defaultColor,
        defaultMarkerSize: defaultMarkerSize,
        pointerTypeOptions: pointerTypeOptions,
        markerLookOptions: markerLookOptions,
        normalizePointerType: normalizePointerType,
        normalizeMarkerLook: normalizeMarkerLook,
        normalizeMarkerSize: normalizeMarkerSize,
        defaultIconForPointerType: defaultIconForPointerType,
        normalizeIconKey: normalizeIconKey,
        pointerTypeLabel: pointerTypeLabel,
        pointerTypeShortLabel: pointerTypeShortLabel,
        renderSvg: renderSvg,
        resolveMarkerMeta: resolveMarkerMeta,
        appearanceVars: appearanceVars,
        markerStyleAttr: markerStyleAttr,
        applyMarkerAppearance: applyMarkerAppearance,
        isAllowed: isAllowed
    };
})();
