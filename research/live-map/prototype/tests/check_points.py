"""Capture sampled live point queries; endpoint success is not weather accuracy."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def read_json(url):
    with urlopen(url, timeout=90) as response:
        return json.load(response)


def capture(site, base_url, output):
    query = urlencode({'lat': site['latitude_deg'], 'lon': site['longitude_deg']})
    point = read_json(base_url.rstrip('/') + '/api/point?' + query)
    expected = {key: site[key] for key in ('latitude_deg', 'longitude_deg')}
    assert all(point['selected_point'][key] == value for key, value in expected.items())
    history = read_json(base_url.rstrip('/') + '/api/history?' + query)
    history_matches = bool(point.get('snapshot_id')) and any(
        item.get('snapshot_id') == point['snapshot_id'] for item in history.get('snapshots', []))
    if point.get('archive_status') == 'saved':
        assert history_matches, 'Saved query was not returned for this exact point'
    for item in history.get('snapshots', []):
        assert item['selected_point'] == point['selected_point'], 'History includes another point'
    independent_alerts = read_json(base_url.rstrip('/') + '/api/alerts?' + query)
    assert independent_alerts['selected_point'] == point['selected_point']
    # Use the input ordinal, not user-provided filenames, for capture paths.
    (output / f"point-{site['ordinal']:02d}.json").write_text(json.dumps(point, indent=2) + '\n')
    current, forecast, alerts = point['current'], point['forecast'], point['alerts']
    return {
        'sample': site, 'generated_at': point['generated_at'], 'status': point['status'],
        'selected_point': point['selected_point'], 'submitted_point': point['submitted_point'],
        'point_source_url': point['source_url'], 'timezone': point.get('timezone'),
        'grid': point.get('grid'), 'quantization_distance_m': point['quantization_distance_m'],
        'current_status': current['status'],
        'stations': [{
            'station_id': s['station_id'], 'distance_km': s['distance_km'],
            'location': s['location'], 'elevation': s.get('elevation'),
            'observed_at': s['observed_at'], 'fetched_at': s.get('fetched_at'),
            'status': s['status'], 'freshness': s['freshness'], 'age_seconds': s['age_seconds'],
            'source_url': s.get('source_url'), 'representativeness': s.get('representativeness'),
            'missing_fields': [name for name, field in s['fields'].items() if field['value_status'] == 'missing'],
            'numeric_v_fields': [name for name, field in s['fields'].items()
                                 if field['value_status'] == 'available' and field['quality_control'] == 'V'],
        } for s in current.get('stations', [])],
        'forecast': {'status': forecast['status'], 'source_url': forecast.get('source_url'),
                     'period_count': len(forecast['periods']), 'updated_at': forecast.get('updated_at'),
                     'fetched_at': forecast.get('fetched_at'), 'freshness': forecast.get('freshness'),
                     'elevation': forecast.get('elevation'),
                     'has_current_or_future_periods': forecast.get('has_current_or_future_periods')},
        'alerts': {'status': alerts['status'], 'source_url': alerts.get('source_url'),
                   'fetched_at': alerts.get('fetched_at'), 'count': len(alerts['features']),
                   'independent_request_status': independent_alerts['status']},
        'archive_status': point['archive_status'], 'exact_point_snapshot_returned': history_matches,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--points', type=Path, required=True, help='JSON array of named decimal-degree sample points')
    parser.add_argument('--output-dir', type=Path, required=True, help='New capture directory; existing summaries are not overwritten')
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    sites = json.loads(args.points.read_text())
    assert isinstance(sites, list) and 0 < len(sites) <= 50, 'Provide 1–50 sample points'
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    def run(item):
        ordinal, site = item
        site = {**site, 'ordinal': ordinal}
        try:
            result = capture(site, args.base_url, args.output_dir)
            print(json.dumps({'sample': site['name'], 'status': result['status'],
                              'office': (result['grid'] or {}).get('office')}), flush=True)
            return result
        except Exception as error:
            result = {'sample': site, 'capture_error': type(error).__name__ + ': ' + str(error)}
            print(json.dumps(result), flush=True)
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, enumerate(sites, start=1)))
    record = {'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Sampled integration checks, not statewide coverage, severe-event validation or meteorological accuracy.',
              'results': results}
    (args.output_dir / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    raise SystemExit(1 if any('capture_error' in row for row in results) else 0)


if __name__ == '__main__':
    main()
