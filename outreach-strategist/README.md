# outreach-strategist

Campaign-level outreach coordinator skill for OpenClaw agents, plus its four
connected pipeline subskills. Together they run human-gated, signal-led
outbound: research → cadence → copy → QA → DRAFT staging (Woodpecker) →
human approval. **Nothing auto-sends below the explicitly-granted autonomy
tier.**

## Architecture

```
Discord channel (human <-> strategist)
        │
  outreach-strategist (this skill)        ← campaign brain: who / when / why
        │  builds cohorts from dossiers (research-protocol per campaign)
        ▼
  /outreach  = outreach-command           ← pipeline conductor
        ├─ outreach-cadence-strategist    ← C2: fit-grade + touch plan
        ├─ outreach-copywriter            ← C3: per-contact grounded copy
        └─ outreach-copy-qa               ← C4: lint + multi-dimension QA gate
        ▼
  Mission Control gates → Woodpecker DRAFT → human activates
```

- `SKILL.md` — the strategist role: campaign folders, streams, autonomy
  tiers, delegation map, reporting duties.
- `campaigns/_template/` — copy to `campaigns/<slug>/` to add a new
  campaign. Campaign folders are DATA, the skill stays generic. (Our live
  campaign folders are kept in the private infra repo, not here.)
- `subskills/` — reference copies of the four pipeline skills' SKILL.md as
  deployed (each begins with the shared SKILL_GUARD block).
- `scripts/` — deploy (skill → container workspace), Discord channel wiring,
  and the daily-nudge / weekly-report cron.

## Supporting tool skills (not bundled here)

The strategist delegates to per-tool skills available in the same workspace:
`hubspot-api`, `apollo-api`, `harvestapi`, `exa-api`, `linkup`, `trigify`,
`woodpecker`, `emailable`, `icypeas`, `leaddelta`, `memelord`, `reclaim` —
plus Graph.one relationship intelligence via Mission Control.

## Design rules worth stealing

1. **Skill = role, campaign = folder.** New campaign is a data change, not a
   prompt change.
2. **Dossier-gated copy.** No per-contact research dossier with a fresh
   (≤90-day) linkable observable → no sequence. Kills AI-slop at the source.
3. **One person, one stream.** Cross-stream routing table with explicit
   transitions and a global suppression list.
4. **Graduated autonomy.** tier1 (approve everything) → tier2 (auto-send QA-passed
   within caps) → tier3 (auto-reply safe classes). Promotions are human-only,
   after ≥2 weeks of calibration. One kill-switch word stops everything.
5. **Honest reporting.** Cron-driven daily nudge + weekly report; metrics
   the agent can't verify are reported as n/a, never invented.

No credentials anywhere in this folder; all secrets come from container env
or runtime config at the deployment site. Campaign folders, `knowledge/`
(the kb.py memory + graph), `dossiers/`, and `LEARNINGS.md` stay private —
the sync to the public mirrors below redacts all of them; only this file,
`SKILL.md`, `bin/kb.py`, and the campaign template are ever published.

## This file's history

This README is authored **here, in the skill source** — not in either public
mirror. It is deployed outward by `scripts/outreach-skills-sync.sh` to both
public targets (`SYNC_TARGETS` in `config/outreach-sync.conf`) and protected
from deletion there via `SYNC_PROTECTED_PATHS`. Editing a mirror's copy
directly will be overwritten (or the mirror's copy deleted and this one
re-synced) on the next sync tick — this file is the one source of truth.
