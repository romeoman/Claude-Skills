#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# outreach-deploy-strategist.sh — deploy the outreach-strategist skill (and
# its campaigns/ context folders) into the openclaw container workspace.
#
# Durable source:   outreach-engine/skills/outreach-strategist/   (git)
# Deployed copy:    <workspace>/skills/outreach-strategist/       (container)
#
# Companion to outreach-deploy-skills.sh (which owns the 4 pipeline skills +
# engine glue). Same rules: additive, idempotent, NO container restart needed
# for skill discovery. Run ON THE VM HOST (needs docker access to the
# container). From the Mac: orb -m openclaw-vm bash ~/openclaw-infra/scripts/outreach-deploy-strategist.sh
#
# NOTE on campaigns/: campaign.yaml + notes.md in the DEPLOYED copy may be
# updated at runtime by the strategist agent (status, list ids, decision log).
# The nightly workspace sync mirrors those back to runtime-workspace/live/ on
# the host. This script therefore does NOT delete or overwrite files that
# exist only in the container; it only pushes newer source files in.
#
# USAGE:
#   scripts/outreach-deploy-strategist.sh            # deploy
#   scripts/outreach-deploy-strategist.sh --dry-run  # show plan only
# ============================================================================

CONTAINER="${OPENCLAW_CONTAINER:-openclaw}"
SKILLS_DIR="${OPENCLAW_SKILLS_DIR:-/home/node/.openclaw/workspace/skills}"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$SELF_DIR/outreach-engine/skills/outreach-strategist"
DEST_DIR="$SKILLS_DIR/outreach-strategist"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

[[ -d "$SRC_DIR" ]] || { echo "FATAL: source missing: $SRC_DIR" >&2; exit 1; }
docker exec "$CONTAINER" true >/dev/null 2>&1 \
  || { echo "FATAL: container '$CONTAINER' unreachable" >&2; exit 1; }

echo "Deploying outreach-strategist -> $CONTAINER:$DEST_DIR"
while IFS= read -r -d '' f; do
  rel="${f#"$SRC_DIR"/}"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "PLAN: docker cp $rel"
    continue
  fi
  docker exec "$CONTAINER" mkdir -p "$DEST_DIR/$(dirname "$rel")"
  docker cp "$f" "$CONTAINER:$DEST_DIR/$rel"
  echo "  deployed: $rel"
done < <(find "$SRC_DIR" -type f -print0)

if [[ $DRY_RUN -eq 0 ]]; then
  # Match ownership of sibling skills so the workspace sync + agent can write.
  owner="$(docker exec "$CONTAINER" stat -c '%u:%g' "$SKILLS_DIR")"
  docker exec --user root "$CONTAINER" chown -R "$owner" "$DEST_DIR" 2>/dev/null || true
  echo "OK — verify with: docker exec $CONTAINER openclaw skills list | grep -i outreach-strategist"
fi
