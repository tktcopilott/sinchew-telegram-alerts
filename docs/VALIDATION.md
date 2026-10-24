# Validation evidence

Validated on 24 October 2026 using Python 3.12.14.

## Passed locally

- `python -m unittest discover -s tests -q`: **56 tests passed**.
- Python compilation and AST parsing for application and test modules.
- YAML parsing for the monitor workflow, test workflow and Dependabot configuration.
- Credential-pattern check: no session cookies, bot tokens or GitHub personal tokens
  in the deliverable. The original uploaded browser capture is excluded.
- Whitespace and complete-archive checks.

## Behaviors exercised

| Area | Evidence |
| --- | --- |
| Setup | Explicit initialization, quiet baseline and refusal to reset existing state |
| Detection | Chinese titles, image/headline duplicate anchors, URL tracking removal, HTML/JSON variants |
| Backlogs | Pagination beyond the first page, pinned known items, page-loop detection and explicit scan-limit failure |
| Delivery | Durable queue before send, per-message acknowledgment/checkpoint, oldest-discovered-first delivery |
| Recovery | Partial Telegram failures, restart with pending work, already-acknowledged IDs not resent on normal reruns |
| Persistence | Local atomic replacement, GitHub SHA concurrency guard, branch creation and lost-write-response verification |
| Rate limits | GET transient retry, explicit 429 retry-after handling, bounded waits and no blind retry of ambiguous POSTs |
| Visibility | Blocked source errors, once-daily failure alert, recovery message and daily source-health heartbeat |
| Secret handling | No raw token-bearing network errors, plain-text messages, no credentials required for diagnostics |
| Full flow | In-memory provider simulations exercise source + GitHub state + Telegram across separate monitor instances |

## Not established by these tests

1. **Live Sin Chew access or payload format.** Both the public tag page and tag-list
   endpoint returned HTTP 403 through this execution environment. A subsequent CLI
   `diagnose` also failed with an explicit HTTP 403 error. Network policy and site
   defenses cannot be distinguished conclusively here. Fixtures are synthetic.
2. **Actual Telegram delivery.** No user bot token or verified chat ID was provided.
3. **A deployed GitHub workflow.** GitHub is confirmed installed, but repository
   operations are not exposed in this session. No repository was created or modified.
4. **Hosted Python matrix results.** Python 3.12/3.13 CI is configured but has not run
   on GitHub. Only the available local Python version was executed here.
5. **Timing guarantees.** GitHub's schedule is best effort, and publication-to-alert
   latency depends on successful polling, source listing order and phone delivery.

## Required acceptance check before enabling

On the target public repository, run the included `Tests` workflow; then run
`Article monitor` manually in `diagnose`, `test-telegram`, `initialize`, and `check`
modes. Inspect sample articles, confirm phone delivery, and only then set repository
variable `MONITOR_ENABLED=true`. Confirm the next scheduled run and daily heartbeat.

Action versions are pinned to official release commits verified during implementation:

- [actions/checkout v7.0.1](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1)
- [actions/setup-python v7.1.0](https://github.com/actions/setup-python/commit/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0)
