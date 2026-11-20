from pathlib import Path

def test_pudge_polish_v3_replaces_v2_runtime():
 root=Path(__file__).parents[1];js=(root/"client/game.js").read_text(encoding="utf-8");css=(root/"client/style.css").read_text(encoding="utf-8");assert "PUDGE_WARS_POLISH_V3" in js;assert "PUDGE_WARS_POLISH_V2\n(()" not in js;assert "UNKNOWN TERRITORY" in js;assert "pudge-v3" in css;assert "backdrop-filter" in css
