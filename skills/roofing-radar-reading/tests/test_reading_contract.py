"""Synthetic metadata policy tests, not real storm accuracy or spatial tests."""
import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'check_reading.py'
spec = importlib.util.spec_from_file_location('check_reading', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
check = module.check
T = '2026-10-11T14:00:00Z'


def fixture():
    claim = dict(claim_type='field_description', hazard='hail', variable='MESH',
                 value=25.4, value_kind='instantaneous', units='mm', time_mode='current', scope='grid',
                 valid_start=T, valid_end=T, evidence_ids=['a'], target_point=[35.0, -97.0])
    evidence = dict(evidence_id='a', evidence_kind='estimate', hazard='hail', variable='MESH',
                    value_kind='instantaneous', units='mm', value=25.4, observed_at=T,
                    valid_start=T, valid_end=T, published_at=T, received_at=T,
                    quality='usable', coverage='available', domain='inside', relation='grid',
                    relation_authority='trusted_adapter', relation_target_point=[35.0, -97.0],
                    upstream_id='synthetic-radar', source_id='synthetic-source', product_id='synthetic-product', product_version='1', policy_id='p')
    policy = dict(variable='MESH', value_kind='instantaneous', units='mm',
                  kinds=['estimate'], max_age_seconds=300, missing_sentinels=[-999],
                  source_id='synthetic-source', product_id='synthetic-product', product_version='1')
    return dict(now_utc=T, cutoff_utc=T, claim=claim, evidence=[evidence], policies={'p': policy})


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.p = fixture()
        self.e = self.p['evidence'][0]

    def expect(self, reason=None, status='blocked'):
        out = check(self.p)
        self.assertEqual(out['status'], status, out)
        if reason:
            self.assertIn(reason, out['reasons'])

    def test_grid_positive(self):
        self.p['claim']['value'] = 25.4
        self.expect(status='eligible_for_scoped_wording')
        self.p['claim']['value'] = 99
        self.expect('CLAIM_VALUE_NOT_GROUNDED')

    def test_nearby_positive(self):
        self.e['relation'] = self.p['claim']['scope'] = 'nearby'
        self.expect(status='eligible_for_scoped_wording')

    def test_point_grid_mismatch(self):
        self.p['claim']['scope'] = 'point'
        self.expect('LOCALITY_SCOPE_MISMATCH')

    def test_point_nearby_mismatch(self):
        self.e['relation'] = 'nearby'
        self.p['claim']['scope'] = 'point'
        self.expect('POINT_MEASUREMENT_NOT_ESTABLISHED')

    def test_wrong_point(self):
        self.e['relation_target_point'] = [36.0, -97.0]
        self.expect('WRONG_RELATION_TARGET')

    def test_invalid_coordinate(self):
        self.p['claim']['target_point'] = [100, -97]
        self.expect('INVALID_TARGET_COORDINATES')

    def test_missing_nonfinite_bool(self):
        for value in [None, float('nan'), float('inf'), True, -999]:
            with self.subTest(value=value):
                self.e['value'] = value
                self.expect('MISSING_SENTINEL' if value == -999 else 'MISSING_OR_NONFINITE_VALUE')

    def test_missing_policy(self):
        self.p['policies'] = {}
        self.expect('MISSING_POLICY', 'review_required')

    def test_missing_lineage(self):
        self.e.pop('upstream_id')
        self.expect('MISSING_LINEAGE', 'review_required')

    def test_scope_cannot_be_self_verified(self):
        self.e['relation_authority'] = 'language_model'
        self.expect('UNVERIFIED_RELATION', 'review_required')

    def test_severity_never_downgraded(self):
        self.e['value'] = None
        self.e.pop('upstream_id')
        self.expect('MISSING_OR_NONFINITE_VALUE')

    def test_current_stale(self):
        self.e['observed_at'] = '2026-10-11T13:00:00Z'
        self.expect('STALE_FOR_REQUEST')

    def test_historical_not_stale(self):
        self.p['now_utc'] = '2026-10-12T14:00:00Z'
        self.p['claim']['time_mode'] = 'historical_asof'
        self.expect(status='eligible_for_scoped_wording')

    def test_cutoff_leakage(self):
        self.p['cutoff_utc'] = '2026-10-11T13:59:00Z'
        self.expect('ASOF_LEAKAGE')

    def test_forecast_future_valid(self):
        self.p['claim']['time_mode'] = 'forecast'
        self.e['evidence_kind'] = 'forecast'
        self.e['issued_at'] = T
        self.e.pop('observed_at')
        self.p['policies']['p']['kinds'] = ['forecast']
        self.p['policies']['p']['max_lead_seconds'] = 7200
        for obj in [self.e, self.p['claim']]:
            obj['valid_start'] = obj['valid_end'] = '2026-10-11T15:00:00Z'
        self.expect(status='eligible_for_scoped_wording')
        self.e['issued_at'] = '2026-10-11T15:00:00Z'
        self.expect('FUTURE_SOURCE_TIMESTAMP')

    def test_future_observation(self):
        self.e['observed_at'] = '2026-10-11T15:00:00Z'
        self.expect('FUTURE_SOURCE_TIMESTAMP')

    def test_rain_rate_not_total(self):
        self.e['variable'] = self.p['claim']['variable'] = 'rain'
        self.e['value_kind'], self.e['units'] = 'rate', 'mm/h'
        self.p['claim']['value_kind'], self.p['claim']['units'] = 'accumulation', 'mm'
        self.expect('INCOMPATIBLE_VALUE_KIND')

    def test_mesh_not_damage(self):
        self.p['claim']['claim_type'] = 'roof_damage'
        self.expect('DAMAGE_OUTSIDE_CHECKER_SCOPE')

    def test_radial_not_gust(self):
        self.e['variable'], self.p['claim']['variable'] = 'radial_velocity', 'surface_gust'
        self.expect('INCOMPATIBLE_VARIABLE')

    def test_alert_is_not_observation(self):
        self.e['evidence_kind'] = 'official_alert'
        self.expect('ALERT_IS_NOT_HAZARD_OBSERVATION')

    def test_forecast_cannot_issue_warning(self):
        self.e['evidence_kind'] = 'forecast'
        self.p['claim']['claim_type'] = 'official_alert_status'
        self.expect('NOT_OFFICIAL_ALERT')

    def test_unusable_quality(self):
        self.e['quality'] = 'unusable'
        self.expect('UNUSABLE_LOCAL_EVIDENCE')

    def test_malformed(self):
        for p in [None, [], {}, {'claim': []}, {**self.p, 'evidence': [1]},
                  {**self.p, 'now_utc': 'ambiguous'}]:
            with self.subTest(payload=p):
                self.assertEqual(check(p)['status'], 'blocked')

    def test_valid_negative_radial_velocity(self):
        for obj in [self.e, self.p['claim'], self.p['policies']['p']]:
            obj['variable'], obj['units'] = 'radial_velocity', 'm/s'
        self.e['evidence_kind'], self.e['value'] = 'measurement', -15
        self.p['claim']['value'] = -15
        self.p['policies']['p']['kinds'] = ['measurement']
        self.expect(status='eligible_for_scoped_wording')

    def test_valid_point_station_temperature(self):
        for obj in [self.e, self.p['claim'], self.p['policies']['p']]:
            obj['variable'], obj['units'] = 'station_air_temperature', 'C'
        self.e['evidence_kind'], self.e['value'] = 'measurement', 10
        self.p['claim']['value'] = 10
        self.e['representative_at_point'] = True
        self.e['relation'] = self.p['claim']['scope'] = 'point'
        self.p['policies']['p']['kinds'] = ['measurement']
        self.expect(status='eligible_for_scoped_wording')


    def test_recent_current_observation(self):
        self.p['now_utc'] = self.p['cutoff_utc'] = '2026-10-11T14:02:00Z'
        self.expect(status='eligible_for_scoped_wording')

    def test_missing_claim_value(self):
        self.p['claim'].pop('value')
        self.expect('MISSING_CLAIM_VALUE')

    def test_observation_after_publication(self):
        self.e['observed_at'] = '2026-10-11T14:01:00Z'
        self.p['now_utc'] = self.p['cutoff_utc'] = '2026-10-11T14:02:00Z'
        self.expect('OBSERVATION_CLOCK_ORDER')

    def test_historical_observation_after_cutoff(self):
        self.p['claim']['time_mode'] = 'historical_asof'
        self.p['cutoff_utc'] = '2026-10-11T13:59:00Z'
        self.e['published_at'] = self.p['cutoff_utc']
        self.expect('ASOF_LEAKAGE')

    def test_forecast_lead_limit(self):
        self.p['claim']['time_mode'] = 'forecast'
        self.e['evidence_kind'] = 'forecast'
        self.e['issued_at'] = T
        self.e.pop('observed_at')
        self.p['policies']['p']['kinds'] = ['forecast']
        for obj in [self.e, self.p['claim']]:
            obj['valid_start'] = obj['valid_end'] = '2200-10-11T15:00:00Z'
        self.expect('UNKNOWN_FORECAST_LEAD_POLICY', 'review_required')
        self.p['policies']['p']['max_lead_seconds'] = 7200
        self.expect('FORECAST_LEAD_OUTSIDE_POLICY')

    def test_registry_binding(self):
        self.e['product_id'] = 'impostor'
        self.expect('POLICY_SOURCE_PRODUCT_MISMATCH')

    def test_separate_registry(self):
        registry = self.p.pop('policies')
        self.assertEqual(check(self.p, registry)['status'], 'eligible_for_scoped_wording')

    def test_transformation_requires_review(self):
        self.p['claim']['transformation'] = 'unit_conversion'
        self.expect('TRANSFORM_REQUIRES_REVIEW', 'review_required')


    def test_historical_forecast_replay(self):
        self.p['claim']['claim_type'] = 'forecast'
        self.p['claim']['time_mode'] = 'historical_asof'
        self.e['evidence_kind'] = 'forecast'
        self.e['issued_at'] = T
        self.e.pop('observed_at')
        self.p['now_utc'] = '2026-10-12T14:00:00Z'
        self.p['policies']['p'].update(kinds=['forecast'], max_lead_seconds=7200)
        for obj in [self.e, self.p['claim']]:
            obj['valid_start'] = obj['valid_end'] = '2026-10-11T15:00:00Z'
        self.expect(status='eligible_for_scoped_wording')
        self.p['claim']['time_mode'] = 'retrospective'
        self.expect(status='eligible_for_scoped_wording')

    def test_official_alert_validity_and_category_value(self):
        self.e['evidence_kind'] = 'official_alert'
        self.p['claim']['claim_type'] = 'official_alert_status'
        self.p['claim']['scope'] = self.e['relation'] = 'alert_area'
        self.p['policies']['p']['kinds'] = ['official_alert']
        for obj in [self.e, self.p['claim'], self.p['policies']['p']]:
            obj.update(variable='warning_status', value_kind='status', units='none')
        for obj in [self.e, self.p['claim']]:
            obj.update(value='active', valid_end='2026-10-11T15:00:00Z')
        self.expect(status='eligible_for_scoped_wording')
        self.p['claim']['value'] = 'cancelled'
        self.expect('CLAIM_VALUE_NOT_GROUNDED')
        self.p['claim']['value'] = 'active'
        self.p['now_utc'] = self.p['cutoff_utc'] = '2026-10-11T15:00:00Z'
        self.expect('ALERT_NOT_CURRENTLY_VALID')


if __name__ == '__main__':
    unittest.main()
