#!/bin/sh
# Install only after approving the exact worker, bindings, secret and alerts.
set -u
umask 077
mode=${1:-inspect}
worker_exit=0
# Set this to the already verified immutable worker image, never a floating tag.
image=REPLACE_WITH_APPROVED_IMAGE_CONFIG_DIGEST
config=/volume1/Tabula_Rasa_Postgres/config
case "$image" in
  sha256:*) ;;
  *) printf '%s\n' 'Approved worker image is not configured.' >&2; exit 2 ;;
esac
for required in "$config/production/recurring.env" \
  "$config/bin/nas_recurring_monitor.py" "$config/production/recurring-monitor.json"
do
  if [ ! -r "$required" ]; then
    printf '%s\n' 'Protected worker configuration is unavailable.' >&2
    exit 1
  fi
done
/usr/local/bin/docker image inspect "$image" >/dev/null 2>&1 || exit 1
case "$mode" in
  inspect) notify= ;;
  tick)
    notify=--notify
    if [ ! -r "$config/production/recurring-heartbeat.env" ]; then
      printf '%s\n' 'Protected heartbeat configuration is unavailable.' >&2
      exit 1
    fi
    /bin/sh /volume1/Tabula_Rasa_Postgres/config/bin/run-recurring.sh tick
    worker_exit=$?
    ;;
  *) printf '%s\n' 'Unsupported monitored worker action.' >&2; exit 2 ;;
esac

set -- --rm --pull=never --network bridge --cap-drop ALL \
  --security-opt no-new-privileges=true --read-only --memory 192m \
  --env-file "$config/production/recurring.env" \
  --mount "type=bind,src=$config/bin/nas_recurring_monitor.py,dst=/monitor.py,readonly" \
  --mount "type=bind,src=$config/production/recurring-monitor.json,dst=/monitor.json,readonly"
if [ "$mode" = tick ]; then
  set -- "$@" --env-file "$config/production/recurring-heartbeat.env"
fi
/usr/local/bin/docker run "$@" --entrypoint python "$image" -c \
  'import runpy; runpy.run_path("/monitor.py", run_name="__main__")' \
  --config /monitor.json --worker-exit-code "$worker_exit" ${notify:+"$notify"}
