#!/usr/bin/env python
"""Fix Windows cp1252 test decoding in an existing Bloodfest project."""
from __future__ import annotations
import argparse, datetime as dt, shutil, subprocess, sys
from pathlib import Path

OLD = '.read_text()'
NEW = '.read_text(encoding="utf-8")'
REL = Path('tests/test_attack_range_ui.py')

def root(arg):
    if arg: return Path(arg).resolve()
    cwd=Path.cwd()
    for p in (cwd,cwd/'Bloodfest',cwd/'bloodfest'):
        if (p/REL).exists(): return p.resolve()
    raise SystemExit('Could not find tests/test_attack_range_ui.py. Run from Bloodfest or pass --dir.')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dir');ap.add_argument('--dry-run',action='store_true');ap.add_argument('--test',action='store_true');a=ap.parse_args()
    r=root(a.dir);p=r/REL; raw=p.read_bytes(); crlf=b'\r\n' in raw; text=raw.decode('utf-8').replace('\r\n','\n')
    old_count=text.count(OLD); new_count=text.count(NEW)
    print(f'Project: {r}'+(' [DRY RUN]' if a.dry_run else ''))
    if old_count==0 and new_count==2:
        print('= tests/test_attack_range_ui.py already fixed'); changed=False
    elif old_count==2 and new_count==0:
        print('+ tests/test_attack_range_ui.py: force UTF-8 for both JavaScript/HTML reads'); changed=True
    else:
        raise SystemExit(f'STOPPED - unexpected file content ({old_count} old, {new_count} fixed reads). Nothing written.')
    if a.dry_run:
        print('Dry run only - nothing was written.');return 0
    if changed:
        stamp=dt.datetime.now().strftime('%Y%m%d_%H%M%S');bak=r/'.installer_backups'/stamp/REL;bak.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,bak)
        text=text.replace(OLD,NEW);p.write_bytes(text.replace('\n','\r\n').encode('utf-8') if crlf else text.encode('utf-8'));print(f'Done. Backup: {bak}')
    if a.test:
        win=r/'.venv'/'Scripts'/'python.exe';nix=r/'.venv'/'bin'/'python';py=win if win.exists() else nix if nix.exists() else Path(sys.executable)
        return subprocess.call([str(py),'-m','pytest','-q','-p','no:warnings'],cwd=r)
    print('Run: python -m pytest -q');return 0
if __name__=='__main__': raise SystemExit(main())
