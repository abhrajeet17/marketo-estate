from flask import request


def crm_parse_page_args(*, default_limit=10, max_limit=100):
    try:
        limit = int(request.args.get('limit', default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(max_limit, limit))
    try:
        page = int(request.args.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)
    offset = (page - 1) * limit
    return page, limit, offset


def crm_parse_sort_args(allowed, *, default_field=None, default_desc=True):
    """Parse ?sort=&dir= for a table, restricted to a whitelist of column names.

    Anything not in ``allowed`` falls back to the endpoint's own default ordering,
    so the raw query param never reaches the database layer.
    """
    requested = str(request.args.get('sort') or '').strip()
    if requested and requested in allowed:
        return requested, str(request.args.get('dir') or '').strip().lower() != 'asc'
    return default_field, default_desc


def _crm_sort_value(value):
    """Comparable key for one cell: numbers first, then text, nulls handled by caller."""
    if isinstance(value, bool):
        return (0, float(value), '')
    if isinstance(value, (int, float)):
        return (0, float(value), '')
    text = str(value).strip()
    try:
        return (0, float(text.replace(',', '')), '')
    except ValueError:
        return (1, 0.0, text.lower())


def crm_sort_rows(rows, field, desc):
    """Sort an in-memory row list by ``field``, always keeping empty values last."""
    if not field:
        return rows
    present = []
    missing = []
    for row in rows:
        value = row.get(field) if isinstance(row, dict) else None
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(row)
        else:
            present.append(row)
    present.sort(key=lambda row: _crm_sort_value(row.get(field)), reverse=bool(desc))
    return present + missing


def crm_page_payload(items, total, page, limit):
    total = int(total or 0)
    pages = max(1, (total + limit - 1) // limit) if limit else 1
    return {
        'items': items or [],
        'total': total,
        'page': page,
        'limit': limit,
        'pages': pages,
    }
