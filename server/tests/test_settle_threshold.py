from types import SimpleNamespace

from game.settle import meets_threshold


def scoring(score: int = 0, self_drawn: bool = False, fan_id: int = 1):
    fan = SimpleNamespace(id=fan_id)
    achieved = [SimpleNamespace(fan=fan, score=score)] if score else []
    return SimpleNamespace(
        achieved_fans=achieved,
        explanation=SimpleNamespace(is_self_drawn=self_drawn),
    )


def test_threshold_is_enabled_without_an_explicit_test_override(monkeypatch):
    for key in ('IMR_DISABLE_WIN_THRESHOLD', 'IMR_WIN_THRESHOLD_MODE', 'IMR_MIN_WIN_SCORE'):
        monkeypatch.delenv(key, raising=False)

    assert not meets_threshold(scoring(), pass_count=0, is_concealed=False, has_declared_wait=False)
    assert meets_threshold(scoring(self_drawn=True), pass_count=0, is_concealed=True, has_declared_wait=False)


def test_threshold_override_is_explicit_and_accidental_fans_do_not_count(monkeypatch):
    monkeypatch.setenv('IMR_WIN_THRESHOLD_MODE', 'test')
    assert meets_threshold(scoring(), pass_count=0, is_concealed=False, has_declared_wait=False)

    monkeypatch.delenv('IMR_WIN_THRESHOLD_MODE', raising=False)
    assert not meets_threshold(scoring(500, fan_id=401), pass_count=0,
                               is_concealed=False, has_declared_wait=False)
    assert meets_threshold(scoring(150), pass_count=0, is_concealed=False, has_declared_wait=False)
