# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""List untranslated template strings without importing the application."""
import argparse
import ast
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_CALL = re.compile(r'''\b_\(\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")\s*\)''')


def template_strings(directory):
    """Collect literal translation calls, including escaped quotes, once each."""
    strings = set()
    for path in sorted(directory.glob('*.html')):
        for match in TRANSLATION_CALL.finditer(path.read_text(encoding='utf-8')):
            strings.add(ast.literal_eval(match.group(1)))
    return strings


def main(argv=None):
    i18n = runpy.run_path(str(ROOT / 'i18n.py'))
    languages = {code: name for code, name in i18n['SUPPORTED_LANGUAGES'].items() if code != 'en'}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lang', choices=sorted(languages), help='check only this language')
    args = parser.parse_args(argv)
    if args.lang:
        languages = {args.lang: languages[args.lang]}

    strings = template_strings(ROOT / 'templates')
    counts = {}
    for code, name in languages.items():
        table = i18n['TRANSLATIONS'].get(code, {})
        missing = sorted(text for text in strings if not table.get(text))
        counts[code] = len(missing)
        print(f'{code} ({name}):')
        for text in missing:
            print(f'  {text!r}')

    print('\nMissing translations:')
    for code, count in counts.items():
        print(f'{code}: {count}')
    return int(any(counts.values()))


if __name__ == '__main__':
    raise SystemExit(main())
