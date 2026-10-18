"""Public landing page in a fresh (incognito) Chrome context: SEO tags, structured data, crawler files,
interactions (FAQ, menus, sliders) and layout at phone width. Read-only."""
import json

import pytest


def test_landing_seo_tags(open_page):
    page, watch = open_page('/', signed_in=False)
    assert 'Virtual Site Visit' in page.title() and len(page.title()) <= 65
    desc = page.locator('meta[name="description"]').get_attribute('content')
    assert 120 <= len(desc) <= 160
    assert page.locator('link[rel="canonical"]').get_attribute('href').endswith('/')
    assert page.locator('meta[property="og:image"]').get_attribute('content').startswith('http')
    assert page.locator('h1').count() == 1
    assert 'plot sales software' in page.locator('h1').text_content().lower()
    # Every image has alt text; headings never skip a level.
    assert page.locator('img:not([alt])').count() == 0
    levels = page.evaluate("[...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => +h.tagName[1])")
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels
    watch.assert_clean()


def test_structured_data_matches_page(open_page):
    page, watch = open_page('/', signed_in=False)
    data = json.loads(page.locator('script[type="application/ld+json"]').inner_text())
    graph = {node['@type']: node for node in data['@graph']}
    assert {'Organization', 'WebSite', 'WebPage', 'SoftwareApplication', 'FAQPage'} <= set(graph)
    visible = page.locator('.msl-faq-item h3').all_inner_texts()
    assert [q['name'] for q in graph['FAQPage']['mainEntity']] == visible
    logo = graph['Organization']['logo']['url']
    assert page.request.get(logo).status == 200
    watch.assert_clean()


@pytest.mark.parametrize('path,needle', [('/robots.txt', 'Sitemap:'), ('/sitemap.xml', '<urlset'),
                                         ('/llms.txt', '# MarketoState'), ('/static/site.webmanifest', 'MarketoState')])
def test_crawler_files(open_page, path, needle):
    page, _watch = open_page('/', signed_in=False)
    resp = page.request.get(page.url.rstrip('/') + path)
    assert resp.status == 200 and needle in resp.text()


def test_app_pages_are_noindex(open_page):
    page, _watch = open_page('/', signed_in=False)
    base = page.url.rstrip('/')
    for path in ('/login', '/dashboard', '/projectselection', '/crm'):
        assert page.request.get(base + path).headers.get('x-robots-tag') == 'noindex, nofollow', path
    assert 'x-robots-tag' not in page.request.get(base + '/').headers


def test_faq_and_anchor_navigation(open_page):
    page, watch = open_page('/', signed_in=False)
    items = page.locator('.msl-faq-item')
    assert items.count() >= 6
    assert items.first.get_attribute('open') is not None
    second = items.nth(1)
    second.locator('summary').click()
    assert second.get_attribute('open') is not None
    second.locator('summary').click()
    assert second.get_attribute('open') is None
    page.locator('.msl-nav a[href="#faq"]').click()
    page.wait_for_function("document.getElementById('faq').getBoundingClientRect().top < window.innerHeight")
    watch.assert_clean()


def test_day_night_slider_and_pano_demo(open_page):
    page, watch = open_page('/', signed_in=False)
    compare = page.locator('#mslCompare')
    compare.scroll_into_view_if_needed()
    compare.focus()
    before = page.evaluate("getComputedStyle(document.getElementById('mslCompare')).getPropertyValue('--split')")
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowRight')
    after = page.evaluate("getComputedStyle(document.getElementById('mslCompare')).getPropertyValue('--split')")
    assert before != after
    box = compare.bounding_box()
    page.mouse.click(box['x'] + box['width'] * 0.2, box['y'] + box['height'] / 2)
    assert int(compare.get_attribute('aria-valuenow')) < 40
    pano = page.locator('#mslPano')
    pano.scroll_into_view_if_needed()
    pb = pano.bounding_box()
    start = page.locator('#mslPanoBg').evaluate('el => el.style.backgroundPosition')
    page.mouse.move(pb['x'] + pb['width'] / 2, pb['y'] + pb['height'] / 2)
    page.mouse.down()
    page.mouse.move(pb['x'] + 20, pb['y'] + pb['height'] / 2, steps=5)
    page.mouse.up()
    assert page.locator('#mslPanoBg').evaluate('el => el.style.backgroundPosition') != start
    watch.assert_clean()


def test_ctas_point_to_signup_and_explore(open_page):
    page, watch = open_page('/', signed_in=False)
    hrefs = page.locator('a.msl-cta-primary').evaluate_all('els => els.map(e => e.getAttribute("href"))')
    assert hrefs and all(h == '/login?mode=signup' for h in hrefs)
    page.locator('a.msl-cta-secondary').click()
    page.wait_for_url('**/explore')
    assert page.locator('h1').count() == 1
    watch.assert_clean()


def test_phone_layout_and_menu(open_page):
    page, watch = open_page('/', signed_in=False, viewport=(390, 844))
    assert page.evaluate('document.documentElement.scrollWidth') <= 392
    toggle = page.locator('#mslMenuToggle')
    toggle.click()
    assert toggle.get_attribute('aria-expanded') == 'true'
    page.locator('#mslMobileNav a[href="#faq"]').click()
    assert toggle.get_attribute('aria-expanded') == 'false'
    watch.assert_clean()


def test_explore_portal_seo(open_page):
    page, watch = open_page('/explore', signed_in=False)
    assert page.locator('meta[name="description"]').count() == 1
    assert page.locator('link[rel="canonical"]').get_attribute('href').endswith('/explore')
    watch.assert_clean()
