import json
import random

from fastapi.testclient import TestClient

from server.game.match import Match
from server.main import create_app
from server.net.protocol import private_part
from server.store import FileStore


def shop(data, gold=5000):
    m = Match(data, 6, random.Random(1))
    p = m.add_player("a", "A", "ronin")
    m.start()
    p.gold = gold
    return m, p


def test_all_recipes_reference_real_non_recipe_components(data):
    recipes = {k: v for k, v in data.items.items() if v.get("recipe")}
    assert set(recipes) == {"heart", "reaver", "archcore", "windstep", "vampedge"}
    for result, item in recipes.items():
        assert item["combine_cost"] >= 0
        assert all(c in data.items and not data.items[c].get("recipe") for c in item["recipe"])


def test_craft_consumes_components_and_gold(data):
    m, p = shop(data)
    assert m.buy("a", "blade") is None
    assert m.buy("a", "gloves") is None
    before = p.gold
    assert m.craft("a", "reaver") is None
    assert p.items == ["reaver"]
    assert p.gold == before - data.items["reaver"]["combine_cost"]
    stats = m.hero_stats(p)
    assert stats["dmg"] == data.heroes["ronin"]["dmg"] + 28
    assert abs(stats["atk_cd"] - data.heroes["ronin"]["atk_cd"] * 0.82) < 1e-9


def test_recipe_errors_do_not_change_inventory_or_gold(data):
    m, p = shop(data, gold=100)
    original = (p.gold, list(p.items))
    assert m.craft("a", "reaver") == "Requires: Iron Blade + Frenzy Gloves"
    assert (p.gold, p.items) == original
    p.items = ["blade", "gloves"]
    original = (p.gold, list(p.items))
    assert m.craft("a", "reaver") == "Need 225 gold to combine."
    assert (p.gold, p.items) == original
    assert m.craft("a", "blade") == "Unknown recipe."


def test_crafting_works_with_full_inventory_because_it_frees_a_slot(data):
    m, p = shop(data)
    p.items = ["blade", "gloves", "plate", "boots", "tome", "fang"]
    assert len(p.items) == data.game["max_items"]
    assert m.craft("a", "reaver") is None
    assert len(p.items) == data.game["max_items"] - 1
    assert "reaver" in p.items and "blade" not in p.items and "gloves" not in p.items


def test_hud_stats_in_shop_include_level_and_items(data):
    m, p = shop(data)
    p.level = 3
    p.items = ["plate", "gem", "blade", "fang"]
    raw = json.loads(private_part(m, p))
    stats = raw[-1]
    expected = m.hero_stats(p)
    assert stats == [round(expected["max_hp"]), round(expected["max_hp"]), round(expected["dmg"]),
                     round(expected["armor"]), round(expected["speed"]), round(100 / expected["atk_cd"]),
                     round(expected["atk_range"]), round(expected["spell_power"] * 100),
                     round(expected["lifesteal"] * 100), 0]


def test_hud_stats_during_fight_show_current_hp_and_shield(data):
    m, p = shop(data)
    m.step(m.timer + 0.01)
    u = m.world.units[p.unit_id]
    u.hp = 321.4
    u.shield = 99.7
    stats = json.loads(private_part(m, p))[-1]
    assert stats[0] == 321 and stats[1] == round(u.max_hp)
    assert stats[2:5] == [round(u.dmg), round(u.armor), round(u.speed)]
    assert stats[-1] == 100


def test_client_receives_recipe_metadata(limits):
    c = TestClient(create_app(FileStore(None), limits))
    code = c.post("/api/rooms").json()["code"]
    with c.websocket_connect(f"/ws/{code}?name=A&hero=ronin") as ws:
        hello = ws.receive_json()
    assert hello["items"]["reaver"]["recipe"] == ["blade", "gloves"]
    assert hello["items"]["reaver"]["combine"] == 225
    assert hello["items"]["blade"]["recipe"] is None
