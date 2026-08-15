#!/usr/bin/env bash
#
# MinIO object lifecycle / retention policy.
#
# Originals are kept deliberately and indefinitely by default: the ingestion
# pipeline improves, and re-processing from source is what lets a chunking or
# embedding change apply retroactively. Deleting sources would freeze the
# corpus at the worst version of the pipeline it ever had.
#
# But "keep forever" must be a DECISION, not an absence of one. This script
# makes the policy explicit and applies it, including versioning so an
# accidental overwrite is recoverable — which matters more here than
# expiration, because MinIO holds the only copy of uploaded documents.
#
# Usage:
#   ./scripts/set-retention.sh                 # apply the default policy
#   RETAIN_DAYS=365 ./scripts/set-retention.sh # expire originals after a year

set -euo pipefail

MINIO_ALIAS="${MINIO_ALIAS:-donna}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-documents}"

# 0 = keep originals indefinitely (the default, and the deliberate choice).
RETAIN_DAYS="${RETAIN_DAYS:-0}"
# Non-current versions are pure recovery headroom; 90 days is plenty.
NONCURRENT_DAYS="${NONCURRENT_DAYS:-90}"
# Incomplete multipart uploads are pure waste — always expire them.
ABORT_INCOMPLETE_DAYS="${ABORT_INCOMPLETE_DAYS:-7}"

log()  { printf '\033[36m[retention]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[retention] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

command -v mc >/dev/null 2>&1 || fail "MinIO client 'mc' not found. Install: https://min.io/docs/minio/linux/reference/minio-mc.html"

log "configuring alias '${MINIO_ALIAS}' -> ${MINIO_ENDPOINT}"
mc alias set "${MINIO_ALIAS}" "${MINIO_ENDPOINT}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null

# Versioning first: without it, a re-upload of the same key silently destroys
# the only copy of the original, and no lifecycle rule can bring it back.
log "enabling versioning on ${MINIO_BUCKET} (protects against overwrite)"
mc version enable "${MINIO_ALIAS}/${MINIO_BUCKET}" || \
    log "  versioning unavailable on this deployment — continuing"

RULES_FILE="$(mktemp)"
trap 'rm -f "${RULES_FILE}"' EXIT

{
    echo '{ "Rules": ['
    echo '  {'
    echo '    "ID": "abort-incomplete-multipart",'
    echo '    "Status": "Enabled",'
    echo "    \"AbortIncompleteMultipartUpload\": { \"DaysAfterInitiation\": ${ABORT_INCOMPLETE_DAYS} }"
    echo '  },'
    echo '  {'
    echo '    "ID": "expire-noncurrent-versions",'
    echo '    "Status": "Enabled",'
    echo "    \"NoncurrentVersionExpiration\": { \"NoncurrentDays\": ${NONCURRENT_DAYS} }"
    if [ "${RETAIN_DAYS}" -gt 0 ]; then
        echo '  },'
        echo '  {'
        echo '    "ID": "expire-originals",'
        echo '    "Status": "Enabled",'
        echo "    \"Expiration\": { \"Days\": ${RETAIN_DAYS} }"
    fi
    echo '  }'
    echo '] }'
} > "${RULES_FILE}"

log "applying lifecycle policy…"
mc ilm import "${MINIO_ALIAS}/${MINIO_BUCKET}" < "${RULES_FILE}" \
    || fail "failed to apply lifecycle rules"

log "current policy:"
mc ilm ls "${MINIO_ALIAS}/${MINIO_BUCKET}" || true

echo
if [ "${RETAIN_DAYS}" -eq 0 ]; then
    log "originals: RETAINED INDEFINITELY (deliberate — enables pipeline reprocessing)"
    log "to change: RETAIN_DAYS=365 $0"
else
    log "originals: expire after ${RETAIN_DAYS} days"
    log "NOTE: after expiry, documents can no longer be re-chunked or re-embedded"
    log "      from source. Chunks and vectors survive; the original does not."
fi
log "non-current versions: expire after ${NONCURRENT_DAYS} days"
log "incomplete uploads:   aborted after ${ABORT_INCOMPLETE_DAYS} days"
