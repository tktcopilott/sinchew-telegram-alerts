# Operations and recovery

## Routine operation

Check that Actions runs succeed and your Telegram daily heartbeat arrives. A run's
JSON summary reports newly discovered, delivered and pending article counts. Ordinary
unchanged polls create no state commits; health metadata is checkpointed periodically.

Set repository variable `MONITOR_ENABLED=false` to pause recurring work. Manual
diagnose/test/check operations remain available. This preserves all state.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Sin Chew HTTP 403 | Run `diagnose` on GitHub. If still blocked, leave the schedule paused and obtain a permitted public feed/API or a representative public response. Do not copy login cookies or conceal the failure. |
| No article links / changed JSON | The source contract may have changed. Save a sanitized public response as a test fixture, update only the source adapter, and rerun tests and `diagnose`. |
| Articles in diagnostic samples are unrelated | Do not initialize. Confirm the tag ID and the tag-list endpoint's page-1 behavior. |
| No saved state | Run `initialize` once manually, after source and Telegram tests pass. |
| Already initialized | Use `check`; never reset working history just to rerun setup. |
| Telegram HTTP 400/401/403 | Check the bot token and numeric chat ID, send `/start`, and ensure the bot is not blocked. Run `test-telegram`. |
| Telegram test succeeds but no phone banner | Unmute the bot chat; enable Telegram notifications in the app and phone OS; check Focus/Do Not Disturb settings. |
| `get-chat-id` has no result | Send a fresh private message; updates may expire or be consumed by another client. Use a dedicated bot without a webhook. |
| Backlog exceeds `max_pages` | Pause, raise the limit up to the supported maximum, and run `check`. The failed scan has not marked undiscovered articles as delivered. |
| Pending queue remains | Each run delivers up to `max_deliveries`; leave it running or invoke `check` again after the previous run finishes. |
| GitHub state write rejected | Ensure Actions may write repository contents and state branch rules allow the workflow token to commit. Do not replace the short-lived token with a broad personal token as the first fix. |
| Concurrent state change | Stop other writers, inspect the latest state, and rerun. Never remove the compare-and-swap guard. |
| Corrupt/incompatible state | Pause and restore a known-good state revision. Do not treat corruption as a fresh installation. |
| Source identity mismatch | Restore the old tag configuration, or deliberately choose a different state branch and initialize a separate monitor. |
| No scheduled runs | Check `MONITOR_ENABLED=true`, Actions enabled, default-branch workflow and GitHub's inactivity policy. Manual runs and code changes can help diagnose. |
| Daily heartbeat missing | Inspect Actions directly; the workflow cannot notify you if GitHub never starts it. Enable GitHub Actions failure emails too. |

## Restoring state

1. Set `MONITOR_ENABLED=false` and wait for any running check to finish.
2. On `monitor-state`, inspect `state.json` and its git history. Make a backup before editing.
3. Restore the intended file revision as a new commit on the same state branch.
4. Run `check` manually, inspect the summary and confirm phone delivery, then resume.

Restoring an older state can resend messages delivered after that revision. This is
preferable to fabricating acknowledgments or silently throwing away a pending queue.
Do not delete the state branch; a missing state deliberately stops monitoring.

## Rotating a Telegram token

Revoke/regenerate the token through BotFather, update `TELEGRAM_BOT_TOKEN` in repository
secrets, run `test-telegram`, then `check`. Article delivery history is unaffected.
Never paste the token into an issue, source file, build log or chat with another person.

## Changes and upgrades

Run tests before merging changes. Dependabot checks action pins monthly; review and
merge compatible updates. Test new source payload shapes with sanitized fixtures.
Current parser fixtures are synthetic and explicitly labeled; they do not establish
that the current Sin Chew live endpoint follows any particular response format.

Official references:

- [Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage)
- [Telegram retry_after](https://core.telegram.org/bots/api#responseparameters)
- [GitHub Contents API](https://docs.github.com/en/rest/repos/contents)
- [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [GitHub workflow notifications](https://docs.github.com/en/actions/how-tos/monitor-workflows/configure-notifications)
