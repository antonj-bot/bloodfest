"""cleanup.py - reusable Bloodfest cleanup to run after an update is committed and pushed.

    python cleanup.py --dry-run     # show what would be removed, delete nothing
    python cleanup.py               # show the list, ask, then delete
    python cleanup.py --yes         # delete without asking

Removes from the project root:
  * install_bloodfest*.py and fix_*_tests.py   one-time Bloodfest patch scripts already applied
  * .installer_backups/ and .<name>-backups/ folders made by Bloodfest installers

Options:
  --keep NAME [NAME ...]   leave these alone. Match a file name, a folder name, or a short tag:
                           --keep ms  keeps install_ms_state.py, install_ms_fixes.py and .ms-backups/ .ms-fixes-backups/
  --include-cleanup        also remove .cleanup-backups/ (old manual cleanups, may hold 'parked' work: look first)
  --older-than DAYS        only remove backup folders whose newest content is older than DAYS days
  --force                  run even if tracked files have uncommitted changes (not recommended)

Safety:
  * Refuses to run while tracked files have uncommitted changes: the backups may be your only way back.
  * An install_*.py / fix_*_tests.py that git neither tracks nor ignores is SKIPPED (it could not be recovered).
  * Never deletes itself, never touches server/, client/, tests/, data files, render.yaml or requirements files.
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

SELF = Path(__file__).name
LEGACY = {"cleanup_installers.py", "cleanup_installers_and_backups.py"}          # the earlier one-shot version, if it is still lying around
SCRIPT_GLOBS = ("install_bloodfest*.py", "fix_*_tests.py")


def git(root: Path, *args: str):
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return None


def is_repo(root: Path) -> bool:
    r = git(root, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0)


def untracked_and_unignored(root: Path, rel: str) -> bool:
    r = git(root, "ls-files", "--error-unmatch", rel)
    if r is None or r.returncode == 0:
        return False                                   # tracked (or no git: cannot tell, do not block)
    c = git(root, "check-ignore", "-q", rel)
    return not (c and c.returncode == 0)


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def newest_mtime(p: Path) -> float:
    if p.is_file():
        return p.stat().st_mtime
    times = [f.stat().st_mtime for f in p.rglob("*") if f.is_file()]
    return max(times) if times else p.stat().st_mtime


def _on_rm_error(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)                      # Windows read-only files
    func(path)


def remove(p: Path):
    shutil.rmtree(p, onerror=_on_rm_error) if p.is_dir() else (os.chmod(p, stat.S_IWRITE), p.unlink())


def is_kept(p: Path, keep: set) -> bool:
    name = p.name.lower()
    for k in keep:
        k = k.lower().strip("./\\")
        if name in (k, f"install_{k}_state.py", f"install_{k}_fixes.py", f".{k}-backups", f".{k}-fixes-backups"):
            return True
        if name.strip(".") == k.strip("."):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove applied installers and their backup folders.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="do not ask before deleting")
    ap.add_argument("--keep", nargs="*", default=[], metavar="NAME")
    ap.add_argument("--include-cleanup", action="store_true")
    ap.add_argument("--older-than", type=float, default=None, metavar="DAYS")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--root", type=Path, default=Path.cwd())
    args = ap.parse_args()

    root = args.root.resolve()
    required = (root / "server", root / "client", root / "tests", root / "render.yaml")
    if not all(p.exists() for p in required):
        sys.exit(f"{root} does not look like the Bloodfest root (need server/, client/, tests/, render.yaml). Run it from the project root.")

    repo = is_repo(root)
    if repo and not args.force and not args.dry_run:
        st = git(root, "status", "--porcelain", "--untracked-files=no")
        # pending deletions of installers from an earlier run are fine; anything else tracked that changed is not
        dirty = [ln for ln in (st.stdout.splitlines() if st else [])
                 if not (ln[:2].strip() == "D" and any(Path(ln[3:].strip().strip('"')).match(g) for g in SCRIPT_GLOBS))]
        if dirty:
            print("Tracked files have uncommitted changes:\n" + "\n".join(dirty) + "\n")
            sys.exit("Commit (or stash) first - the backups may be your only way back. Use --force to override.")
    if not repo:
        print("warning: not a git repo, so nothing can be recovered after deleting.")

    keep = set(args.keep)
    cutoff = time.time() - args.older_than * 86400 if args.older_than is not None else None
    targets, skipped, kept = [], [], []

    scripts = {p for g in SCRIPT_GLOBS for p in root.glob(g)} | {root / n for n in LEGACY if (root / n).exists()}
    for p in sorted(scripts):
        if p.name == SELF:
            continue
        if is_kept(p, keep):
            kept.append(p)
        elif repo and p.name not in LEGACY and untracked_and_unignored(root, p.name):
            skipped.append(p)
        else:
            targets.append(p)

    for d in sorted({*root.glob(".*-backups"), root / ".installer_backups"}):
        if not d.is_dir():
            continue
        if is_kept(d, keep):
            kept.append(d)
        elif d.name == ".cleanup-backups" and not args.include_cleanup:
            kept.append(d)
        elif cutoff is not None and newest_mtime(d) > cutoff:
            kept.append(d)
        else:
            targets.append(d)

    if not targets and not skipped:
        print("Nothing to clean.")
        return 0

    total = 0
    for p in targets:
        s = size_of(p)
        total += s
        print(f"  remove  {p.name}{'/' if p.is_dir() else ''}  ({s/1024:.0f} KB)")
    for p in skipped:
        print(f"  SKIP    {p.name}  (not tracked by git and not ignored - commit it or delete it by hand)")
    for p in kept:
        print(f"  keep    {p.name}{'/' if p.is_dir() else ''}")
    print(f"\n{len(targets)} item(s), {total/1e6:.2f} MB")

    if args.dry_run or not targets:
        print("Dry run - nothing deleted." if args.dry_run else "")
        return 0
    if not args.yes and input("Delete these? [y/N] ").strip().lower() != "y":
        print("Cancelled, nothing deleted.")
        return 0

    for p in targets:
        remove(p)
    print(f"Done, {total/1e6:.2f} MB freed. Next: python -m pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
