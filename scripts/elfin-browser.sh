#!/usr/bin/env bash
# Wait for elfin to be healthy, then open Firefox
for _ in $(seq 1 60); do
  curl -sf http://localhost:8885/api/health >/dev/null 2>&1 && break
  sleep 2
done
exec firefox --kiosk http://localhost:8885
