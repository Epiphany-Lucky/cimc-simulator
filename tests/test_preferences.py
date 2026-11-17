"""Theme settings persist across processes and localhost origins."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from preferences import Preferences, THEME_COLORS


class PreferencesTests(unittest.TestCase):
    def test_defaults_do_not_create_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Preferences(directory)
            self.assertEqual(settings.read(),{'themeColor':'blue'})
            self.assertFalse(settings.path.exists())

    def test_every_theme_survives_new_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            for color in THEME_COLORS:
                Preferences(directory).update({'themeColor':color})
                self.assertEqual(Preferences(directory).read(),{'themeColor':color})
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_invalid_disk_settings_fall_back_without_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Preferences(directory)
            for data in ('{broken','[]','null','{"themeColor":"unknown"}'):
                settings.path.write_text(data,encoding='utf-8')
                self.assertEqual(settings.read(),{'themeColor':'blue'})
                self.assertEqual(settings.path.read_text(encoding='utf-8'),data)

    def test_invalid_update_keeps_existing_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Preferences(directory)
            settings.update({'themeColor':'purple'})
            for value in (None,[],{}, {'themeColor':'unknown'}, {'themeColor':None}):
                with self.assertRaises(ValueError):settings.update(value)
                self.assertEqual(settings.read(),{'themeColor':'purple'})

    def test_atomic_replace_failure_keeps_previous_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Preferences(directory)
            settings.update({'themeColor':'green'})
            with patch('preferences.os.replace',side_effect=OSError('injected replacement failure')):
                with self.assertRaises(OSError):settings.update({'themeColor':'rose'})
            self.assertEqual(json.loads(settings.path.read_text(encoding='utf-8')),{'themeColor':'green'})
            self.assertEqual(len(list(Path(directory).iterdir())),1)


if __name__=='__main__':unittest.main()
