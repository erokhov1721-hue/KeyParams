#!/bin/sh
# Восстановить копию тома /data из хранилища restic в папку.
#
#   keyparams-restore.sh <папка> [копия]
#
# <папка> — куда развернуть (будет создана; внутри появится data/);
# [копия] — номер копии из «restic snapshots», по умолчанию самая свежая.
# Работающий том программы не трогается: копия разворачивается рядом, а
# подменить ею том — отдельный осознанный шаг (см. README, «Резервные
# копии»).

set -eu

if [ $# -lt 1 ]; then
    echo "использование: $0 <папка> [копия]" >&2
    exit 2
fi

CONF="${KEYPARAMS_BACKUP_CONF:-$HOME/.config/keyparams-backup}"
REPO="${KEYPARAMS_BACKUP_REPO:-$HOME/backups/keyparams-restic}"
IMAGE="${KEYPARAMS_BACKUP_IMAGE:-restic/restic:0.18.1}"
TARGET="$1"
SNAPSHOT="${2:-latest}"

mkdir -p "$TARGET" "$CONF/cache"
docker run --rm --user "$(id -u):$(id -g)" \
    -v "$REPO:/repo:ro" \
    -v "$CONF/restic-password:/run/restic-password:ro" \
    -v "$CONF/cache:/cache" \
    -v "$(cd "$TARGET" && pwd):/restore" \
    -e RESTIC_REPOSITORY=/repo \
    -e RESTIC_PASSWORD_FILE=/run/restic-password \
    -e RESTIC_CACHE_DIR=/cache \
    "$IMAGE" restore "$SNAPSHOT" --no-lock --host keyparams --target /restore
