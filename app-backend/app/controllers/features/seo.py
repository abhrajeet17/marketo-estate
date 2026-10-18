"""
Search and AI-crawler plumbing: robots.txt, sitemap.xml, llms.txt and X-Robots-Tag.

Only the marketing pages are indexable (INDEXABLE_PATHS). Every other HTML page (the app,
login, buyers' share links) answers with `X-Robots-Tag: noindex` so private project pages never
show up in Google or in AI answers. Set SITE_URL (e.g. https://marketostate.com) so canonical
links and the sitemap use the public domain; without it the request host is used.
"""
import os
from datetime import datetime, timezone

from flask import Response, render_template, request

from app import paths

# Public, indexable pages. Keep in sync with the sitemap and llms.txt.
INDEXABLE_PATHS = ('/', '/explore')

# Search engines and AI assistants that may read and cite the marketing pages.
AI_CRAWLERS = (
    'Googlebot', 'Bingbot', 'Google-Extended', 'GPTBot', 'OAI-SearchBot', 'ChatGPT-User',
    'ClaudeBot', 'Claude-SearchBot', 'Claude-User', 'PerplexityBot', 'Perplexity-User',
    'Applebot', 'Applebot-Extended', 'DuckAssistBot', 'meta-externalagent',
)

# App areas crawlers should not spend time on (they are noindex anyway).
DISALLOWED_PREFIXES = (
    '/api/', '/admin', '/dashboard', '/projectselection', '/crm', '/editor', '/salestools',
    '/building-plans', '/full-view', '/daynight', '/users', '/organizations', '/customer-dashboard',
    '/auth/', '/uploads/',
)


LANDING_TITLE = '360° Virtual Site Visit & Plot Sales Software | MarketoState'
LANDING_DESCRIPTION = (
    'Real estate sales software for plotted developments & builders: 360° drone virtual site visits, '
    'live plot inventory, one shareable link and a built-in CRM.'
)

# Shown on the landing page and published as FAQPage data, so the answers stay identical in both.
LANDING_FAQS = (
    ('What is MarketoState?',
     'MarketoState is real estate sales software for land developers, plotted developments, townships and builders. '
     'It turns drone panoramas into interactive 360° virtual site visits, shows live plot availability on the imagery, '
     'shares the whole project in one branded link and sends every buyer enquiry to a built-in CRM.'),
    ('How does a 360° virtual site visit work?',
     'Upload a drone or ground 360° panorama and MarketoState turns it into a spherical tour that opens in any browser. '
     'Buyers drag to look around, follow hotspots from scene to scene and open photos, videos and voice notes pinned to '
     'exact spots. No app, headset or login is needed.'),
    ('Can I show plot availability and prices on the layout?',
     'Yes. You draw each plot as a polygon directly on the 360° drone view with its number, area, price and status: '
     'Available, On hold or Sold. When a status changes, every shared link updates instantly, so buyers and brokers '
     'always see live plot inventory.'),
    ('How do I stop two agents from selling the same plot?',
     'Plot Lock holds a plot against a named buyer. Only people with lock rights can hold or release it, so a plot can '
     'never be sold twice.'),
    ('Does MarketoState include a real estate CRM?',
     'Yes. Buyers shortlist plots into a cart inside the tour and send a buy interest, which arrives in the CRM as a '
     'lead. Your team moves leads from New to Won, books site visits and emails quotations in one step.'),
    ('Can brokers and channel partners use it?',
     'Yes. Brokers get their own access, register their buyers and share project links. Buyer contact details stay '
     'masked until the referring broker reveals them, which protects every channel partner\'s leads.'),
    ('Who is MarketoState for?',
     'Plotted development and township developers, land developers, residential builders and promoters, channel '
     'partners and real estate marketing agencies that sell plots, villas or apartments, including before construction '
     'starts.'),
    ('Do buyers need to install an app?',
     'No. Every tour, project microsite and day/night view opens from a link in a phone or desktop browser, so you can '
     'share it on WhatsApp, email, ads or a QR code at the site office.'),
)

FEATURES = (
    '360° virtual site visits from drone panoramas', 'Live plot inventory drawn on the 360° view',
    'Plot Lock to prevent double selling', 'Branded project microsite in one link', 'Day and night views',
    '3D Earth view of land parcels', 'Sales route maps', 'Building maps and floor plans',
    'Real estate CRM with quotations', 'Broker and channel partner referrals with masked contacts',
    'Public property portal',
)


def landing_schema(site, updated):
    """schema.org JSON-LD for the landing page: organization, site, page, software and FAQ."""
    image = f'{site}/static/img/landing/hero-aerial.jpg'
    return {
        '@context': 'https://schema.org',
        '@graph': [
            {'@type': 'Organization', '@id': f'{site}/#organization', 'name': 'MarketoState', 'url': f'{site}/',
             'logo': {'@type': 'ImageObject', 'url': f'{site}/static/Marketostate/icon-512.png',
                      'width': 512, 'height': 512},
             'description': 'Real estate sales software for plotted developments, townships and builders.'},
            {'@type': 'WebSite', '@id': f'{site}/#website', 'url': f'{site}/', 'name': 'MarketoState',
             'inLanguage': 'en-IN', 'publisher': {'@id': f'{site}/#organization'}},
            {'@type': 'WebPage', '@id': f'{site}/#webpage', 'url': f'{site}/', 'name': LANDING_TITLE,
             'description': LANDING_DESCRIPTION, 'inLanguage': 'en-IN', 'isPartOf': {'@id': f'{site}/#website'},
             'about': {'@id': f'{site}/#software'}, 'primaryImageOfPage': image,
             'dateModified': updated.strftime('%Y-%m-%d')},
            {'@type': 'SoftwareApplication', '@id': f'{site}/#software', 'name': 'MarketoState',
             'applicationCategory': 'BusinessApplication', 'applicationSubCategory': 'Real estate sales software',
             'operatingSystem': 'Web browser', 'url': f'{site}/', 'image': image,
             'description': LANDING_DESCRIPTION, 'publisher': {'@id': f'{site}/#organization'},
             'audience': {'@type': 'BusinessAudience',
                          'audienceType': 'Real estate developers, builders, brokers and channel partners'},
             'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'INR', 'description': 'Start for free',
                        'url': f'{site}/login?mode=signup'},
             'featureList': list(FEATURES)},
            {'@type': 'FAQPage', '@id': f'{site}/#faq', 'mainEntity': [
                {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}}
                for q, a in LANDING_FAQS
            ]},
        ],
    }


def site_url():
    """Public origin without a trailing slash: SITE_URL, else the request host (https behind a proxy)."""
    configured = (os.environ.get('SITE_URL') or '').strip().rstrip('/')
    if configured:
        return configured
    root = request.url_root.rstrip('/')
    if request.headers.get('X-Forwarded-Proto', '').split(',')[0].strip() == 'https' and root.startswith('http://'):
        root = 'https://' + root[len('http://'):]
    return root


def _template_mtime(name):
    for folder in paths.TEMPLATE_DIRS:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    return datetime.now(timezone.utc)


def _text(body, mimetype):
    resp = Response(body, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


def register_seo_routes(app, auth_ctx):
    @app.context_processor
    def _seo_context():
        return {'seo_site_url': site_url}

    @app.route('/')
    def index():
        site = site_url()
        return render_template(
            'landing.html', site=site, seo_title=LANDING_TITLE, seo_description=LANDING_DESCRIPTION,
            faqs=LANDING_FAQS, schema=landing_schema(site, _template_mtime('landing.html')), **auth_ctx(),
        )

    @app.route('/robots.txt')
    def robots_txt():
        disallow = ''.join(f'Disallow: {p}\n' for p in DISALLOWED_PREFIXES)
        named = ''.join(f'User-agent: {bot}\n' for bot in AI_CRAWLERS)
        body = (
            f'# Search engines and AI assistants are welcome to read and cite the public pages.\n'
            f'{named}Allow: /\n{disallow}\n'
            f'User-agent: *\nAllow: /\n{disallow}\n'
            f'Sitemap: {site_url()}/sitemap.xml\n'
        )
        return _text(body, 'text/plain')

    @app.route('/sitemap.xml')
    def sitemap_xml():
        lastmod = _template_mtime('landing.html').strftime('%Y-%m-%d')
        urls = ''.join(
            f'  <url><loc>{site_url()}{path}</loc><lastmod>{lastmod}</lastmod>'
            f'<changefreq>weekly</changefreq><priority>{"1.0" if path == "/" else "0.8"}</priority></url>\n'
            for path in INDEXABLE_PATHS
        )
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + '</urlset>\n')
        return _text(body, 'application/xml')

    @app.route('/llms.txt')
    def llms_txt():
        return _text(render_template('llms.txt', site=site_url()), 'text/markdown')

    @app.after_request
    def _robots_header(response):
        path = request.path
        if (response.mimetype == 'text/html' and path not in INDEXABLE_PATHS
                and not path.startswith('/static/')):
            response.headers.setdefault('X-Robots-Tag', 'noindex, nofollow')
        return response
