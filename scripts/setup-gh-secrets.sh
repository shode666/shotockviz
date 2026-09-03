#!/usr/bin/env bash
# setup-gh-secrets.sh — run ONCE on your Mac (after bootstrap-server.sh).
# Requires: gh (logged in), ssh (with `my-do` alias configured), ssh-keygen, ssh-keyscan.
#
# - Generates an ed25519 deploy keypair (skips if it already exists)
# - Appends the public key to the server's authorized_keys (deduped)
# - Sets repo secrets: DEPLOY_SSH_KEY, VITE_GOOGLE_CLIENT_ID
# - Sets repo variables: DEPLOY_HOST, DEPLOY_USER, DOMAIN, DEPLOY_KNOWN_HOSTS
#
# Usage:
#   bash scripts/setup-gh-secrets.sh --repo shode666/shotockviz [--host my-do] [--ip 188.166.234.146]
set -euo pipefail

REPO="shode666/shotockviz"
SSH_ALIAS="my-do"
DEPLOY_IP="188.166.234.146"
DEPLOY_USER="root"
KEY_PATH="${HOME}/.ssh/shotockviz_deploy"

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --host) SSH_ALIAS="$2"; shift 2 ;;
    --ip) DEPLOY_IP="$2"; shift 2 ;;
    --user) DEPLOY_USER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

log() { printf '==> %s\n' "$1"; }

for bin in gh ssh ssh-keygen ssh-keyscan; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Missing required tool: $bin" >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not logged in. Run: gh auth login" >&2
  exit 1
fi

# ---------- Prompts ----------
read -r -p "DOMAIN (e.g. stock.shode.dev — DNS A record must point to ${DEPLOY_IP}): " DOMAIN
read -r -p "CADDY_EMAIL (informational only — set on the server .env, not stored as a GH secret): " CADDY_EMAIL
read -r -s -p "VITE_GOOGLE_CLIENT_ID (baked into the frontend build): " VITE_GOOGLE_CLIENT_ID
echo

if [ -z "${DOMAIN}" ]; then
  echo "DOMAIN is required." >&2
  exit 1
fi
echo "(CADDY_EMAIL noted: ${CADDY_EMAIL:-not set} — remember to set it in /opt/shotockviz/.env on the server, it is not sent to GitHub)"

# ---------- Deploy keypair ----------
if [ -f "${KEY_PATH}" ]; then
  log "Deploy key already exists at ${KEY_PATH} — reusing it"
else
  log "Generating ed25519 deploy keypair at ${KEY_PATH}"
  ssh-keygen -t ed25519 -f "${KEY_PATH}" -N "" -C "shotockviz-deploy-$(date +%Y%m%d)"
fi

# ---------- Authorize the deploy key on the server (dedupe) ----------
log "Appending deploy public key to ${SSH_ALIAS}:~/.ssh/authorized_keys (deduped)"
PUBKEY="$(cat "${KEY_PATH}.pub")"
# shellcheck disable=SC2029  # intentional: ${PUBKEY} must expand client-side so the literal key value is sent to the remote shell
ssh "${SSH_ALIAS}" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && \
  grep -qxF '${PUBKEY}' ~/.ssh/authorized_keys || echo '${PUBKEY}' >> ~/.ssh/authorized_keys && \
  chmod 600 ~/.ssh/authorized_keys"

# ---------- Pin host key (no StrictHostKeyChecking=no in the workflow) ----------
log "Scanning ${DEPLOY_IP} host keys for pinning"
KNOWN_HOSTS="$(ssh-keyscan -t ed25519,rsa "${DEPLOY_IP}" 2>/dev/null)"
if [ -z "${KNOWN_HOSTS}" ]; then
  echo "ssh-keyscan returned nothing for ${DEPLOY_IP} — check connectivity." >&2
  exit 1
fi

# ---------- Push secrets/vars to GitHub ----------
log "Setting repo secret DEPLOY_SSH_KEY"
gh secret set DEPLOY_SSH_KEY --repo "${REPO}" < "${KEY_PATH}"

log "Setting repo secret VITE_GOOGLE_CLIENT_ID"
printf '%s' "${VITE_GOOGLE_CLIENT_ID}" | gh secret set VITE_GOOGLE_CLIENT_ID --repo "${REPO}"

log "Setting repo variables DEPLOY_HOST, DEPLOY_USER, DOMAIN, DEPLOY_KNOWN_HOSTS"
gh variable set DEPLOY_HOST --repo "${REPO}" --body "${DEPLOY_IP}"
gh variable set DEPLOY_USER --repo "${REPO}" --body "${DEPLOY_USER}"
gh variable set DOMAIN --repo "${REPO}" --body "${DOMAIN}"
printf '%s' "${KNOWN_HOSTS}" | gh variable set DEPLOY_KNOWN_HOSTS --repo "${REPO}"

echo
echo "Summary (secrets masked):"
printf '  %-22s %s\n' "repo:" "${REPO}"
printf '  %-22s %s\n' "DEPLOY_HOST (var):" "${DEPLOY_IP}"
printf '  %-22s %s\n' "DEPLOY_USER (var):" "${DEPLOY_USER}"
printf '  %-22s %s\n' "DOMAIN (var):" "${DOMAIN}"
printf '  %-22s %s\n' "DEPLOY_KNOWN_HOSTS (var):" "$(printf '%s' "${KNOWN_HOSTS}" | wc -l) host key line(s) set"
printf '  %-22s %s\n' "DEPLOY_SSH_KEY (secret):" "***** (from ${KEY_PATH})"
printf '  %-22s %s\n' "VITE_GOOGLE_CLIENT_ID (secret):" "*****"
echo
echo "Not sent to GitHub (server-only, edit in /opt/shotockviz/.env): CADDY_EMAIL and everything else in .env.example"
echo "Next: run the deploy workflow — gh workflow run deploy.yml --repo ${REPO}"
