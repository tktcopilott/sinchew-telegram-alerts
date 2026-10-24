import json
import unittest

from article_alerts.domain import DeliveryError
from article_alerts.http import HttpError, NetworkError
from article_alerts.telegram import TelegramNotifier, find_private_chat
from tests.helpers import ScriptedHttp, response


class TelegramTests(unittest.TestCase):
    def test_plain_text_message_no_markup_injection_and_rate_pacing(self):
        http = ScriptedHttp(response({"ok": True, "result": {"message_id": 5}}),
                            response({"ok": True, "result": {"message_id": 6}}))
        waits = []
        notifier = TelegramNotifier(http, "secret-token", "123", sleep=waits.append)
        notifier.send("<b>Chinese 中文</b> & link")
        payload = json.loads(http.calls[0][3])
        self.assertNotIn("parse_mode", payload)
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(waits, [])
        notifier.send("Second message")
        self.assertEqual(waits, [1.1])

    def test_ok_false_and_invalid_acknowledgment_are_not_success(self):
        for value in ({"ok": False}, {"ok": True, "result": {}}, []):
            notifier = TelegramNotifier(ScriptedHttp(response(value)), "token", "123", sleep=lambda _: None)
            with self.subTest(value=value), self.assertRaises(DeliveryError):
                notifier.send("message")

    def test_network_and_api_errors_never_leak_token(self):
        for error in (NetworkError("https://api.telegram.org/botSECRET"), HttpError(401, b"SECRET")):
            notifier = TelegramNotifier(ScriptedHttp(error), "SECRET", "123", sleep=lambda _: None)
            with self.assertRaises(DeliveryError) as caught:
                notifier.send("message")
            self.assertNotIn("SECRET", str(caught.exception))

    def test_utf16_length_limit_includes_surrogate_pairs(self):
        notifier = TelegramNotifier(ScriptedHttp(), "token", "123")
        with self.assertRaises(DeliveryError):
            notifier.send("😀" * 2049)

    def test_chat_id_helper_only_returns_unambiguous_private_chat(self):
        updates = {"ok": True, "result": [{"message": {"chat": {"type": "private", "id": 123}}}]}
        self.assertEqual(find_private_chat(ScriptedHttp(response(updates)), "token"), "123")
        updates["result"].append({"message": {"chat": {"type": "private", "id": 456}}})
        with self.assertRaises(DeliveryError):
            find_private_chat(ScriptedHttp(response(updates)), "token")
