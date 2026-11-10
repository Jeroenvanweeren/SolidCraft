#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -z "${SOLIDCRAFT_UPDATE_TOKEN:-}" ]]; then
    if [[ -s "$SCRIPT_DIR/.update-token" ]]; then
        IFS= read -r SOLIDCRAFT_UPDATE_TOKEN < "$SCRIPT_DIR/.update-token"
    else
        command -v openssl >/dev/null 2>&1 || {
            echo "Required command not found: openssl" >&2
            exit 1
        }
        SOLIDCRAFT_UPDATE_TOKEN="$(openssl rand -hex 32)"
        (umask 077; printf '%s\n' "$SOLIDCRAFT_UPDATE_TOKEN" > "$SCRIPT_DIR/.update-token")
    fi
    export SOLIDCRAFT_UPDATE_TOKEN
fi

if [[ -f "$SCRIPT_DIR/.update-token" ]]; then
    chmod 600 "$SCRIPT_DIR/.update-token"
fi

if (( ${#SOLIDCRAFT_UPDATE_TOKEN} < 32 )); then
    echo "SOLIDCRAFT_UPDATE_TOKEN must contain at least 32 characters." >&2
    exit 1
fi

for command in docker curl python3; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Required command not found: $command" >&2
        exit 1
    }
done

echo "Running all updater tests..."
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v

echo "Validating Docker Compose configuration..."
docker compose config -q

port="${SOLIDCRAFT_PORT:-8080}"
update_url="http://127.0.0.1:${port}/_admin/update?version=latest"

echo "Ensuring the current service is running..."
docker compose up -d solidcraft

echo "Installing the latest SolidCraft web release..."
if ! curl --fail --silent \
    --connect-timeout 5 \
    --max-time 900 \
    --retry 30 \
    --retry-all-errors \
    --retry-connrefused \
    --retry-delay 2 \
    --retry-max-time 900 \
    -X POST \
    -H "Authorization: Bearer ${SOLIDCRAFT_UPDATE_TOKEN}" \
    "$update_url"; then
    echo "Could not reach the SolidCraft update API." >&2
    exit 1
fi
printf '\n'

container_id="$(docker compose ps -q solidcraft)"
site_dir="$SCRIPT_DIR/.build/site"
mkdir -p "$site_dir"
find "$site_dir" -mindepth 1 -maxdepth 1 ! -name .keep -exec rm -rf -- {} +
docker cp "$container_id:/data/current/." "$site_dir/"
release_target="$(docker exec "$container_id" readlink /data/current)"
if [[ "$release_target" != releases/* ]]; then
    echo "Could not determine the installed SolidCraft release." >&2
    exit 1
fi
was_stopped=0
restart_previous_container() {
    result=$?
    if (( result != 0 && was_stopped == 1 )); then
        echo "Deployment failed; attempting to restart the previous container." >&2
        docker compose start solidcraft || true
    fi
    return "$result"
}
trap restart_previous_container EXIT

echo "Stopping the current container..."
docker compose stop solidcraft
was_stopped=1

echo "Rebuilding the container image..."
docker compose build --build-arg "IMAGE_VERSION=${SOLIDCRAFT_IMAGE_TAG:-local}" solidcraft
docker run --rm --entrypoint sh "ghcr.io/jeroenvanweeren/solidcraft-web:${SOLIDCRAFT_IMAGE_TAG:-local}" \
    -c 'test -s /opt/solidcraft/baked-release/index.html' || {
        echo "The rebuilt image does not contain the SolidCraft web bundle." >&2
        exit 1
    }

echo "Starting the rebuilt container..."
docker compose up -d --force-recreate solidcraft
was_stopped=0
trap - EXIT

echo "SolidCraft is running at http://localhost:${port}/"