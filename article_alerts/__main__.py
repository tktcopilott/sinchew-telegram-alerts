"""Composition root and CLI. No imports trigger network requests or side effects."""

import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import re
import sys

from .config import Config, require_secret
from .domain import AlertError, ConfigurationError
from .http import RetryingHttpClient, UrlLibHttpClient
from .service import Monitor
from .source import SinChewTagSource
from .state import FileStateStore, GitHubStateStore
from .telegram import TelegramNotifier, find_private_chat


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sin Chew article alerts → Telegram")
    parser.add_argument("command", choices=["initialize", "check", "diagnose", "test-telegram", "get-chat-id"])
    parser.add_argument("--config", type=Path, default=Path("monitor.toml"))
    parser.add_argument("--local-state", type=Path, help="Development only; GitHub uses durable repository state.")
    args = parser.parse_args(argv)
    monitor = None
    try:
        http = RetryingHttpClient(UrlLibHttpClient())
        if args.command == "get-chat-id":
            token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass.getpass("Bot token (hidden): ")
            token = require_secret({"TELEGRAM_BOT_TOKEN": token}, "TELEGRAM_BOT_TOKEN")
            print("TELEGRAM_CHAT_ID=" + find_private_chat(http, token))
            return 0
        config = Config.load(args.config)
        source = SinChewTagSource(http, tag_id=config.tag_id, max_pages=config.max_pages,
                                 baseline_pages=config.baseline_pages)
        if args.command == "diagnose":
            articles = source.baseline()
            print(json.dumps({"status": "source-readable", "articles_found": len(articles),
                              "source_id": source.identity, "cookies_used": False,
                              "samples": [asdict(article) for article in articles[:3]]}, ensure_ascii=False))
            return 0
        notifier = TelegramNotifier(http, require_secret(os.environ, "TELEGRAM_BOT_TOKEN"),
                                    require_secret(os.environ, "TELEGRAM_CHAT_ID"))
        if args.command == "test-telegram":
            notifier.send("Article alerts: Telegram delivery test succeeded.")
            print('{"status": "telegram-test-sent"}')
            return 0
        if args.local_state:
            store = FileStateStore(args.local_state)
        else:
            repository = os.environ.get("GITHUB_REPOSITORY", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                raise ConfigurationError("Set GITHUB_REPOSITORY=owner/repository or use --local-state for development.")
            default_branch = os.environ.get("DEFAULT_BRANCH", "main")
            if config.state_branch == default_branch:
                raise ConfigurationError("State branch must differ from the repository's default branch.")
            store = GitHubStateStore(http, require_secret(os.environ, "GITHUB_TOKEN"), repository,
                                     branch=config.state_branch, default_branch=default_branch)
        monitor = Monitor(source, store, notifier, label=config.label,
                          max_deliveries=config.max_deliveries, heartbeat_hours=config.heartbeat_hours)
        result = monitor.initialize() if args.command == "initialize" else monitor.check()
        print(json.dumps(asdict(result)))
        return 0
    except AlertError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if monitor and args.command == "check":
            try:
                monitor.report_failure(exc)
            except Exception:
                print("Failure notification/checkpoint also failed; consult this Actions run.", file=sys.stderr)
        return 1
    except Exception:
        # Raw tracebacks from HTTP libraries can contain token-bearing URLs.
        print("ERROR: Unexpected internal failure. Run the test suite and inspect configuration; credentials were not logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
