# App-wide styling pass: one consistent "productive environment" theme

Scope decision up front: individually redesigning the layout of all ~25
distinct pages isn't realistic in one pass — and isn't actually the
highest-leverage thing to do. Instead this fixes the shared foundation
every page already inherits through `base.html` + `style.css`, so the
whole app reads as one consistent, professional tool instead of a
patchwork of an older design pass and the newer one (from the home
dashboard redesign). Two real, concrete bugs turned up along the way that
were actively breaking the look of large parts of the app — fixing those
alone is a big share of the visual improvement here.

## 1. 27 CSS variables were referenced but never defined, anywhere

Checked every `var(--x)` used across all templates against every `--x`
actually defined in `style.css`. 21 template files — spanning CheckMK,
Fan Commander, System Monitor, SMART, Storage, VM Controller, Hosts,
Plugin Manager, Server Update — reference variables like `var(--danger)`,
`var(--success)`, `var(--warning)`, `var(--primary)`, `var(--bg-secondary)`,
`var(--border-color)` that don't exist in the stylesheet. An undefined
CSS variable with no fallback doesn't error — it just silently resolves
to nothing, so all the color-coding built on top of it (SMART disk temps,
VM/Storage online status, alert counts, form field emphasis) was quietly
not working.

Fixed by aliasing all 27 to the design tokens that already exist (`--danger`
→ `--accent-red`, `--primary` → `--accent-blue`, etc.), in both the dark
and light theme blocks so the theme toggle keeps working. Zero template
changes needed — this alone fixes color-coding across ~20 pages at once.

## 2. Plain `<table class="table">` had no styling at all

Found by counting: `.table` (with modifiers like `table-hover`, `table-sm`,
`table-striped`) is used ~50+ times across the app, but the stylesheet
only ever styled `.table-dark` specifically — the base `.table` class had
zero rules. No Bootstrap framework is actually loaded (just its class
naming convention, backed by custom CSS), so any table using just `.table`
rendered with no padding, no borders, no header treatment — flat,
unstyled HTML.

Added real base styling for `.table` (padding, borders, uppercase muted
headers, hover/striped/bordered/sm variants, and the `.table-success` /
`.table-danger` / `.table-warning` row-tint classes several pages use)
matching the same visual language as the dashboard's `.fleet-table`.
Also filled in the same way for checkboxes/switches (`.form-check`,
`.form-switch` — 45+ uses), progress bars (`.progress` / `.progress-bar`
— 8 uses), `.list-group`, and `.nav-tabs`, which had the identical
"class name exists, no styling backs it" gap.

## 3. Hardware Overview used an unrelated color palette

`templates/hw_overview/index.html` and `detail.html` each define their
own `:root` block with hardcoded colors — a GitHub-dark-inspired palette
(`#0d1117` background, `#58a6ff` blue, etc.) completely disconnected from
the rest of FleetPilot's actual navy/blue theme (`#070c14` background,
`#3b82f6` blue). The values were self-consistent within that one page,
just visibly a different product from everything around it — jarring
mid-navigation.

Remapped every value to FleetPilot's real theme tokens (only the
variable *values* changed, not the ~400 lines of markup referencing
them by name, so this was a low-risk fix). Kept the NVIDIA green and AMD
red exactly as-is — those exist for vendor brand recognition, not as
decorative theme colors, so they shouldn't be normalized away.

## Testing

Ran a full page crawl after the change — every major page (`/index`,
`/hosts`, `/scanner`, `/dashboard`, `/hw_overview`, `/smart`, `/disks`,
`/fans`, `/vm`, `/storage`, `/backup`, `/checkmk`, `/monitor`,
`/fleetpilot_update`, `/update_settings`, `/email_settings`, `/plugins`,
`/users`, `/users/profile`, `/commander`) returns 200 with no server
errors. Confirmed the new base `.table` rule doesn't collide with the
dashboard's `.fleet-table`/`.table-v4` classes (verified they never carry
the bare `.table` class). CSS brace-balance checked (812/812).

## What this doesn't cover

This is a foundation-level fix, not a page-by-page redesign — pages that
had genuinely awkward layouts (not just missing color/table styling)
still have those layouts; they just now render in the app's actual
color system instead of partially-broken or mismatched ones. If there
are one or two specific pages you use constantly and want a fuller,
dashboard-level treatment (custom layout, not just theme), point me at
them and I'll go deeper on those specifically rather than spreading
effort thin across all of them.
