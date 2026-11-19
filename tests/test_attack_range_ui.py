from pathlib import Path


def test_client_has_basic_attack_range_overlay():
    js = (Path(__file__).parents[1] / "client" / "game.js").read_text(encoding="utf-8")
    assert "function drawAttackRange" in js
    assert "Basic attack range" in js
    assert "IN RANGE" in js and "TOO FAR" in js
    assert 'k === "a"' in js
    assert "stats[6]" in js                    # uses server-authoritative range from private stats


def test_index_explains_range_toggle():
    html = (Path(__file__).parents[1] / "client" / "index.html").read_text(encoding="utf-8")
    assert "A toggles range" in html
