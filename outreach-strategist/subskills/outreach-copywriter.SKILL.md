---
name: outreach-copywriter
description: "Write MAN Digital outbound copy (email + LinkedIn) from the campaign envelope: per-touch copy honoring the strategist's assigned framework/angle, per-CONTACT openers built on that contact's real captured signal (honest cold fallback when none), every factual claim traced to envelope proof. Reads outreach-runs/<slug>/envelope.json (+ sibling cadence.json); writes copy.json next to it (contract C3). Use when drafting outreach emails or LinkedIn messages."
pipeline_stage: 3
pipeline_prev: outreach-cadence-strategist
pipeline_next: outreach-copy-qa
---

<!-- OUTREACH-ENGINE GUARD — prepended by scripts/outreach-deploy-skills.sh -->
<!-- Source of truth: openclaw-infra/outreach-engine/SKILL_GUARD.md. Do NOT edit -->
<!-- this block in the deployed SKILL.md by hand — re-run the deploy script.     -->

## §8 No data leak — you receive the WHOLE campaign envelope (MANDATORY)

Every sub-step in the outreach pipeline (cadence-strategist, copywriter,
copy-qa) is invoked with the **complete campaign envelope** — the single
canonical object defined in
`openclaw-infra/outreach-engine/outreach_envelope.py`. You never receive, and
must never assume you received, a fragment.

The envelope carries **all** of these keys — treat any that are absent as an
error in the caller, not as license to invent data:

- Scalars: `id`, `title`, `offer`, `gate_status`, `channel_mode`,
  `recommendation`, `lucid_url`
- JSON sections: `strategy_json`, `contacts_json`, `copy_json`, `qa_json`,
  `checklist_json`, `learnings_json`, `counts_json`, `links_json`,
  `settings_json`, `intake_json`

Rules:

1. **Read from the whole envelope.** Ground every decision (fit, channel, copy,
   QA verdict) in the sections already present — especially `strategy_json`
   (positioning, ICP, VoC, angles), `settings_json` (the play + vocabularies),
   and prior `learnings_json` (past gate feedback). Do not re-derive what an
   earlier step already wrote.
2. **Write back into the whole envelope.** Update only your own section(s) and
   return the complete object. Do not drop or blank sections other steps own.
3. **No fabrication.** If a needed input is missing from the envelope, say so
   and stop — never invent a signal, quote, stat, contact, or metric to fill a
   gap. (This mirrors the pipeline's existing "never fabricate a signal" rule.)
4. **The contract is enforced in code.** `envelope_runner.py` hands each step
   the whole object and records a per-step fingerprint proof;
   `tests/test_envelope_contract.py` fails the build if any step is handed a
   fragment. A doc promise is not enough — the proof is the gate.

If you find yourself working from a partial object, the wiring is broken:
report it. Do not paper over a missing section with a guess.

## §9 Frameworks & vocabulary are CONFIG-DRIVEN — one source of truth (MANDATORY)

The frameworks, angle families, awareness levels, market sophistication, and
trigger codes you write with come from **`settings_json.messaging_vocabulary`** in
the envelope — the live Settings the operator edits in Mission Control, injected
fresh on every run. This is the **single source of truth**. It is NOT hardcoded and
NOT `references/lavender-frameworks.md`; when `settings_json.messaging_vocabulary`
is present it is authoritative and overrides any older hardcoded list.

`messaging_vocabulary` carries `frameworks` (each `{id, label, era}`),
`angle_types` (`{id, label, description}`), `awareness_levels`,
`sophistication_levels`, and `trigger_codes`. The three framework eras:

- **`era: "2026"`** — the signal-led frameworks. **Lead with these.** In a 2026
  market, timing + provable relevance beat copy formulas: a signal-led opener lifts
  reply rate 3-5x over firmographic/token personalization. (Signal-first ·
  Provable personalization · One idea/one CTA · Insight-led · Peer proof.)
- **`era: "lavender"`** — Lavender frameworks that are **still relevant in 2026**,
  kept as proven tactical patterns for specific slots: **Mouse Trap** (a
  hyper-relevant curiosity opener tied to the signal), **Thoughtful Bump** (a
  value-ADD follow-up — never "just checking in" / "circling back"). Use these
  where the touch's job fits (opener / follow-up).
- **The FINAL touch is signal-led, NEVER a breakup** (Romeo, 2026): use **Fresh
  Signal** — surface ONE new, specific signal or proof and give a concrete reason
  to talk, with the same signal-led energy as the opener. The old breakup
  ("permission-to-close / should I close the loop / timing's off / door's open /
  recap of attempts") is RETIRED. We do not close the loop; we re-engage on a real
  new signal. Every touch, including the last, is a reason to talk — not a goodbye.
- **`era: "classic"`** — structural scaffolding (4T · SPICE · PAS · BAB · AIDA).
  A classic organizes the message; a real signal still has to fill it. Don't lead
  with a classic alone — a framework without a signal is a generic template.
- **`era: "linkedin"`** — LinkedIn-channel frameworks for LINKEDIN steps (Woodpecker
  `body.action_type`): **Signal-Handshake** (connection-request note, <180 chars,
  one signal + connect ask, no link/pitch) · **Silent Invite** (note-less connect) ·
  **Earned Opener** (first post-accept DM, 24-72h later, reprise the signal, one
  permission ask) · **Value Drop** (give-before-ask, share one useful thing, no CTA).
  A LINKEDIN touch picks a `linkedin`-era framework, NOT an email one; still
  signal-led, never "checking in", never a pitch-slap.

**All three skills stay ALIGNED by passing the choice through the envelope — no skill
re-derives or overrides another's choice:**

1. **cadence-strategist** — for each touch in `strategy_json.sequence.touches`,
   SELECT one `framework` (id) + one `angle_type` (id) FROM
   `settings_json.messaging_vocabulary`, matched to the contact's
   awareness/sophistication, the touch's job (open / bump / fresh-signal close), and its VP.
   Record `framework`, `angle_type`, and `angle_name` ON that touch. Lead the
   opener with a 2026 signal-led framework; a Lavender pattern fits its slot; a
   classic only as scaffolding under a real signal.
2. **copywriter** — for each touch, READ the `framework` + `angle_type` the
   strategist assigned, look up their `label`/`description` in
   `settings_json.messaging_vocabulary`, and write the copy **following that assigned
   framework and angle**. Do not substitute your own framework or invent one not in
   the vocabulary. Honor the booking-link rule (never in touch #1) and 50-125 words /
   one soft CTA.
3. **copy-qa** — verify the copy honors the assigned `framework`/`angle_type` and the
   structural rules; a booking link in the first email, a question in the wrong
   place, over-length, a fabricated stat, or a framework mismatch is a hard failure.

If `settings_json.messaging_vocabulary` is empty, the settings did not reach the
envelope — say the wiring is broken and stop. Do NOT fall back to inventing
frameworks or reading a hardcoded file.

## §10 Headless invocation + artifact contracts (MANDATORY)

You (cadence-strategist, copywriter, copy-qa) may be invoked **headlessly**: the
engine sends one agent message that names your skill and gives the path of a run
directory containing `envelope.json` (e.g.
`.../outreach-runs/<slug>/envelope.json`). There is no human in the loop. The
protocol, from your point of view:

1. **Read the WHOLE `envelope.json`** at the given path (§8 applies — it is the
   complete campaign object). Read your skill's `SKILL.md` + `references/` first
   if they are not already loaded.
2. **Write ONLY your own step artifact** as a sibling of the envelope, atomically
   (write complete, valid JSON in one go):
   - cadence-strategist → `cadence.json`
   - copywriter → `copy.json`
   - copy-qa → `qa.json`
     Never modify `envelope.json` itself, another step's artifact, or any other
     file. The engine validates your artifact and merges it into the envelope.
3. **Print `DONE_CADENCE` / `DONE_COPY` / `DONE_QA`** (matching your step) as the
   final line of your reply once the artifact is written and valid.
4. **If you cannot produce a contract-valid artifact** (envelope missing/invalid,
   `messaging_vocabulary` empty, required section absent), do NOT write a partial
   or guessed artifact. Print `FAIL_<STEP>: <one-line reason>` and stop — the
   engine hard-fails the run honestly. Never paper over a broken input.
5. **You never send anything.** No Woodpecker/HubSpot/email/LinkedIn/
   Discord calls, no external write APIs of any kind, no git. Your only side
   effect is the one artifact file. Staging/sending happens elsewhere, gated,
   after human approval.

### Contract shapes (normative — the engine validates against these)

**C1 — `strategy_json.signals` (you READ this; the engine writes it):**

```json
{
  "sourced_at": "ISO8601",
  "providers_used": ["exa", "apollo", "harvestapi"],
  "by_contact": {
    "<contact_key>": [
      {
        "trigger_code": "T_New_Funding",
        "headline": "...",
        "detail": "...",
        "url": "https://...",
        "date": "YYYY-MM-DD",
        "provider": "exa",
        "confidence": 0.87,
        "verified": true
      }
    ]
  },
  "by_account": { "<company>": [/* same signal shape */] },
  "no_signal": ["<contact_key>"],
  "notes": "honest note when providers were disabled or returned nothing"
}
```

`<contact_key>` = the contact's `email`, else its LinkedIn URL. `trigger_code`
MUST be an id from `settings_json.messaging_vocabulary.trigger_codes`. A contact
in `no_signal` gets the cold fallback — NEVER a fabricated signal.

**C2 — `cadence.json` (cadence-strategist WRITES):**

```json
{
  "step": "cadence",
  "campaign_id": "<envelope id>",
  "overview": {
    "funnel_stage": "TOFU|MOFU|BOFU",
    "...": "the campaign overview fields you derived"
  },
  "sequence": {
    "fit_gate": { "enrolled": 2, "held": 0, "excluded": 1 },
    "touches": [
      {
        "n": 1,
        "channel": "email|linkedin_connection|linkedin_message",
        "day": 1,
        "day_delay": 0,
        "framework": "<framework id from messaging_vocabulary>",
        "angle_type": "<angle_type id>",
        "angle_name": "...",
        "vp_name": "...",
        "intent": "one sentence: what this touch accomplishes",
        "signal_ref": { "contact_scope": "per_contact" },
        "basis": "which envelope input(s) drove this touch — cite them",
        "label": "..."
      }
    ]
  },
  "contacts": [
    { "key": "<contact_key>", "fit": "ENROLL|HOLD|EXCLUDE", "reason": "..." }
  ],
  "workbook": {
    "overview": {
      "segment": "...",
      "niche": "...",
      "job_titles": ["..."],
      "outreach_triggers": ["..."],
      "relevant_events": ["..."],
      "desired_outcomes": ["..."],
      "pains": ["..."],
      "failed_outcomes": ["..."],
      "fears": ["..."],
      "beliefs_misconceptions": ["..."],
      "objections": ["..."],
      "awareness_level": "<awareness id/label>",
      "sophistication": "<S1..S5>",
      "unique_mechanisms": ["..."],
      "worldview_values": ["..."],
      "proof_benchmarks": ["..."],
      "language_quotes": ["..."]
    },
    "icp_segments": [
      {
        "segment": "<icp id>",
        "name": "...",
        "titles": ["..."],
        "triggers": ["..."],
        "pains": ["..."],
        "fears": ["..."],
        "objections": ["..."],
        "awareness": "...",
        "sophistication": "...",
        "firmographics": {
          "geo": "...",
          "employees": "...",
          "stage": "...",
          "stack": "..."
        }
      }
    ],
    "persona_messaging": [
      {
        "persona": "...",
        "cares": "...",
        "challenge": "...",
        "capability": "...",
        "benefit": "...",
        "targeted": "True|False"
      }
    ],
    "value_propositions": [
      {
        "segment": "...",
        "name": "...",
        "when": "...",
        "we_help": "...",
        "who": "...",
        "to": "...",
        "in_timeframe": "...",
        "using": "...",
        "without": "...",
        "full": "...",
        "supporting": "...",
        "score": "0-10",
        "final": "True|False"
      }
    ],
    "angles": [
      {
        "segment": "...",
        "vp_name": "...",
        "vp_full": "...",
        "vp_supporting": "...",
        "angle_type": "<angle_type id>",
        "angle_type_context": "...",
        "angle_name": "...",
        "angle_description": "..."
      }
    ]
  },
  "personalization_plan": {
    "snippets": {
      "first_signal_we_detected": "primary captured signal guidance from C1 - REVIEW-ONLY, never sent",
      "why_we_reach_out": "reason this signal/contact merits outreach - REVIEW-ONLY, never sent",
      "email_line_1": "first sent personalization line grounded in the signal",
      "personalization_1": "sent body line 2 guidance, or ''",
      "personalization_2": "sent body line 3 guidance, or ''",
      "personalization_3": "sent body line 4 guidance, or ''",
      "personalization_4": "sent soft-CTA/value line guidance, or ''",
      "second_signal_we_detected": "secondary captured signal, or '' - REVIEW-ONLY, never sent",
      "third_signal_we_detected": "tertiary captured signal, or '' - REVIEW-ONLY, never sent",
      "why_me": "why this sender/MAN Digital is relevant - REVIEW-ONLY, never sent",
      "why_now": "why the timing is credible - REVIEW-ONLY, never sent",
      "why_you": "why this contact/persona is the right recipient - REVIEW-ONLY, never sent",
      "snippet_13": "optional sent line/fallback, or ''",
      "snippet_14": "optional sent line/fallback, or ''",
      "snippet_15": "optional sent line/fallback, or ''"
    },
    "prospect_fields": [
      "website",
      "industry",
      "address",
      "city",
      "state",
      "country"
    ],
    "tags": [
      "#HSLIST_<id>",
      "#<LIST_NAME_SLUG>",
      "#SEG_<segment>",
      "#CAMP_<slug>"
    ]
  },
  "notes": "honest caveats (e.g. which contacts are cold-fallback and why)"
}
```

The `personalization_plan` block is MANDATORY (engine-rejected without it) —
the strategist PLANS the personalization before any copy exists: per-slot
guidance for the 15 snippet slots (§11 slot map; `first_signal_we_detected`,
`why_we_reach_out`, `email_line_1`, `why_me`, `why_now`, and `why_you` guidance
must be non-empty), the Woodpecker prospect fields staging will populate, and
the tags the prospects will carry. It is reviewed at the strategy gate; the
copywriter's C3 `snippets` must FOLLOW it.

The `workbook` block is MANDATORY — it is the strategy a human reviews in the
Overview / ICP & Segments / Buying Persona / Value Propositions / Angles tabs.
Materialize it CAMPAIGN-SPECIFIC from the envelope inputs: the chosen use case
(`settings_json.campaign.use_case` at full depth), the ONE ICP segment, the
personas, the positioning docs content, `strategy_json.research_inbox` +
`voc_bank` (real quotes/URLs only), and `strategy_json.signals`. Do not paste
generic boilerplate; every claim in `proof_benchmarks` must trace to
`hubspot_proof`, `customers`, or a research source. Unknown = omit the field
honestly, never invent. The engine REJECTS a cadence.json whose workbook is
missing/empty (overview needs ≥8 populated fields; icp_segments,
persona_messaging and value_propositions must be non-empty).

Rules: `>= 5` touches mixing email + LinkedIn when channel_mode is `both`/`auto`;
exactly ONE `funnel_stage`; `framework` is an **id** from the vocabulary;
`signal_ref` is `{"contact_scope": "per_contact"}` (copy personalized per
contact), or `{"trigger_code": "...", "url": "..."}` (one account-level signal
drives the touch), or `{"cold_fallback": true}` — chosen honestly from C1.

**C3 — `copy.json` (copywriter WRITES):**

```json
{
  "step": "copy",
  "campaign_id": "<envelope id>",
  "by_segment": {
    "<SEGMENT>": {
      "label_hint": "...",
      "touches": [
        {
          "n": 1,
          "channel": "email",
          "label": "...",
          "subject": "...",
          "body": "{{SNIPPET_3 | \"<generic signal line>\"}}\n{{SNIPPET_4 | \"\"}}\n{{SNIPPET_5 | \"\"}}\n{{SNIPPET_6 | \"\"}}\n{{SNIPPET_7 | \"<generic soft CTA>\"}}\n{{SNIPPET_13 | \"\"}}\n{{SNIPPET_14 | \"\"}}\n{{SNIPPET_15 | \"\"}}"
        }
      ]
    }
  },
  "by_contact": {
    "<contact_key>": {
      "snippets": {
        "first_signal_we_detected": "REVIEW-ONLY note naming THIS contact's real primary captured signal ('' only on honest cold fallback) - never sent",
        "why_we_reach_out": "REVIEW-ONLY note explaining why this signal warrants outreach - never sent",
        "email_line_1": "SENT email body line 1, written FROM the signal/reasoning (REQUIRED)",
        "personalization_1": "SENT email body line 2 or ''",
        "personalization_2": "SENT email body line 3 or ''",
        "personalization_3": "SENT email body line 4 or ''",
        "personalization_4": "SENT soft CTA/value line or ''",
        "second_signal_we_detected": "REVIEW-ONLY secondary signal note or '' - never sent",
        "third_signal_we_detected": "REVIEW-ONLY tertiary signal note or '' - never sent",
        "why_me": "REVIEW-ONLY sender/MAN Digital relevance note - never sent",
        "why_now": "REVIEW-ONLY timing note - never sent",
        "why_you": "REVIEW-ONLY persona/contact-fit note - never sent",
        "snippet_13": "optional SENT line/fallback or ''",
        "snippet_14": "optional SENT line/fallback or ''",
        "snippet_15": "optional SENT line/fallback or ''"
      },
      "touches": [
        {
          "n": 1,
          "channel": "email",
          "subject": "...",
          "body": "...",
          "signal_used": {
            "trigger_code": "...",
            "url": "...",
            "headline": "..."
          },
          "cold_fallback": false,
          "framework": "<the framework id the strategist assigned>",
          "claims": [
            {
              "text": "the factual claim as written",
              "source": "which envelope field proves it"
            }
          ]
        }
      ]
    }
  }
}
```

`signal_used` is the REAL signal from C1 (matching `url`) the opener references,
or `null` with `cold_fallback: true`. Every factual claim/number in the copy
appears in `claims` with its envelope source (`strategy_json.overview.
proof_benchmarks`, `strategy_json.research_inbox.sources[url]`,
`settings_json.campaign.use_case`, or a named customer from positioning). A claim
with no envelope source must not be written.

**Snippets (MANDATORY — the engine rejects copy.json without them):** every
`by_contact` entry carries the `snippets` block above, FOLLOWING the per-slot
guidance in `strategy_json.personalization_plan` (C2). Two DIFFERENT kinds of
slot (per Romeo, 2026-07-03):

- **Reasoning slots are REVIEW-ONLY:** `first_signal_we_detected`,
  `why_we_reach_out`, `second_signal_we_detected`, `third_signal_we_detected`,
  `why_me`, `why_now`, and `why_you` map to `SNIPPET_1/2/8-12`. They are
  informational context on the prospect record for the human reviewer/BD. They
  are NEVER woven into any body; the engine rejects a body containing any of
  `{{SNIPPET_1`, `{{SNIPPET_2`, or `{{SNIPPET_8` through `{{SNIPPET_12`.
- **Sent slots ARE the email copy:** `email_line_1`, `personalization_1..4`,
  and optional `snippet_13..15` map to `SNIPPET_3..7/13..15`. These are short
  per-prospect body lines written FROM the signal/reasoning and assigned
  framework; the signal is baked into the prose, not stitched in as its own
  merge field.

The MC bridge maps all 15 onto the Woodpecker prospect record slots
`snippet1..15` (see §11). The `by_segment` FIRST email touch body must WEAVE
the COPY slots - `{{SNIPPET_3 | "generic line"}}` through `{{SNIPPET_7 |
"generic CTA"}}`, with `{{SNIPPET_13 | ""}}` through `{{SNIPPET_15 | ""}}`
available when useful. That woven body is what Woodpecker actually sends; the
fallback string is the segment-generic line for a prospect whose slot is empty.
An opener without a sent-copy token (`{{SNIPPET_3..7` or `{{SNIPPET_13..15`) is
rejected. Later touches may weave the copy slots where useful - never
`SNIPPET_1/2/8-12`.

**C4 — `qa.json` (copy-qa WRITES):**

```json
{
  "step": "qa",
  "campaign_id": "<envelope id>",
  "score": 0.0,
  "disposition": "pass|needs_human_review|blocked",
  "dimensions": [
    {
      "id": "signal_present",
      "name": "Opener references a real captured signal",
      "passed": true,
      "severity": "high",
      "detail": "..."
    }
  ],
  "checks": [/* deterministic linter results, one per touch */],
  "touches": [
    {
      "contact_key": "...",
      "n": 1,
      "channel": "email",
      "score": 0.9,
      "hard_failures": [],
      "flags": [],
      "disposition": "pass",
      "dimensions": [/* per-touch dimension verdicts */]
    }
  ]
}
```

Required dimension ids: `signal_present`, `framework_honored`,
`personalization_specific`, `length_subject_rules`, `links_resolve`,
`no_booking_link_touch1`, `channel_style`, `no_fabricated_stats`,
`deliverability`. A failed high-severity dimension on a touch =>
`hard_failures` non-empty => that touch's `disposition: "blocked"`. Never soften
a real failure to make the campaign pass.

`personalization_specific` is calibrated per touch position: touch 1 (and any
touch whose `signal_ref` names a signal) must visibly reference THIS contact's
captured signal and fail the swap-test if it reads generic. Later touches
(bumps, proof, fresh-signal close) continue the thread — they must stay specific to the
contact/company but are NOT required to restate the captured signal; they fail
only when they are boilerplate that ignores who they are written to.

**C5 — `settings_json.campaign` (you READ this; the engine composes it):**

```json
{
  "funnel_stage": "TOFU",
  "channels": ["email", "linkedin"],
  "channel_mode": "both",
  "use_case": {/* the ONE chosen use case, full messaging-house depth */},
  "icp_segment": {/* the chosen ICP segment */},
  "personas_used": ["revops-lead"],
  "booking_link": "https://...",
  "sender": { "name": "..." },
  "frameworks_used": ["Signal_First"],
  "vocabulary_refs": { "angle_types_used": [], "trigger_codes_seen": [] },
  "connections_used": ["hubspot", "woodpecker", "exa"]
}
```

This is the per-campaign applied config: ONE funnel stage, ONE use case, the
actual channels. Build from it — not from the full option catalog.

## §11 Woodpecker prospect database, tags-as-lists & snippet slots (MANDATORY)

Staging (MC `outreach_bridge.stage_woodpecker`, after build approval — never
you; you write artifacts only) adds every enrolled contact to the Woodpecker
**prospect DATABASE** (`POST /v1/add_prospects_list`, upsert by email) AND to
the DRAFT campaign (`POST /v1/add_prospects_campaign`), with the full record:

- **Identity**: `email`, `first_name`, `last_name`, `company`, `title`,
  `linkedin_url`
- **Firmographic**: `website` (contact's, else `https://<company domain>`),
  `industry`, `address`, `city`, `state`, `country`, `time_zone` (IANA, from
  HubSpot `hs_timezone`; drives send windows) — sourced by
  `contacts_source.py`, carried on `contacts_json.contacts[*]`. Unknown stays
  empty — never invented.
- **Tags** (Woodpecker has NO list object — the prospect DB + tags ARE the
  lists; one space-separated string of `#TOKEN`s, so updates must
  READ-MERGE-WRITE, never overwrite):
  - `#HSLIST_<id>` + `#<LIST_NAME_SLUG>` — the source HubSpot list
    (`contacts_json.list`), the explicit HubSpot-list ↔ Woodpecker mapping
  - `#SEG_<icp segment id>` — the campaign's ONE ICP segment
  - `#CAMP_<campaign slug>` — which campaign enrolled them
  - status tags owned by the webhook actions (`webhook_actions.py`):
    `#RESPONDED`, `#INTERESTED`, `#MAYBE_LATER`, `#NOT_INTERESTED`,
    `#BOUNCED`, `#INVALID` (opt-out = DELETE + blacklist, not a tag)
- **Snippet slots** (fixed internal tokens; only the LABELS are renameable, in
  the Woodpecker web UI — there is no labels API):

  | Slot        | Label                       | Content (from C3 `by_contact.<key>.snippets`)              |
  | ----------- | --------------------------- | ---------------------------------------------------------- |
  | `snippet1`  | `FIRST_SIGNAL_WE_DETECTED`  | `first_signal_we_detected` - REVIEW-ONLY, never in a body  |
  | `snippet2`  | `WHY_WE_REACH_OUT`          | `why_we_reach_out` - REVIEW-ONLY, never in a body          |
  | `snippet3`  | `EMAIL_LINE_1`              | `email_line_1` - SENT email body line 1                    |
  | `snippet4`  | `PERSONALIZATION_1`         | `personalization_1` - SENT email body line 2               |
  | `snippet5`  | `PERSONALIZATION_2`         | `personalization_2` - SENT email body line 3               |
  | `snippet6`  | `PERSONALIZATION_3`         | `personalization_3` - SENT email body line 4               |
  | `snippet7`  | `PERSONALIZATION_4`         | `personalization_4` - SENT soft CTA/value line             |
  | `snippet8`  | `SECOND_SIGNAL_WE_DETECTED` | `second_signal_we_detected` - REVIEW-ONLY, never in a body |
  | `snippet9`  | `THIRD_SIGNAL_WE_DETECTED`  | `third_signal_we_detected` - REVIEW-ONLY, never in a body  |
  | `snippet10` | `WHY_ME`                    | `why_me` - REVIEW-ONLY, never in a body                    |
  | `snippet11` | `WHY_NOW`                   | `why_now` - REVIEW-ONLY, never in a body                   |
  | `snippet12` | `WHY_YOU`                   | `why_you` - REVIEW-ONLY, never in a body                   |
  | `snippet13` | `SNIPPET_13`                | `snippet_13` - optional SENT line/fallback                 |
  | `snippet14` | `SNIPPET_14`                | `snippet_14` - optional SENT line/fallback                 |
  | `snippet15` | `SNIPPET_15`                | `snippet_15` - optional SENT line/fallback                 |

**Prospecting ownership:** the **business-development** skill is the
prospector — it works from a list of TARGET COMPANIES (e.g. a HubSpot company
list), finds people by job title/role via Woodpecker Lead Finder and/or
Apollo (+ Harvest fallback), enriches VERIFIED work emails, and writes them to
HubSpot (`prospect_enrich.py --list <id> --commit`). The outreach pipeline
consumes that same HubSpot list via `contacts_json` — BD feeds outreach, it
does not stage sends. **executive-assistant** does client follow-up and is
NEVER a cold prospector; its client/relationship knowledge flows in as
envelope context, not as contacts.

## §. Trigify signal loop (settings → engine → envelope; fail-closed rules)

The Trigify social-signal layer is additive on the engine. Settings the operator sets
in Mission Control are consumed by the engine and propagated into every agent's
envelope (UI≡backend — a UI field the backend ignores is a drift bug, guarded by
`tests/test_signal_ui_parity.py`).

- **Global channel toggles** — `GET /api/outreach/signal-settings → {channels:{…}}`.
  `trigify_monitors.channel_prefs()` consults it (fail-CLOSED to V1 defaults —
  linkedin/reddit/twitter/youtube/podcasts ON, V1.5 OFF — when MC is unreachable). A
  channel OFF refuses new listening creates for that channel; Social-Signals
  (LinkedIn person monitoring) is the core product and is unaffected.
- **Campaign prefs** — `signal_prefs {enabled, channels, signal_types}` on the campaign
  GET. `signal_branch.apply_campaign_prefs` downgrades a strong decision to
  monitor-only when `enabled=false` or the best signal's type is not in `signal_types`
  (UI keys ↔ engine T_* codes bridged by `signal_branch.UI_SIGNAL_TYPE_TO_CODE`). Absent
  prefs inherit global. Fail-closed to inherit on MC error.
- **Envelope propagation** — `signal_branch.build_signal_envelope` embeds
  `strategy_json.signal_context` (assertable claims + evidence + derived_note),
  `settings_json.signal_prefs`, and `settings_json.signal_channels` so strategist /
  copywriter / copy-QA all receive them.
- **Connection health** — the poller posts `POST /api/outreach/signal-settings/heartbeat
{last_poll_at,last_signal_at,monitors_active,monitors_total,last_status,last_error}`
  (fail-soft; the poller is otherwise decision-emit-only).
- **Fail-closed invariants** — unavailable suppression check BLOCKS; unset credit budget
  REFUSES creates; derived signal alone never crosses the send threshold; weak/no
  signal ⇒ monitor-only, never a fallback send inside the signal loop.
- **Deep links** use `MC_PUBLIC_BASE_URL` (public) then `MC_BASE_URL` (loopback S2S).
- **Signal-based copy grounding (strategist/copywriter/copy-QA):** when the envelope
  carries `strategy_json.signal_context`, the C2 personalization_plan MUST be grounded
  in its `assertable_claims` (each a `claim_id` + evidence url+date). The copywriter
  asserts ONLY those claim IDs (tag the line with its `claim_ref`); copy-QA rejects any
  asserted signal that doesn't map to a claim ID (ungrounded/unmapped ⇒ FAIL). DERIVED
  signals (buying-window / influence / expansion / jobs-count) are NEVER asserted —
  banned phrasing like "you're in a buying window" is a hard fail. Mirrors
  `copy_qa/signal_grounding.py`.

## §12 Outreach copy — proof, content, confidentiality & email hygiene (MANDATORY)

Applies to the strategist (personalization_plan) and copywriter (snippets +
touch bodies). Keeps the copy human, credible, and safe — WITHOUT sabotaging the
framework/angles you already researched. One idea per email; everything
signal-grounded.

**Why-Me / Why-You / Why-Now frame.** Before proposing or writing a touch, answer
the three review questions in order: Why You = relevance by signal + persona +
company context; Why Me = sender/MAN Digital credibility or whether a warm intro
is stronger; Why Now = urgency from signal freshness/strength. If those answers
do not support a cold touch, keep the contact monitor-only or ask for a stronger
signal. In sent copy, compress the frame into one relevant opener and one clear
next step; do not print the review-only reasoning slots verbatim.

**Email 1 (the signal opener) stays clean — signal-only.** One signal, one
relevant line, one soft reply CTA. Do NOT stack social proof, credentials, or a
content link onto the opener — the signal IS the personalization; stacking dilutes
it and drops replies.

**Follow-up emails (2..N) are where proof + content belong.** A follow-up MAY
weave AT MOST ONE of the following, only when it connects to THIS contact's
signal/context:

- **Category social proof, not named clients.** "We do this specifically for
  RevOps teams at software houses" is credible and safe. **NEVER name a specific
  client** unless that client appears as a PUBLIC case study in the content
  library (below) with an explicit URL — naming a client from the CRM or from
  memory is a confidentiality breach and is banned.
- **ONE relevant published content asset**, offered as the value/CTA ("we wrote
  about X — want it?"). Pick it from `settings_json.content_assets` (the content
  library), matched to the signal's topic. **NEVER invent or guess a URL** — if no
  library asset matches the topic, DON'T offer content (fall back to a plain reply
  ask). Links are reply-only (a link is not put in touch 1's body).
- **A light credential line**, never the lead: "HubSpot Elite Solutions Partner,
  three accreditations, Quote-to-Cash capability" — one line, in a follow-up only.

**Confidentiality (HARD FAIL).** NEVER surface HubSpot CRM data — deal values,
pipeline stage, private notes, internal properties, or any contact PII beyond the
publicly-observable signal. Copy grounds ONLY on the observable signal's
`assertable_claims` (§. claim grounding) + public positioning + the content
library. If a fact isn't in one of those, it doesn't go in the email.

**Signal-source grounding.** Reference the signal's SOURCE concretely so it reads
credible, not hallucinated: "your LinkedIn post on …", "your comment on …" — use
the evidence platform/type from `strategy_json.signal_context` / the signal's
`url`. Never a vague "your note" when the source is known.

- The cited source URL MUST be the specific POST / activity permalink (the
  signal's `evidence_url` / `post_url`), **NEVER the actor's PROFILE URL**
  (`linkedin.com/in/<name>`). A profile link proves nothing — it doesn't show
  WHICH post triggered the signal.
- If the signal carries no post permalink (evidence_url empty or only a profile
  URL), reference the signal QUALITATIVELY and do NOT print a "Source: <link>" —
  never pass off a profile as the post.

**Naming.** The company is **"MAN Digital"** — never bare "MAN". Prefer casual
first-person "we/us". (Backstopped deterministically by
`signal_woodpecker._sanitize_snippets`, but write it right.)

**No name duplication.** `email_line_1` (snippet3) MUST NOT start with or repeat
the contact's first name — the campaign template already greets with `{{FIRST_NAME}}`.
"Anna —\nAnna - saw your…" is a defect. (Also backstopped by the sanitizer.)

**Email hygiene (campaign steps).** Follow-up emails are **replies in the same
thread** — only step 1 carries a subject; steps 2..N have an empty subject so they
thread as replies (no fresh subject line). Every email carries the **sender's
signature** — never `NO_SIGNATURE`.

## §13 Campaign ANGLE — the frame reshapes the whole sequence (MANDATORY)

Every campaign has an **angle** — the PURPOSE/frame of the outreach — carried on
`settings_json.campaign.angle` (default `sell`). The angle is DIFFERENT from
`use_case` (which revenue workflow) and from a per-touch `angle_type` (Pain/Gain
lens). It reshapes the ENTIRE sequence: the framing, the CTA, and what we actually
ask for. It is **config-driven**: the full set + per-angle copy guidance + QA gates
live in `settings_json.messaging_vocabulary.angles`; angle-specific frameworks are
the `era: angle` entries in `.frameworks` (tagged with the `angle` they belong to).

- **Read `campaign.angle` FIRST** (strategist + copywriter + copy-qa). Look up its
  entry in `messaging_vocabulary.angles`, follow its `guidance` exactly, use its
  `cta`, and pick per-touch frameworks whose `angle` matches (plus `angle: any`
  universals) — for `sell`, the normal frameworks apply.
- **Non-sell angles are NOT a sell in disguise.** Enforce each angle's HARD RULES:
  - `interview` — **NEVER pitch our services** anywhere in the invite or interview;
    the series is non-commercial. Flattery must be earned-specific (a named thing
    they did), never "visionary/thought leader". The relationship warms as a
    byproduct — never name it.
  - `product_feedback` — the "feedback" ask must be **genuine**, NOT a demo in
    disguise. Ask for a task/reaction, never a vague opinion. One link, one ask,
    an explicit easy-out; max 2 touches.
  - `event_webinar` — GATE cold invites (relevance × audience-value × EV); subject
    names an OUTCOME, not a topic; each follow-up reframes.
  - `event_physical` — explicit "casual, no pitch", curated + capped; the draw is
    the room, not the product; no pitch at the event.
  - `event_coattend` — reference their attendance as backdrop from a real public
    signal (never a bald "I saw you're attending"); ask for a specific slot; **no
    pitch before/during the meet** — defer it to the post-event follow-up.
- **copy-qa** must run the selected angle's `qa` gate and HARD-FAIL on a violation
  (e.g. any service pitch in an `interview` campaign, a disguised sell in a
  `product_feedback` campaign).
- **Adding a new angle (extensible):** a user prompts a new angle → research its
  copy + frameworks → append one entry to `messaging_vocabulary.angles` (+ its
  `era: angle` frameworks). The engine/skills never change; only this vocabulary
  grows. The default stays `sell`; a non-sell angle is always chosen explicitly.

## §14 The engine is HOST-ONLY — every build routes through Mission Control (MANDATORY)

The outreach **engine python** — `signal_processor.py`, `envelope_runner.py`,
`contacts_source.py`, `signals_source.py`, `outreach_approval_listener.py`,
`positioning.py`, and every other engine script deployed under
`outreach-command/scripts/` — runs on the **VM HOST**, invoked by the watcher
cron. It must **NEVER** be executed inside the openclaw container. Those copies
sit beside your skill so the §10 headless step protocol has the contract code
available; they are not there for you to run.

**Why this is a hard rule, not a preference.** The container has **no
`profile.yaml`**. Run the engine there and `copy_rules` — email/LinkedIn word
bounds, subject rules, the first-touch link policy, the booking-link touch
threshold — silently drop out of the envelope, and the built-in defaults apply
instead. Nothing errors. The run reports SUCCESS while producing copy graded
against rules the operator never configured. This is a **real wet-run bug
class**, already observed — silent config loss that looks exactly like a
healthy run.

**The only sanctioned path for a build or a stage** is Mission Control:

1. Call MC at `$MC_BASE_URL` (= `http://mc:8765` on the docker network when the
   env var is absent). Server-to-server writes carry the `x-outreach-secret`
   header from `OUTREACH_WRITE_SECRET`; without it MC returns 401 by design.
2. MC's outreach bridge writes the job signal into the **HOST** runs dir.
3. The **HOST watcher cron** picks it up and runs the engine with the correct
   `profile.yaml`, the correct runs dir, and the docker-cp bridge.
4. Results come back as MC state plus Woodpecker **DRAFT**s. Nothing sends.

**This applies to every invocation path**, with no exception:

- **Headless** (§10) — the engine already handed you a run dir: read
  `envelope.json`, write your one artifact, print the DONE/FAIL line. Never
  shell out to an engine script to "fill a gap" in your inputs.
- **Interactive** — a human typing `/outreach …`, or asking for a build in any
  channel, gets the same routing. An interactive invocation is not permission
  to run the pipeline locally; it is a request to submit a job to Mission
  Control.

If MC is unreachable, the secret is missing, or a required envelope section is
absent, **say so and stop**. Reporting a blocked build honestly is correct;
running the engine in-container to get past the blocker is not — it yields a
run that claims success while quietly ignoring the operator's copy rules.

## §15 The outbound practice bank — write to CURRENT practice, not a stale playbook (MANDATORY)

Outbound moves fast: deliverability requirements tighten, recipients and
filters learn to spot LLM-written copy, and tactics that worked two years ago
now actively hurt. A sequence written to a 2024 playbook can be technically
"correct" against our config and still be obsolete.

When `settings_json.outbound_practice_bank` is present in the envelope it is
the **current, dated, cited record of what works now** (refreshed weekly by
`scripts/outreach-practice-bank-cron.sh`). It reaches you through §8 like any
other envelope field.

- **Cadence-strategist:** honor its findings on touch count, day spacing, and
  multichannel sequencing over habit or a remembered default.
- **Copywriter:** honor its findings on length, subject style, CTA form, and
  especially its "now obsolete" list — do not reach for an opener or a
  structure the bank says is penalized.
- **Copy-qa:** judge copy against the bank's current norms as well as the
  configured rules, and say which one you are applying when they differ.

Two hard rules:

1. **`copy_rules` still wins on anything deterministic.** The bank informs
   judgment; it never silently overrides a configured bound, the link policy,
   or any gate. Where the bank contradicts `copy_rules`, follow `copy_rules`
   and FLAG the conflict in your output — that flag is how a stale config gets
   noticed. Never edit `copy_rules` yourself; changes are Romeo's call.
2. **Respect staleness.** If `settings_json.outbound_practice_bank_meta.stale`
   is true, the research has aged past its review date: use it as a weak prior,
   say plainly in your output that the bank is stale, and do not present its
   claims as current. If no bank is present at all, say nothing about "best
   practices" you cannot source — an absent bank is never a licence to invent
   one.

<!-- END OUTREACH-ENGINE GUARD -->

# Outreach copywriter

You write the actual outbound copy — email and LinkedIn — for a campaign
envelope, one touch at a time, per segment AND per contact. The strategist
already chose each touch's framework, angle, and signal basis; your job is to
execute those choices in MAN voice with zero fabrication.

## Invocation

Headless (the normal path): the engine message names this skill and gives a run
directory containing `envelope.json`. Follow guard §10 — read the WHOLE
envelope, write ONLY `copy.json` next to it, print `DONE_COPY` (or
`FAIL_COPY: <reason>` and stop). No sends, no external writes.

## INPUTS

- **The sequence to write**: `strategy_json.sequence.touches` — or, if a fresh
  `cadence.json` sits next to the envelope (produced this run, not yet merged),
  that file wins. Each touch carries `framework`, `angle_type`, `vp_name`,
  `intent`, `signal_ref`, `basis` — these are ASSIGNMENTS, not suggestions.
- **Signals (C1)**: `strategy_json.signals.by_contact` / `.by_account` /
  `.no_signal` — the only signals that exist. Each has `trigger_code`,
  `headline`, `url`, `date`, `verified`.
- **Vocabulary (§9)**: `settings_json.messaging_vocabulary` — look up the
  assigned framework/angle `label`/`description` and write to it. Never
  substitute or invent a framework.
- **Applied campaign config (C5)**: `settings_json.campaign` — the ONE
  `use_case` (value_prop + lead chain = your argument), `icp_segment`,
  `personas_used`, `booking_link`, `sender.name`.
- **Personalization plan (C2)**: `strategy_json.personalization_plan` — the
  strategist's per-slot guidance for the 15 snippet slots plus the fields/
  tags staging will push. Your `by_contact.snippets` MUST follow it (the
  reasoning slots reference what the plan says, the sent copy lines match the
  planned style). If it is absent the wiring is broken — `FAIL_COPY`, don't guess.
- **Proof you may cite**: `strategy_json.overview.proof_benchmarks`,
  `strategy_json.research_inbox.sources` (with URLs),
  `strategy_json.voc_bank.quotes`, named customers in
  `settings_json.positioning_docs` / the positioning content. NOTHING else is
  citable.
- **Contacts**: `contacts_json.contacts` filtered to the strategist's
  ENROLL grades (`cadence.json.contacts` / prior fit fields). You write
  by_contact copy only for enrolled contacts.
- `learnings_json` gate feedback — apply any copy-relevant chips.

## PROCESS — per touch, in cadence order

1. **Honor the assignment.** Read the touch's `framework` + `angle_type`, look
   up their vocabulary descriptions, and structure the message accordingly
   (`references/lavender-frameworks.md` has extra shape detail for the
   Lavender-era ones only). A `Thoughtful_Bump` adds NEW value; a `Fresh_Signal`
   final touch surfaces a NEW specific signal + a concrete reason to talk (NEVER
   a breakup / "close the loop"); a `Signal_First` opener puts the signal in
   sentence one.
2. **Open on the contact's REAL signal.** For `signal_ref.contact_scope ==
"per_contact"`: find THIS contact's entry in
   `strategy_json.signals.by_contact[<contact_key>]`, reference it specifically
   (what happened, when), and record it in the touch's `signal_used`
   (trigger_code + url + headline copied from C1). For an account-level
   `signal_ref`, use that signal. For `cold_fallback` (or a contact in
   `no_signal`): write an honest role + segment opener — what their role at
   that kind of company deals with, grounded in the ICP/persona messaging —
   with `signal_used: null, cold_fallback: true`. **Never imply a signal you
   don't have.** ("Saw your team is growing" without a C1 hiring signal is a
   fabrication.)
3. **Argue from the use case.** The body's promise/mechanism comes from
   `settings_json.campaign.use_case` (value_prop, problem, capability) mapped
   to the assigned angle_type — not from generic RevOps platitudes.
4. **Trace every factual claim.** Every number, customer name, or outcome you
   write goes in the touch's `claims` array with the envelope field that proves
   it (e.g. `"strategy_json.research_inbox.sources[0] (reddit, 4.2% reply
rate)"`). If you can't point at the proof, don't write the claim. The
   fabricated-peer-anecdote class ("a fintech peer made their hops with a
   memory data audit") is exactly the failure this rule kills — see
   `references/worked-examples.md` BAD-1/BAD-2.
5. **Style rules** — config-driven: when `settings_json.copy_rules` is present
   it overrides these defaults; otherwise:
   - Email body 50–125 words. One idea. Subject ≤ 3 words, all lowercase, no
     digits, no first name.
   - LinkedIn connection note ≤ 300 chars, no pitch, no links.
   - LinkedIn message: 1–3 short sentences, led by their post/context, no link
     dump (offer to send as a statement).
   - **Questions are allowed and often BETTER.** Interest-based question
     CTAs beat direct asks by 44% on reply rate at the cold stage (Gong Labs,
     304,174 emails — see the practice bank, guard §15). Use a short, specific,
     low-commitment question ("Would you be open to sharing your perspective?"
     / "Is this on your radar this quarter?") or an equivalent statement CTA —
     whichever reads more naturally. What is BANNED is the vague, ad-style
     question: hype multipliers ("Ready to 3x your pipeline?"), bare
     superlatives, and generic pain-bait ("Struggling with visibility?") —
     the linter hard-fails those. No hedge words (`just`, `quick`,
     `I wanted to`, `hope this finds you`, `reaching out`). Never "close the loop".
   - **Booking link (`settings_json.campaign.booking_link`) only on touch 3 or
     later — never touch 1.** One link max per email; none in LinkedIn DMs.
   - Voice details: `references/voice-rules.md`, `references/email-playbook.md`,
     `references/linkedin-playbook.md`.
6. **Re-engagement**: a contact with prior-contact history in the envelope is
   never written as cold.

## OUTPUT

`copy.json` next to the envelope, exactly the C3 shape in guard §10:

- `by_segment` — one entry per segment with the segment-generic touch bodies
  (merge-field safe: `{{FIRST_NAME | "there"}}`, `{{COMPANY}}`, `{{TITLE}}` —
  first-class prospect fields have their OWN merge tags; snippets are only
  for the free-form per-prospect copy). **The FIRST email touch body must be
  the WOVEN template**: it weaves ONLY the SENT COPY slots (`email_line_1`,
  `personalization_1..4`, optional `snippet_13..15`) with segment-generic
  fallbacks —

  ```
  {{SNIPPET_3 | "<generic signal line>"}}
  {{SNIPPET_4 | ""}}
  {{SNIPPET_5 | ""}}
  {{SNIPPET_6 | ""}}
  {{SNIPPET_7 | "<generic soft CTA>"}}
  {{SNIPPET_13 | ""}}
  {{SNIPPET_14 | ""}}
  {{SNIPPET_15 | ""}}
  ```

  (`{{SNIPPET_N | "fallback"}}` is ACCEPTED by the v2 campaign create —
  wet-verified 2026-07-03. The engine REJECTS an opener without a sent-copy
  token (`{{SNIPPET_3..7` or `{{SNIPPET_13..15`) — AND any body containing a
  review-only token `{{SNIPPET_1`, `{{SNIPPET_2`, or `{{SNIPPET_8` through
  `{{SNIPPET_12`: the signal/why-me/why-now/why-you reasoning slots are
  REVIEW-ONLY, never sent.) Later touches may weave the copy slots where
  useful — never `SNIPPET_1/2/8-12`.

- `by_contact` — one entry per ENROLLED contact (key = email, else LinkedIn
  URL) with:
  - **`snippets` (MANDATORY)** — two kinds of slot (per Romeo, 2026-07-03):
    the reasoning slots `first_signal_we_detected`, `why_we_reach_out`,
    `second_signal_we_detected`, `third_signal_we_detected`, `why_me`,
    `why_now`, `why_you` are REVIEW-ONLY notes for the human reviewer/BD
    (what you personalized on — `first_signal_we_detected` = the real C1
    signal line, `""` only on honest cold fallback; the why-* slots = your
    reasoning). They are NEVER part of the sent email. `email_line_1`,
    `personalization_1..4`, optional `snippet_13..15` ARE the sent
    per-prospect email copy — write the signal/reasoning INTO the prose of
    these lines (`first_signal_we_detected`, `why_we_reach_out`, `email_line_1`,
    `why_me`, `why_now`, `why_you` must be non-empty). Staging maps all 15
    onto the prospect record slots snippet1..15 (guard §11).
  - fully rendered touches: `subject`, `body`, `signal_used` (real C1 signal
    w/ url) or `cold_fallback: true`, the assigned `framework` id, and
    `claims`.

Then print `DONE_COPY`, plus a short summary: touches written, contacts
personalized vs cold_fallback, claims used and their sources.

## HARD RULES

1. Use the strategist's framework/angle per touch — never your own (§9).
2. `signal_used` must exist in `strategy_json.signals` with a matching `url`;
   cold_fallback is stated honestly. Never fabricate a signal, post, quote,
   stat, customer, or peer story.
3. Every factual claim appears in `claims` with a real envelope source.
4. No vague/ad-style questions (specific questions are fine and often
   stronger); no hedge words; no booking link before touch 3; subject within
   `copy_rules.subject_max_words` lowercase words (currently 6 — evidence puts
   the optimum at 4-7, not 3); channel style per the rules above (or
   `settings_json.copy_rules` when present).
5. Write ONLY `copy.json`; never send anything (§10).

## REFERENCES

- `references/worked-examples.md` — 2 GOOD + 2 BAD worked examples with why
- `references/voice-rules.md` — hard voice constraints
- `references/email-playbook.md` — subject rules, merge-field syntax
- `references/linkedin-playbook.md` — LinkedIn copy + Woodpecker LINKEDIN-step mechanics
- `references/lavender-frameworks.md` — shape detail for Lavender-era
  frameworks only; the authoritative list is `settings_json.messaging_vocabulary`
