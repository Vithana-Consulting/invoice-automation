#!/bin/sh
# Nightly MySQL dump + attachments archive → Backblaze B2.
# Runs inside the `backup` container (cron). Restore by reversing both files.
set -eu

TS=$(date -u +%Y%m%dT%H%M%SZ)
DUMP=/backups/db-${TS}.sql.gz
ATTACH=/backups/attachments-${TS}.tar.gz

# 1. MySQL dump (single-transaction = consistent without locking)
mysqldump \
  -h db -u accounting -p"${MYSQL_PASSWORD}" \
  --single-transaction --quick --routines --triggers \
  accounting_automation \
  | gzip -9 > "${DUMP}"

# 2. Attachments archive (incremental rsync would be cheaper at scale; full tar is fine <10GB)
tar czf "${ATTACH}" -C /var/lib/docker/volumes/day3_attachments/_data . 2>/dev/null || \
  echo "WARN: attachments volume not mounted; skipping"

# 3. Upload to B2
b2 authorize-account "${B2_KEY_ID}" "${B2_APP_KEY}" >/dev/null
b2 upload-file "${B2_BUCKET}" "${DUMP}"   "$(basename "${DUMP}")"
[ -f "${ATTACH}" ] && b2 upload-file "${B2_BUCKET}" "${ATTACH}" "$(basename "${ATTACH}")"

# 4. Local retention: keep last 3 days
find /backups -name 'db-*.sql.gz'      -mtime +3 -delete
find /backups -name 'attachments-*.tar.gz' -mtime +3 -delete

echo "[$(date -u)] backup OK: ${DUMP}"
