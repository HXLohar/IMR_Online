import pytest

from scoring.fan import detect_fans, load_fans_from_csv
from scoring.parsing import analyze_hand


FANS = load_fans_from_csv()


@pytest.mark.parametrize(
    ('fan_id', 'example'),
    [
        (111, '22334b555cGGGWhWh + 4b* +BOH'),
        (112, '22334b555cGGGWhWh + 4b* +BOE'),
        (407, '[1111d*][333d]778899cWh + Wh* +AQ'),
        (408, '[1111d*][333d]778899cWh + Wh +RQ'),
        (409, '[1111d*][333d]778899cWh + Wh +LT'),
        (410, '111b333555c234d1d + 1d'),
        (411, '111b333555c234d1d + 1d +EW'),
        (412, '111b333555c234d1d + 1d +DW'),
        (501, '123c444d56789cNN + 4c*'),
    ],
)
def test_special_or_edge_fan_example_is_detected(fan_id: int, example: str):
    result = analyze_hand(example)
    assert result['is_valid'], result.get('error')
    detected = {found_id for found_id, _ in detect_fans(result['explanations'][0], FANS)}
    assert fan_id in detected


def test_mirrored_tiles_normalizes_quad_to_triplet():
    result = analyze_hand('[234b][8888b*]234c8899c + 8c')
    assert result['is_valid'], result.get('error')
    detected = {found_id for found_id, _ in detect_fans(result['explanations'][0], FANS)}
    assert 406 in detected
