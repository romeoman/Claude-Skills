#!/usr/bin/env bash
set -uo pipefail

# ============================================================================
# outreach-report-cron.sh — daily nudge / weekly report for the outreach
# strategist, delivered as a post (-> auto-thread) in the business-development
# Discord channel.
#
# Runs an agent turn in the openclaw container (same mechanism as
# recover-interrupted-runs.sh — `openclaw agent ... --deliver`) so the
# strategist gathers REAL state with its tools and composes the report.
# Deterministic cron, agent-composed content.
#
# USAGE (host cron):
#   scripts/outreach-report-cron.sh --daily
#   scripts/outreach-report-cron.sh --weekly
# Config env (all optional):
#   OPENCLAW_CONTAINER        (default openclaw)
#   OUTREACH_REPORT_CHANNEL   Discord channel id (default: container env
#                             DISCORD_BD_CHANNEL_ID)
#   OUTREACH_REPORT_TIMEOUT_S agent turn timeout (default 900)
# ============================================================================

CONTAINER="${OPENCLAW_CONTAINER:-openclaw}"
TIMEOUT_S="${OUTREACH_REPORT_TIMEOUT_S:-900}"
MODE="${1:---daily}"
LOCK="/tmp/outreach-report-cron.lock"

log() { echo "[$(date '+%F %T')] [outreach-report] $*"; }

exec 9>"$LOCK"
if ! flock -n 9; then log "another report run in progress; skipping"; exit 0; fi

if ! docker exec "$CONTAINER" true >/dev/null 2>&1; then
  log "container '$CONTAINER' unreachable; skipping"; exit 0
fi

CHANNEL="${OUTREACH_REPORT_CHANNEL:-$(docker exec "$CONTAINER" printenv DISCORD_BD_CHANNEL_ID 2>/dev/null || true)}"
if [ -z "$CHANNEL" ]; then log "no report channel configured; skipping"; exit 0; fi

COMMON="You are operating as the outreach-strategist skill (read skills/outreach-strategist/SKILL.md first, then the revenue-context campaign folder: campaign.yaml, routing.md, research-protocol.md, streams/*/stream.yaml, notes.md, dossiers/). Gather REAL current state before writing anything — outreach-runs artifacts, Mission Control state, Woodpecker campaign/prospect state via read APIs, dossier counts. NEVER invent numbers: if a metric is unavailable, write 'n/a' and say why. If the campaign has not started producing artifacts yet, say exactly that in 3 lines max instead of padding. Post ONE message; numbers first; no filler; flag risks honestly."

if [ "$MODE" = "--weekly" ]; then
  PROMPT="$COMMON Produce the WEEKLY REPORT per SKILL.md Reporting duties: trend vs targets (24 interviews: UK 10 / US 8 / EMEA 6 by Nov 30; registrations; audit-app), per-stream funnel (researched -> sequenced -> replied -> booked), suppression/routing incidents, mailbox capacity + warmup state, and 1-3 recommendations with reasoning."
else
  PROMPT="$COMMON Produce the DAILY NUDGE per SKILL.md Reporting duties: dossiers completed vs queued, drafts awaiting approval (as a one-click batch summary Romeo can approve by replying), replies waiting, interviews booked vs 24, top 1-3 signals worth acting on today, anything skipped and why."
fi

if docker exec "$CONTAINER" openclaw agent \
     --session-key "agent:main:discord:channel:$CHANNEL" \
     --channel discord --reply-to "channel:$CHANNEL" --deliver \
     --message "$PROMPT" \
     --timeout "$TIMEOUT_S" >/dev/null 2>&1; then
  log "$MODE report turn delivered to channel $CHANNEL"
else
  log "$MODE report agent turn FAILED (gateway busy or error)"
  # Best-effort visible fallback so a silent failure never hides for days.
  # OPENCLAW_REPO_DIR: this script may run from a copy OUTSIDE the repo (the
  # VM repo can be on another branch than the one shipping this file).
  SELF_DIR="${OPENCLAW_REPO_DIR:-$HOME/openclaw-infra}"
  OPENCLAW_OPS_DISCORD_CHANNEL="$CHANNEL" "$SELF_DIR/scripts/notify-discord.sh" \
    "⚠️ Outreach ${MODE#--} report failed to generate this cycle (agent turn error). Check outreach-report-cron logs." || true
fi
exit 0
