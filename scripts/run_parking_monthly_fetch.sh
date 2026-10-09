#!/bin/bash
# Self-healing wrapper for the monthly parking-ticket fetch. The
# underlying python process has died silently a couple of times in this
# sandbox, apparently during a retry backoff sleep rather than from a real
# error -- fetch_socrata.py's --force=false (default) resume support makes
# re-invoking cheap, so just loop until every period succeeds instead of
# depending on an external check-in to notice and restart it.
cd "$(dirname "$0")/.."
TARGET=80  # ~7 years x 12 months through the current month

for i in $(seq 1 50); do
  count=$(ls data/raw/parking_tickets_monthly/*.csv 2>/dev/null | wc -l)
  if [ "$count" -ge "$TARGET" ]; then
    echo "[wrapper] $count files present, target reached, stopping."
    break
  fi
  echo "[wrapper] attempt $i: $count files so far, running fetch_socrata.py..."
  python3 -m src.gov_usage.fetch_socrata --granularity month --start-year 2020 --end-year 2026
  echo "[wrapper] fetch_socrata.py exited (code $?), re-checking..."
  sleep 2
done
echo "[wrapper] done. final count: $(ls data/raw/parking_tickets_monthly/*.csv 2>/dev/null | wc -l)"
