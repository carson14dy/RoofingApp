"""Optional Chromium integration checks. Synthetic outage/race cases are not weather tests."""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.async_api import async_playwright

PILOT = Path(__file__).resolve().parents[2]


async def main(args):
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = json.loads(args.fixture.read_text())
    checks = []
    async with async_playwright() as p:
        launch_options = {'headless': True}
        if args.chromium:
            launch_options['executable_path'] = args.chromium
        browser = await p.chromium.launch(**launch_options)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(args.base_url, wait_until='networkidle')
        await page.wait_for_function("document.querySelectorAll('#current .card').length===3", timeout=60000)
        assert await page.locator('#forecast tr').count() > 1
        assert await page.locator('#map path').count() > 0
        assert not errors, errors
        await page.screenshot(path=str(out / 'kansas-city-pilot.png'), full_page=True)
        checks.append({'name': 'real_kansas_city_map_observations_forecast', 'passed': True})
        await page.set_viewport_size({'width': 390, 'height': 844})
        assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        checks.append({'name': 'mobile_no_horizontal_overflow', 'passed': True})
        await page.close()

        config = {'alert_failure': False, 'point_failure': False, 'race': False}
        page = await browser.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def route_api(route):
            u = urlsplit(route.request.url)
            q = parse_qs(u.query)
            if u.path == '/api/alerts':
                if config['alert_failure']:
                    await route.abort()
                    return
                payload = {'status': 'available', 'fetched_at': source['generated_at'], 'features': [
                    {'type': 'Feature', 'geometry': None, 'properties': {'event': 'Synthetic test warning',
                     'headline': 'Fixture warning; no real weather claim', 'effective': source['generated_at'],
                     'expires': source['generated_at']}}]}
            elif u.path == '/api/history':
                payload = {'archive_start': '2020-01-01T00:00:00Z', 'point_archive_start': None, 'snapshots': []}
            else:
                if config['point_failure']:
                    await route.abort()
                    return
                payload = copy.deepcopy(source)
                payload['current']['stations'][0]['fields']['temperature']['quality_control'] = 'S'
                payload['forecast']['periods'][0]['temperature'] = {'value': 24, 'unitCode': 'wmoUnit:degC'}
                if config['race']:
                    if q.get('lat') == ['39.1']:
                        await asyncio.sleep(.5)
                        name = 'Older point A'
                    else:
                        name = 'Latest point B'
                    payload['current']['stations'][0]['name'] = name
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
        await page.route('**/api/**', route_api)
        await page.goto(args.base_url, wait_until='networkidle')
        await page.wait_for_function("document.querySelector('#alerts').textContent.includes('Synthetic test warning')")
        assert 'QC review needed' in await page.locator('#current .card').first.inner_text()
        assert '24.0 °C' in await page.locator('#forecast').inner_text()
        checks.append({'name': 'station_qc_withheld_without_blocking_forecast_quantity', 'passed': True})
        config['alert_failure'] = True
        config['point_failure'] = True
        await page.get_by_role('button', name='Refresh', exact=True).click()
        await page.wait_for_function("document.querySelector('#request-status').textContent.includes('Request unavailable')")
        assert 'Last-known messages' in await page.locator('#alerts').inner_text()
        assert 'Synthetic test warning' in await page.locator('#alerts').inner_text()
        assert 'Forecast unavailable' in await page.locator('#forecast').inner_text()
        checks.append({'name': 'browser_outage_retains_unverified_same_point_warning', 'passed': True})
        await page.evaluate('selectPoint(39.11,-94.57)')
        await page.wait_for_timeout(100)
        assert 'Synthetic test warning' not in await page.locator('#alerts').inner_text()
        checks.append({'name': 'different_point_never_inherits_previous_warning', 'passed': True})
        config.update(point_failure=False, race=True)
        await page.evaluate('selectPoint(39.1,-94.58)')
        await page.wait_for_timeout(50)
        await page.evaluate('selectPoint(39.11,-94.57)')
        await page.wait_for_timeout(900)
        assert 'Latest point B' in await page.locator('#current').inner_text()
        assert 'Older point A' not in await page.locator('#current').inner_text()
        assert '39.110000' in await page.locator('#point-label').inner_text()
        checks.append({'name': 'reverse_order_click_responses_stay_on_latest_point', 'passed': True})
        await page.get_by_role('button', name='Saved history', exact=True).click()
        await page.wait_for_timeout(50)
        assert 'not yet collected' in await page.locator('#history').inner_text()
        assert '2020' not in await page.locator('#history').inner_text()
        checks.append({'name': 'history_uses_point_collection_start', 'passed': True})
        assert not errors, errors
        await browser.close()
    report = {'checks': checks, 'javascript_errors': errors,
              'scope': 'One real integration display, layout, and synthetic failure/race checks; no meteorological accuracy benchmark.'}
    (out / 'browser-validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--fixture', type=Path, default=PILOT / 'validation-evidence' / 'kc_point_final.json')
    parser.add_argument('--output-dir', type=Path, default=PILOT / 'prototype' / '.local' / 'browser-checks')
    parser.add_argument('--chromium', help='Optional system Chromium executable; otherwise use Playwright Chromium')
    asyncio.run(main(parser.parse_args()))
