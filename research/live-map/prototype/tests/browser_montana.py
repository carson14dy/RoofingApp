"""Live Montana navigation and synthetic boundary/failure checks, not accuracy tests."""
import argparse
import asyncio
import copy
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.async_api import async_playwright

PILOT = Path(__file__).resolve().parents[2]


async def main(args):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fixture = json.loads((PILOT / 'validation-evidence/montana/billings-point.json').read_text())
    checks, errors = [], []
    def passed(name):
        checks.append({'name': name, 'passed': True})
    async with async_playwright() as p:
        launch = {'headless': True}
        if args.chromium:
            launch['executable_path'] = args.chromium
        browser = await p.chromium.launch(**launch)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(args.base_url, wait_until='networkidle')
        await page.wait_for_function('pointData !== null && outlineLayer !== null', timeout=60000)
        assert await page.title() == 'Roofing Weather · Montana pilot'
        assert await page.locator('#territory').input_value() == 'montana'
        assert await page.locator('#sample-site option:not([disabled])').count() == 13
        assert await page.evaluate("map.getBounds().contains(outlineLayer.getLayers().find(l=>String(l.feature.id)==='30').getBounds())")
        assert await page.evaluate('sampleSitesLayer.getLayers().length') == 13
        assert await page.locator('#current .card').count() > 0
        assert await page.locator('#forecast tr').count() > 1
        assert await page.evaluate('pointData.timezone') == 'America/Denver'
        passed('real_billings_default_and_entire_montana_navigation')
        assert 'Station elevation:' in await page.locator('#current').inner_text()
        assert 'Grid elevation:' in await page.locator('#forecast').text_content()
        assert 'selected point only' in await page.locator('#coverage-note').inner_text()
        assert 'Precip. chance' in await page.locator('#forecast').text_content()
        passed('elevation_terrain_and_point_alert_scope_are_visible')
        await page.screenshot(path=str(args.output_dir / 'montana-pilot.png'), full_page=True)
        await page.locator('#sample-site').select_option('missoula')
        await page.wait_for_function('pointData?.selected_point.latitude_deg === 46.8721', timeout=60000)
        assert await page.evaluate('selected.lon') == -113.994
        assert 'Missoula' in await page.locator('#selected-name').inner_text()
        assert await page.evaluate('zone') == 'America/Denver'
        assert 'MDT' in await page.locator('#request-status').inner_text()
        passed('real_missoula_sample_selection_and_mountain_time')
        await page.set_viewport_size({'width': 390, 'height': 844})
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        passed('montana_mobile_layout')
        await page.close()

        page = await browser.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.clock.install(time=datetime.fromisoformat(fixture['generated_at'].replace('Z', '+00:00')))
        pending = asyncio.Event()
        config = {'delay_alert': False, 'missing': False}
        async def route_api(route):
            u = urlsplit(route.request.url)
            q = parse_qs(u.query)
            lat, lon = float(q['lat'][0]), float(q['lon'][0])
            is_mt = lat > 44
            if u.path == '/api/alerts':
                if is_mt and config['delay_alert']:
                    pending.set()
                    await asyncio.sleep(.5)
                if not is_mt:
                    await route.abort()
                    return
                payload = {'status': 'available', 'fetched_at': fixture['generated_at'],
                           'features': [{'type': 'Feature', 'geometry': None, 'properties': {
                               'event': 'Synthetic Montana warning', 'headline': 'Fixture only',
                               'effective': fixture['generated_at'], 'expires': fixture['generated_at']}}]}
            elif u.path == '/api/history':
                payload = {'point_archive_start': None, 'snapshots': []}
            else:
                payload = copy.deepcopy(fixture)
                payload['selected_point'].update(latitude_deg=lat, longitude_deg=lon)
                payload['timezone'] = None if config['missing'] else ('America/Denver' if is_mt else 'America/Chicago')
                if config['missing']:
                    payload['current'] = {'status': 'unavailable', 'stations': [], 'error': 'Synthetic source outage'}
                    payload['forecast'] = {'status': 'unavailable', 'periods': [], 'error': 'Synthetic source outage'}
                else:
                    for station in payload['current']['stations']:
                        station['freshness'] = 'stale'
                        station['fields']['windGust']['value'] = None
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
        await page.route('**/api/**', route_api)
        await page.goto(args.base_url + '/?region=montana', wait_until='networkidle')
        assert 'stale' in await page.locator('#current').inner_text()
        assert 'Unavailable' in await page.locator('#current').inner_text()
        passed('stale_station_and_missing_gust_are_not_hidden')
        config['delay_alert'] = True
        await page.locator('#refresh').click()
        await asyncio.wait_for(pending.wait(), timeout=5)
        await page.locator('#territory').select_option('kansas-city')
        await page.wait_for_timeout(750)
        assert await page.title() == 'Roofing Weather · Kansas City pilot'
        assert await page.evaluate('selected.lat') == 39.0997
        assert 'Synthetic Montana warning' not in await page.locator('#alerts').inner_text()
        assert 'could not be verified' in await page.locator('#alerts').inner_text()
        passed('delayed_montana_warning_cannot_replace_failed_kansas_city_alerts')
        config.update(delay_alert=False, missing=True)
        await page.locator('#territory').select_option('montana')
        await page.wait_for_function("document.querySelector('#current').textContent.includes('Current observations unavailable')")
        assert 'Synthetic Montana warning' in await page.locator('#alerts').inner_text()
        assert 'No currently applicable hourly periods' in await page.locator('#forecast').text_content()
        passed('official_point_warning_survives_weather_source_outage')
        await page.locator('#latitude').fill('46.872112345')
        await page.locator('#longitude').fill('-113.994012345')
        await page.get_by_role('button', name='Inspect point').click()
        await page.wait_for_function('pointData?.selected_point.latitude_deg === 46.872112345')
        assert await page.evaluate('zone') == 'UTC'
        assert '46.872112345' in await page.locator('#point-label').inner_text()
        assert '-113.994012345' in await page.locator('#point-label').inner_text()
        assert await page.locator('#sample-site').input_value() == ''
        passed('custom_coordinate_precision_and_unknown_timezone_fallback')
        await page.get_by_role('button', name='View territory').click()
        assert await page.evaluate('selected.lat') == 46.872112345
        passed('territory_view_preserves_selected_coordinate')
        # Exercise actual Leaflet click conversion, not only the coordinate form.
        await page.locator('#map').click(position={'x': 210, 'y': 150})
        await page.wait_for_function('pointData?.selected_point.latitude_deg !== 46.872112345')
        assert await page.evaluate('Math.abs(selected.lat)<=90 && Math.abs(selected.lon)<=180')
        passed('map_click_uses_clicked_coordinate')
        assert not errors, errors
        await browser.close()
    report = {'checks': checks, 'javascript_errors': errors,
              'scope': 'Live Billings/Missoula integration and explicitly synthetic failures; no meteorological accuracy benchmark.'}
    (args.output_dir / 'browser-montana.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--output-dir', type=Path, default=PILOT / 'prototype/.local/montana-browser')
    parser.add_argument('--chromium')
    asyncio.run(main(parser.parse_args()))
