#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# outreach-wire-discord-channel.sh — bind the #outreach-strategist Discord
# channel to the outreach-strategist skill in openclaw's runtime config.
#
# PRECONDITION: the channel exists in the Discord guild (the bot lacks
# Manage Channels, so a human creates it), and you have its channel ID
# (Discord: right-click channel -> Copy Channel ID with developer mode on).
#
# WHAT IT DOES:
#   1. Backs up /home/node/.openclaw/openclaw.json inside the container.
#   2. Adds a channel entry (systemPrompt + skills allowlist) under
#      channels.discord.guilds.<guild>.channels.<id>. Idempotent — an
#      existing entry for the ID is replaced.
#   3. Restarts the container so the gateway picks up the config.
#      (Runtime volume config survives restarts; see .claude memory.)
#
# RUN ON THE VM HOST:
#   bash scripts/outreach-wire-discord-channel.sh <channel_id>
# From the Mac:
#   orb -m openclaw-vm bash ~/openclaw-infra/scripts/outreach-wire-discord-channel.sh <channel_id>
# ============================================================================

CONTAINER="${OPENCLAW_CONTAINER:-openclaw}"
GUILD_ID="${OPENCLAW_DISCORD_GUILD_ID:-1480246506895315015}"
CHANNEL_ID="${1:?usage: $0 <discord_channel_id>}"
CFG=/home/node/.openclaw/openclaw.json

docker exec "$CONTAINER" cp "$CFG" "$CFG.bak-outreach-wire-$(date +%Y%m%d-%H%M%S)"

docker exec -i -e GUILD_ID="$GUILD_ID" -e CHANNEL_ID="$CHANNEL_ID" "$CONTAINER" python3 - <<'PYEOF'
import json, os

CFG = "/home/node/.openclaw/openclaw.json"
guild, chan = os.environ["GUILD_ID"], os.environ["CHANNEL_ID"]

PROMPT = (
    "This Discord channel is the OUTREACH STRATEGIST room — campaign-level "
    "outreach coordination. For EVERY request here, first invoke the "
    "outreach-strategist skill and follow it. Default campaign: "
    "revenue-context — load skills/outreach-strategist/campaigns/"
    "revenue-context/ (campaign.yaml, brief.md, mentionable-interviewees.md) "
    "before acting, unless the user names another campaign; 'list campaigns' "
    "enumerates campaigns/*/campaign.yaml. You coordinate: build/curate "
    "target lists, commission signal research (Trigify, Exa, Linkup, Apollo, "
    "HarvestAPI, Graph.one via Mission Control), invoke /outreach to build "
    "campaigns, and report status vs targets. You NEVER write outreach copy "
    "yourself (only the /outreach pipeline does, under SKILL_GUARD) and "
    "NOTHING EVER SENDS from this channel — DRAFT-only staging; approvals "
    "stay with Romeo in Mission Control and Woodpecker. Check persona fit "
    "against skills/business-development/persona-job-titles.md. Keep replies "
    "in the thread, short and operational, lead with status vs target, flag "
    "risks honestly. Never reply with complete silence — if holding, post a "
    "one-line acknowledgment."
)

entry = {
    "enabled": True,
    "requireMention": False,
    "autoThread": True,
    "autoThreadName": "message",
    "includeThreadStarter": True,
    "autoArchiveDuration": 10080,
    "skills": [
        "outreach-strategist", "outreach-command", "trigify", "exa-api",
        "linkup", "apollo-api", "harvestapi", "hubspot-api", "woodpecker",
        "business-development", "emailable", "leaddelta", "icypeas",
    ],
    "systemPrompt": PROMPT,
}

cfg = json.load(open(CFG))
channels = cfg["channels"]["discord"]["guilds"][guild]["channels"]
channels[chan] = entry
json.dump(cfg, open(CFG, "w"), indent=2)
print(f"wired channel {chan} in guild {guild}")
PYEOF

echo "Restarting container to apply..."
docker restart "$CONTAINER" >/dev/null
echo "OK — verify with: docker exec $CONTAINER openclaw channels status"
