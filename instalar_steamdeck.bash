#!/usr/bin/env bash

# Internal helper. instalar.bash sends this program to the Steam Deck over SSH.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

die() {
    printf 'ERROR (Steam Deck): %s\n' "$*" >&2
    exit 1
}

say() {
    printf 'Steam Deck: %s\n' "$*"
}

[[ "$#" -eq 8 ]] || die "protocolo remoto incompleto"

readonly OPERATION="$1"
readonly REQUESTED_GAME_DIR="$2"
readonly PAYLOAD_DIR_RAW="$3"
readonly ORIGINAL_ASSET_SHA256="$4"
readonly ORIGINAL_DLL_SHA256="$5"
readonly OUTPUT_ASSET_SHA256="$6"
readonly OUTPUT_DLL_SHA256="$7"
readonly LEGACY_ASSET_SHA256="$8"

case "$OPERATION" in
    preflight-install|preflight-restore|install|restore) ;;
    *) die "operación remota desconocida: $OPERATION" ;;
esac

for digest in "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "$LEGACY_ASSET_SHA256"; do
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "fingerprint remoto inválido"
done
if [[ "$OPERATION" == "install" ]]; then
    [[ "$OUTPUT_ASSET_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "SHA-256 del asset generado inválido"
    [[ "$OUTPUT_DLL_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "SHA-256 del DLL generado inválido"
fi

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "falta el comando requerido: $1"
}

for command_name in bash sha256sum cut realpath mktemp cp chmod mv ln rm rmdir dirname pgrep flock sync; do
    require_command "$command_name"
done

sha256_file() {
    sha256sum -- "$1" | cut -d ' ' -f 1
}

hash_matches() {
    local path="$1"
    local expected="$2"

    [[ ! -L "$path" ]] && [[ -f "$path" ]] && [[ "$(sha256_file "$path")" == "$expected" ]]
}

verify_hash() {
    local path="$1"
    local expected="$2"
    local description="$3"
    local actual

    [[ ! -L "$path" ]] || die "$description no puede ser un enlace simbólico"
    [[ -f "$path" ]] || die "$description no existe"
    actual="$(sha256_file "$path")"
    [[ "$actual" == "$expected" ]] || die "$description tiene un SHA-256 inesperado"
}

declare -A SEEN_GAME_DIRS=()
GAME_DIR_CANDIDATES=()

add_game_dir_candidate() {
    local candidate="$1"
    local resolved

    [[ -d "$candidate/Gnosia_Data/Managed" ]] || return 0
    [[ -f "$candidate/Gnosia_Data/sharedassets0.assets" ]] || return 0
    [[ -f "$candidate/Gnosia_Data/Managed/Assembly-CSharp.dll" ]] || return 0
    resolved="$(realpath -e -- "$candidate")"
    if [[ -z "${SEEN_GAME_DIRS[$resolved]+present}" ]]; then
        SEEN_GAME_DIRS["$resolved"]=1
        GAME_DIR_CANDIDATES+=("$resolved")
    fi
}

detect_game_dir() {
    local mount
    local mounts=()

    if [[ "$REQUESTED_GAME_DIR" != "-" ]]; then
        [[ "$REQUESTED_GAME_DIR" == /* ]] || die "--deck-game-dir debe ser una ruta absoluta"
        add_game_dir_candidate "$REQUESTED_GAME_DIR"
    else
        add_game_dir_candidate "$HOME/.local/share/Steam/steamapps/common/GNOSIA"
        add_game_dir_candidate "$HOME/.steam/steam/steamapps/common/GNOSIA"
        shopt -s nullglob
        mounts=(/run/media/deck/*)
        shopt -u nullglob
        for mount in "${mounts[@]}"; do
            add_game_dir_candidate "$mount/steamapps/common/GNOSIA"
        done
    fi

    if [[ "${#GAME_DIR_CANDIDATES[@]}" -eq 0 ]]; then
        die "no se encontró una instalación de GNOSIA"
    fi
    if [[ "${#GAME_DIR_CANDIDATES[@]}" -ne 1 ]]; then
        die "se encontraron varias instalaciones; usa --deck-game-dir"
    fi
    GAME_DIR="${GAME_DIR_CANDIDATES[0]}"
}

detect_game_dir

readonly DATA_DIR="$GAME_DIR/Gnosia_Data"
readonly ASSET_TARGET="$DATA_DIR/sharedassets0.assets"
readonly DLL_TARGET="$DATA_DIR/Managed/Assembly-CSharp.dll"
readonly ASSET_BACKUP="${ASSET_TARGET}.traductor_es-original.bak"
readonly DLL_BACKUP="${DLL_TARGET}.traductor_es-original.bak"
readonly STATE_FILE="$DATA_DIR/.traductor_es-state"
readonly JOURNAL_FILE="$DATA_DIR/.traductor_es-install.pending"
readonly LOCK_FILE="$DATA_DIR/.traductor_es.lock"

[[ ! -L "$ASSET_TARGET" ]] || die "el asset instalado es un enlace simbólico"
[[ ! -L "$DLL_TARGET" ]] || die "el DLL instalado es un enlace simbólico"

CURRENT_ASSET_SHA=""
CURRENT_DLL_SHA=""
PAIR_STATUS=""
BACKUP_STATUS=""
LAST_ASSET_SHA=""
LAST_DLL_SHA=""
PENDING_ASSET_STAGE=""
PENDING_DLL_STAGE=""
PAYLOAD_DIR=""
PAYLOAD_SAFE=0

load_state_hashes() {
    LAST_ASSET_SHA=""
    LAST_DLL_SHA=""
    [[ -e "$STATE_FILE" ]] || return 0
    [[ ! -L "$STATE_FILE" ]] || die "el estado remoto es un enlace simbólico"
    [[ -f "$STATE_FILE" ]] || die "el estado remoto no es un archivo regular"

    local key value
    while IFS=' ' read -r key value; do
        case "$key" in
            asset_sha256) LAST_ASSET_SHA="$value" ;;
            dll_sha256) LAST_DLL_SHA="$value" ;;
        esac
    done <"$STATE_FILE"
}

inspect_pair() {
    [[ -f "$ASSET_TARGET" ]] || die "falta el asset instalado"
    [[ -f "$DLL_TARGET" ]] || die "falta el DLL instalado"
    CURRENT_ASSET_SHA="$(sha256_file "$ASSET_TARGET")"
    CURRENT_DLL_SHA="$(sha256_file "$DLL_TARGET")"
    load_state_hashes

    if [[ "$CURRENT_ASSET_SHA" == "$ORIGINAL_ASSET_SHA256" ]] && \
       [[ "$CURRENT_DLL_SHA" == "$ORIGINAL_DLL_SHA256" ]]; then
        PAIR_STATUS="original"
    elif [[ -n "$LAST_ASSET_SHA" ]] && [[ -n "$LAST_DLL_SHA" ]] && \
         [[ "$CURRENT_ASSET_SHA" == "$LAST_ASSET_SHA" ]] && \
         [[ "$CURRENT_DLL_SHA" == "$LAST_DLL_SHA" ]]; then
        PAIR_STATUS="managed"
    elif [[ "$CURRENT_ASSET_SHA" == "$LEGACY_ASSET_SHA256" ]] && \
         [[ "$CURRENT_DLL_SHA" == "$ORIGINAL_DLL_SHA256" ]]; then
        PAIR_STATUS="legacy"
    else
        PAIR_STATUS="unknown"
    fi
}

inspect_backups() {
    if [[ ! -e "$ASSET_BACKUP" ]] && [[ ! -e "$DLL_BACKUP" ]]; then
        BACKUP_STATUS="absent"
        return 0
    fi
    if [[ -e "$ASSET_BACKUP" ]]; then
        verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup remoto del asset"
    fi
    if [[ -e "$DLL_BACKUP" ]]; then
        verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup remoto del DLL"
    fi
    if [[ -e "$ASSET_BACKUP" ]] && [[ -e "$DLL_BACKUP" ]]; then
        BACKUP_STATUS="valid"
    else
        BACKUP_STATUS="partial"
    fi
}

preflight() {
    inspect_pair
    inspect_backups
    [[ ! -L "$JOURNAL_FILE" ]] || die "el journal remoto es un enlace simbólico"
    [[ ! -e "$JOURNAL_FILE" || -f "$JOURNAL_FILE" ]] || die "el journal remoto no es un archivo regular"

    say "juego=$GAME_DIR"
    say "estado=$PAIR_STATUS backups=$BACKUP_STATUS journal=$([[ -e "$JOURNAL_FILE" ]] && printf pendiente || printf limpio)"

    if [[ "$OPERATION" == "preflight-restore" ]]; then
        [[ "$BACKUP_STATUS" == "valid" ]] || die "no hay backups remotos originales que restaurar"
        return 0
    fi

    if [[ -e "$JOURNAL_FILE" ]]; then
        [[ "$BACKUP_STATUS" == "valid" ]] || die "hay un journal pendiente sin backups recuperables"
        return 0
    fi
    [[ "$PAIR_STATUS" != "unknown" ]] || die "la pareja remota es desconocida; no se modificará"
    if [[ "$BACKUP_STATUS" != "valid" ]]; then
        [[ "$PAIR_STATUS" == "original" || "$PAIR_STATUS" == "legacy" ]] || \
            die "faltan backups remotos para el estado administrado"
    fi
}

if [[ "$OPERATION" == preflight-* ]]; then
    preflight
    exit 0
fi

game_is_running() {
    pgrep -fi '[g]nosia\.exe|SteamLaunch.*AppId=1608290' >/dev/null 2>&1
}

require_game_closed() {
    if game_is_running; then
        die "GNOSIA está abierto; ciérralo antes de publicar"
    fi
}

sync_path() {
    sync -f "$1" 2>/dev/null || sync
}

write_state() {
    local asset_sha="$1"
    local dll_sha="$2"
    local status="$3"
    local stage

    stage="$(mktemp "${STATE_FILE}.pending.XXXXXX")"
    {
        printf 'version 1\n'
        printf 'status %s\n' "$status"
        printf 'asset_sha256 %s\n' "$asset_sha"
        printf 'dll_sha256 %s\n' "$dll_sha"
    } >"$stage"
    sync_path "$stage"
    mv -T -- "$stage" "$STATE_FILE"
    sync_path "$DATA_DIR"
}

publish_backup() {
    local source="$1"
    local destination="$2"
    local expected="$3"
    local stage

    stage="$(mktemp "${destination}.pending.XXXXXX")"
    cp -p -- "$source" "$stage"
    verify_hash "$stage" "$expected" "backup remoto temporal"
    sync_path "$stage"
    if ! ln -- "$stage" "$destination"; then
        rm -f -- "$stage"
        die "no se pudo publicar el backup remoto sin sobrescribirlo"
    fi
    rm -f -- "$stage"
    verify_hash "$destination" "$expected" "backup remoto publicado"
    sync_path "$(dirname -- "$destination")"
}

make_stage() {
    local source="$1"
    local target="$2"
    local expected="$3"
    local mode_reference="$target"
    local stage

    verify_hash "$source" "$expected" "artefacto remoto"
    [[ -f "$mode_reference" ]] || mode_reference="$source"
    stage="$(mktemp "${target}.traductor_es-stage.XXXXXX")"
    cp -p -- "$source" "$stage"
    chmod --reference="$mode_reference" -- "$stage"
    verify_hash "$stage" "$expected" "archivo remoto preparado"
    sync_path "$stage"
    printf '%s\n' "$stage"
}

restore_originals_low_level() {
    local asset_stage dll_stage

    verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup remoto original del asset"
    verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup remoto original del DLL"
    asset_stage="$(make_stage "$ASSET_BACKUP" "$ASSET_TARGET" "$ORIGINAL_ASSET_SHA256")"
    dll_stage="$(make_stage "$DLL_BACKUP" "$DLL_TARGET" "$ORIGINAL_DLL_SHA256")"
    mv -T -- "$asset_stage" "$ASSET_TARGET"
    if ! mv -T -- "$dll_stage" "$DLL_TARGET"; then
        say "FALLO CRÍTICO: no se pudo completar la restauración del DLL"
        return 1
    fi
    sync_path "$ASSET_TARGET"
    sync_path "$DLL_TARGET"
    verify_hash "$ASSET_TARGET" "$ORIGINAL_ASSET_SHA256" "asset remoto restaurado"
    verify_hash "$DLL_TARGET" "$ORIGINAL_DLL_SHA256" "DLL remoto restaurado"
}

rollback_on_signal() {
    local status="$1"

    trap - INT TERM HUP
    say "interrupción detectada; restaurando originales"
    rm -f -- "$PENDING_ASSET_STAGE" "$PENDING_DLL_STAGE"
    if restore_originals_low_level; then
        write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored-after-interruption"
        rm -f -- "$JOURNAL_FILE"
    fi
    exit "$status"
}

commit_pair() {
    local asset_source="$1"
    local dll_source="$2"
    local asset_sha="$3"
    local dll_sha="$4"
    local status="$5"
    local journal_stage

    PENDING_ASSET_STAGE="$(make_stage "$asset_source" "$ASSET_TARGET" "$asset_sha")"
    PENDING_DLL_STAGE="$(make_stage "$dll_source" "$DLL_TARGET" "$dll_sha")"
    journal_stage="$(mktemp "${JOURNAL_FILE}.pending.XXXXXX")"
    {
        printf 'asset_sha256 %s\n' "$asset_sha"
        printf 'dll_sha256 %s\n' "$dll_sha"
    } >"$journal_stage"
    sync_path "$journal_stage"
    mv -T -- "$journal_stage" "$JOURNAL_FILE"
    sync_path "$DATA_DIR"

    trap 'rollback_on_signal 130' INT
    trap 'rollback_on_signal 143' TERM
    trap 'rollback_on_signal 129' HUP

    if ! mv -T -- "$PENDING_ASSET_STAGE" "$ASSET_TARGET"; then
        rm -f -- "$PENDING_ASSET_STAGE" "$PENDING_DLL_STAGE" "$JOURNAL_FILE"
        trap - INT TERM HUP
        die "no se pudo instalar el asset remoto"
    fi
    PENDING_ASSET_STAGE=""
    if ! mv -T -- "$PENDING_DLL_STAGE" "$DLL_TARGET"; then
        trap - INT TERM HUP
        rm -f -- "$PENDING_DLL_STAGE"
        say "falló el DLL; restaurando ambos originales"
        restore_originals_low_level || die "falló también la recuperación; se conserva el journal"
        write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored-after-error"
        rm -f -- "$JOURNAL_FILE"
        die "publicación remota cancelada"
    fi
    PENDING_DLL_STAGE=""
    sync_path "$ASSET_TARGET"
    sync_path "$DLL_TARGET"

    if ! hash_matches "$ASSET_TARGET" "$asset_sha" || ! hash_matches "$DLL_TARGET" "$dll_sha"; then
        trap - INT TERM HUP
        say "falló la verificación final; restaurando ambos originales"
        restore_originals_low_level || die "falló también la recuperación; se conserva el journal"
        write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored-after-error"
        rm -f -- "$JOURNAL_FILE"
        die "publicación remota no verificada"
    fi

    trap - INT TERM HUP
    write_state "$asset_sha" "$dll_sha" "$status"
    rm -f -- "$JOURNAL_FILE"
    sync_path "$DATA_DIR"
}

cleanup_payload() {
    local stage

    for stage in "$PENDING_ASSET_STAGE" "$PENDING_DLL_STAGE"; do
        [[ -n "$stage" ]] && rm -f -- "$stage"
    done
    [[ "$PAYLOAD_SAFE" -eq 1 ]] || return 0
    rm -f -- \
        "$PAYLOAD_DIR/original-sharedassets0.assets" \
        "$PAYLOAD_DIR/original-Assembly-CSharp.dll" \
        "$PAYLOAD_DIR/translated-sharedassets0.assets" \
        "$PAYLOAD_DIR/translated-Assembly-CSharp.dll"
    rmdir -- "$PAYLOAD_DIR" 2>/dev/null || true
}
trap cleanup_payload EXIT

[[ ! -L "$LOCK_FILE" ]] || die "el lock remoto es un enlace simbólico"
exec 8>"$LOCK_FILE"
flock -n 8 || die "ya hay otra publicación de GNOSIA en esta Steam Deck"
require_game_closed

inspect_pair
inspect_backups
if [[ -e "$JOURNAL_FILE" ]]; then
    [[ ! -L "$JOURNAL_FILE" ]] || die "el journal remoto es un enlace simbólico"
    [[ -f "$JOURNAL_FILE" ]] || die "el journal remoto no es un archivo regular"
    [[ "$BACKUP_STATUS" == "valid" ]] || die "journal pendiente sin backups recuperables"
    say "recuperando una publicación anterior interrumpida"
    restore_originals_low_level
    write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "recovered"
    rm -f -- "$JOURNAL_FILE"
    inspect_pair
fi

if [[ "$OPERATION" == "restore" ]]; then
    [[ "$BACKUP_STATUS" == "valid" ]] || die "no hay backups remotos originales que restaurar"
    commit_pair "$ASSET_BACKUP" "$DLL_BACKUP" \
        "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored"
    say "restauración completada y verificada; los backups se conservan"
    exit 0
fi

readonly PAYLOAD_BASE="$HOME/.cache/traductor_es"
PAYLOAD_DIR="$(realpath -m -- "$PAYLOAD_DIR_RAW")"
[[ ! -L "$PAYLOAD_DIR_RAW" ]] || die "el directorio de transferencia es un enlace simbólico"
case "$PAYLOAD_DIR" in
    "$PAYLOAD_BASE"/deploy.*) ;;
    *) die "directorio de transferencia remoto no permitido" ;;
esac
[[ -d "$PAYLOAD_DIR" ]] || die "no existe el directorio de transferencia remoto"
PAYLOAD_SAFE=1

readonly PAYLOAD_ORIGINAL_ASSET="$PAYLOAD_DIR/original-sharedassets0.assets"
readonly PAYLOAD_ORIGINAL_DLL="$PAYLOAD_DIR/original-Assembly-CSharp.dll"
readonly PAYLOAD_OUTPUT_ASSET="$PAYLOAD_DIR/translated-sharedassets0.assets"
readonly PAYLOAD_OUTPUT_DLL="$PAYLOAD_DIR/translated-Assembly-CSharp.dll"

verify_hash "$PAYLOAD_ORIGINAL_ASSET" "$ORIGINAL_ASSET_SHA256" "original local transferido"
verify_hash "$PAYLOAD_ORIGINAL_DLL" "$ORIGINAL_DLL_SHA256" "DLL original local transferido"
verify_hash "$PAYLOAD_OUTPUT_ASSET" "$OUTPUT_ASSET_SHA256" "asset traducido transferido"
verify_hash "$PAYLOAD_OUTPUT_DLL" "$OUTPUT_DLL_SHA256" "DLL traducido transferido"
[[ "$OUTPUT_ASSET_SHA256" != "$ORIGINAL_ASSET_SHA256" ]] || die "el asset transferido no contiene cambios"
[[ "$OUTPUT_DLL_SHA256" != "$ORIGINAL_DLL_SHA256" ]] || die "el DLL transferido no contiene cambios"

[[ "$PAIR_STATUS" != "unknown" ]] || die "la pareja remota cambió y ahora es desconocida"
if [[ "$PAIR_STATUS" == "legacy" ]]; then
    readonly PREEXISTING_ASSET_BACKUP="${ASSET_TARGET}.traductor_es-preexisting-${CURRENT_ASSET_SHA:0:12}.bak"
    if [[ -e "$PREEXISTING_ASSET_BACKUP" ]]; then
        verify_hash "$PREEXISTING_ASSET_BACKUP" "$CURRENT_ASSET_SHA" "backup de la traducción anterior"
    else
        publish_backup "$ASSET_TARGET" "$PREEXISTING_ASSET_BACKUP" "$CURRENT_ASSET_SHA"
        say "traducción anterior preservada en $PREEXISTING_ASSET_BACKUP"
    fi
fi

if [[ ! -e "$ASSET_BACKUP" ]]; then
    if [[ "$CURRENT_ASSET_SHA" == "$ORIGINAL_ASSET_SHA256" ]]; then
        publish_backup "$ASSET_TARGET" "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256"
    elif [[ "$PAIR_STATUS" == "legacy" ]]; then
        publish_backup "$PAYLOAD_ORIGINAL_ASSET" "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256"
    else
        die "no se puede crear el backup original remoto del asset"
    fi
fi
if [[ ! -e "$DLL_BACKUP" ]]; then
    if [[ "$CURRENT_DLL_SHA" == "$ORIGINAL_DLL_SHA256" ]]; then
        publish_backup "$DLL_TARGET" "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256"
    elif [[ "$PAIR_STATUS" == "legacy" ]]; then
        publish_backup "$PAYLOAD_ORIGINAL_DLL" "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256"
    else
        die "no se puede crear el backup original remoto del DLL"
    fi
fi
verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup remoto original del asset"
verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup remoto original del DLL"
inspect_pair
[[ "$PAIR_STATUS" != "unknown" ]] || die "la pareja remota cambió durante la preparación"

commit_pair "$PAYLOAD_OUTPUT_ASSET" "$PAYLOAD_OUTPUT_DLL" \
    "$OUTPUT_ASSET_SHA256" "$OUTPUT_DLL_SHA256" "installed"
say "instalación completada y verificada"
