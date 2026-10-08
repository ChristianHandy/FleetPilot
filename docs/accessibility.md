# Accessibility

FleetPilot aims to meet WCAG 2.2 level AA. Every page in the web interface is checked with the
[axe](https://github.com/dequelabs/axe-core) rules for WCAG 2.0–2.2 A/AA plus best practices, and
`test_accessibility.py` guards the basics on every test run.

## Settings (Account → Accessibility)

Each user can choose, and the choice follows their account:

| Setting | What it does |
|---|---|
| Text size | Normal, large or extra large; the whole layout scales |
| Easy-to-read font | Atkinson Hyperlegible, loaded only when chosen |
| More space | Line, letter and word spacing per WCAG 1.4.12 |
| Easy language | Simple menu names and a short "In simple words" explanation on each page (English and German Leichte Sprache) |
| High contrast | Black/white surfaces, stronger text and borders, bright focus outline; works in light and dark theme |
| Underline links | Every link underlined, not only links in running text |
| Reduce motion | No animations; FleetPilot also follows the operating system setting |

The sign-in page uses the settings last saved in that browser.

## Always on

- **Skip to content** link as the first Tab stop; one `h1` per page; navigation, main and status landmarks.
- Sidebar groups are buttons that announce whether they are open; the mobile menu closes with Escape.
- Every form field has a label; icon-only buttons have names that say what they act on (for example "Delete web-01").
- Messages that appear after an action are read out through a polite live region.
- Charts are described as images; the same numbers are shown as text on the page.
- Home page cards can be reordered with **Move up / Move down** buttons instead of drag and drop.
- Colors meet 4.5:1 contrast for text in both themes; links in running text are underlined.
- The public status page's auto-refresh can be paused.

## Known gaps

- Testing so far is automated (axe) plus keyboard-only checks. It has not yet been tested with
  NVDA, JAWS or VoiceOver by a screen-reader user; reports are welcome.
- Easy-language texts exist for English and German. French, Spanish and Dutch fall back to English.
- Plugin pages are written by plugin authors and may not follow these rules.
