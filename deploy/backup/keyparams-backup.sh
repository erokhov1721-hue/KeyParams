#!/bin/sh
# Ежедневная зашифрованная копия тома /data программы (Docker-том
# keyparams_keyparams-data) — restic в Docker, без установки на сервер.
#
#   - копия всего /data: проекты, users.json, журналы, анализ КП;
#   - хранится 14 ежедневных и 8 еженедельных копий, остальные удаляются;
#   - по воскресеньям — проверка целостности хранилища (restic check);
#   - если есть файл $CONF/offsite.env — копии ещё и уходят во второе
#     хранилище за пределами сервера (см. README, «Резервные копии»):
#     подключается этим файлом, скрипт править не нужно.
#
# Запускается cron'ом пользователя, который состоит в группе docker. Ничего
# секретного не печатает: пароль хранилища генерируется при первом запуске
# в $CONF/restic-password (права 600) и в журнал не попадает.

set -eu

CONF="${KEYPARAMS_BACKUP_CONF:-$HOME/.config/keyparams-backup}"
REPO="${KEYPARAMS_BACKUP_REPO:-$HOME/backups/keyparams-restic}"
VOLUME="${KEYPARAMS_BACKUP_VOLUME:-keyparams_keyparams-data}"
IMAGE="${KEYPARAMS_BACKUP_IMAGE:-restic/restic:0.18.1}"
HOST_TAG="keyparams"
KEEP_DAILY=14
KEEP_WEEKLY=8
LOG="$CONF/backup.log"

mkdir -p "$CONF" "$REPO" "$CONF/cache"
chmod 700 "$CONF"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"
}

# Один запуск за раз: ручной запуск во время ночного не должен им помешать.
exec 9>"$CONF/lock"
if ! flock -n 9; then
    log "уже идёт другой запуск — пропускаю"
    exit 0
fi

if [ ! -s "$CONF/restic-password" ]; then
    (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$CONF/restic-password")
    log "создан пароль хранилища: $CONF/restic-password — сохраните его вне сервера"
fi

# restic в контейнере от имени этого пользователя: файлы хранилища — его,
# а не root; том с данными — только для чтения.
restic() {
    docker run --rm --user "$(id -u):$(id -g)" \
        -v "$REPO:/repo" \
        -v "$CONF/restic-password:/run/restic-password:ro" \
        -v "$CONF/cache:/cache" \
        -v "$VOLUME:/data:ro" \
        -e RESTIC_REPOSITORY=/repo \
        -e RESTIC_PASSWORD_FILE=/run/restic-password \
        -e RESTIC_CACHE_DIR=/cache \
        "$IMAGE" "$@"
}

run() {
    if "$@" >> "$LOG" 2>&1; then
        return 0
    fi
    log "ОШИБКА: $*"
    return 1
}

log "начало копии"
if [ ! -f "$REPO/config" ]; then
    run restic init
fi
run restic backup /data --host "$HOST_TAG" --tag keyparams
run restic forget --host "$HOST_TAG" --tag keyparams \
    --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --prune
if [ "$(date -u +%u)" = "7" ]; then
    run restic check
fi

# Второе хранилище за пределами сервера — когда появится. offsite.env задаёт
# RESTIC_REPOSITORY (например sftp:user@host:/path или s3:...), RESTIC_PASSWORD
# (свой пароль того хранилища) и, если нужно, ключи доступа к нему
# (AWS_ACCESS_KEY_ID и т. п.). Копии туда переносятся как есть — restic copy.
if [ -f "$CONF/offsite.env" ]; then
    offsite() {
        docker run --rm --user "$(id -u):$(id -g)" \
            --env-file "$CONF/offsite.env" \
            -v "$REPO:/repo" \
            -v "$CONF/restic-password:/run/restic-password:ro" \
            -v "$CONF/cache:/cache" \
            -e RESTIC_CACHE_DIR=/cache \
            "$IMAGE" "$@"
    }
    if ! offsite cat config >/dev/null 2>&1; then
        run offsite init --from-repo /repo --from-password-file /run/restic-password \
            --copy-chunker-params
    fi
    run offsite copy --from-repo /repo --from-password-file /run/restic-password
    run offsite forget --host "$HOST_TAG" --tag keyparams \
        --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --prune
fi
log "копия готова"
