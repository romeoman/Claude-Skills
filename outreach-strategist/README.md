# outreach-strategist

An AI SDR system for OpenClaw agents: a campaign-level coordinator skill, four
pipeline subskills, a Python engine, three inbox watchers, a set of
deterministic pre-send gates, and a persistent knowledge base.

This file is the install-and-run document. Everything in it was read out of the
code or run as a command; anything not verifiable that way is marked
**unverified** or left out.

---

## 1. What this is / what it can do

The system runs human-gated, signal-led outbound. Concretely, it:

- **Coordinates campaigns as data, not prompts.** A campaign is a folder
  (`campaigns/<slug>/`) with `campaign.yaml`, `brief.md`,
  `research-protocol.md`, `routing.md`, `dossiers/`, and per-stream
  `streams/<name>/stream.yaml`. Adding a campaign is a data change. The skill
  itself (`SKILL.md`) is generic.
- **Assembles SDR knowledge before a word of copy is written.** Eight
  per-contact sources via `context_spine.py`, plus market intelligence, the
  Reddit slice of it, podcasts, YouTube transcripts, Graph.one warm paths,
  Trigify prospect/company intelligence (three sources, §7.1), a voice corpus,
  and follow-up asset options via the `knowledge/` package.
  All of it lands in one envelope key, `settings_json.sdr_context`
  (`outreach-engine/knowledge/__init__.py`).
- **Gates every message before it can be staged.** Seven deterministic,
  fail-closed gates run in `presend_review.review_envelope()` on the finished
  envelope, before the Mission Control upsert and before any Woodpecker write.
  A block returns `EXIT_RECOVERABLE` and the envelope is not upserted, so
  blocked copy never reaches an approval UI or a draft.
- **Watches three inboxes** — Woodpecker email, LinkedIn DM/InMail via LinkUp,
  Gmail via Maton — each with its own durable cursor, its own idempotency
  ledger, its own state file, its own cron, and its own log
  (`inbox_common.py` + `inbox_woodpecker.py` / `inbox_linkedin.py` /
  `inbox_gmail.py`).
- **Classifies replies deterministically** with one shared classifier
  (`reply_classifier.py`, config `config/reply-classifier.yaml`, no LLM) into
  `objection | negative | positive | auto_reply | ooo | bounce | referral |
unclear`, with the matched rule recorded for audit.
- **Records objections person-level, across channels.** An objection raised on
  any channel writes to one canonical opt-out ledger (`suppression_ledger.py`)
  that the suppression gate reads before any cohort is built or staged. The
  ledger is sticky: there is no `clear_optout` function anywhere in the module.
- **Regenerates copy on a cadence.** `copy_refresh.py --propose` runs monthly
  and writes a versioned proposal file for a human to approve; `--apply` /
  `--apply-proposal` PATCH Woodpecker step versions only after the real gate
  passes, with a rollback record written first.

### What it does NOT do

- **It never sends autonomously.** Nothing in the system auto-sends. The
  pipeline stages Woodpecker **DRAFT** campaigns; a human activates them in the
  Woodpecker UI. `copy_refresh.py` refuses any campaign whose status is not in
  `allowed_statuses` (DRAFT) and never activates one.
- **InMail objection handling is manual.** LinkUp's InMail/Sales-Nav store is
  readable, but a LinkedIn identity cannot be resolved to an enrolled contact
  reliably enough to auto-act on it (see §10). Those objections are recorded by
  a human running `record_objection.py`.
- **No browser automation, ever.** No headless-browser scraping of LinkedIn or
  any other platform is part of this system. Every LinkedIn read and write goes
  through a vendor API (LinkUp, Woodpecker, HarvestAPI).
- **It does not write copy at the strategist layer.** The strategist coordinates;
  the `outreach-copywriter` and `outreach-copy-qa` subskills write and check
  copy inside the pipeline, under `outreach-engine/SKILL_GUARD.md`.
- **It does not act on people we did not enrol.** See §9.

---

## 2. Architecture at a glance

```
 SIGNALS IN                          COHORT BUILD
 ──────────                          ────────────
 trigify_poller.py   ┐               contacts_source.py   (HubSpot lists)
 albacross_receiver.py│              signals_source.py    (Harvest + Exa)
 web_visitor_qualify.py             event_sourcing.py    (pasted/event lists)
 signals_source.py   ┘                     │
        │                                  │
        └──────────► signal_store.py ──────┤
                     signal_score.py       │
                     signal_ranking.py     │
                                           ▼
                             KNOWLEDGE SPINE
                             ───────────────
                             context_spine.py      (8 per-contact sources)
                             knowledge/__init__.py (build_sdr_context)
                             knowledge/{mi_intel,podcasts,youtube,
                                        warm_paths,voice,assets,
                                        trigify_intel}.py
                             content_library.py    (our published assets)
                                           │
                             writes settings_json.sdr_context
                                           ▼
                             COPYWRITER (pipeline subskills)
                             ───────────
                             envelope_runner.py -> outreach-cadence-strategist
                                                -> outreach-copywriter
                                                -> outreach-copy-qa
                                        (copy_qa/full_qa.py, lint_copy.py)
                                           │
                                           ▼
                             PRE-SEND GATES
                             ──────────────
                             presend_review.review_envelope()
                               calls presend_gates.py:
                                 ai_disclosure, pii_leak, suppression,
                                 compliance, art14_notice,
                                 linkedin_copy_bands
                               + recycling.py
                               + suppression_ledger.py (persisted ledger)
                               + unsubscribe_verify.py (live evidence)
                                           │
                          blocked ─────────┴───────── allowed
                             │                            │
                     not upserted,                        ▼
                     reasons logged              mc_client.py  -> Mission Control
                                                 signal_woodpecker.py
                                                        │
                                                        ▼
                                          WOODPECKER **DRAFT** campaign
                                          (human activates in the UI)
                                                        │
                                            messages go out
                                                        │
                                                        ▼
 INBOX WATCHERS  ─────────────────────────────────────────────────────
 inbox_woodpecker.py   (email)      inbox_common.py = shared cursor,
 inbox_linkedin.py     (LinkUp)                      idempotency, stall
 inbox_gmail.py        (Maton)                       detection
 webhook_receiver.py   (push: Woodpecker prospect_replied,
                        LinkUp message_received)
        │
        ├──► campaign_contacts.is_in_scope()   allowlist, fail closed
        │
        ├──► inbound_reply_store.record_reply()  JSONL, idempotent on event_id
        │
        ▼
 CLASSIFIER  reply_classifier.classify()
        │
        ├── objection ──► record_objection.py ──► suppression_ledger.py
        │                                          (person + domain, sticky)
        │                                          + Woodpecker blacklist
        │
        └── every class ──► signal_notify.py ──► DISCORD (embed, dated thread)
                            category -> channel: config/notify-routing.yaml
```

Copy evolution runs alongside: `copy_refresh.py` reads `sdr_context`, lints,
runs the same `presend_review` gate, and writes proposal / version / rollback
records under `$OUTREACH_RUNS_DIR/_copy_refresh/`.

---

## 3. Install for someone else

### 3.1 Prerequisites

| Requirement               | Notes                                                                                                                                                                                                                                                                 |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python 3.11+              | The engine modules are **stdlib-only** by design (PyYAML is not assumed; every config reader ships its own minimal YAML-subset parser). The test runner picks the first of `python3`, `python3.13`, `python3.12`, `python3.11` that can import `pytest` and `PyYAML`. |
| An OpenClaw gateway       | The strategist skill runs as an OpenClaw agent skill; the Discord channel wiring in §5 writes into the gateway's `openclaw.json`.                                                                                                                                     |
| Docker                    | Only for the container layout (§3.2). The host-run watchers do not need it.                                                                                                                                                                                           |
| `bash` 4+                 | Some shell harnesses assume it. Stock macOS ships bash 3.2 — see §10.                                                                                                                                                                                                 |
| A writable runs directory | `$OUTREACH_RUNS_DIR`. Required, no fallback for the ledger. See §3.4.                                                                                                                                                                                                 |

### 3.2 The three deployed layouts, and what runs where

The same source tree is used three ways. Which parts run where is not
incidental — modules are placed by what secrets and filesystem they need.

| Layout                     | What it is                                  | What runs there                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Mac / dev checkout**     | the full repo                               | every offline harness, the unit suites, `--dry-run` deploys                                                                                                                                                                                                                                                                                                                                                      |
| **VM host**                | the full repo checkout the crons run from   | **the watchers and the copy refresh**: `inbox_woodpecker.py`, `inbox_linkedin.py`, `inbox_gmail.py`, `inbox_common.py`, `campaign_contacts.py`, `reply_classifier.py`, `inbound_reply_store.py`, `copy_refresh.py`, `content_library.py`, `signal_branch.py`, the `knowledge/` package, and the webhook receivers. Also the signal watcher, the trigify monitor watcher, the approval listener, and the reports. |
| **Container** (`openclaw`) | the OpenClaw gateway + its skills workspace | the strategist skill and the four pipeline subskills, plus a **deliberate subset** of engine modules shipped by `scripts/outreach-deploy-skills.sh`                                                                                                                                                                                                                                                              |

The container subset is the `ENGINE_FILES` allowlist in
`scripts/outreach-deploy-skills.sh`. It ships the envelope/runner, the Mission
Control client, the signal processor, the **gates and their call site**
(`presend_review.py`, `presend_gates.py`, `sdr_orchestrator.py`,
`suppression_ledger.py`, `unsubscribe_verify.py`, `deliverability_breaker.py`,
`compliance_review.py`, `recycling.py`, `context_spine.py`, `plan_review.py`),
the manual objection route (`record_objection.py`), and the trigify signal
substrate. The script's own header lists the **host-only** modules that must
never be added to that allowlist, and why.

The container also needs a `config/` directory next to the deployed scripts
dir; the deploy copies `ENGINE_CONFIGS` (`presend-gates.yaml`, `recycling.yaml`,
`plan-review.yaml`, `context-spine.yaml`, `signal-scoring.yaml`,
`trigify_signal_ranking.yaml`) there. Miss it and every config loader raises,
which `presend_review` turns into a fail-closed block — the container would
refuse every signal.

```bash
# deploy the container subset (run after every engine-source change)
scripts/outreach-deploy-skills.sh --dry-run          # show what would change
scripts/outreach-deploy-skills.sh                    # deploy
scripts/outreach-deploy-skills.sh --check            # sha256 parity vs source
scripts/outreach-deploy-skills.sh --target-dir /tmp/x --dry-run   # no docker
```

### 3.3 Clone

```bash
git clone https://github.com/romeoman/openclaw-infra.git
cd openclaw-infra
```

The public mirrors carry the skill only (`SKILL.md`, this README,
`bin/kb.py`, `campaigns/README.md`, `campaigns/_template/`, `subskills/`) — not
the engine. To run the engine you need the private infra repo.

### 3.4 Configuration

All tunables are files, never literals in code (project rule). They live in
`config/` at the repo root:

| File                             | Read by                                         | Controls                                                                                                 |
| -------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `config/presend-gates.yaml`      | `presend_gates.py`                              | every gate threshold, the jurisdiction table, the LinkedIn character bands, the never-emit fields        |
| `config/recycling.yaml`          | `recycling.py`                                  | re-approach eligibility, cool-offs, permanent blocks                                                     |
| `config/reply-classifier.yaml`   | `reply_classifier.py`                           | the per-language vocabulary, confidence threshold, `always_needs_human` classes                          |
| `config/inbox-watchers.yaml`     | `inbox_common.py`, `campaign_contacts.py`       | `state_subdir`, per-watcher `schedule` + `max_silence_seconds`, the allowlist source globs               |
| `config/webhooks.yaml`           | `inbound_reply_store.py`, `webhook_receiver.py` | the reply-store subdir, event lists, header names, heartbeat thresholds                                  |
| `config/copy-refresh.yaml`       | `copy_refresh.py`                               | the four campaign ids, allowed statuses, persona/period objectives, cadence cron, approval marker suffix |
| `config/knowledge-sources.yaml`  | `knowledge/config.py`                           | per-source enable/disable, caps, freshness thresholds                                                    |
| `config/context-spine.yaml`      | `context_spine.py`                              | the eight per-contact sources                                                                            |
| `config/suppression-ledger.yaml` | ops record (not parsed)                         | the canonical `OUTREACH_RUNS_DIR` value **per deployed layout**                                          |
| `config/outreach-sync.conf`      | `scripts/outreach-skills-sync.sh`               | the three publish targets and the public redaction filters                                               |
| `config/crontab.txt`             | humans                                          | the reference crontab (§8)                                                                               |

Every override is an env var of the form `$OUTREACH_<THING>_CONFIG` (e.g.
`OUTREACH_PRESEND_CONFIG`, `OUTREACH_INBOX_WATCHERS_CONFIG`,
`OUTREACH_REPLY_CLASSIFIER_CONFIG`, `OUTREACH_COPY_REFRESH_CONFIG`). A missing
or malformed config is a **loud** failure in every one of these modules, never
a silent fallback to permissive defaults.

### 3.5 The required directory: `OUTREACH_RUNS_DIR`

This is the one directory the whole system agrees on. It is **required**:
`suppression_ledger.ledger_path()` resolves from `$OUTREACH_RUNS_DIR` **only**
and raises `SuppressionLedgerError` when it is unset. There is deliberately no
fallback, because a silent fallback once wrote opt-outs to a file no gate read
while every route reported "recorded".

What lives under it:

```
$OUTREACH_RUNS_DIR/
  <run-slug>/envelope.json          a campaign build envelope (the allowlist reads these)
  _suppression/ledger.json          the canonical opt-out ledger
  _watcher_state/<watcher>.json     one durable state file per inbox watcher
  _inbound_replies/<UTC-date>.jsonl the shared inbound reply store
  _signal_touches/*.json            per-prospect enrolments POSTed to Woodpecker
  _signal_touches/_consumed/*.json  the same, after consumption (still evidence)
  _copy_refresh/                    baselines, versions/, proposals
```

Set it identically everywhere that must agree. Read
`config/suppression-ledger.yaml` before pasting a command from a runbook: the
host cron's value and the container's value have historically been _different
storage_ under the same variable name.

### 3.6 First-run smoke test — no credentials needed

Two harnesses prove the install without any vendor key. Both run the **real**
production modules (never a reimplementation) inside their own temporary
`$OUTREACH_RUNS_DIR`, so the production ledger is never touched.

```bash
# 1. Objection routing, adversarially. Runs reply_classifier, record_objection,
#    suppression_ledger, campaign_contacts, all three watchers' processing
#    paths and presend_review against recorded vendor-response fixtures.
python3 scripts/tests/objection_e2e_test.py

# 2. A raw pasted list, straight through the real machine: dedupe, exclusion
#    with a stated reason, suppression before any research spend, the real
#    gates with the real config, tier1-vs-tier2 disclosure both directions,
#    and the CRM-leak gate.
python3 scripts/tests/dummy_pasted_list_test.py

# 3. Everything the current layout can run, one summary table, non-zero if any
#    harness is red. Use --list first to see the manifest and what is skipped.
bash scripts/tests/run-all-harnesses.sh --list
bash scripts/tests/run-all-harnesses.sh
```

Expected clean output: `RESULT: 42/42 scored checks passed` for the objection
harness and `20/20 checks passed` for the pasted-list harness.

Caveat, stated because the harness's own docstring states it:
`dummy_pasted_list_test.py` includes one **live, read-only** Graph.one query
via Mission Control. Where Mission Control is unreachable the harness reports
that honestly rather than pretending; the other 19 checks are fully offline.

`run-all-harnesses.sh` prints what it **skipped for this layout and why** — a
green subset is not a green build. On a Mac it lists `sync-protect`,
`deploy-parity-check` and `container-unittest` as skipped.

---

## 4. Tools and credentials

Environment variable **names** only. Never commit a value; the container gets
them from its env, the host crons load the repo `.env` with a safe line parser
(plain `source` breaks on values containing shell metacharacters).

| Tool                                          | Used here for                                                                                                                                                                                                                                                                                                                                                               | Env var(s)                                                                                                                     | Required?                                                        | If absent                                                                                                                                                      |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Woodpecker**                                | email sequences, DRAFT staging, the email inbox poller, prospect blacklist writes, step-version PATCH for copy refresh                                                                                                                                                                                                                                                      | `WOODPECKER_API_KEY`, `WOODPECKER_FIRM_ID`                                                                                     | **Required** for any staging, the email watcher and copy refresh | No staging, no email inbox watch, no copy apply. `record_objection --remote` reports the failure instead of reaching the API.                                  |
| **LinkUp**                                    | LinkedIn DM + InMail inbox. Real endpoint is `POST https://api.linkupapi.com/v2/messages` with `action: list_inbox` / `get_conversation` / `check_invitation`; `sales_nav: true` selects the InMail store. Guessed paths (`/v2/inbox/list`, `/v2/inbox`, `/v2/message`) return 404 `INVALID_ACCOUNT`. Webhooks: `POST /v2/webhooks`, event `message_received`, HMAC-SHA256. | `LINKUP_API_KEY`, `LINKUP_ACCOUNT_ID`, `LINKUP_WEBHOOK_SECRET`                                                                 | Required for the LinkedIn watcher                                | LinkedIn replies are invisible to the system.                                                                                                                  |
| **Maton**                                     | Gmail read, scoped to Maton-draft threads only                                                                                                                                                                                                                                                                                                                              | `MATON_API_KEY`                                                                                                                | Required for the Gmail watcher                                   | Direct-to-Romeo replies are not watched.                                                                                                                       |
| **HubSpot**                                   | source and curated lists, CRM facts in the spine, unsubscribe writes                                                                                                                                                                                                                                                                                                        | `HUBSPOT_ACCESS_TOKEN`                                                                                                         | Required for HubSpot-cohort builds                               | No list build, no CRM facts; the spine reports the source `unavailable` with a reason.                                                                         |
| **Trigify**                                   | prospect + company intelligence in the knowledge spine (three sources, §7.1), listening monitors. **Social Signals — the always-on buying-intent feed — is not entitled on this account**; see the entitlement table below.                                                                                                                                                 | `TRIGIFY_API_KEY`, `TRIGIFY_API_BASE`, `TRIGIFY_WEBHOOK_TOKEN`, `TRIGIFY_CREDIT_BUDGET_DAILY`, `TRIGIFY_CREDIT_BUDGET_MONTHLY` | Optional                                                         | The three `trigify_*` sources report `unavailable` with a reason. An **unset** budget never authorises a spend — the two paid sources fail closed.             |
| **Albacross**                                 | website-visitor signals via a webhook receiver                                                                                                                                                                                                                                                                                                                              | `ALBACROSS_WEBHOOK_TOKEN`                                                                                                      | Optional                                                         | No web-visit signals.                                                                                                                                          |
| **Exa**                                       | company/topic research (campaign-level)                                                                                                                                                                                                                                                                                                                                     | `EXA_API_KEY`                                                                                                                  | Optional                                                         | Research facts drop out of the spine with an honest `unavailable` row.                                                                                         |
| **Apollo / HarvestAPI / Icypeas / Emailable** | enrichment, verification, the voice corpus snapshot                                                                                                                                                                                                                                                                                                                         | `APOLLO_API_KEY`, `HARVEST_API_KEY` (others via their own skills)                                                              | Optional                                                         | Enrichment and voice reference degrade to `unavailable`.                                                                                                       |
| **Graph.one via Mission Control**             | warm paths / relationship intelligence                                                                                                                                                                                                                                                                                                                                      | `MC_BASE_URL`, `OUTREACH_WRITE_SECRET` (header `x-outreach-secret`)                                                            | Required for build/stage routing through MC                      | `GET /api/outreach/relationships/status` is preflight row 2b. When the cache is stale or degraded, **zero paths is not evidence that no warm path exists**.    |
| **PodcastIndex**                              | campaign-level podcast knowledge                                                                                                                                                                                                                                                                                                                                            | `PODCASTINDEX_API_KEY`, `PODCASTINDEX_API_SECRET`                                                                              | Optional                                                         | `podcasts` source reports `unavailable`.                                                                                                                       |
| **Zernio (YouTube transcripts)**              | transcript knowledge                                                                                                                                                                                                                                                                                                                                                        | `ZERNIO_API_KEY`                                                                                                               | Optional                                                         | **Currently `disabled` in config**: the Tools API returned HTTP 403 "only available on paid plans" while the key itself authenticates.                         |
| **Memelord**                                  | follow-up asset options (`--category trending`)                                                                                                                                                                                                                                                                                                                             | `MEMELORD_API_KEY`                                                                                                             | Optional                                                         | `follow_up_assets` is empty. Note these are always `auto_insert: false`.                                                                                       |
| **Reddit**                                    | the Reddit slice of market intelligence                                                                                                                                                                                                                                                                                                                                     | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`                                                                                     | Optional                                                         | The Data API is not available to us; expect zero rows and a `collector_notes` entry saying so.                                                                 |
| **crawl4ai**                                  | fetching public event/speaker pages for list sourcing                                                                                                                                                                                                                                                                                                                       | `CRAWL4AI_API_TOKEN`, `CRAWL4AI_BASE_URL`                                                                                      | Optional                                                         | Use `exa-api` for the same route.                                                                                                                              |
| **Discord bot**                               | the strategist channel, reply escalation, the daily nudge and weekly report                                                                                                                                                                                                                                                                                                 | `DISCORD_BOT_TOKEN`, `OUTREACH_DISCORD_CHANNEL_ID`, `DISCORD_BD_CHANNEL_ID`, `SALES_OPS_DISCORD_CHANNEL_ID`                    | Required for the human interface                                 | The system still gates and stages; you just do not hear about it. With `OUTREACH_DISCORD_CHANNEL_ID` unset each category fails soft to its old channel (§5.4). |
| **OpenClaw gateway**                          | runs the skill; every caller must name its agent                                                                                                                                                                                                                                                                                                                            | gateway config `openclaw.json`; callers send `x-openclaw-agent-id` or address `openclaw/<id>`                                  | **Required**                                                     | OpenClaw 2026.8.x with explicit agent ownership returns HTTP 400 "no explicit owner" to any caller that does not name an agent.                                |

**Credit costs verified from the vendor contract (LinkUp, docs
`docs.linkupapi.com/api-reference/v2`, checked live 2026-09-02):**

- `list_inbox` — **1 credit per 10 conversations** returned.
- `send` — 1 credit.
- `check_invitation` — 1 credit.
- webhook monitoring — approximately 10 credits/day.

**Trigify: what this plan is entitled to, and what each call costs.** Measured
live against the real STARTER-plan account on 2026-09-02 across the whole
133-endpoint surface. The table is recorded in `trigify_client.py`'s module
docstring, which is the file to read before changing any `max_items`. The
OpenAPI spec is served at **`https://api.trigify.io/docs`** — not
`/openapi.json`.

**Entitled:**

| Endpoint                                     | Client method                     | Cost                                                                                                      |
| -------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `POST /v1/profile/enrich`                    | `enrich_profile`                  | 1 credit/call                                                                                             |
| `POST /v1/profile/posts`                     | `get_profile_posts`               | charged **per result**, and the endpoint has **no `limit` parameter** — one live call cost **50 credits** |
| `POST /v1/company/enrich`                    | `enrich_company`                  | 1 credit/call                                                                                             |
| `POST /v1/company/posts`                     | `get_company_posts`               | per result; `limit` **is** supported, so `max_items` caps spend 1:1                                       |
| `POST /v1/company/comments`                  | `get_company_comments`            | per result; `limit` supported (max 50)                                                                    |
| `POST /v1/post/by-url`                       | `get_post_by_url`                 | 1 credit/call                                                                                             |
| `POST /v1/searches/linkedin/profile/preview` | `preview_linkedin_profile_search` | **free** — zero credits, zero search quota; capped to `time_frame="past-week"` on STARTER                 |
| `POST /v1/searches/linkedin/posts/preview`   | `preview_linkedin_posts_search`   | **free**, same past-week cap                                                                              |

**Not entitled (HTTP 403, recorded honestly, never worked around):**
`social-signals/*` ("Signals is not enabled for this workspace"),
`social/mapping` (Enterprise "Keyword Engagement"), `discover/creators`,
`post/engagements`, `post/comments` and `post/comments/replies` (Max and
above), `profile/engagement/*`, `topics/*` (Enterprise or Custom). Note the
asymmetry: `company/comments` (comments on a **company page's** post) is
entitled; `post/comments` (comments on a **person's** post) is not — different
endpoints.

Because these reads spend real credits, the six credit-spending methods sit
behind the same `confirm=True` write guard as a monitor create, and every
confirmed spend logs a line to stderr. The two paid knowledge sources are
budget-gated fail-closed against `TRIGIFY_CREDIT_BUDGET_DAILY` /
`TRIGIFY_CREDIT_BUDGET_MONTHLY` on their own ledger action, so a monitor create
and a knowledge-adapter spend cannot borrow each other's headroom. The deployed
values in `.env.example` are **50/day and 1500/month** against the plan's
4000-credit monthly limit; keep monthly ≥ 30× daily or the daily figure is
inert.

**`GET /v1/credits/balance` is not a spend tracker.** It read the same
`{"used": "0", "remaining": "4000"}` before and after the session's real,
confirmed spends (69 credits). Use `GET /v1/usage` — its
`data.credits.by_feature` map updates within one poll and is the authoritative
ledger.

Other vendors' per-call costs are not documented in this repo and are
deliberately not asserted here.

**The four knowledge sources added on 2026-09-03 introduce NO new vendor and no
new credential** — checked against this table rather than assumed:

| Source             | Vendor it reuses                                                   | Row above                   |
| ------------------ | ------------------------------------------------------------------ | --------------------------- |
| `industry_reading` | Exa, via the existing `research_exa.py` client                     | **Exa** (`EXA_API_KEY`)     |
| `events`           | Exa; optional, default-OFF Trigify `/v1/company/posts` half        | **Exa**, **Trigify**        |
| `job_changes`      | HarvestAPI `/linkedin/profile`, same auth the linkedin-engine uses | **Apollo / HarvestAPI / …** |
| `team_intel`       | Granola via the Maton gateway                                      | **Maton** (`MATON_API_KEY`) |

`industry_reading` and `events` prefer `MATON_API_KEY` (Maton gateway) and fall
back to `EXA_API_KEY` (Exa direct) — the same order `research_exa.py` already
uses. Neither set → `unavailable("credentials absent …")`, never a crash and
never an attempted call.

---

## 5. Using it in OpenClaw from the `#outreach-strategist` channel

### 5.1 The channel configuration that makes it work

Written by `scripts/outreach-wire-discord-channel.sh` into the gateway's
`/home/node/.openclaw/openclaw.json` under
`channels.discord.guilds.<guild>.channels.<id>`:

- guild `1480246506895315015`, channel `1544045843483594772`
- `enabled: true`
- `requireMention: false` — you do not have to @ the bot
- `autoThread: true`, `autoThreadName: "message"` — every request opens its own
  thread named after your message
- `includeThreadStarter: true` — the agent sees the message that opened the thread
- `autoArchiveDuration: 10080` (7 days)
- `skills`: `outreach-strategist`, `outreach-command`, `trigify`, `exa-api`,
  `linkup`, `apollo-api`, `harvestapi`, `hubspot-api`, `woodpecker`,
  `business-development`, `emailable`, `leaddelta`, `icypeas`

```bash
# on the VM host; the channel must already exist (the bot lacks Manage Channels)
bash scripts/outreach-wire-discord-channel.sh <channel_id>
# from a Mac
orb -m openclaw-vm bash ~/openclaw-infra/scripts/outreach-wire-discord-channel.sh <channel_id>
# verify
docker exec openclaw openclaw channels status
```

The script backs up `openclaw.json` first and restarts the container to apply.

### 5.2 The channel's systemPrompt, quoted

> "This Discord channel is the OUTREACH STRATEGIST room — campaign-level
> outreach coordination. For EVERY request here, first invoke the
> outreach-strategist skill and follow it. Default campaign: revenue-context …
> You coordinate: build/curate target lists, commission signal research
> (Trigify, Exa, Linkup, Apollo, HarvestAPI, Graph.one via Mission Control),
> invoke /outreach to build campaigns, and report status vs targets. You NEVER
> write outreach copy yourself (only the /outreach pipeline does, under
> SKILL_GUARD) and NOTHING EVER SENDS from this channel — DRAFT-only staging;
> approvals stay with Romeo in Mission Control and Woodpecker."

### 5.3 What to type, and what happens

| You type                                           | What happens                                                                                                                                                                                                                                                                     |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list campaigns`                                   | Enumerates `campaigns/*/campaign.yaml` and reports slug, name, status, one-line objective.                                                                                                                                                                                       |
| `work on <slug>`                                   | Loads that campaign folder (campaign.yaml, brief.md, research-protocol.md, routing.md, streams/) and restates objective + current status in one short message. Without a named campaign the default is `revenue-context`.                                                        |
| `build the list` / `build a list`                  | Runs the **preflight checklist** (9 rows, SKILL.md "Engine integration"), posts the PASS/FAIL table in the thread, then builds or updates the curated list per `campaign.yaml`'s `lists:` block. Any FAIL on a required row stops the action. The source list is never modified. |
| `commission research` / `research the next cohort` | Builds per-contact dossiers for a small batch (10–25) per the campaign's `research-protocol.md`. **No dossier → no sequence; no fresh (≤90-day) linkable observable → monitor, don't force.**                                                                                    |
| `/outreach`                                        | Invokes the pipeline conductor (`outreach-command`) over the cohort: cadence → copy → QA → gates → Mission Control upsert → Woodpecker **DRAFT**. This is the only way copy gets written.                                                                                        |
| `how is <slug> going` / `status vs target`         | Cohort size, signals found, drafts staged, approvals pending, replies/interviews booked vs target. Metrics it cannot verify are reported `n/a`, never invented.                                                                                                                  |
| `who should we contact next`                       | Reads `kb.py` history + current signals and recommends who, why now, which touch. It does not act without a go-ahead.                                                                                                                                                            |
| `STOP-OUTREACH`                                    | Halts everything.                                                                                                                                                                                                                                                                |
| _(cron) daily nudge_                               | 08:30 daily. Dossiers done vs queued, drafts awaiting approval, replies waiting, interviews vs target, top 1–3 signals worth acting on, anything skipped and why.                                                                                                                |
| _(cron) weekly report_                             | Mondays 08:00. The same plus trend vs target, per-stream funnel, suppression/routing incidents, 1–3 recommendations.                                                                                                                                                             |

**The binding rule for this channel: nothing sends from it.** Everything is
DRAFT-only staging. Approvals live in Mission Control and Woodpecker; a human
activates the campaign in the Woodpecker UI. Autonomy tiers are declared per
stream in `stream.yaml` and promoted **only** by an explicit human decision
after at least two weeks of calibration; when two tiers could apply, the lower
wins.

Replies come back **in the thread as Discord embeds** — the agent keeps the
conversation inside the auto-created thread rather than the channel root, and
reply escalations from the inbox watchers arrive the same way via
`signal_notify.py`.

### 5.4 Where the autopilot reports, and how that routing is configured

The autopilot reports into **this same room** — channel `1544045843483594772`,
read from `OUTREACH_DISCORD_CHANNEL_ID` — as Discord **embeds**, in a **dated
thread per category**. `signal_notify.py` creates the thread once per Warsaw
calendar day, named `"<prefix> · <YYYY-MM-DD>"`, and reuses it for every event
that day; a new day rolls to a fresh thread.

The category → channel table is config, not code:
**`config/notify-routing.yaml`**, read fresh on every call with the repo's own
stdlib YAML-subset parser (no PyYAML — the file is read inside the container
too). A missing file, a malformed line, a duplicate category, or a category
missing a required field raises `NotifyRoutingConfigError` **loud**; an
unrecognised category passed to `notify()` is a loud `ValueError`. There is no
silent fallback to a made-up route.

| Category     | Thread prefix      | Primary channel env            | Fallback when unset            |
| ------------ | ------------------ | ------------------------------ | ------------------------------ |
| `replies`    | `Replies`          | `OUTREACH_DISCORD_CHANNEL_ID`  | `DISCORD_BD_CHANNEL_ID`        |
| `objections` | `Objections`       | `OUTREACH_DISCORD_CHANNEL_ID`  | `SALES_OPS_DISCORD_CHANNEL_ID` |
| `copy`       | `Copy Proposals`   | `OUTREACH_DISCORD_CHANNEL_ID`  | `DISCORD_BD_CHANNEL_ID`        |
| `alerts`     | `Alerts`           | `OUTREACH_DISCORD_CHANNEL_ID`  | `SALES_OPS_DISCORD_CHANNEL_ID` |
| `signals`    | `Trigify Signals`  | `DISCORD_BD_CHANNEL_ID`        | (same)                         |
| `research`   | `Trigify Research` | `DISCORD_BD_CHANNEL_ID`        | (same)                         |
| `ops`        | `Trigify Ops`      | `SALES_OPS_DISCORD_CHANNEL_ID` | (same)                         |

The four autopilot categories are new; the three legacy Trigify categories keep
the routing they always had — only the **location** of the table moved out of a
hardcoded Python dict. The fallback is fail-soft and logged, never silent, so a
deployment that has not yet picked up the new env var still delivers. `ops`,
`alerts` and `objections` render in the red "critical" embed colour; everything
else in BD blue.

Emitters on this table: the three inbox watchers (`replies`; objections get
their own category and thread; watcher failures go to `alerts`),
`copy_refresh.py` proposals (`copy`), and the webhook receiver's loud alerts.
`scripts/outreach-report-cron.sh` prefers `OUTREACH_REPORT_CHANNEL`, then the
container's `OUTREACH_DISCORD_CHANNEL_ID`, then the BD channel.

**Deploying the env var needs a container RECREATE, not a restart.**
`docker compose up -d openclaw` — a plain `docker restart` reuses the
environment baked in at container creation and the new variable will not be
visible, so the routing silently keeps using the fallback. The same applies to
the two cron wrappers, which grep-export an env allowlist:
`tests/test_cron_notify_env_wiring.py` derives the required names from the
routing config, so a wrapper missing `DISCORD_BOT_TOKEN` or the channel var
fails the suite instead of degrading quietly to the file queue.

---

## 6. The flow, end to end

1. **Signal or list arrives.**
   `trigify_poller.py` (hourly), `albacross_receiver.py` (webhook),
   `web_visitor_qualify.py`, `signals_source.py`, or a pasted/event list through
   `event_sourcing.py`.
   _Artefact:_ a row in the signal store (`signal_store.py`), scored by
   `signal_score.py` / `signal_ranking.py`.
   _Caveat:_ the poller's Social-Signals leg
   (`client.get_social_signals_feed`) returns **403 on this plan** — that
   stream produces nothing until the entitlement changes. Its listening-search
   leg (`client.get_search_results`) is unaffected. Trigify's contribution to a
   build today comes from the three knowledge sources in §7.1, not from the
   buying-intent feed.

2. **Preflight.** The strategist runs the 9-row checklist and posts the PASS/FAIL
   table in the Discord thread. _Artefact:_ a `type=decision` event in
   `knowledge/outreach.db` via `bin/kb.py`.

3. **Cohort build.** `contacts_source.py` fetches the HubSpot cohort;
   `campaign_reuse.py` / `guardrails.py` apply routing and suppression rules.
   _Artefact:_ `$OUTREACH_RUNS_DIR/<run>/envelope.json` (`contacts_json`).

4. **Knowledge spine.** `context_spine.assemble()` gathers the eight per-contact
   sources; `knowledge.build_sdr_context()` merges them with the campaign-level
   sources, the content library and the freshness warnings.
   _Artefact:_ `envelope.settings_json.sdr_context` (schema in §7.1).

5. **Cadence, copy, QA.** `envelope_runner.py` hands the **whole** envelope to
   each pipeline step in turn (`outreach-cadence-strategist` →
   `outreach-copywriter` → `outreach-copy-qa`) and records a per-step
   fingerprint proof that the whole envelope was received.
   _Artefact:_ `copy_json`, `qa_json`, plus the runner's proofs.

6. **Pre-send gates.** `signal_processor.process_signal` calls
   `presend_review.review_envelope(envelope, action=...)` **after** the
   deterministic QA merge and **before** the Mission Control upsert. The same
   function is called by `signal_woodpecker.gate_envelope` on the
   signal→prospect-add path with `action="stage"`.

   **Gate 0 — cohort dedupe.** Before the per-contact loop,
   `review_envelope` groups the whole cohort by
   `presend_gates.normalize_email()`. Two entries that collapse to the same
   human — `dup@x.example` and `DUP@x.example`, a plus-tag, a Gmail-dot
   variant, an IDN/punycode spelling of the same domain — are a **build
   defect**: each would be gated and staged as an independent contact, so one
   person could receive two independent first-touch sequences. This is
   deliberately **not** a silent dedupe-and-continue: it fails closed with a
   `cohort_dedupe:` reason naming every raw form and every contact id
   involved, so a human fixes the cohort rather than having it merged out from
   under them. Genuinely different people do not collapse. Contacts with a
   missing or malformed email are skipped here — that case is already reported
   by the malformed-email check and must not also be reported as a spurious
   duplicate.

   **Wired gates (7):**

   | Gate                  | Scope                                                  | Blocks when                                                                                                                                                                                                                                                                                                                                                                                                                              |
   | --------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | `ai_disclosure`       | every touch, at the tier the campaign actually runs at | the autonomy tier requires a disclosure label and the copy has none. At tier1 no label is required (a human sends); flipping to tier2 turns the requirement on with no code change.                                                                                                                                                                                                                                                      |
   | `pii_leak`            | every touch, always                                    | copy echoes CRM internals back at a prospect — deal amounts traceable to the record, internal note text, another person's email/phone, CRM ids, lifecycle jargon, any configured never-emit value — or a prompt-injection payload echoed verbatim.                                                                                                                                                                                       |
   | `suppression`         | every enrolled contact                                 | the normalised email or its domain chain is on the persisted ledger. Free-mail domains are never company-suppressed. Missing/unusable email or a malformed ledger ⇒ block, `fail_closed=True`.                                                                                                                                                                                                                                           |
   | `compliance`          | every enrolled contact at build/stage                  | the jurisdiction's consent model is not satisfied. Inputs are real: jurisdiction from the contact's fetched country via the config map, `legal_basis` from an operator declaration in config, provenance from the recorded cohort source, `has_unsubscribe` from dated live Woodpecker verification (`unsubscribe_verify.py`), fail-closed on missing or stale evidence. An unrecognised jurisdiction resolves to the **strictest** row. |
   | `recycling`           | every enrolled contact                                 | this contact is not eligible to be re-approached (permanent block, bounce, an unclassified reply on file, or an unexpired cool-off).                                                                                                                                                                                                                                                                                                     |
   | `art14_notice`        | the **first** communication, per channel               | touch 1 carries no GDPR Art. 14 source notice. A non-email touch is exempt only when an email in the _same_ sequence carries the notice — a LinkedIn-only sequence has no such email. A copy channel label that disagrees with the planned channel for that touch also blocks (a mislabelled DM/InMail branch would defeat this check).                                                                                                  |
   | `linkedin_copy_bands` | LinkedIn touches only                                  | the copy breaks the measured bands in `config/presend-gates.yaml`: DM ≤ 200 chars / ≤ 2 sentences; InMail ≤ 400 chars, subject 3–5 words, hook 30 chars, ≤ 1 link. Structural sameness across touches of one `action_type` is reported under the same gate name.                                                                                                                                                                         |

   **Declared unwired (1):** `deliverability`. Its reason is recorded in
   `presend_review.UNWIRED_GATES` and asserted by `tests/test_suite_integrity.py`,
   so a gate can never be silently skipped. `check_deliverability` needs a stats
   snapshot with **both** bounce_rate and complaint_rate. Per-mailbox quota and
   per-campaign bounce rate _are_ available from Woodpecker; **complaint/spam
   rate does not exist anywhere in the Woodpecker API**, so an honest snapshot
   cannot be built and a `0.0` placeholder would be invented data. The
   circuit-breaking that _can_ be honest lives at the activation boundary
   instead: Woodpecker's own Bounce Shield auto-pause thresholds, ensured by
   `deliverability_breaker.py` from this config's `bounce_rate_halt`, plus a
   watcher cron that polls real bounce rates and pauses breaching campaigns.

   **What a block looks like.** `review_envelope` never raises; a surprise is a
   block. It returns `{"blocked": true, "reasons": [...], "summary": {...}}`.
   `signal_processor` writes that verbatim into
   `envelope.qa_json.presend_gates` and returns:

   ```
   EXIT_RECOVERABLE, "pre-send gates BLOCKED build slug=<id>: art14_notice: <msg-id> --
   first email carries no Art. 14 source notice; suppression: dana@acme.example --
   opted out 2026-08-14 (+3 more); not upserting"
   ```

   The envelope is **not** upserted, so nothing reaches the approval UI or a
   Woodpecker draft. `presend_review.py` can also be run read-only on any
   envelope file:

   ```bash
   python3 outreach-engine/presend_review.py path/to/envelope.json --action build
   # exit 0 = clean, exit 1 = blocked; prints the full verdict JSON
   ```

7. **Stage.** `mc_client.py` upserts the campaign to Mission Control;
   `signal_woodpecker.py` adds prospects and their `snippet1..15` copy fields to
   a Woodpecker **DRAFT** campaign.
   _Artefact:_ `$OUTREACH_RUNS_DIR/_signal_touches/<key>.json`, moved to
   `_consumed/` after processing. These files are also the enrolment evidence
   the inbox allowlist reads.

   **The creation-time check now agrees with the send-time one.**
   `validate_campaign.py` — the pre-create validator the woodpecker skill tells
   a human to run — used to check only the `settings.gdpr_unsubscribe` /
   `settings.list_unsubscribe` booleans. Per Woodpecker's own documentation
   those flags do nothing without the `{{UNSUBSCRIBE}}` snippet in the body or
   the account signature, so a hand-built body with the flags on and no visible
   tag got a green light at creation on copy that `unsubscribe_verify.py`
   correctly blocks at every later build/stage. The validator now calls
   `unsubscribe_verify`'s own `_email_versions` / `_tag_visible` — one source of
   truth, not two parsers that can drift — and fails closed on a `SENDER`
   signature delegation it cannot confirm without the live API, pointing at
   `unsubscribe_verify.py --verify` as the check that can. A broken checkout
   that cannot import `unsubscribe_verify` is a loud problem, never a skipped
   check.

8. **Human approves and activates** in Mission Control / the Woodpecker UI.
   Nothing before this point has sent anything.

9. **Inbox watch.** The three watchers poll on their own crons; the webhook
   receiver takes pushes (`prospect_replied`, `message_received`).
   _Artefact:_ `_watcher_state/<watcher>.json` (cursor, processed ids, last
   success, last error) and `_inbound_replies/<date>.jsonl`.

10. **Scope check.** `campaign_contacts.is_in_scope(channel, identity)` — an
    allowlist union of the identities found in every `*/envelope.json`,
    `_signal_touches/*.json` and `_signal_touches/_consumed/*.json`. Unknown,
    unresolvable, or an unrecognised channel is **always** False. A glob that
    matches nothing yields an empty allowlist, i.e. nobody is in scope.

11. **Classify.** `reply_classifier.classify(text)` → a `ReplyClassification`.
    Anything without a real signal match is `unclear` with `needs_human=True`.
    Quoted earlier text is stripped first, and negation-guarded phrases
    ("please don't stop sending") do not fire the objection rule.

12. **Route.** An `objection` goes to `record_objection.py` →
    `suppression_ledger.record_optout()` (person, and domain where applicable)
    **and** a Woodpecker blacklist write. `positive` and `referral` are always
    escalated to Discord even at high confidence; so is anything
    `needs_human`.
    _Artefact:_ `_suppression/ledger.json` and a Discord embed in the thread.

13. **Copy evolves.** Monthly, `copy_refresh.py --propose` regenerates snippet
    fallbacks and openers from `sdr_context`, lints them, runs the real gate,
    and writes a proposal for human approval. It never applies.

---

## 7. Data schemas

Every field below was read out of the module that writes it.

### 7.1 The build envelope and `settings_json.sdr_context`

The canonical envelope (`outreach_envelope.py`) has seven scalar fields —
`id`, `title`, `offer`, `gate_status`, `channel_mode`, `recommendation`,
`lucid_url` — and ten JSON sections: `strategy_json`, `contacts_json`,
`copy_json`, `qa_json`, `checklist_json`, `learnings_json`, `counts_json`,
`links_json`, `settings_json`, `intake_json`. Every pipeline step receives the
**whole** object; the runner records a fingerprint proof of that.

`settings_json.sdr_context` (`knowledge/__init__.py`, `SCHEMA_VERSION = 1`):

| Field                                       | Type                                                                                   | Meaning                                                                                                                                            |
| ------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`                            | int                                                                                    | bumped on a breaking change                                                                                                                        |
| `generated_at`                              | str, `YYYY-MM-DDTHH:MM:SSZ`                                                            | when the context was assembled                                                                                                                     |
| `facts_by_contact`                          | object keyed by email                                                                  | per-contact, from `context_spine`                                                                                                                  |
| `facts_by_contact[<email>].copy_safe_facts` | array of `Fact`                                                                        | **the only facts that may be cited in copy**                                                                                                       |
| `facts_by_contact[<email>].unavailable`     | array of `{source, reason}`                                                            | sources that produced nothing, with the reason                                                                                                     |
| `facts_by_contact[<email>].token_estimate`  | int                                                                                    |                                                                                                                                                    |
| `facts_by_contact[<email>].fact_count`      | int                                                                                    |                                                                                                                                                    |
| `knowledge_facts`                           | array of `Fact`                                                                        | campaign-level, citable                                                                                                                            |
| `voice_reference`                           | `{available: bool, reason: str, samples_block: str, sample_count: int, snapshot: str}` | **style only, never citable, never merged into `knowledge_facts`**                                                                                 |
| `follow_up_assets`                          | array                                                                                  | each entry always carries `auto_insert: false` and `requires_human_approval: true`; also `provider`, `kind`, `category`, `cost`, `command`, `note` |
| `source_status`                             | array of `{source, status, reason, count, newest, meta}`                               | one row per source; `status` ∈ `wired` \| `unavailable` \| `disabled`; `reason` is non-empty whenever status is not `wired`                        |
| `freshness_warnings`                        | array of `{subject, newest, age_days, threshold_days, message}`                        | material past its configured freshness threshold                                                                                                   |
| `content_assets_count`                      | int                                                                                    | our published assets available to cite                                                                                                             |

`Fact` (`knowledge/base.py::KnowledgeItem.to_dict()`, identical to
`context_spine.Fact.to_dict()` so the envelope carries exactly one fact shape):

```json
{
  "key": "recent_post",
  "value": "posted on forecast trust, 2026-08-21",
  "source": "market_intelligence",
  "url": "https://example.com/post",
  "date": "2026-08-21",
  "trust": "primary",
  "source_trust": "untrusted"
}
```

`trust` ∈ `primary | derived | inferred`. `source_trust` ∈ `trusted |
untrusted`. Invariants the collector enforces: a failing source contributes
**zero** facts and a stated reason — never a placeholder, a guessed URL, or a
"probably"; collection never raises, because any adapter exception becomes an
`unavailable` row.

**Three Trigify sources joined `FACT_SOURCES` on 2026-09-02**
(`knowledge/trigify_intel.py`), each appearing in `source_status` as
`wired` / `unavailable` / `disabled` with a real reason like every other
source. They exist because the Social-Signals buying-intent feed is not
entitled on this plan (§4); they are its read-time replacement, not the same
thing.

| `source_status.source`       | Cost                                                       | What the facts are                                                                                                                                                     |
| ---------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `trigify_prospect_activity`  | **free** (the dry-run preview endpoint)                    | the prospect's own recent LinkedIn posts, `trust: primary`. `time_frame` is config (`past-week` on this plan) because it is a real plan boundary, not a code constant. |
| `trigify_company_intel`      | paid: 1 credit + per-result                                | the company's firmographics and recent posts/launches/hiring, `trust: primary`. `max_items` is sent as the wire `limit`, so it caps spend 1:1 with results.            |
| `trigify_company_engagement` | paid: per-result on two calls (anchor post, then comments) | who publicly commented on the company's most recent post, `trust: derived`.                                                                                            |

**`trigify_company_engagement` is a PROXY, and the copy must treat it as one.**
It is public engagement on the company's **own** content — it is **not** a
mutual-connection warm path. Real warm paths come from `warm_paths.py` /
Graph.one and nowhere else. Every fact this adapter emits carries the caveat in
its own `value` string ("NOT a confirmed mutual connection, an
account-engagement signal only"), and its `unavailable` reason says the same,
so a copywriter reading only the envelope cannot overstate it. It exists
because `/v1/social/mapping`, `/v1/post/engagements` and `/v1/post/comments` —
the endpoints that would give a real engagement graph — all 403 on this plan.

Both paid sources are budget-checked **before** the call and fail closed:
an unset budget never authorises a spend, and an unreachable signal store
(no `OUTREACH_RUNS_DIR` / `OUTREACH_SIGNAL_DB`) also fails closed, because
without it the budget ledger cannot be trusted at all. `trigify_prospect_activity`
is free and never touches the budget ledger; it degrades only on an
entitlement/transport failure or an empty result.

**Four more sources joined on 2026-09-03**, taking `knowledge.collect()` to
**14**. Each obeys the same contract as every source above — zero facts and a
stated reason on failure, an honest `source_status` row, never an invented
fact or URL — and each is bound to a context dimension in
`config/context-dimensions.yaml`, so the registry-driven completeness harness
(`scripts/tests/context_join_test.py`) fails until a new source is either
wired or explicitly marked unavailable-with-reason. That mechanism, not a
hand-maintained list, is what stops this table going stale.

| `source_status.source` | Config block              | Ships          | What the facts are                                                                     |
| ---------------------- | ------------------------- | -------------- | -------------------------------------------------------------------------------------- |
| `industry_reading`     | `source_industry_reading` | `enabled`      | Substack posts and named industry articles the campaign's market is currently reading  |
| `events`               | `source_events`           | `enabled`      | webinars, conferences and speaking slots the prospect or their company runs/appears at |
| `job_changes`          | `source_job_changes`      | `enabled`      | a real, dated title/company change, diffed against `contact_snapshots`                 |
| `team_intel`           | `source_team_intel`       | **`disabled`** | short, non-attributed summaries of what our own team learned on calls (Granola)        |

**`industry_reading`** searches on campaign-level terms only (niche / offer /
segment / topics) — **never the prospect's own name**. A campaign with none of
those set makes no call at all. Every item must carry a real citation URL AND a
real date (Exa's `publishedDate`); an item missing either is dropped, the drop
is counted in `meta.dropped_missing_citation` and logged, and if every candidate
is dropped the source reports `unavailable` with the drop count in the reason
rather than a bare "0 results". `allowed_domains` is a comma-separated
allow-list (this file's parser has no nested list inside a source block) and
`recency_days` bounds the window; an absent or `<= 0` `recency_days` means **no
recency restriction**, never a guessed window.

**`events` — getting the TENSE right is a correctness bug, not a cosmetic one.**
"Sarah spoke at RevOps Live" and "Sarah is speaking at RevOps Live" are
different claims and a competent SDR is never wrong about which. Two Exa
searches are issued (a past window and a future window), but that is only to
shape the query toward event-shaped content near the right time: the PAST vs
UPCOMING wording always comes from parsing each result's **own** publish date
against "now" at classification time, never from which bucket surfaced it. A
result that appears in the "past" bucket but carries a future date still ships
as "is speaking at". A date that fails to parse **drops the item** — it is never
guessed into either bucket. The subject is built from the contact's own name
and/or company; with neither present, no call is made.

`events` also has a Trigify half that scans `/v1/company/posts` for event-shaped
language. It is real, working, entitled code that reuses `trigify_intel.py`'s
own credit-budget machinery (one definition of "an unset budget never authorises
spend", not a second implementation to drift). It ships
`trigify_company_posts_enabled: false` **purely on cost grounds** — enabling it
issues a second paid, per-result-charged call to the same endpoint in the same
envelope for substantially overlapping information. **This is a config decision,
not an entitlement gap**, and it is not the Social-Signals 403 — do not conflate
the two.

**`job_changes` replaces a capability that is gone by decision.** Trigify
Signals — which would have included job-change alerts — became unentitled on
2026-08-12 (HTTP 403, a plan cutoff, not a credits problem). This source is the
deliberate read-time replacement: refresh title/company via HarvestAPI, diff
against `contact_snapshots`, emit **only** on a real, dated change. Do not
re-litigate re-wiring Trigify Signals as "the fix". Two invariants: a **first
sighting is never a change** (it reports `unavailable` — nothing to compare
against yet — rather than a fabricated "changed"), and **a vendor failure never
overwrites good history** — every failure path returns before the single call
that writes the snapshot store, leaving it byte-for-byte as it was.

**`team_intel` ships DISABLED, and confidentiality is the whole reason.**
Granola's natural-language query can return a blended answer covering several
accounts at once. Three independent layers stand between that and the copy:
**exclusion, not redaction** (a note matching the `other_client_names` denylist
is dropped whole — a half-redacted note can still identify someone); the
existing **`pii_leak` gate run per item before anything ships**, where a blocked
item is dropped rather than sanitised into a "safer" version; and items are
**never attributed** — no meeting title, no date, no attendee name. Turning it
on means populating `other_client_names` first; an empty denylist with the
source enabled is the configuration to avoid.

### 7.8 The absent-context policy (2026-09-03)

`settings_json.sdr_context` is the join this whole section describes. What
happens when it is **missing or entirely unavailable** is a config threshold,
not a code constant, so it can be flipped either direction without a code
change (`config/presend-gates.yaml`, enforced by
`presend_gates.check_context_completeness`, called from `presend_review`):

| Key                                         | Ships   | Meaning                                                   |
| ------------------------------------------- | ------- | --------------------------------------------------------- |
| `context_completeness_required`             | `true`  | the gate runs at all                                      |
| `context_completeness_block_unattended`     | `true`  | **an unattended/autopilot build with no context BLOCKS**  |
| `context_completeness_block_human_approved` | `false` | the same envelope under human approval FLAGS and proceeds |

The asymmetry is the point: generic copy going out unattended is the exact
outcome the knowledge layer exists to prevent, while a human who can see the
flag is entitled to decide. An `sdr_context` that is present but whose every
source is `unavailable` is treated as **empty, not populated** — a table full of
honest failures is not knowledge.

### 7.2 The suppression ledger

One JSON file at `$OUTREACH_RUNS_DIR/_suppression/ledger.json`, plain JSON so
it is auditable by eye and greppable. Written under an exclusive `fcntl.flock`
across load→mutate→save so two concurrent writers cannot lose a write.

```json
{
  "persons": {
    "dana@acme.example": {
      "opted_out": true,
      "reason": "LinkedIn DM: 'please stop contacting me'",
      "recorded_at": "2026-09-02T10:15:00+00:00",
      "first_recorded_at": "2026-08-14T09:02:11+00:00"
    }
  },
  "domains": {
    "acme.example": {
      "opted_out": true,
      "reason": "company-wide opt-out request",
      "recorded_at": "2026-08-30T11:00:00+00:00",
      "first_recorded_at": "2026-08-30T11:00:00+00:00"
    }
  }
}
```

| Field               | Type                                 | Notes                                                                                                                                    |
| ------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `persons`           | object keyed by **normalised** email | case-folded, plus-tag stripped                                                                                                           |
| `domains`           | object keyed by lowercased domain    | subdomain-aware on read; free-mail domains never company-suppress                                                                        |
| `opted_out`         | bool                                 | **monotonic true-only.** There is no `clear_optout` / `unsuppress` function in the module — the re-entry loophole is closed by omission. |
| `reason`            | str                                  | re-recording refreshes this                                                                                                              |
| `recorded_at`       | ISO 8601                             | refreshed on every re-record                                                                                                             |
| `first_recorded_at` | ISO 8601                             | preserved from the first record                                                                                                          |

A ledger that exists but cannot be read raises `SuppressionLedgerError` rather
than returning empty — an empty ledger is indistinguishable from "nobody has
ever opted out". A **missing** file is different and is fine.

### 7.3 The inbox watcher state file

`$OUTREACH_RUNS_DIR/_watcher_state/<watcher>.json` — one per watcher, so each
watcher's crash or stall is its own failure domain. `<watcher>` is
`woodpecker`, `linkedin`, or `gmail`.

```json
{
  "watcher": "linkedin",
  "cursor": "eyJwYWdlIjoyfQ==",
  "processed_ids": ["linkup:urn:li:msg:7301...", "linkup:urn:li:msg:7302..."],
  "last_success_at": "2026-09-02T18:20:00Z",
  "last_error": null,
  "created_at": "2026-09-02T07:00:00Z"
}
```

| Field             | Type                                    | Notes                                                                                                                  |
| ----------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `watcher`         | str                                     | its own name                                                                                                           |
| `cursor`          | any (vendor-defined) or `null`          | durable poll cursor                                                                                                    |
| `processed_ids`   | array of str                            | idempotency ledger                                                                                                     |
| `last_success_at` | ISO 8601 `…Z` or `null`                 | **written even when 0 items were processed** — that is what makes a quiet inbox distinguishable from a stalled watcher |
| `last_error`      | `{message: str, at: ISO8601}` or `null` | recording a failure deliberately does **not** advance `last_success_at`                                                |
| `created_at`      | ISO 8601 `…Z`                           | when the state file was first created                                                                                  |

A file that exists but cannot be parsed raises `InboxStateError` — never a
silent reset (which would replay every message ever seen, or re-poll from the
beginning). A genuinely missing file is a fresh state.

### 7.4 The inbound reply store

`$OUTREACH_RUNS_DIR/_inbound_replies/<UTC-date>.jsonl`, one JSON object per
line, written by every reply-capable path. Idempotent on `event_id`: replaying
the same delivery writes nothing and returns `None`.

```json
{
  "received_at": "2026-09-02T10:15:00+00:00",
  "channel": "linkedin",
  "source_event": "message_received",
  "event_id": "linkup:urn:li:msg:7301234567890",
  "counterpart": { "profile_url": "https://www.linkedin.com/in/example/" },
  "conversation_urn": "urn:li:conv:2-ABCDEF",
  "text": "thanks, but please take me off your list",
  "delivered_at": "2026-09-02T10:14:58Z",
  "scope": "in_scope",
  "raw": {}
}
```

| Field              | Type                                            | Notes                                            |
| ------------------ | ----------------------------------------------- | ------------------------------------------------ |
| `received_at`      | ISO 8601 UTC                                    | when we recorded it                              |
| `channel`          | `"email"` \| `"linkedin"`                       |                                                  |
| `source_event`     | `"prospect_replied"` \| `"message_received"`    | the vendor event name                            |
| `event_id`         | str                                             | `wp:<id>` or `linkup:<urn>`; the idempotency key |
| `counterpart`      | `{"email": str}` or `{"profile_url": str}`      | channel-appropriate identity                     |
| `conversation_urn` | str or `null`                                   | LinkedIn only                                    |
| `text`             | str                                             | the reply body, verbatim                         |
| `delivered_at`     | ISO 8601 or `null`                              | vendor-reported                                  |
| `scope`            | `"unknown"` \| `"in_scope"` \| `"out_of_scope"` | the campaign-contacts-only allowlist decision    |
| `raw`              | object                                          | the original vendor payload                      |

Woodpecker replies are always from prospects we enrolled (the platform has no
other reply source), so those write `in_scope`. Callers **must not** alert on
or act upon an `unknown`-scope record; it exists so nothing is silently
dropped.

### 7.5 The reply classifier result

`reply_classifier.classify()` returns a frozen `ReplyClassification`:

| Field          | Type          | Notes                                                                                                                                         |
| -------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `cls`          | str           | one of the closed class set below                                                                                                             |
| `confidence`   | float 0.0–1.0 | base score for whichever rule fired                                                                                                           |
| `matched_rule` | str           | e.g. `"objection:strong:en:unsubscribe"`, `"unclear:no_match"` — the audit trail shown in Discord and logs                                    |
| `needs_human`  | bool          | always true for `unclear`; always true for `objection` (the Discord escalation contract); also true below `human_review_confidence_threshold` |
| `matched_text` | str           | the literal snippet that triggered the rule, or `""`                                                                                          |

Classes: `objection`, `negative`, `positive`, `auto_reply`, `ooo`, `bounce`,
`referral`, `unclear`. Languages: `en`, `de`, `pl`. Deterministic — no LLM — so
the same input always gives the same output and a log can name the rule.

```json
{
  "cls": "objection",
  "confidence": 0.95,
  "matched_rule": "objection:strong:en:unsubscribe",
  "needs_human": true,
  "matched_text": "take me off your list"
}
```

### 7.6 The copy-refresh proposal, version and rollback records

All under `$OUTREACH_RUNS_DIR/<runs_subdir>/` from `config/copy-refresh.yaml`;
versions in `<versions_subdir>/`.

**Proposal** (`--propose`, written monthly, never applied automatically):

| Field                    | Type                                                                                                         | Notes                                                                                                                                                                                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kind`                   | `"copy_refresh_proposal"`                                                                                    |                                                                                                                                                                                                                                                          |
| `schema_version`         | int (1)                                                                                                      |                                                                                                                                                                                                                                                          |
| `generated_at`           | ISO 8601                                                                                                     |                                                                                                                                                                                                                                                          |
| `period`, `period_label` | str                                                                                                          |                                                                                                                                                                                                                                                          |
| `status`                 | `"pending_human_approval"`                                                                                   |                                                                                                                                                                                                                                                          |
| `cadence_cron`           | str                                                                                                          | from config                                                                                                                                                                                                                                              |
| `approval.how`           | str                                                                                                          | write the marker file `<proposal>.json<approval_marker_suffix>`, then `--apply-proposal`                                                                                                                                                                 |
| `linkedin_disposition`   | str                                                                                                          | LinkedIn variants are **proposal only, hand review**; never applied by this tool                                                                                                                                                                         |
| `inputs_available`       | `{citable_facts, content_assets, facts_by_contact, source_status, freshness_warnings, context_generated_at}` | what the generator actually had                                                                                                                                                                                                                          |
| `voice`                  | `{available, sample_count, snapshot, citable: false, guidance}`                                              | style only                                                                                                                                                                                                                                               |
| `follow_up_assets`       | array                                                                                                        | forced `auto_insert: false`, `requires_human_approval: true`                                                                                                                                                                                             |
| `campaigns`              | object keyed by campaign id                                                                                  | per-campaign entry: `campaign_id`, `name`, `stream`, `persona`, `persona_label`, `campaign_objective`, `objective_source`, `period`, `period_objective`, `structure`, `email_fallbacks`, `linkedin_variants`, `inputs_used`, `lint`, `reasons`, `status` |
| `gate`                   | `{ran: bool, ...}`                                                                                           | the real `presend_review` verdict                                                                                                                                                                                                                        |
| `link_guard`, `notes`    | object / array                                                                                               |                                                                                                                                                                                                                                                          |

A campaign with no configured period objective produces an entry that **says
so** and generates nothing — no invented objective, no invented fact.

**Version record** (written **before** any PATCH, so rollback always exists):

| Field                          | Type                                                | Notes                                                                                                                     |
| ------------------------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `kind`                         | `"copy_refresh_version"`                            |                                                                                                                           |
| `campaign_id`, `campaign_name` | str                                                 |                                                                                                                           |
| `created_at`                   | ISO 8601                                            |                                                                                                                           |
| `source`                       | str                                                 | what produced this change                                                                                                 |
| `status_before`                | str                                                 | must be an allowed (DRAFT) status                                                                                         |
| `gate`                         | `{action, blocked: false, summary, sample_contact}` | the gate verdict on the rendered copy of a sample prospect                                                                |
| `changes`                      | array                                               | per email step: the token mapping, the `before` and `after` message, and `applied: bool` (flipped after a verified PATCH) |
| `rollback`                     | `{endpoint, body_per_change, command}`              | `PATCH /v2/campaigns/{cid}/steps/{sid}/versions/{vid}` with `{"message": <change.before>}`                                |
| `verified`                     | bool                                                | set true only after a byte-for-byte read-back                                                                             |

**Rollback record**: same shape with `kind: "copy_refresh_rollback"`,
`source: "rollback of <path>"`, and each change reset to `applied: false`
until its own read-back verifies.

### 7.7 The pre-send gate verdict

Every gate function in `presend_gates.py` returns this shape, and never raises
on bad input data:

```json
{
  "gate": "suppression",
  "blocked": true,
  "allowed": false,
  "warn": false,
  "halt_all": false,
  "fail_closed": false,
  "reasons": ["suppression: dana@acme.example -- opted out 2026-08-14"],
  "detail": { "matched": "person" },
  "checked_at": "2026-09-02T18:40:56+00:00"
}
```

| Field         | Type         | Notes                                                                                                                         |
| ------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `gate`        | str          | `ai_disclosure` \| `pii_leak` \| `suppression` \| `compliance` \| `deliverability` \| `art14_notice` \| `linkedin_copy_bands` |
| `blocked`     | bool         | true ⇒ do not proceed                                                                                                         |
| `allowed`     | bool         | always `not blocked`                                                                                                          |
| `warn`        | bool         | advisory only, never blocking on its own                                                                                      |
| `halt_all`    | bool         | **deliverability only**: halt _all_ sends account-wide, not just this one                                                     |
| `fail_closed` | bool         | true ⇒ blocked because the input or config could not be verified safe, not because a clean breach was found                   |
| `reasons`     | array of str | human-readable, offending values redacted                                                                                     |
| `detail`      | object       | machine-readable specifics, never raw PII beyond what `reasons` already redacts                                               |
| `checked_at`  | ISO 8601     |                                                                                                                               |

Two different failure contracts, deliberately: `load_config()` raises
`PresendConfigError` **loudly** on a missing or corrupt
`config/presend-gates.yaml` (we cannot gate anything without thresholds), while
the gate functions themselves never raise on bad _input_ — malformed input
returns a blocking `fail_closed: true` verdict.

`presend_review.review_envelope()` aggregates them:

```json
{
  "blocked": true,
  "reasons": ["art14_notice: t1-email -- first touch carries no source notice"],
  "summary": {
    "action": "build",
    "tier": "tier1",
    "touches_checked": 5,
    "contacts_checked": 18,
    "gates": [
      "ai_disclosure",
      "pii_leak",
      "suppression",
      "compliance",
      "recycling",
      "art14_notice",
      "linkedin_copy_bands"
    ],
    "unwired": {
      "deliverability": "check_deliverability requires a stats snapshot …"
    }
  }
}
```

---

## 8. Operations

### 8.1 Cron schedule

From `config/crontab.txt`. Schedules are pinned to the `schedule:` values in
`config/inbox-watchers.yaml` and `cadence_cron` in `config/copy-refresh.yaml`;
`tests/test_deploy_parity.py` asserts both, so changing one without the other
fails the suite. All of these run on the **VM host**, not in the container.

| Job                           | Schedule               | Script                                     | Log                                                                                       |
| ----------------------------- | ---------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Woodpecker email inbox        | `*/15 * * * *`         | `scripts/inbox-woodpecker-cron.sh`         | `data/openclaw/logs/inbox-woodpecker.log`                                                 |
| LinkedIn (LinkUp) inbox       | `*/10 * * * *`         | `scripts/inbox-linkedin-cron.sh`           | `data/openclaw/logs/inbox-linkedin-cron.log`                                              |
| Gmail (Maton) inbox           | `*/15 * * * *`         | `scripts/inbox-gmail-cron.sh`              | `data/openclaw/logs/inbox-gmail.log`                                                      |
| Copy-refresh **proposal**     | `10 6 1 * *` (monthly) | `scripts/copy-refresh-cron.sh`             | `data/openclaw/logs/copy-refresh.log`                                                     |
| Daily nudge                   | `30 8 * * *`           | `scripts/outreach-report-cron.sh --daily`  | `data/openclaw/logs/outreach-report.log`                                                  |
| Weekly report                 | `0 8 * * 1`            | `scripts/outreach-report-cron.sh --weekly` | `data/openclaw/logs/outreach-report.log`                                                  |
| Signal watcher (engine)       | `*/5 * * * *`          | `scripts/outreach-signal-watcher.sh`       | `data/openclaw/logs/outreach-signal-watcher.log`                                          |
| Approval listener             | `*/2 * * * *`          | `scripts/outreach-listener-cron.sh`        | `data/openclaw/logs/outreach-approval-listener.log`                                       |
| Trigify monitor               | `12 * * * *`           | `scripts/trigify-monitor-watcher.sh`       | `data/openclaw/logs/trigify-monitor-watcher.log`                                          |
| Skill sync to the three repos | `*/30 7-20 * * *`      | `scripts/outreach-skills-sync.sh`          | `data/openclaw/logs/outreach-skills-sync.log` (the script owns its log; no cron redirect) |

Every watcher cron line sets `OUTREACH_RUNS_DIR` explicitly and takes its own
`flock`, so a slow vendor response cannot stack two ticks on top of each other.
Secrets are **not** inlined in crontab rows; each wrapper loads the repo `.env`.

### 8.2 Stalled watcher vs. quiet watcher

`--status` is a **local-state-only** heartbeat: no network call, so it still
answers when the thing that would tell you "stalled" is itself what stopped
working.

```bash
python3 outreach-engine/inbox_woodpecker.py --status
python3 outreach-engine/inbox_linkedin.py  --status
python3 outreach-engine/inbox_gmail.py     --status
```

Exit codes are protocol constants, not tunables:

| Exit | Meaning                                                                                         |
| ---- | ----------------------------------------------------------------------------------------------- |
| `0`  | `healthy` (recent success, not stalled) or `never_run` (no state file yet — nothing to measure) |
| `1`  | the `--status` invocation **itself** errored                                                    |
| `2`  | the heartbeat says stale/dead — one of `never_able_to_read`, `stalled_quiet`, `recent_failure`  |

The five heartbeat statuses:

- `never_run` — no state file yet.
- `healthy` — recent success, not past `max_silence_seconds`.
- `stalled_quiet` — stalled, but the last recorded event was a **success**: the
  poll worked and nothing came back for longer than the threshold. Worth a look;
  not the same failure mode as the next one.
- `never_able_to_read` — stalled **and** the last recorded event was a failure
  (an expired key, sustained 401s).
- `recent_failure` — the last poll failed but has not yet crossed the stall
  threshold; it pages immediately rather than waiting for the threshold.

A `--commit` run follows `inbox_common.exit_code_for()`: `ok=False` is always a
non-zero exit. An HTTP/auth error is never reported as "no new replies".

### 8.3 Rolling back a copy change

Every apply writes its version record **before** the PATCH.

```bash
# list the records
ls $OUTREACH_RUNS_DIR/_copy_refresh/versions/

# roll one back (PATCHes every `before` message back, then verifies by read-back)
python3 outreach-engine/copy_refresh.py \
  --rollback $OUTREACH_RUNS_DIR/_copy_refresh/versions/<cid>-<stamp>.json \
  --runs-dir $OUTREACH_RUNS_DIR
```

The rollback refuses if the record shows no applied change, if the campaign is
no longer in an allowed (DRAFT) status, or if the campaign is not one of the
configured ids. It writes its own `copy_refresh_rollback` record.

### 8.4 Staging a real Woodpecker add without posting to Discord

`signal_woodpecker.process_build_output()` used to call `queue_bd_embed()`
unconditionally on its success path, and `dry_run=True` skips the Woodpecker
add entirely — so there was no way to stage a real add and inspect it without
posting into a live, human-monitored Discord channel. (That is exactly what
made the 2026-09-02 campaign rehearsal drop a synthetic signal into
`#business-development`.)

It now takes a `notify` parameter, default `True`, so no existing caller
changes behaviour:

```python
process_build_output(store, record, notify=False)   # real add, no Discord embed
# outcome["bd_embed"] is then None
```

On top of that sits the env kill switch `OUTREACH_SIGNAL_WOODPECKER_NOTIFY`
(same convention as `webhook_receiver.py`'s `OUTREACH_WEBHOOK_NOTIFY_ALL`).
Setting it to `0` / `false` / `no` suppresses the embed. It can only ever
**suppress**: a caller that explicitly passed `notify=False` is honoured
unconditionally, and no env value can re-enable a notification the caller
turned off. The Woodpecker add, the ledger write and the exactly-once
semantics are unchanged either way — this switch governs the Discord side
effect only, never whether the prospect is added.

### 8.5 Publishing a change to this skill

The **container workspace copy is the source of truth** for the sync:
`scripts/outreach-skills-sync.sh` stages
`/home/node/.openclaw/workspace/skills/outreach-strategist` via `docker cp` and
mirrors it to the three targets in `config/outreach-sync.conf`. A file edited
only in the repo is reverted by the next sync tick — edit **both**, or edit the
container copy and let the sync carry it back.

```bash
scripts/outreach-skills-sync.sh --dry-run   # per-target add/change/delete plan, no writes
scripts/outreach-skills-sync.sh             # real sync; change-detected commits
```

Two safety layers you will see in the log: the **content-shrink guard**
(protects any file the incoming copy would materially shrink; re-run once with
`SYNC_ALLOW_SHRINK=1` if the deletion is intended) and the **public redaction
floor** (a fail-closed allowlist scanned on the copied public tree before any
git write; a violation refuses the publish entirely).

**A guard that always fires is not a guard.** Until 2026-09-02 the shrink
guard walked the destination and flagged `subskills/<name>.SKILL.md` as
"absent on the container side" — which it structurally always is: `$SRC` never
contains a `subskills/` directory, because those four files are written into
the **destination** by the script's own post-rsync `SYNC_SUBSKILLS` loop, which
runs after the guard. Both public mirrors therefore reported FAILED and paged
Discord on every 30-minute tick (40 occurrences in the log). A path the script
materialises itself is now exempt from the "absent" branch only, derived from
`SYNC_SUBSKILLS` in config rather than a hardcoded list, and still carries an
`--exclude` filter so `--delete` can never remove it. Every other protection is
untouched: genuine shrink, same-count rewrite, salami drift, byte and
non-blank-line checks, and a genuinely absent protected path the script does
**not** write all still fail and page.

### 8.6 The seed loop, and its kill switch

The seed loop is a controlled canary: mailboxes and LinkedIn identities **we
own**, enrolled in a real campaign, so the inbound half of the system
(watcher → classifier → suppression → escalation → approval) can be proven on
real traffic without ever touching a real prospect.

**As shipped it is BUILT BUT UNARMED, by Romeo's decision on 2026-09-03**
("build it, decide sending later"). `config/seed-loop.yaml` carries **no live
allowlist**, and `seed_loop_ops.py status` exits non-zero. Nothing has been
sent, and the four inbound acceptance criteria are recorded as NOT MET rather
than quietly dropped — the system is **tested but unproven on real inbound**.

Safety is structural, not procedural:

- `seed_cohort.build_seed_cohort` **refuses the whole cohort** if any address
  falls outside the configured allowlist — it names the offending address and
  refuses, rather than silently filtering it out.
- An **empty or missing allowlist blocks**. Absent is not permission.
- Normalisation matches `presend_gates.normalize_email`, so plus-tags,
  Gmail-dot variants and look-alike domains (`.co` vs `.com`) cannot sneak
  through.
- These files are **deliberately host-only and are NOT deployed into the
  container** — they are absent from `ENGINE_FILES`/`ENGINE_CONFIGS` in
  `scripts/outreach-deploy-skills.sh` and must stay absent:
  `seed_cohort.py`, `seed_loop_ops.py`, `config/seed-loop.yaml`.
  `seed_cohort` imports `campaign_contacts.py`, which the deploy script's own
  header forbids shipping, and the config will eventually hold real mailbox
  identities.

**The kill switch.** One documented command. It halts seed enrolment **and**
pauses every named campaign, then **re-reads each campaign's status to verify
the pause actually took** — an HTTP 200 is not treated as proof, because a
check that cannot fail is not a check:

```bash
# THE kill switch: halt enrolment AND pause the named campaign(s), verified
python3 outreach-engine/seed_loop_ops.py kill \
    --campaign <id> --reason "why" --actor "<your name>"

# rehearse it without changing anything
python3 outreach-engine/seed_loop_ops.py kill --dry-run \
    --campaign <id> --reason "rehearsal" --actor "<your name>"

python3 outreach-engine/seed_loop_ops.py halt --reason "why" --actor "<name>"
python3 outreach-engine/seed_loop_ops.py status
python3 outreach-engine/seed_loop_ops.py resume --actor "<name>"
```

`resume` **never un-pauses a campaign** — un-pausing is a deliberate, separate,
human act in Woodpecker. Creating, activating or sending is structurally
unreachable from this module, and cleanup is import-only with no CLI
subcommand on purpose.

Two operational facts worth knowing before using any of it: **deleting a
Woodpecker campaign does NOT delete its prospects** (they survive and stay
ACTIVE in the account, so cleanup must delete prospects separately via
`DELETE /rest/v1/prospects?id=<pid>` and end on a residue assertion), and the
v1 prospects filter params (`search=`, `email=`) are **ignored** by the API —
it returns everything, so filter client-side. `GET /rest/v2/campaigns` (list)
returns 405; read campaigns by id.

---

## 9. Compliance posture

- **GDPR Art. 14 source notice.** The first communication must tell the person
  where we got their data. Enforced by `presend_gates.check_art14_notice`, wired
  per touch position and per channel: a non-email touch is exempt only when an
  email in the _same_ sequence carries the notice, so a LinkedIn-only sequence
  has no exemption.
- **GDPR Art. 21 objections are absolute, person-level, and cross-channel.** An
  objection raised on any channel — email reply, LinkedIn DM, InMail, phone —
  writes to the one canonical ledger and blocks that person on **every**
  channel. The ledger is sticky by construction: `presend_gates` exposes no
  function that can clear an opt-out, so a later re-import cannot silently
  un-suppress anyone. `objection_e2e_test.py` exercises this adversarially
  (42 scored checks, including dot/plus-tag folding, IDN-vs-punycode, disk-full
  mid-write, SIGKILL between classify and record, concurrent writers, and an
  out-of-scope sender saying "stop").
- **Jurisdiction gate.** `check_compliance` resolves a jurisdiction from the
  contact's fetched country through a config table. Unmapped but non-empty ⇒
  `UNKNOWN`, treated as strictly as DE. Empty or unusable ⇒ the configured
  **strictest** row. Never the most permissive.
- **Unsubscribe evidence must be live and dated.** `unsubscribe_verify.py`
  supplies `has_unsubscribe` from real Woodpecker verification; stale evidence
  (past the configured max age) blocks even a US contact.
- **Campaign-contacts-only, both channels — BINDING.** The Gmail and LinkedIn
  watchers act **only** on threads whose counterpart is a contact we ourselves
  enrolled in an outbound campaign. Clients, suppliers, partners, live sales
  conversations, inbound pitches, and every unknown sender are **invisible**:
  not classified, not logged, never replied to. This is an allowlist, never a
  denylist, and unknown or ambiguous is out of scope. Implemented in
  `campaign_contacts.is_in_scope()`; the allowlist source globs are in
  `config/inbox-watchers.yaml`.
- **AI disclosure.** `check_ai_disclosure` is keyed to _who sends_. At tier1 a
  human sends and no label is required or accurate; promoting a stream to tier2
  turns the requirement on with no code change. Background:
  `docs/compliance/eu-ai-act-art50.md`.
- **Legitimate interest.** The written assessment is
  `docs/compliance/legitimate-interest-assessment.md`. `legal_basis` is an
  operator declaration in config — undeclared blocks wherever an LIA is
  required. That is a human's field to fill, never the engine's to guess.

### What remains manual

- **Activation.** Every campaign is activated by a human in the Woodpecker UI.
- **InMail objections.** Recorded by a human running `record_objection.py` (see
  §10).
- **Declaring a legal basis** per list/jurisdiction.
- **Autonomy-tier promotion**, and any change to guardrails.
- **Applying a copy-refresh proposal** — writing the approval marker file is a
  human act, and LinkedIn variants are never applied by the tool at all.

---

## 10. Limits and known gaps

Stated plainly because a hidden limit is worse than a known one.

1. **InMail identity resolution is not possible on LinkUp today.** The
   Sales-Nav/InMail store is readable (`sales_nav: true` returned real
   conversations on 2026-09-02, even though the account's `sales_nav.connected`
   flag reads `false`), but a LinkUp conversation counterpart cannot be resolved
   to an enrolled contact reliably enough to auto-act under the
   campaign-contacts-only allowlist. **InMail objections are therefore handled
   manually** via `record_objection.py`. If InMail reads start failing, the
   Sales Nav seat must be connected in LinkUp.
2. **LinkUp path discipline.** The only correct endpoint is the action-style
   `POST /v2/messages`. `/v2/inbox/list`, `/v2/messages/inbox`, `/v2/inbox` and
   `/v2/message` all return a misleading generic 404 `INVALID_ACCOUNT`. A
   doc-summariser invented `/v2/inbox/list`; it does not exist.
3. **LinkUp webhook retry policy and hosted-mode SSE are unexercised.** Verify
   on first registration. **Unverified** until then.
4. **Trigify Social Signals, social mapping, topics and post engagements are
   plan-gated — not broken, and not a credit problem.** The account has credit
   (4000/month limit). Every `/v1/social-signals/*` call returns HTTP 403
   "Signals is not enabled for this workspace"; `social/mapping`,
   `discover/creators`, `post/engagements`, `post/comments(+replies)` and
   `profile/engagement/*` are likewise 403, and `topics/*` needs Enterprise. No
   code change can open any of them, and none is retried or worked around. The
   entitled surface is wired instead (§4, §7.1). Consequences to keep in mind:
   the buying-intent feed contributes nothing, so "no Trigify signal" still
   means "not measured"; and `trigify_company_engagement` is an
   account-engagement **proxy**, never evidence of a mutual connection.
5. **`hooks.man.digital` does not resolve usefully from every internal
   layout.** Vendors POSTing to the tunnel reach the receiver; a local lookup
   from the Mac returns edge addresses that then time out, so a failed local
   `curl` is not evidence the receiver is down. The polling watchers are the
   designed backstop precisely because push cannot be the only path. The DNS
   behaviour itself is an operator observation, **not measured from this
   checkout**.
6. **macOS needs bash 4 for some suites.** `test_outreach_sync_protect.sh` is
   100/100 on the VM and fails on the Mac on a macOS-only double-logging quirk;
   `run-all-harnesses.sh` lists it as skipped **with the reason** rather than
   hiding it.
7. **`deliverability` is declared unwired**, with the reason recorded in code
   and asserted by a test (§6, step 6). Complaint rate does not exist in the
   Woodpecker API; wiring it needs an external feed such as Google Postmaster
   Tools for the sending domains.
8. **The container unit suite ships against a deliberate module allowlist.**
   A test whose imports are not all on `ENGINE_FILES` is skipped by the deploy
   selection on purpose, with a printed reason. Do not read a skipped
   in-container test as a passing one.
9. **`campaigns/README.md` and everything under `campaigns/_template/` are
   name-based public carve-outs.** The sync's redaction floor trusts those two
   paths _by name_ and
   never inspects their content. Anything typed into either publishes verbatim
   to two public GitHub repos on the next tick. This is a human-trust boundary
   that no scan can close.
10. **Zernio YouTube transcripts are disabled**, not broken: the key
    authenticates but the Tools API is not on our plan (HTTP 403). Reddit is
    similarly unavailable — the Data API is not open to us, so expect zero rows
    and a `collector_notes` entry saying so.

---

## Design rules worth stealing

1. **Skill = role, campaign = folder.** A new campaign is a data change, not a
   prompt change.
2. **Dossier-gated copy.** No per-contact research dossier with a fresh
   (≤90-day) linkable observable → no sequence. This kills AI slop at the source.
3. **One person, one stream.** A cross-stream routing table with explicit
   transitions and a global suppression list; a contact found in two streams is
   an incident to report, not a statistic.
4. **Gates are code, not prompt instructions.** A system-prompt request is a
   suggestion; a fail-closed function that returns a blocking verdict is a
   guardrail. Every gate is deterministic and every one has a caller —
   `test_suite_integrity.py` fails if a gate is neither wired nor listed as
   unwired with a reason.
5. **A source that failed contributes zero facts and a stated reason.** Never a
   placeholder, never a guessed URL, never "probably". `unavailable` means we
   have no facts from it — not that there is nothing to know.
6. **Honest reporting.** Metrics the agent cannot verify are reported `n/a`,
   never invented.

---

## Repository layout of this skill

| Path                                                                       | What it is                                                                                                                     |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `SKILL.md`                                                                 | the strategist role: campaign folders, streams, preflight, autonomy tiers, delegation map, reporting duties                    |
| `README.md`                                                                | this file                                                                                                                      |
| `bin/kb.py`                                                                | the persistent memory CLI — a SQLite event log + knowledge graph at `knowledge/outreach.db`                                    |
| `campaigns/_template/`                                                     | copy to `campaigns/<slug>/` to add a campaign. Campaign folders are DATA; the skill stays generic                              |
| `campaigns/README.md`                                                      | the campaign-folder schema                                                                                                     |
| `subskills/`                                                               | reference copies of the four pipeline skills' `SKILL.md` as deployed (public mirrors only)                                     |
| `knowledge/`, `dossiers/`, `banks/`, `LEARNINGS.md`, real campaign folders | **private** — redacted from both public mirrors by `config/outreach-sync.conf` and refused by the sync's fail-closed allowlist |

No credentials live anywhere in this folder. All secrets come from container
env or runtime config at the deployment site.

### This file's history

This README is authored **here, in the skill source**, and in the container
workspace copy — not in either public mirror. It is deployed outward by
`scripts/outreach-skills-sync.sh` to both public targets (`SYNC_TARGETS` in
`config/outreach-sync.conf`) and protected from deletion there via
`SYNC_PROTECTED_PATHS`. Editing a mirror's copy directly will be overwritten on
the next sync tick.

---

**Verified on 2026-09-03.** What was re-run on the Mac checkout at
`/Users/romeoman/openclaw-infra` for this revision (§4 Trigify entitlement,
§5.4 notify routing, §6 cohort dedupe + creation-time unsubscribe check, §7.1
Trigify sources, §8.4 `notify`, §8.5 sync guard, §10):

- `python3.13 -m pytest outreach-engine/tests/{test_cohort_dedupe,test_notify_routing,test_signal_woodpecker,test_knowledge_trigify_intel,test_trigify_client,test_cron_notify_env_wiring}.py` → **111 passed**
- `bash scripts/tests/sync_shrink_guard_test.sh` → **34 passed, 0 failed**
- `bash outreach-engine/tests/test_outreach_report_cron.sh` → **ALL PASS** (4 cases)
- `python3.13 scripts/tests/objection_e2e_test.py` → `RESULT: 42/42 scored checks passed` (0 documented findings)

Carried over from the 2026-09-02 revision, not re-run here:

- `python3 scripts/tests/dummy_pasted_list_test.py` → `20/20 checks passed at 2026-09-02T18:40:56+00:00`, "Nothing was sent, staged, activated, listed, or written to the kb."
- `bash scripts/tests/run-all-harnesses.sh --list` → the 9-harness Mac manifest, plus the 3 harnesses it lists as skipped on this layout with their reasons
- `sha256sum` comparison of `SKILL.md` and `LEARNINGS.md` between the repo copy
  and the container copy at
  `/home/node/.openclaw/workspace/skills/outreach-strategist/` → identical

The container was deliberately **not** touched while writing this revision, so
no in-container or live-vendor call was made for it. The Trigify entitlement
and cost figures in §4 are the live 2026-09-02 measurements recorded in
`outreach-engine/trigify_client.py`'s module docstring and
`docs/trigify-setup.md`; they were read out of those files, not re-measured.

Every schema in §7, every gate in §6, every env var name in §4, and every cron
row in §8 was read out of the module, config, or script that owns it. The
LinkUp endpoint contract and credit costs in §4 come from the dated vendor
verification recorded in `.claude/tasks/review-findings-sdr-autopilot.md`
(Addendum 2, live read-only checks on 2026-09-02). Items marked **unverified**
were not exercised.
