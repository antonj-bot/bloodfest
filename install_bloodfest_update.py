#!/usr/bin/env python
r"""
install_bloodfest_update.py - UPDATES an existing Bloodfest project in place (v1 -> v2).

What it changes
  * Pacing   : shop 25->12 s, storm 150->45 s (harder), boss enrage 90->30 s, 70 s hard cap per fight,
               round break 4->2 s, results 15->8 s.
  * Art      : drawn-in-canvas heroes / goblins / boss / imps, arena floor, hit flash, storm vignette.
  * Fixes    : "Ready" button resets each shop; canvas no longer resized every frame.
  * Network / database / free-tier limits: NOT touched.

Usage (PowerShell, from the Bloodfest folder or its parent)
    python install_bloodfest_update.py --dry-run     # show what would change, write nothing
    python install_bloodfest_update.py               # apply
    python install_bloodfest_update.py --test        # apply, then run the test suite in .venv
    python install_bloodfest_update.py --dir "C:\Python Projects\Bloodfest"
    python install_bloodfest_update.py --overwrite-mismatched   # replace match.py / game.js wholesale if patches don't fit

Safety
  * Everything is computed in memory first. If any required patch does not fit, NOTHING is written.
  * Already-applied patches are detected and skipped, so re-running is harmless.
  * Every file that changes is copied to .installer_backups\<timestamp>\ first.
  * Python / JSON results are syntax-checked before anything is written.
  * Windows (CRLF) and Unix (LF) line endings are both handled and preserved.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import zlib
from pathlib import Path


# ---- embedded NEW versions (used to extract the art block and for --overwrite-mismatched) ----
_NEW_B64 = {
    "server/game/match.py": (
    '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'
),
    "client/game.js": (
    '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'
),
    "tests/test_gameplay_pacing.py": (
    'eNqFVE2P0zAQvfdXGJ9SEUVptQuoogekBZYDu6sFTtXKcuNpY20cB9vph9D+d8Z226RUGyJVzXy88byZ50jVaOOI4bXQarQy'
    'WhELZgMmW3MFmeKuKImMSd+9kZIv377e/kzJ4/2vuxv2+e4mJT9u7x9Go5GAFeEGap4I7nhKCt3Wbj4dz0YEH0XmscIh+i49'
    'nJo9hr/kajwOiSttiCSy9uE1JKHKoUaok3EhWFPxPZjEOpPIcUroQ7ApeUtOLqNrWdNYU2XWceOSzoImUZmTCgxi8iyfxJAB'
    '15qaqAMdB9Yxgx0IVnIjWMEbBhuo2Va6kpXtGlgJvHKRVI9pN4eOVOtJqWyrTSUyXsmNBxsNNunRa7OyQfwEJtOeT/Edi/6e'
    '0zYAAn356QTWjW3yfpqfTS1QRqLX45NTrtDflNwCeTOPe+0Q/lka4M/Bwy3Kwp3S5/Nu/+fxOFKMe+5BRAsaBwj4s1DoWlj6'
    '1AfV2r0ylv4WBPDj2nENNYKY0pirvWnd/xagskIrhUpLaE5T8oc6OqO2lYUUQF9iTou4YyNtLZ1dIN9wol0g6ik4mRSx+0Zb'
    'zE/abJfiMvYDx/g+0aA7OvuQ5/iyp7Or6/xlAOIpeYittDd/D8H/2Wxvqm2cJ8HivUb9drD5V/YaZNAfvC11w1AIYs/ss2ws'
    '23J5Me6zm31srHdRKfcMPtHBe3nZTPiyHBLBxS58rWHqQ2yW2lqUouFrsGwJeGuAWaeN6jM61AkS9gDA/fOlrKSTgOJd0FjA'
    'v/GVQ0Gik3y8lHwn979FgJsx'
),
}
README_SECTION = '## Pacing (v2)\n\n| Phase | Time |\n|---|---|\n| Shop | 12 s (ends early when everyone clicks Ready) |\n| Fight | storm starts at 45 s, hard cap 70 s, boss enrages at 30 s |\n| Round break / results | 2 s / 8 s |\n\nA 10-round match takes roughly 8 minutes (bot-simulated; humans will vary).\nAll art is drawn on the canvas in the browser, so it adds **zero** network traffic.\nNetwork update rate and database use are unchanged.\n'


OK, SKIP, FAIL = "applied", "already applied", "MISMATCH"


def new_text(rel: str) -> str:
    return zlib.decompress(base64.b64decode("".join(_NEW_B64[rel]))).decode("utf-8")


# ---------------------------------------------------------------- file model
class Doc:
    """A text file held in memory, edited with LF newlines, written back in its original style."""

    def __init__(self, root: Path, rel: str, must_exist: bool = True) -> None:
        self.rel, self.path = rel, root / rel
        self.exists = self.path.exists()
        raw = self.path.read_bytes().decode("utf-8") if self.exists else ""
        self.crlf = "\r\n" in raw
        self.orig = raw.replace("\r\n", "\n")
        self.text = self.orig
        self.must_exist = must_exist

    @property
    def changed(self) -> bool:
        return self.text != self.orig

    def output(self) -> bytes:
        t = self.text.replace("\n", "\r\n") if self.crlf else self.text
        return t.encode("utf-8")


# ---------------------------------------------------------------- patch primitives
def replace_once(doc: Doc, old: str, new: str, label: str) -> str:
    if new in doc.text:          # check the NEW text first: some anchors also occur inside their replacement
        return SKIP
    if doc.text.count(old) == 1:
        doc.text = doc.text.replace(old, new)
        return OK
    return FAIL


def json_set(doc: Doc, updates: dict, label: str) -> str:
    try:
        data = json.loads(doc.text)
    except ValueError:
        return FAIL
    changed = False

    def apply(node: dict, upd: dict) -> None:
        nonlocal changed
        for k, v in upd.items():
            if isinstance(v, dict) and isinstance(node.get(k), dict):
                apply(node[k], v)
            elif node.get(k) != v:
                node[k] = v
                changed = True

    apply(data, updates)
    if not changed:
        return SKIP
    doc.text = json.dumps(data, indent=2) + "\n"
    return OK


ART_START_OLD = "  function frame() {"
ART_START_NEW = "  // ---- art: everything is drawn"
ART_END = "  requestAnimationFrame(frame);\n\n  // ---------------------------------------------------------------- helpers"


def art_block(doc: Doc, label: str) -> str:
    if ART_START_NEW in doc.text:
        return SKIP
    a, e = doc.text.find(ART_START_OLD), doc.text.find(ART_END)
    if a < 0 or e < 0 or e < a or doc.text.count(ART_START_OLD) != 1:
        return FAIL
    full = new_text("client/game.js").replace("\r\n", "\n")
    block = full[full.index(ART_START_NEW):full.index(ART_END)]
    doc.text = doc.text[:a] + block + doc.text[e:]
    return OK


def bump_cache(doc: Doc, label: str) -> str:
    out = re.sub(r"\?v=\d+", "?v=4", doc.text)
    if out == doc.text:
        return SKIP if "?v=4" in doc.text else FAIL
    doc.text = out
    return OK


def readme_patch(doc: Doc, label: str) -> str:
    if "## Pacing (v2)" in doc.text:
        return SKIP
    t = doc.text.replace("after 150 s everything bleeds", "after 45 s everything bleeds").replace("(25 s)", "(12 s)")
    doc.text = t.rstrip() + "\n\n" + README_SECTION
    return OK


def gitignore_patch(doc: Doc, label: str) -> str:
    if ".installer_backups/" in doc.text:
        return SKIP
    doc.text = doc.text.rstrip("\n") + "\n.installer_backups/\n" if doc.text else ".installer_backups/\n"
    return OK


def create_file(doc: Doc, rel: str) -> str:
    want = new_text(rel).replace("\r\n", "\n")
    if doc.text == want:
        return SKIP
    doc.text = want
    return OK


# ---------------------------------------------------------------- the plan
def plan(root: Path):
    """Returns (docs, results) - results is a list of (file, description, status, required)."""
    docs: dict[str, Doc] = {}

    def D(rel: str) -> Doc:
        if rel not in docs:
            docs[rel] = Doc(root, rel)
        return docs[rel]

    results: list[tuple[str, str, str, bool]] = []

    def run(rel: str, desc: str, fn, *args, required: bool = True) -> None:
        d = D(rel)
        if not d.exists and rel not in ("tests/test_gameplay_pacing.py", ".gitignore"):
            results.append((rel, desc, FAIL + " (file not found)", required))
            return
        results.append((rel, desc, fn(d, *args), required))

    run("server/data/game.json", "pacing values (shop/storm/round caps)", json_set, {
        "shop_seconds": 12, "round_end_seconds": 2, "results_seconds": 8,
        "round_seconds": 45, "round_hard_cap_seconds": 70,
        "storm": {"start_pct": 0.08, "growth_pct": 0.05, "growth_every_s": 5},
    }, "game.json")
    run("server/data/bosses.json", "boss enrage after 30 s", json_set,
        {"abilities": {"enrage": {"after_s": 30}}}, "bosses.json")
    run("server/game/match.py", "70 s hard cap on fights", replace_once,
        "        self._process_deaths()\n        self._respawn_camps(dt)\n",
        "        # Hard cap kills all remaining heroes rather than reviving anyone early.\n"
        "        if self.timer >= self.g.get(\"round_hard_cap_seconds\", 85):\n"
        "            for hero in w.alive_heroes():\n"
        "                w.kill(hero.id)\n"
        "        self._process_deaths()\n        self._respawn_camps(dt)\n", "hard cap")
    run("client/game.js", "stop resizing the canvas every frame", replace_once,
        "    cv.width = innerWidth * devicePixelRatio; cv.height = innerHeight * devicePixelRatio;\n",
        "    const width = Math.round(innerWidth * devicePixelRatio);\n"
        "    const height = Math.round(innerHeight * devicePixelRatio);\n"
        "    if (cv.width !== width || cv.height !== height) {\n"
        "      cv.width = width; cv.height = height;\n"
        "    }\n", "resize")
    run("client/game.js", "Ready button resets each shop", replace_once,
        "    if (inShop) renderShop(gold, items, m.tm);\n",
        "    if (inShop) {\n"
        "      if (S.lastShopRound !== m.rd) {\n"
        "        S.lastShopRound = m.rd;\n"
        "        $(\"btnReady\").textContent = \"Ready\";\n"
        "      }\n"
        "      renderShop(gold, items, m.tm);\n"
        "    }\n", "shop ready")
    run("client/game.js", "bigger unit hit-boxes", replace_once,
        "u[1] === KIND.BOSS ? 46 : u[1] === KIND.HERO ? 18 : u[1] === KIND.ADD ? 16 : 14",
        "u[1] === KIND.BOSS ? 54 : u[1] === KIND.HERO ? 22 : u[1] === KIND.ADD ? 18 : 16", "radius")
    run("client/game.js", "new art + arena floor + effects", art_block, "art")
    run("client/index.html", "cache-bust JS/CSS (?v=4)", bump_cache, "cache")
    run("tests/test_gameplay_pacing.py", "new pacing tests", create_file, "tests/test_gameplay_pacing.py")
    run("README.md", "pacing section", readme_patch, "readme", required=False)
    run(".gitignore", "ignore .installer_backups/", gitignore_patch, "gitignore", required=False)
    return docs, results


# ---------------------------------------------------------------- checks
def validate(docs: dict[str, Doc]) -> list[str]:
    problems = []
    for rel, d in docs.items():
        if not d.changed:
            continue
        try:
            if rel.endswith(".py"):
                compile(d.text, rel, "exec")
            elif rel.endswith(".json"):
                json.loads(d.text)
        except (SyntaxError, ValueError) as exc:
            problems.append(f"{rel}: {exc}")
    js = docs.get("client/game.js")
    if js and js.changed and shutil.which("node"):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(js.text)
        r = subprocess.run(["node", "--check", fh.name], capture_output=True, text=True)
        if r.returncode:
            problems.append("client/game.js: " + r.stderr.strip().splitlines()[0])
    return problems


def find_root(arg: Path | None) -> Path:
    if arg:
        return arg.resolve()
    cwd = Path.cwd()
    for c in (cwd, cwd / "Bloodfest", cwd / "bloodfest"):
        if (c / "server" / "game" / "match.py").exists():
            return c.resolve()
    raise SystemExit("Could not find the Bloodfest project (server/game/match.py). "
                     "Run this from the Bloodfest folder, or pass --dir.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Update Bloodfest in place (pacing + art).")
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true", help="run pytest in .venv afterwards")
    ap.add_argument("--overwrite-mismatched", action="store_true",
                    help="if match.py / game.js patches don't fit, replace those files with the new versions")
    args = ap.parse_args()

    root = find_root(args.dir)
    print(f"Project: {root}" + ("   [DRY RUN]" if args.dry_run else ""))
    docs, results = plan(root)

    failed = [r for r in results if r[2].startswith(FAIL) and r[3]]
    if failed and args.overwrite_mismatched:
        for rel in {r[0] for r in failed}:
            if rel in ("server/game/match.py", "client/game.js"):
                d = docs[rel]
                d.text = new_text(rel).replace("\r\n", "\n")
                results = [(f, de, (OK + " (file replaced)") if f == rel and s.startswith(FAIL) else s, rq)
                           for f, de, s, rq in results]
        failed = [r for r in results if r[2].startswith(FAIL) and r[3]]

    width = max(len(r[0]) for r in results)
    for rel, desc, status, req in results:
        mark = {"applied": "+", "already applied": "=", }.get(status.split(" (")[0], "!")
        print(f"  {mark} {rel:<{width}}  {desc}: {status}" + ("" if req or mark != "!" else "  (optional, skipped)"))

    if failed:
        print("\nSTOPPED - nothing was written. These required patches did not fit your files:")
        for rel, desc, status, _ in failed:
            print(f"   - {rel}: {desc}")
        print("Your file differs from the version this patch expects. Options:\n"
              "  * send me the file (or the failing section), or\n"
              "  * re-run with --overwrite-mismatched to replace match.py / game.js with the new versions "
              "(a backup is kept; any custom edits in those two files would be lost).")
        return 1

    problems = validate(docs)
    if problems:
        print("\nSTOPPED - the patched result failed validation, nothing was written:")
        for p in problems:
            print("   -", p)
        return 1

    changed = [d for d in docs.values() if d.changed]
    print(f"\n{len(changed)} file(s) to change, {len(docs) - len(changed)} already up to date.")
    if args.dry_run:
        print("Dry run only - nothing was written.")
        return 0
    if not changed:
        print("Nothing to do - Bloodfest is already updated.")
    else:
        backup = root / ".installer_backups" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        for d in changed:
            if d.exists:
                (backup / d.rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d.path, backup / d.rel)
            d.path.parent.mkdir(parents=True, exist_ok=True)
            d.path.write_bytes(d.output())
        print(f"Done. Backups: {backup}")

    if args.test:
        win = root / ".venv" / "Scripts" / "python.exe"
        py = win if win.exists() else (root / ".venv" / "bin" / "python" if (root / ".venv" / "bin" / "python").exists() else Path(sys.executable))
        print(f"\n> {py} -m pytest -q")
        return subprocess.call([str(py), "-m", "pytest", "-q", "-p", "no:warnings"], cwd=root)
    print("\nRestart the server and hard-refresh the browser (Ctrl+F5):")
    print("  python -m uvicorn server.main:app --reload --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
