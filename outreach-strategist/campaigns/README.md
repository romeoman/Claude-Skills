# Campaign folders

One folder per campaign. The `outreach-strategist` skill is generic; these
folders are the ONLY place campaign-specific context lives.

## Schema — `campaign.yaml`

```yaml
slug: kebab-case-id # folder name must match
name: Human-readable name
status: setup | active | paused | done
objective: >
  One paragraph: what this campaign is trying to achieve and what it is NOT
  (e.g. "research invitation, not a sales pitch").

targets: # measurable, with deadlines
  # free-form keys; keep numbers and dates explicit

audience:
  personas: [] # titles / roles
  geography: []
  industries: []
  qualifiers: [] # e.g. "on HubSpot", "navigating CRM change"

lists:
  source: # existing list(s) — read-only
    hubspot_list_id: ""
    note: ""
  curated: # the working list this campaign sequences from
    rule: "" # e.g. "1 best-fit person per company"
    hubspot_folder_id: ""
    hubspot_list_id: "" # filled once created

assets: # URLs the campaign references
  # publish pages, strategy docs, registration pages...

messaging:
  value_exchange: ""
  cta: ""
  regional_split: [] # e.g. distinct US vs UK messaging
  ai_disclosure: undecided | required | forbidden | ab_test

channels:
  email_mailboxes: all | [ids]
  linkedin: woodpecker_tasks | native | both

signals: # which sources feed timing for this campaign
  - trigify
  - graphone
  - exa
  - linkup
  - albacross

mention_policy: >
  Which file is the name-drop allowlist, and the rule for using it.
```

Optional siblings: `brief.md` (distilled strategy), `mentionable-*.md`
(allowlists), `notes.md` (running decision log — the strategist appends
dated entries for every material decision).

## Deployment

Durable source: `openclaw-infra/outreach-engine/skills/outreach-strategist/`
(git). Deployed copy: `<workspace>/skills/outreach-strategist/` in the
container via `scripts/outreach-deploy-strategist.sh`. Never hand-edit the
deployed copy — except `notes.md`/`campaign.yaml` runtime updates written by
the strategist itself, which the nightly workspace sync mirrors back to the
host for review.
