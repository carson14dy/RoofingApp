"""Synthetic reference metadata gate; no geometry computation or weather prediction.

Relations and policies must come from trusted adapters, never untrusted model claims.
This fixture checker does not authenticate an adapter or establish factual accuracy.
"""
import json
import math
import sys
from datetime import datetime, timezone

RANK = {'eligible_for_scoped_wording': 0, 'review_required': 1, 'blocked': 2}
KINDS = {'measurement', 'report', 'estimate', 'forecast', 'official_alert', 'simulation'}
MODES = {'current', 'historical_asof', 'retrospective', 'forecast'}


def instant(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp needs timezone')
    return result.astimezone(timezone.utc)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check(payload, registry=None):
    """Return monotonic severity and reason codes; malformed input never escapes."""
    status = 'eligible_for_scoped_wording'
    reasons = []

    def flag(code, severity='blocked'):
        nonlocal status
        if code not in reasons:
            reasons.append(code)
        if RANK[severity] > RANK[status]:
            status = severity

    def result():
        return {'status': status, 'reasons': reasons,
                'scope': payload.get('claim', {}).get('scope')
                if isinstance(payload, dict) and isinstance(payload.get('claim'), dict)
                and isinstance(payload['claim'].get('scope'), str) else None,
                'limitation': 'Metadata eligibility only; no geometry verification or accuracy claim.'}

    try:
        if not isinstance(payload, dict):
            raise ValueError('envelope')
        claim, evidence = payload['claim'], payload['evidence']
        policies = registry if registry is not None else payload['policies']
        if not isinstance(claim, dict) or not isinstance(evidence, list) or not isinstance(policies, dict):
            raise ValueError('structure')
        now, cutoff = instant(payload['now_utc']), instant(payload['cutoff_utc'])
        if cutoff > now:
            flag('FUTURE_CUTOFF')
        mode, scope = claim['time_mode'], claim['scope']
        if mode not in MODES or scope not in {'point', 'nearby', 'grid', 'alert_area'}:
            flag('INVALID_CLAIM_SCOPE_OR_MODE')
        start, end = instant(claim['valid_start']), instant(claim['valid_end'])
        if start > end:
            flag('REVERSED_CLAIM_INTERVAL')
        if claim.get('transformation'):
            flag('TRANSFORM_REQUIRES_REVIEW', 'review_required')
        if 'value' not in claim:
            flag('MISSING_CLAIM_VALUE')
        if claim.get('claim_type') not in {'field_description', 'observation', 'forecast', 'official_alert_status', 'roof_damage'}:
            flag('UNSUPPORTED_CLAIM_TYPE')
        point = claim['target_point']
        if not isinstance(point, list) or len(point) != 2 or not all(finite(x) for x in point) or not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180):
            flag('INVALID_TARGET_COORDINATES')
        ids = claim['evidence_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids):
            raise ValueError('evidence ids')
        if any(not isinstance(e, dict) or not isinstance(e.get('evidence_id'), str) for e in evidence):
            raise ValueError('evidence record')
        by_id = {e['evidence_id']: e for e in evidence}
        if len(by_id) != len(evidence):
            flag('DUPLICATE_EVIDENCE_ID')
        for eid in ids:
            if eid not in by_id:
                flag('MISSING_EVIDENCE')
                continue
            e = by_id[eid]
            kind = e['evidence_kind']
            if e.get('hazard') != claim.get('hazard') or not e.get('hazard'):
                flag('HAZARD_MISMATCH')
            if e.get('relation_target_point') != point:
                flag('WRONG_RELATION_TARGET')
            if kind not in KINDS:
                flag('UNKNOWN_EVIDENCE_KIND')
            if claim.get('claim_type') == 'forecast' and kind != 'forecast':
                flag('CLAIM_REQUIRES_FORECAST')
            if claim.get('claim_type') == 'observation' and kind not in {'measurement', 'report'}:
                flag('CLAIM_REQUIRES_OBSERVATION')
            if kind == 'simulation':
                flag('SIMULATION_IS_NOT_REAL_EVIDENCE')
            if not isinstance(e.get('upstream_id'), str) or not e['upstream_id'].strip():
                flag('MISSING_LINEAGE', 'review_required')
            if not isinstance(e.get('source_id'), str) or not e['source_id'].strip():
                flag('MISSING_SOURCE', 'review_required')
            policy_id = e.get('policy_id')
            policy = policies.get(policy_id) if isinstance(policy_id, str) else None
            if not isinstance(policy, dict):
                flag('MISSING_POLICY', 'review_required')
                policy = {}
            if policy:
                for binding in ('source_id', 'product_id', 'product_version'):
                    if not policy.get(binding) or not e.get(binding):
                        flag('MISSING_POLICY_BINDING', 'review_required')
                    elif policy[binding] != e[binding]:
                        flag('POLICY_SOURCE_PRODUCT_MISMATCH')
            for key in ('variable', 'value_kind', 'units'):
                if not isinstance(e.get(key), str) or e[key] != claim.get(key):
                    flag('INCOMPATIBLE_' + key.upper())
                if policy and e.get(key) != policy.get(key):
                    flag('POLICY_' + key.upper() + '_MISMATCH')
            if policy and kind not in policy.get('kinds', []):
                flag('POLICY_KIND_MISMATCH')
            if 'value' in claim and (claim['value'] != e.get('value') or
                                     (e['value_kind'] not in {'status', 'category', 'event_report'} and not finite(claim['value']))):
                flag('CLAIM_VALUE_NOT_GROUNDED')
            if e['value_kind'] not in {'status', 'category', 'event_report'}:
                value = e.get('value')
                if not finite(value):
                    flag('MISSING_OR_NONFINITE_VALUE')
                elif value in policy.get('missing_sentinels', []):
                    flag('MISSING_SENTINEL')
                elif e['value_kind'] == 'probability':
                    ceiling = {'%': 100, 'fraction': 1}.get(e['units'])
                    if ceiling is None or not 0 <= value <= ceiling:
                        flag('INVALID_PROBABILITY')
                    if not e.get('probability_definition') or e.get('probability_definition') != claim.get('probability_definition'):
                        flag('PROBABILITY_DEFINITION_MISMATCH')
            elif not isinstance(e.get('value'), str) or not e['value']:
                flag('MISSING_CATEGORY_OR_STATUS')
            es, ee = instant(e['valid_start']), instant(e['valid_end'])
            if es > ee:
                flag('REVERSED_EVIDENCE_INTERVAL')
            # Conservative exact-period profile: no undocumented time interpolation.
            if (es, ee) != (start, end):
                flag('TEMPORAL_SCOPE_MISMATCH')
            receipt = instant(e['received_at'])
            issued = instant(e['issued_at']) if e.get('issued_at') else None
            published = instant(e['published_at']) if e.get('published_at') else None
            observed = instant(e['observed_at']) if e.get('observed_at') else None
            if receipt > now or any(t and t > now for t in (issued, published, observed)):
                flag('FUTURE_SOURCE_TIMESTAMP')
            if kind != 'forecast' and ee > now:
                if kind != 'official_alert':
                    flag('FUTURE_OBSERVATION_INTERVAL')
            if observed and (observed > receipt or (published and observed > published)):
                flag('OBSERVATION_CLOCK_ORDER')
            if kind not in {'forecast', 'official_alert'} and (ee > receipt or (published and ee > published)):
                flag('VALID_INTERVAL_CLOCK_ORDER')
            if (published and published > receipt) or (issued and issued > receipt):
                flag('SOURCE_CLOCK_ORDER')
            if mode in {'current', 'historical_asof', 'forecast'}:
                if published is None:
                    flag('UNKNOWN_ASOF_AVAILABILITY', 'review_required')
                elif published > cutoff:
                    flag('ASOF_LEAKAGE')
                if (issued and issued > cutoff) or (observed and observed > cutoff):
                    flag('ASOF_LEAKAGE')
                if kind not in {'forecast', 'official_alert'} and ee > cutoff:
                    flag('ASOF_LEAKAGE')
            if kind == 'forecast':
                if mode not in {'forecast', 'historical_asof', 'retrospective'}:
                    flag('FORECAST_IS_NOT_OBSERVATION')
                if issued is None:
                    flag('MISSING_FORECAST_ISSUANCE')
                max_lead = policy.get('max_lead_seconds')
                if not finite(max_lead) or max_lead < 0:
                    flag('UNKNOWN_FORECAST_LEAD_POLICY', 'review_required')
                elif issued and ((ee - issued).total_seconds() > max_lead or es < issued):
                    flag('FORECAST_LEAD_OUTSIDE_POLICY')
                anchor = issued
            else:
                if mode == 'forecast' and kind != 'official_alert':
                    flag('OBSERVATION_IS_NOT_FORECAST')
                anchor = observed
            if kind == 'official_alert' and mode == 'current' and not es <= now < ee:
                flag('ALERT_NOT_CURRENTLY_VALID')
            if kind == 'official_alert' and claim.get('claim_type') != 'official_alert_status':
                flag('ALERT_IS_NOT_HAZARD_OBSERVATION')
            if claim.get('claim_type') == 'official_alert_status' and kind != 'official_alert':
                flag('NOT_OFFICIAL_ALERT')
            if claim.get('claim_type') == 'roof_damage':
                flag('DAMAGE_OUTSIDE_CHECKER_SCOPE')
            if kind != 'official_alert' and (mode in {'current', 'forecast'} or (kind == 'forecast' and mode == 'historical_asof')):
                limit = policy.get('max_age_seconds')
                if not finite(limit) or limit < 0 or anchor is None:
                    flag('UNKNOWN_FRESHNESS_POLICY_OR_TIME', 'review_required')
                elif ((cutoff if mode == 'historical_asof' else now) - anchor).total_seconds() > limit:
                    flag('STALE_FOR_REQUEST')
            if e.get('quality') == 'unusable' or e.get('coverage') == 'missing' or e.get('domain') == 'outside':
                flag('UNUSABLE_LOCAL_EVIDENCE')
            elif e.get('quality') != 'usable' or e.get('coverage') != 'available' or e.get('domain') != 'inside':
                flag('UNKNOWN_LOCAL_QUALITY', 'review_required')
            if e.get('relation_authority') != 'trusted_adapter':
                flag('UNVERIFIED_RELATION', 'review_required')
            relation = e.get('relation')
            if relation != scope:
                flag('LOCALITY_SCOPE_MISMATCH')
            if scope == 'point' and (kind != 'measurement' or e.get('representative_at_point') is not True):
                flag('POINT_MEASUREMENT_NOT_ESTABLISHED')
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        flag('MALFORMED_INPUT')
    return result()


def main():
    try:
        with open(sys.argv[1], encoding='utf-8') if len(sys.argv) > 1 else sys.stdin as stream:
            payload = json.load(stream)
        output = check(payload)
    except (OSError, ValueError):
        output = {'status': 'blocked', 'reasons': ['INVALID_JSON_OR_FILE']}
    print(json.dumps(output, allow_nan=False))
    return 0 if output['status'] == 'eligible_for_scoped_wording' else 1


if __name__ == '__main__':
    sys.exit(main())
