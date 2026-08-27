import csv
from pathlib import Path

import pytest

from scoring.fan import FAN_CHECKERS, compute_recursive_overrides, detect_fans, load_fans_from_csv
from scoring.parsing import analyze_hand


FAN_CSV = Path(__file__).parents[1] / 'scoring' / 'data' / 'fan.csv'

# The source CSV contains 11 malformed examples. Keep the data issue visible
# and isolated until the missing rule-source corrections are available.
KNOWN_INVALID_EXAMPLES = {
    '114', '203', '204', '208', '257', '258', '408', '409', '410', '411', '412',
}


def fan_rows():
    with FAN_CSV.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def test_every_csv_fan_has_a_checker():
    fans = load_fans_from_csv(str(FAN_CSV))
    assert set(fans) == set(FAN_CHECKERS)
    assert len(fans) == 80


def test_fan_overrides_have_no_mutual_or_unknown_targets():
    fans = load_fans_from_csv(str(FAN_CSV))
    overrides = compute_recursive_overrides(fans)
    for fan_id, overridden in overrides.items():
        assert fan_id not in overridden
        assert overridden <= set(fans)
        for other_id in overridden:
            assert fan_id not in overrides.get(other_id, set())


@pytest.mark.parametrize('row', fan_rows(), ids=lambda row: row['id'])
def test_every_fan_example_is_covered_or_documented(row):
    result = analyze_hand(row['examples'])
    if not result['is_valid']:
        assert row['id'] in KNOWN_INVALID_EXAMPLES, result['error']
        return

    detected = {fan_id for fan_id, _ in detect_fans(result['explanations'][0], load_fans_from_csv(str(FAN_CSV)))}
    assert int(row['id']) in detected, f"{row['id']} not detected from {row['examples']}"
