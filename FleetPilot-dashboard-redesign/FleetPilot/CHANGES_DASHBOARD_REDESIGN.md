# Home dashboard redesign — what changed and why

Goal: make the `/index` (Home) dashboard match the target screenshot
(glowing stat cards with sparklines, a full Fleet Overview table, and a
Fan & Cooling + SMART Disk Health row). Your `main` branch already had
most of the "v4" CSS component system built (`stat-card-v4`, `fleet-table`,
`status-pill`, `temp-chip-v4`) — this mostly wires it up rather than
building it from scratch.

## Files changed

- **`requirements.txt`** — `smartmontools` was listed as a pip package.
  It's a system package (provides the `smartctl` CLI), so this broke
  `pip install -r requirements.txt` on every fresh clone. Removed it,
  added a comment pointing to `apt`/`dnf`, and added `psutil` (already an
  implicit dependency of `system_monitor.py`; now a real one).

- **`static/style.css`**
  - `#dashboardContainer` is now an actual 2-column grid. Before, every
    widget stacked full-width regardless of its `"size"` field — `"half"`
    widgets never actually sat side-by-side.
  - Fleet table usage bars: green/amber/red → blue/blue/red, matching the
    target design (blue for normal usage, red only at the critical tier).
  - New rules for inline SVG sidebar icons, temp-chip icons, and a
    `.health-bar` / `.control-pill` pair for the new widgets.

- **`templates/base.html`**
  - Replaced every emoji glyph in the sidebar, mobile nav, and theme
    toggle with a small set of inline SVG line icons (defined once near
    the top via `{% set ICON_X %}...{% endset %}`, reused with
    `{{ ICON_X|safe }}`).
  - Split the "Betrieb" group (which mixed Backup + CheckMK + System
    Monitor under one German label) into separate **Backup** and
    **Monitoring** sections, and renamed "Virtualisierung" → "Virtualization".

- **`templates/index.html`**
  - Stat cards now show Total Servers / Online / Offline / Updates
    Available / Warnings (previously: Managed Hosts / Disk Drives /
    Updates Run / Active Users / Unique Tags), each with a real sparkline
    and an honest up/down/flat trend indicator.
  - New **Fan & Cooling** widget: local CPU/GPU/NVMe temps + fan RPMs via
    `psutil` (GPU via a best-effort `nvidia-smi` probe). Shows a clean
    empty state on machines with no exposed sensors (most VMs/containers)
    instead of ever faking a reading.
  - **SMART widget** upgraded from a 4-number summary to a full per-disk
    table (device, model, capacity, health bar, temp, status), reusing
    `smart_manager.get_all_disks()`. Also fixed: the old summary
    referenced `smart_summary.total_disks` / `.healthy` / `.warning`,
    none of which exist in `get_health_summary()`'s real return shape
    (`{total, counts: {GOOD, WARNING, CRITICAL, FAILED, UNKNOWN}, active_alerts}`)
    — so those numbers never actually rendered.
  - Reordered/regrouped widgets so Fan & Cooling and SMART pair up as a
    row right under Fleet Overview (see `user_management.py` below).

- **`user_management.py`** — registered the new `fan_cooling` widget in
  `DEFAULT_DASHBOARD_LAYOUT` and reordered entries so it sits next to
  `smart_summary`. Existing per-user saved layouts pick up the new widget
  automatically (the existing merge logic in `get_dashboard_layout()`
  already handles adding new default widgets).

- **`app.py`** (`index()` view) — computes the real numbers the new stat
  cards need:
  - `online_count` / `offline_count`: reuses the existing `is_online()`
    SSH probe, looped over all hosts (same check the Update Dashboard uses).
  - `updates_needed_count`: hosts with no `last_update`, or one older than
    30 days. There's no per-host "pending package count" anywhere in this
    app today (updates are applied on demand, not dry-run checked), so
    this is the most honest signal already on hand rather than a new
    SSH-based check-everything-on-every-page-load feature.
  - `warnings_count`: SMART disks in `WARNING` state.
  - `local_sensors` / `stat_trends`: see `home_widgets.py`.

## New file

- **`home_widgets.py`** — small, self-contained module with two things:
  1. `get_local_sensors()` — reads local temps/fans via `psutil`
     (+ `nvidia-smi` best-effort for GPU). Never fabricates a value; a
     chip/row only appears when a real sensor reading was found.
  2. `get_trends(...)` — records a daily snapshot of the 5 stat-card
     values to `data/dashboard_stats_history.json` (capped at 30 entries)
     and computes each card's trend/sparkline from real history. On a
     fresh install there's no history yet, so every card starts flat
     ("— 0%") until a few days of real snapshots accumulate — which is
     also what two of the cards look like in the target screenshot.

## Known pre-existing issue (not touched, flagged for you)

`smart_manager.classify_health()` returns `"GOOD"` by default whenever it
*can't* get real SMART data (e.g. `smartctl` missing, or a device that
returns no output), rather than `"UNKNOWN"`. Worth a look separately —
didn't want to change disk-health business logic as a drive-by inside a
UI redesign PR.

## Testing

Ran the app locally end-to-end (Flask dev server) through both a
populated-hosts scenario and a completely fresh install with zero
configured hosts — both render cleanly with no server errors. The Fleet
Overview table's live CPU/RAM/uptime values come from your existing
`/api/host_metrics` SSH polling, unchanged; only its coloring and the
container's grid layout changed.
