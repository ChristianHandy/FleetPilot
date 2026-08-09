# Self-update & server-persistence fixes

Two connected bugs, both root-caused by actually tracing where data goes
rather than guessing. Everything below was reproduced and verified against
a running instance before/after the fix (see "Testing" at the bottom).

## Bug 1: configured servers didn't survive updates/redeploys

`vm_controller.py`, `storage_controller.py`, `smart_manager.py`, and
`disktool_core.py` each stored their SQLite database next to their own
`.py` file (the repo checkout itself) instead of in `DATA_DIR`:

```python
DB_FILE = Path(__file__).parent / "vm_controller.db"   # repo root — wrong
```

...while `app.py` calls each module's `init_db()` with no arguments, so
none of them ever knew about `DATA_DIR` at all. Every other module
(`fan_controller.py`, `hw_info.py`, `system_monitor.py`, ...) already used
the correct pattern — `init_db(data_dir)` — so this was an inconsistency
introduced when these four modules were added, not a one-off typo.

**Why this breaks "permanent" servers specifically:** VM Controller and
Storage Controller are exactly where servers get configured. Any
deployment that treats `DATA_DIR` as the one directory to persist (a
Docker volume mount, a backup job, etc.) — which is the documented,
sensible thing to do, since `data/` is what `.gitignore` tells you matters
— would silently not include these four `.db` files, because they were
never actually inside it.

**Fix:** all four now take `data_dir` (matching the working modules) and
`app.py` passes `DATA_DIR` to each. Each module also does a one-time
migration on startup: if it finds its old repo-root `.db` file and no
file yet at the correct `data/` location, it moves it into place — so
upgrading doesn't itself wipe out servers you already configured. Verified
by simulating a legacy install (server saved at the old path), starting
the fixed app, and confirming the server was present, intact, at the new
path afterward.

## Bug 2: the self-update function could silently discard data

This is likely the actual mechanism behind servers disappearing after an
update specifically. The sidebar's "FleetPilot Update" (`/fleetpilot_update`
→ `_run_fp_update_bg()` in `app.py`) does, roughly: discard local changes →
stash any untracked files that would conflict with the incoming `git pull`
→ pull → restart.

The stash step existed; **the restore never did.** There was no
`git stash pop` anywhere in the function. Anything swept into that stash
(pre-fix: potentially the misplaced server `.db` files from Bug 1; more
generally, any locally-added untracked file) was stashed and then simply
abandoned — recoverable only by someone going into the repo by hand and
running `git stash list` / `git stash pop`, which nothing prompted anyone
to do.

**Fix:** the function now tracks whether it actually created a stash
(`git stash` prints "No local changes to save" when there's nothing to
do — that case is correctly *not* treated as a stash), and always
attempts `git stash pop` afterward, whether the pull succeeded or failed.
If the pop itself can't apply cleanly (a real merge conflict), that's
logged explicitly with recovery instructions instead of failing silently.

Verified directly: staged an untracked file, ran the exact
`git add -A && git stash` → `git stash pop` sequence the fix performs,
confirmed the file's content survived byte-for-byte. Also confirmed the
"nothing to stash" path is detected correctly and doesn't attempt a
no-op pop.

### Also fixed while in this code path

- **`version_manager.py`**'s *other*, older self-update implementation
  (`perform_self_update()`, reachable via `/dashboard_version/update` —
  not the one linked from the sidebar, but still a live route) had the
  same root issue in a different shape: it backed up/restored a hardcoded
  filename list (`hosts.json`, `users.db`, `disks.db`, `operations.db`,
  `smart.db`...) at paths relative to the repo root. Several of those
  filenames don't match anything the app actually creates anymore
  (it's `disktool_core.db`, not `disks.db`; `smart_manager.db`, not
  `smart.db`) — drift from an earlier version of the codebase. Rewrote it
  to back up/restore the entire `DATA_DIR` as a unit instead of an
  enumerated list that can silently go stale again.

- **`version_manager.py`**'s `version_check.json` (tracks update-available
  / dismissed-notification state) was read/written as a bare relative
  filename, resolved against the process's current working directory —
  fine run by hand from the repo root, fragile under systemd/Docker where
  the working directory may differ. Now resolved against `DATA_DIR`, with
  a migration for any existing file.

- **`app.py`**'s `.env` loading was hardcoded to `/opt/fleetpilot/.env`
  only. The documented setup (`README.md`: `cp .env.example .env`) puts it
  in the repo root, which was never actually checked. Now checks the repo
  root first, then falls back to `/opt/fleetpilot/.env` so existing
  deployments relying on that path keep working.

## `.gitignore`

Added `hosts.json`, `history.json`, `update_settings.json` (`version_check.json`
was already ignored). These three are still **committed** in the repo today
containing stale/dummy data (including an XSS-test string in one host's
description field) and are no longer read or written by the app at all —
everything real lives under `data/`. Gitignoring them stops them from ever
being re-added or swept into a stash by accident, but doesn't itself untrack
the already-committed copies. To finish that cleanup, run once:

```bash
git rm --cached hosts.json history.json update_settings.json
git commit -m "Stop tracking legacy root-level data files (superseded by data/)"
```

## Testing

Ran end-to-end against a live instance for: a completely fresh install
(zero pre-existing data), a simulated pre-fix install (server configured
at the old, wrong path — confirmed migrated intact), and a smoke test of
every page touched by the changed modules (`/vm`, `/storage`, `/smart`,
`/hosts`, `/fleetpilot_update`, `/dashboard`, `/fans`, `/index`) — all
200, no server errors. The stash/pop mechanism was verified directly
against real `git` commands in an isolated throwaway clone (not the
delivered one) since exercising it via a real upstream divergence isn't
possible from here.
