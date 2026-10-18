"""SEO and AI-crawler plumbing: landing meta tags, JSON-LD, robots.txt, sitemap, llms.txt, noindex."""
import html as html_lib
import json
import re
import xml.etree.ElementTree as ET

import pytest

from app.controllers.features.seo import AI_CRAWLERS, INDEXABLE_PATHS, LANDING_FAQS


def _json_ld(html):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert match, 'landing page has no JSON-LD'
    return json.loads(match.group(1))


def test_landing_head(client):
    html = client.get('/', base_url='https://example.com').get_data(as_text=True)
    title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
    assert 'Virtual Site Visit' in title and len(title) <= 65
    desc = html_lib.unescape(re.search(r'<meta name="description" content="([^"]+)"', html).group(1))
    assert 120 <= len(desc) <= 160
    assert '<link rel="canonical" href="https://example.com/" />' in html
    assert 'property="og:url" content="https://example.com/"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert 'rel="manifest"' in html and 'href="/llms.txt"' in html
    # Exactly one H1, carrying the category keywords.
    assert html.count('<h1') == 1
    assert 'Plot Sales Software' in html[html.index('<h1'):html.index('</h1>')]
    # Web fonts do not block rendering.
    assert re.search(r'<link rel="preload" as="style" href="https://fonts\.googleapis\.com[^>]+onload=', html)
    assert not re.search(r'<link href="https://fonts\.googleapis\.com[^>]+rel="stylesheet"', html)


def test_landing_structured_data_matches_visible_faq(client):
    html = client.get('/', base_url='https://example.com').get_data(as_text=True)
    graph = {node['@type']: node for node in _json_ld(html)['@graph']}
    assert {'Organization', 'WebSite', 'WebPage', 'SoftwareApplication', 'FAQPage'} <= set(graph)
    assert graph['SoftwareApplication']['url'] == 'https://example.com/'
    questions = [q['name'] for q in graph['FAQPage']['mainEntity']]
    assert questions == [q for q, _a in LANDING_FAQS]
    for question, _answer in LANDING_FAQS:
        assert f'<h3>{question}</h3>' in html


def test_site_url_setting_wins(client, monkeypatch):
    monkeypatch.setenv('SITE_URL', 'https://marketostate.example/')
    html = client.get('/').get_data(as_text=True)
    assert '<link rel="canonical" href="https://marketostate.example/" />' in html
    assert 'Sitemap: https://marketostate.example/sitemap.xml' in client.get('/robots.txt').get_data(as_text=True)


def test_https_behind_proxy(client):
    html = client.get('/', base_url='http://example.com', headers={'X-Forwarded-Proto': 'https'}).get_data(as_text=True)
    assert '<link rel="canonical" href="https://example.com/" />' in html


def test_robots_txt(client):
    resp = client.get('/robots.txt', base_url='https://example.com')
    assert resp.status_code == 200 and resp.mimetype == 'text/plain'
    body = resp.get_data(as_text=True)
    for bot in AI_CRAWLERS:
        assert f'User-agent: {bot}\n' in body
    assert 'User-agent: *\nAllow: /\n' in body
    for private in ('/api/', '/dashboard', '/projectselection', '/crm'):
        assert f'Disallow: {private}\n' in body
    assert 'Disallow: /\n' not in body
    assert 'Sitemap: https://example.com/sitemap.xml' in body


def test_sitemap_lists_public_pages(client):
    resp = client.get('/sitemap.xml', base_url='https://example.com')
    assert resp.status_code == 200 and resp.mimetype == 'application/xml'
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    locs = [el.text for el in ET.fromstring(resp.data).findall('s:url/s:loc', ns)]
    assert locs == [f'https://example.com{p}' for p in INDEXABLE_PATHS]


def test_llms_txt(client):
    resp = client.get('/llms.txt', base_url='https://example.com')
    assert resp.status_code == 200 and resp.mimetype == 'text/markdown'
    body = resp.get_data(as_text=True)
    assert body.startswith('# MarketoState\n\n> ')
    assert '(https://example.com/explore)' in body


@pytest.mark.parametrize('path', INDEXABLE_PATHS)
def test_public_pages_are_indexable(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert 'X-Robots-Tag' not in resp.headers


@pytest.mark.parametrize('path', ('/login', '/dashboard', '/projectselection', '/crm', '/salestools'))
def test_private_pages_are_noindex(client, path):
    assert client.get(path).headers.get('X-Robots-Tag') == 'noindex, nofollow'


def test_explore_has_description_and_canonical(client):
    html = client.get('/explore', base_url='https://example.com').get_data(as_text=True)
    assert '<meta name="description"' in html
    assert '<link rel="canonical" href="https://example.com/explore">' in html
