import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from article_alerts.__main__ import main
from article_alerts.config import Config, require_secret
from article_alerts.domain import ConfigurationError


class ConfigCliTests(unittest.TestCase):
    def test_shipped_config_validates(self):
        self.assertEqual(Config.load(Path(__file__).parent.parent / "monitor.toml").tag_id, 1495)

    def test_invalid_settings_are_actionable(self):
        for content in ('[monitor]\nmax_pages=0', '[monitor]\nunknown=1', '[monitor]\ntag_id=true',
                        '[monitor]\nstate_branch="../../main"', '[monitor]\nbaseline_pages=30\nmax_pages=20'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ConfigurationError):
                    Config.load(path)

    def test_secret_validation_does_not_echo_values(self):
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN"):
            with self.assertRaises(ConfigurationError) as caught:
                require_secret({name: ""}, name)
            self.assertIn(name, str(caught.exception))

    def test_cli_missing_secret_fails_without_network_or_traceback(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(output):
            code = main(["test-telegram", "--config", str(Path(__file__).parent.parent / "monitor.toml")])
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
