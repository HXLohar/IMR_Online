from bots.efficiency_bot import EfficiencyBot
from bots.auto_call_bot import AutoCallBot
from game.player_state import PlayerState


def test_efficiency_bot_never_calls_but_wins():
    bot = EfficiencyBot()
    assert bot.decide_claim({}, ['straight_call', 'triplet_call', 'direct_quad_call']) == {'claim': 'skip'}
    assert bot.decide_claim({}, ['win', 'skip']) == {'claim': 'win'}


def test_efficiency_bot_discards_junk_to_reach_wait():
    bot = EfficiencyBot()
    hand = ['1b', '2b', '3b', '4b', '5b', '6b', '7b', '8b', '9b', '1c', '2c', '1c', '1c', '9d']
    action = bot.decide_turn({'hand': hand, 'options': ['discard']})
    assert action['tile'] == '9d'


def test_bot_seats_put_call_bot_upstream_of_human():
    players = [
        PlayerState(seat=0, name='Guest'),
        PlayerState(seat=1, name='Bot-1', is_bot=True, bot=EfficiencyBot()),
        PlayerState(seat=2, name='Bot-2', is_bot=True, bot=EfficiencyBot()),
        PlayerState(seat=3, name='Bot-3', is_bot=True, bot=AutoCallBot()),
    ]
    assert isinstance(players[1].bot, EfficiencyBot)
    assert isinstance(players[2].bot, EfficiencyBot)
    assert isinstance(players[3].bot, AutoCallBot)
