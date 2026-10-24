# Sin Chew → Telegram article alerts

A personal news monitor that runs on GitHub's servers and sends new article titles
and links to Telegram. Your computer can stay switched off after setup.

**Status:** implemented and tested locally with synthetic fixtures. Live requests
to Sin Chew returned HTTP 403 in the development environment. This does not prove
that GitHub's runners are blocked, but live payload parsing and Telegram delivery
must be verified there before enabling the schedule. This project is not running yet.

The initial source is Sin Chew's **诈骗** tag, based on the supplied browser capture:
`https://www.sinchew.com.my/tag/诈骗`, tag ID `1495`.

## What you get

- Five-minute scheduled checks, offset from the busiest minute of each hour.
- A durable pending queue and delivery history on a separate `monitor-state` branch.
- Quiet initialization: existing articles are recorded without flooding your phone.
- Individual message checkpoints, catch-up pagination, bounded retries and rate-limit handling.
- Daily health messages, throttled outage alerts and a recovery message after an outage.
- Explicit failures for blocked pages, changed markup, corrupt state or excessive backlog.
- A small, standard-library-only Python 3.12+ implementation; no pip installation required.
- Automated tests on Python 3.12 and 3.13; pinned GitHub Actions with Dependabot updates.

## Cost and service limits

Use **GitHub Free**, a **public repository** and **standard GitHub-hosted runners**
for the free configuration. Private repositories have a free quota and possible
overage charges. Telegram Premium, a paid RSS service and a rented server are not needed.

GitHub schedules are best effort: they may be delayed or dropped under load. A
five-minute schedule is not a five-minute delivery guarantee. Public repository
schedules can be disabled after 60 days without activity; check the Actions page
if the daily heartbeat disappears. GitHub's usage and acceptable-use limits still apply.

References: [GitHub billing](https://docs.github.com/en/actions/concepts/billing-and-usage),
[scheduled workflow limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[Telegram bot limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).

## Setup

### 1. Create the repository

Create an empty public GitHub repository, for example `sinchew-telegram-alerts`.
Upload **all the project files at the repository root**, including the hidden
`.github` directory. Do not upload the ZIP as a single file, the `upload` folder,
the original browser capture, cookies or credentials.

If using git from this extracted directory:

```bash
git init -b main
git add .
git commit -m "Add reliable Sin Chew Telegram article monitor"
git remote add origin https://github.com/YOUR_USERNAME/sinchew-telegram-alerts.git
git push -u origin main
```

The root must contain `article_alerts/`, `monitor.toml` and `.github/workflows/`.
The included `Tests` workflow should pass. Scheduled checks remain disabled until step 6.

### 2. Create your Telegram bot

1. Open the verified **@BotFather** account in Telegram and send `/newbot`.
2. Follow its instructions and save the bot token privately.
3. Open your new bot's private chat and send `/start`.

This is an outbound notifier, so it needs no webhook and no continuously running bot server.

### 3. Get your chat ID

With Python 3.12+ installed temporarily on your computer, run:

```bash
python -m article_alerts get-chat-id
```

Paste the token into the hidden prompt. The command uses Telegram's official
`getUpdates` API and prints the private chat ID. It does not print the token.
Only one private chat should have contacted the new bot; this avoids guessing a recipient.
If no update is available, send another message privately and retry. A bot that
already uses a webhook must have that webhook removed or use a separate new bot.

For phone-only setup, send a message to the bot, then privately open
`https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your own browser. Read
`result → message → chat → id`. This URL contains your credential: keep it out of
screenshots, public links and source code, and clear it from shared browser history.

### 4. Add two secrets

In the repository, open **Settings → Secrets and variables → Actions → Secrets**.
Add these repository secrets:

| Secret | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | The token from BotFather |
| `TELEGRAM_CHAT_ID` | Your numeric private chat ID |

GitHub supplies its own short-lived `GITHUB_TOKEN`; no personal access token is required.
The workflow requests `contents: write` to checkpoint state. Organization policies or
branch rules must permit writes to `monitor-state`.

### 5. Verify, then initialize

Open **Actions → Article monitor → Run workflow** on the default branch:

1. Select **diagnose**. It must find articles and show sample titles/links from the
   intended tag. This step needs no Telegram credentials and does not write state.
2. Select **test-telegram**. Confirm that your phone receives the test message.
3. Select **initialize**. It saves the current baseline and sends a ready message.

If `diagnose` fails or sample articles do not match the tag, **stop before activation**.
See [Troubleshooting](docs/OPERATIONS.md). The capture confirms the page-2/page-3 request
format; page-1 behavior and the live response shape have not been validated here.
Do not add session cookies to make a blocked source appear healthy.

If initialization saves state but its ready message fails, fix Telegram and run
`test-telegram`, then `check`. Do not delete state or repeatedly initialize it.

### 6. Activate the schedule

Under **Settings → Secrets and variables → Actions → Variables**, add:

| Repository variable | Value |
| --- | --- |
| `MONITOR_ENABLED` | `true` |

Run **check** manually once, then confirm scheduled runs appear under Actions.
Enable GitHub Actions failure emails in your personal GitHub notification settings.
Keep Telegram phone notifications enabled and the bot conversation unmuted.

You can now switch off your computer. To pause, set `MONITOR_ENABLED` to `false`.
Resume by setting it to `true`; the saved queue and history remain intact.

## Settings

Edit `monitor.toml` for non-secret behavior:

| Setting | Default | Meaning |
| --- | --- | --- |
| `tag_id` | `1495` | Sin Chew tag to monitor |
| `label` | `Sin Chew · 诈骗` | Notification prefix |
| `max_pages` | `20` | Catch-up safety limit; failure preserves existing state |
| `baseline_pages` | `2` | Pages quietly recorded on first initialization |
| `max_deliveries` | `50` | Maximum article messages per run; leftovers remain queued |
| `heartbeat_hours` | `24` | Health-message interval; `0` disables it |
| `state_branch` | `monitor-state` | Durable state; keep separate from the default branch |

To change polling frequency, edit the cron in `.github/workflows/monitor.yml`.
GitHub's shortest scheduled interval is five minutes. Keep it reasonable for the source.
Do not point an existing state branch at a different tag: use a separate branch and
initialize it deliberately. Scheduled cron runs on the repository's default branch.

## Delivery guarantees and practical limits

- A discovered article is queued durably **before** delivery and marked delivered
  only after Telegram returns a message ID and the checkpoint is saved.
- A crash after Telegram accepts a message but before its checkpoint may cause a
  duplicate. Telegram provides no send-message idempotency key. This is retry-oriented
  delivery, **not exactly-once delivery**; a duplicate is preferable to silently losing an alert.
- Only articles that appear on the monitored tag listing can be discovered. An
  article removed between polls, retroactively tagged far behind the scanned frontier,
  or never included in the tag cannot be guaranteed. A long outage may exceed the page limit.
- The monitor checks public title/link listings, not paid article bodies. Notification
  delivery does not grant access to subscription content.
- The daily health message confirms successful source access, not merely that the script started.
  A disabled workflow or a complete GitHub outage needs a separate observer; this project
  cannot alert about its own total absence. Notice missing heartbeats and check Actions.
- Public repository code, run logs and state are public. State contains public article
  titles/URLs, IDs and timestamps; credentials and chat IDs are not saved in it.

## Development and maintainability

Run from the project root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q article_alerts tests
python -m article_alerts diagnose
```

Use `--local-state local-state.json` with `initialize` or `check` only for local
development. That file is ignored by git; the production workflow always uses GitHub state.
Concurrent local runs against the same local file are unsupported; production runs
are serialized and protected by GitHub compare-and-swap checks.

See [architecture and SOLID mapping](docs/ARCHITECTURE.md),
[operations and recovery](docs/OPERATIONS.md) and [validation evidence](docs/VALIDATION.md).
