# Help Me Tibooo Design

## Purpose

`help-me-tibooo` watches public posts and replies from Tibo
([@thsottiaux](https://x.com/thsottiaux)) and forwards relevant OpenAI news to a
Discord text channel. It runs without paid X or language-model APIs.

## Scope

The first milestone will:

- run publicly in a GitHub repository under the MIT license;
- check for new source items approximately every 10 minutes with GitHub Actions;
- inspect Tibo's original posts and replies while ignoring plain reposts;
- detect reset announcements and hints, usage-limit changes, major model or
  product launches, plan or pricing changes, and significant incidents or
  recoveries;
- favor recall over precision when a post is ambiguous;
- send a Discord message containing a category label, the unmodified source
  text, and the original X URL;
- establish a baseline without sending old posts on its first run;
- send a monitoring-health alert after three consecutive failed checks; and
- expose a manually triggered workflow for sending a test notification.

Scheduled quiet hours are explicitly deferred to a later milestone. A future
version may send nighttime webhook messages with Discord's
`SUPPRESS_NOTIFICATIONS` message flag.

## Architecture

The project will be a small Python application invoked by GitHub Actions.
Modules will be separated by responsibility:

1. A source client fetches JSON from the Codex Reset public feed and public HTML
   from a Tibo timeline mirror.
2. A normalizer converts both sources into one post model containing the post
   ID, text, timestamp, URL, reply status, and repost status.
3. A rules classifier assigns zero or more alert categories. Reset-feed
   classifications are used when available; explicit, version-controlled rules
   cover the broader news categories.
4. A state component tracks the newest processed post and the consecutive
   source-failure count in the GitHub Actions cache.
5. A Discord client formats and sends webhook payloads. It disables mention
   parsing so source text cannot accidentally ping users or roles.

The workflow restores the latest state, runs the watcher, and saves new state
under a key derived from the newest processed post. If no state exists, the
watcher records the current newest post and exits without notifying Discord.

## Data Sources and Fallbacks

The primary reset source is `https://codex-reset.com/api/feed`. It exposes
Tibo's reset-related original posts and replies as structured JSON. A public
Tibo timeline mirror supplies posts outside the reset lane so the project can
detect major product news.

Both sources are unofficial dependencies and may change without notice. A
single-source failure will not stop items from the healthy source from being
processed. A run is considered failed for health tracking only when no source
can provide usable fresh data. Three consecutive failed runs produce one
Discord health alert; recovery clears the failure state.

Parsers will reject malformed records, enforce request timeouts, and cap input
sizes. Source URLs and request behavior will be isolated so a broken provider
can be replaced without changing classification or delivery code.

## Classification

Classification will be deterministic and free of paid APIs. Rules will cover:

- **Reset:** reset, banked reset, refreshed usage, reset-button hints, and
  scheduled reset timing.
- **Limits:** usage or rate-limit changes, quota behavior, and material plan
  allocation changes.
- **Launch:** named model launches, major Codex or ChatGPT releases, and broad
  rollouts.
- **Plans:** significant subscription, access, or pricing changes.
- **Incident:** widespread service degradation, investigation, mitigation, or
  recovery.

Positive rules will combine phrases and product context instead of matching
isolated words such as `reset`, which may be conversational. The classifier
will still favor sending an uncertain but plausibly important OpenAI post over
silently discarding it. Rules will live in code with fixture-based tests so
changes are reviewable.

## Discord Delivery

The user creates an incoming webhook in an existing Discord server and stores
its URL as the repository secret `DISCORD_WEBHOOK_URL`. No Discord bot,
application registration, or bot invitation is required.

Messages will contain no `@everyone`, role, or user mention. The webhook payload
will set `allowed_mentions.parse` to an empty list. Delivery failures will be
retried with bounded backoff, and logs will never include the webhook URL.

The manual GitHub Actions workflow will send a clearly labeled test message
without reading or changing watcher state.

## State and Duplicate Prevention

State will contain:

- the highest processed post ID or equivalent source cursor;
- a bounded set of recently processed IDs for cross-source deduplication;
- the consecutive total-source-failure count; and
- whether a health alert has already been emitted for the current outage.

The first successful run initializes these fields from current source data and
sends no historical alerts. Later runs process unseen items from oldest to
newest so Discord messages remain chronological. Repeated source items and
overlap between the reset feed and timeline mirror produce only one alert.

## Repository and Operations

The public repository will be named `help-me-tibooo`. It will include:

- a concise README with setup, webhook creation, GitHub Secret configuration,
  manual testing, limitations, and troubleshooting;
- an MIT license;
- pinned Python dependencies;
- a scheduled workflow using `*/10 * * * *` plus `workflow_dispatch`;
- least-privilege GitHub Actions permissions; and
- no committed credentials or user-specific Discord identifiers.

The implementation will log source status, classification results, and delivery
outcomes without logging secrets or full response bodies.

## Testing and Acceptance

Unit tests will cover normalization, reply inclusion, repost exclusion, each
alert category, ambiguous-news behavior, first-run baselining, chronological
delivery, cross-source deduplication, and three-failure health alerts.

HTTP tests will use recorded local fixtures rather than live services. A
separate smoke command may fetch live public sources without sending Discord
messages. Before release, the GitHub Actions workflow will run tests and the
manual test action will verify the configured Discord webhook.

The milestone is accepted when a fresh deployment sends no historical posts,
a qualifying fixture produces exactly one correctly formatted alert, an
irrelevant repost produces none, and three simulated total-source failures
produce a single health alert.

## Known Limitations

- GitHub Actions schedules can run later than the nominal 10-minute interval.
- Unofficial public sources can become unavailable or change format.
- Deterministic classification can occasionally produce false positives or
  miss unusually phrased news.
- The first milestone does not suppress nighttime notifications.
