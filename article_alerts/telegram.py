"""Outbound-only Telegram notifications; no webhook or always-on bot process."""

import json
import time
from typing import Callable

from .domain import AlertError, DeliveryError
from .http import HttpClient, HttpError, NetworkError


class TelegramNotifier:
    def __init__(self, http: HttpClient, token: str, chat_id: str,
                 sleep: Callable[[float], None] = time.sleep):
        self.http, self.token, self.chat_id, self.sleep = http, token, chat_id, sleep
        self._sent_before = False

    def _call(self, method: str, payload: dict):
        try:
            result = self.http.request("POST", f"https://api.telegram.org/bot{self.token}/{method}",
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload, ensure_ascii=False).encode()).json()
        except (HttpError, NetworkError) as exc:
            status = f" HTTP {exc.status}." if isinstance(exc, HttpError) else " Network error."
            raise DeliveryError("Telegram delivery failed." + status + " The queued item remains for retry.") from None
        except AlertError:
            raise DeliveryError("Telegram returned invalid JSON; delivery was not checkpointed.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DeliveryError("Telegram rejected the request; verify the bot, chat and permissions.")
        return result.get("result")

    def send(self, text: str) -> None:
        if not text or len(text.encode("utf-16-le")) // 2 > 4096:
            raise DeliveryError("Notification exceeds Telegram's message length limit.")
        if self._sent_before:
            # Pace before the next send so a successful send can be checkpointed immediately.
            self.sleep(1.1)
        result = self._call("sendMessage", {
            "chat_id": self.chat_id, "text": text,
            "link_preview_options": {"is_disabled": True},
        })
        if not isinstance(result, dict) or type(result.get("message_id")) is not int:
            raise DeliveryError("Telegram did not acknowledge a message ID; delivery was not checkpointed.")
        self._sent_before = True


def find_private_chat(http: HttpClient, token: str) -> str:
    notifier = TelegramNotifier(http, token, "")
    updates = notifier._call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    chats = set()
    if isinstance(updates, list):
        for update in updates:
            chat = update.get("message", {}).get("chat", {})
            if chat.get("type") == "private" and type(chat.get("id")) is int:
                chats.add(str(chat["id"]))
    if len(chats) != 1:
        raise DeliveryError("Send /start privately to your new bot first. Exactly one private chat must be present.")
    return chats.pop()
