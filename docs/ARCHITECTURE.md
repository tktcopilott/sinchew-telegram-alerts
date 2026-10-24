# Architecture

Python 3.12+, standard library only. The executable entry point is `python -m article_alerts`.

| Module | Responsibility |
| --- | --- |
| `domain.py` | Article/state models, safe domain errors and narrow protocols |
| `service.py` | Initialization, discovery, durable queue, delivery checkpoints and health reporting |
| `source.py` | Sin Chew tag-list HTTP and HTML/JSON parsing |
| `telegram.py` | Official Telegram API message delivery and private-chat setup helper |
| `state.py` | Atomic development files and GitHub Contents API state checkpoints |
| `http.py` | HTTPS transport, safe error boundaries and bounded retry policy |
| `config.py` | Typed configuration and credential validation |
| `__main__.py` | CLI and dependency composition |

## SOLID in this implementation

| Principle | Concrete application |
| --- | --- |
| Single responsibility | Parsing, orchestration, persistence and delivery live in separate adapters/use cases. |
| Open/closed | Add a new `ArticleSource`, `Notifier` or `StateStore` adapter without modifying the monitoring use case; wire it in the composition root. |
| Liskov substitution | The local and GitHub stores honor the same load/save behavior; fake adapters exercise the same service contract in tests. Local storage has an explicit single-process scope. |
| Interface segregation | The service depends on small protocols rather than large client APIs. Sources do not need notification methods; notifiers do not need storage methods. |
| Dependency inversion | `Monitor` receives its source, state store, notifier and clock; it imports no concrete network provider. HTTP adapters also accept an injected transport. |

These are deliberately small interfaces rather than an extensibility framework.
There is no dependency injection container, ORM, queue server or background daemon.

## Successful check

1. Load and validate state; reject missing state, incompatible schemas or a different tag identity.
2. Drain persisted pending work first, up to the per-run limit.
3. Fetch latest pages until reaching a completely known page or explicit end of listing.
   One pinned old article does not prematurely end a catch-up scan.
4. Deduplicate by stable numeric article ID where available and persist new articles
   in a pending queue, with oldest-discovered items first.
5. Send one item; require Telegram's `ok: true` and a numeric `message_id`.
6. Add its ID to delivery history, remove it from the queue, and checkpoint immediately.
7. Report recovery/daily health if due; checkpoint periodic health metadata.

Initialization is a different operation. It records two current pages without sending
their articles. A second initialization refuses to overwrite existing state.

## State consistency

GitHub state is stored as `state.json` on `monitor-state`, separate from application code.
The Contents API's file SHA implements optimistic concurrency: a conflicting writer
causes failure instead of overwriting newer state. Workflow concurrency also serializes
scheduled and manual runs. Never run an additional external writer against this branch.

A new state branch is created from the repository's default branch. Writes use the
workflow-scoped GitHub token. Branch creation handles a lost response by checking the ref.
A lost state-write response is verified by reading the desired content before deciding
whether the checkpoint succeeded. It never blindly overwrites after a conflict.

Article history is retained instead of expired by an arbitrary time window. The store
fails before its serialized content approaches the Contents API's 1 MB response limit;
archiving/migration must then be a deliberate operational decision. State branch commit
history grows as articles are delivered, which is the tradeoff for using no database service.

## Retry semantics

- GET requests: bounded exponential backoff for network failures and HTTP 500/502/503/504.
- HTTP 429: honor `Retry-After` or Telegram's JSON `retry_after` for up to 60 seconds per wait.
  Longer delays fail the run and leave queued work for the next schedule.
- POST requests: retry only an explicit 429 rejection. A network timeout or 5xx after a
  send may be ambiguous; retain the queue and let the next run retry.
- GitHub PUT: verify a possibly successful write after a lost response. Conflicts fail closed.
- No retry for authentication failures or HTTP 403 block pages.

No design can atomically commit a Telegram send and a GitHub write across the two providers.
The small duplicate window is documented rather than hidden behind an exactly-once claim.

## Credentials and untrusted content

Only the two repository secrets and the ephemeral GitHub token reach the runtime.
No token, cookie or chat ID is embedded in the source or state. Network exception messages
never include token-bearing URLs. Tracebacks from third-party response paths are not logged.
Article text uses Telegram plain text to avoid markup injection. Article URLs must be
HTTPS links on the expected Sin Chew host, and navigation/advertising links are ignored.
Redirects are refused to prevent forwarding credentials to another host.

The monitor runs only trusted default-branch code with secrets. Pull requests run the
isolated test workflow with read-only permissions and no Telegram credentials.
