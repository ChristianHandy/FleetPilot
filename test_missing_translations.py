# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The translation report checks literal calls and signals gaps to CI."""
import pytest

from scripts import missing_translations


@pytest.fixture
def translation_project(tmp_path, monkeypatch):
    templates = tmp_path / 'templates'
    templates.mkdir()
    (templates / 'index.html').write_text(
        '''{{ _('Ready') }} {{ _("Missing") }} {{ _('Ready') }} {{ _("It's ready") }}''',
        encoding='utf-8',
    )
    (tmp_path / 'i18n.py').write_text(
        '''SUPPORTED_LANGUAGES = {'en': 'English', 'fr': 'Français', 'de': 'Deutsch'}
TRANSLATIONS = {'fr': {'Ready': 'Prêt', "It's ready": 'Prêt'},
                'de': {'Ready': 'Bereit', 'Missing': 'Fehlt', "It's ready": 'Bereit'}}
''', encoding='utf-8',
    )
    monkeypatch.setattr(missing_translations, 'ROOT', tmp_path)
    return templates


def test_reports_missing_strings_and_counts(translation_project, capsys):
    assert missing_translations.main([]) == 1
    output = capsys.readouterr().out
    assert "  'Missing'" in output
    assert "  'Ready'" not in output
    assert 'fr: 1' in output
    assert 'de: 0' in output
    assert 'en (' not in output


def test_lang_filter_and_complete_language(translation_project, capsys):
    assert missing_translations.main(['--lang', 'de']) == 0
    output = capsys.readouterr().out
    assert 'de: 0' in output
    assert 'fr' not in output


def test_unknown_language_is_an_argument_error(translation_project):
    with pytest.raises(SystemExit) as error:
        missing_translations.main(['--lang', 'xx'])
    assert error.value.code == 2


def test_extracts_escaped_quotes_and_ignores_dynamic_calls(translation_project):
    (translation_project / 'escaped.html').write_text(
        r'''{{ _('It\'s ready') }} {{ _("Say \"hello\"") }} {{ _(dynamic) }}''',
        encoding='utf-8',
    )
    assert missing_translations.template_strings(translation_project) == {
        'Ready', 'Missing', "It's ready", 'Say "hello"',
    }
