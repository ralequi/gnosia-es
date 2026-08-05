#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly GAME_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly DATA_DIR="$GAME_DIR/Gnosia_Data"
readonly ASSET_TARGET="$DATA_DIR/sharedassets0.assets"
readonly DLL_TARGET="$DATA_DIR/Managed/Assembly-CSharp.dll"
readonly BUNDLE_DIR="$DATA_DIR/StreamingAssets/aa/StandaloneWindows64"
readonly ASSET_BACKUP="${ASSET_TARGET}.traductor_es-original.bak"
readonly DLL_BACKUP="${DLL_TARGET}.traductor_es-original.bak"
readonly STATE_FILE="$DATA_DIR/.traductor_es-state"
readonly JOURNAL_FILE="$DATA_DIR/.traductor_es-install.pending"
readonly TMP_ROOT="$SCRIPT_DIR/tmp"
readonly VENV_DIR="$SCRIPT_DIR/.venv"
readonly VENV_PYTHON="$VENV_DIR/bin/python"
readonly STEAM_DECK_HELPER="$SCRIPT_DIR/instalar_steamdeck.bash"

# Fingerprints of the supported Steam build. Never make a backup from an
# installed file unless it matches its original fingerprint exactly.
readonly ORIGINAL_ASSET_SHA256="f97e8e126e3b2419d4748af6c0550715a208c02166b543f224e8895434470057"
readonly ORIGINAL_DLL_SHA256="d5b0f013fc343e5cdde56f598a251c7cd7acfdd258430910b50707faf2362fe2"
# Fingerprint of the previous asset-only translation installed before this
# installer managed both files. It is safe to migrate, but never to treat as
# an original backup.
readonly LEGACY_ASSET_SHA256="47afc93d2522d56752b22935ab30fbe926175274bce222a6fdef96bcd159c3fb"

ACTION="install"
CECIL_PATH=""
BUILD_DIR=""
ASSET_OUTPUT=""
DLL_OUTPUT=""
PENDING_ASSET_STAGE=""
PENDING_DLL_STAGE=""
STEAM_DECK_DEST=""
DECK_GAME_DIR="-"
REMOTE_PAYLOAD_DIR=""
REMOTE_PAYLOAD_ACTIVE=0
SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=10)

say() {
    printf '\n==> %s\n' "$*"
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Uso: bash instalar.bash [opciones]

Sin opciones, reconstruye, valida e instala la traducción completa.

Opciones:
  --build-only       Genera y valida, pero no sustituye archivos del juego.
  --restore          Restaura los dos originales desde los backups verificados.
  --cecil RUTA       Usa este Mono.Cecil.dll para parchear Assembly-CSharp.dll.
  --steam-deck HOST  Publica por SSH en una Steam Deck (p. ej. deck@steamdeck.local).
  --deck-game-dir RUTA
                     Ruta absoluta remota si la autodetección es ambigua.
  -h, --help         Muestra esta ayuda.

Los backups nunca se sobrescriben:
  Gnosia_Data/sharedassets0.assets.traductor_es-original.bak
  Gnosia_Data/Managed/Assembly-CSharp.dll.traductor_es-original.bak
EOF
}

while (($# > 0)); do
    case "$1" in
        --build-only)
            [[ "$ACTION" == "install" ]] || die "solo se puede elegir una acción"
            ACTION="build-only"
            shift
            ;;
        --restore)
            [[ "$ACTION" == "install" ]] || die "solo se puede elegir una acción"
            ACTION="restore"
            shift
            ;;
        --cecil)
            (($# >= 2)) || die "--cecil necesita una ruta"
            CECIL_PATH="$2"
            shift 2
            ;;
        --steam-deck|--steamdeck)
            (($# >= 2)) || die "$1 necesita USUARIO@HOST"
            [[ "$2" != -* ]] || die "$1 necesita USUARIO@HOST"
            [[ -z "$STEAM_DECK_DEST" ]] || die "--steam-deck solo puede indicarse una vez"
            STEAM_DECK_DEST="$2"
            shift 2
            ;;
        --deck-game-dir)
            (($# >= 2)) || die "--deck-game-dir necesita una ruta absoluta remota"
            [[ "$DECK_GAME_DIR" == "-" ]] || die "--deck-game-dir solo puede indicarse una vez"
            DECK_GAME_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "opción desconocida: $1 (usa --help)"
            ;;
    esac
done

if [[ -n "$STEAM_DECK_DEST" ]]; then
    [[ "$STEAM_DECK_DEST" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*(@[A-Za-z0-9][A-Za-z0-9_.-]*)?$ ]] || \
        die "destino SSH inválido: $STEAM_DECK_DEST"
fi
if [[ "$DECK_GAME_DIR" != "-" ]]; then
    [[ -n "$STEAM_DECK_DEST" ]] || die "--deck-game-dir requiere --steam-deck"
    [[ "$DECK_GAME_DIR" == /* ]] || die "--deck-game-dir debe ser absoluta"
    [[ "$DECK_GAME_DIR" != *$'\n'* ]] || die "--deck-game-dir contiene caracteres no permitidos"
fi

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "no se encontró el comando requerido: $1"
}

sha256_file() {
    sha256sum -- "$1" | cut -d ' ' -f 1
}

verify_hash() {
    local path="$1"
    local expected="$2"
    local description="$3"
    local actual

    [[ ! -L "$path" ]] || die "$description no puede ser un enlace simbólico: $path"
    [[ -f "$path" ]] || die "$description no existe: $path"
    actual="$(sha256_file "$path")"
    [[ "$actual" == "$expected" ]] || die \
        "$description tiene SHA-256 inesperado: $actual (esperado: $expected)"
}

hash_matches() {
    local path="$1"
    local expected="$2"

    [[ ! -L "$path" ]] && [[ -f "$path" ]] && [[ "$(sha256_file "$path")" == "$expected" ]]
}

find_original_backup() {
    local target="$1"
    local expected="$2"
    local candidate
    local candidates=()

    shopt -s nullglob
    candidates=("$target"*.bak*)
    shopt -u nullglob
    for candidate in "${candidates[@]}"; do
        [[ -f "$candidate" ]] && [[ ! -L "$candidate" ]] || continue
        if [[ "$(sha256_file "$candidate")" == "$expected" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

publish_backup() {
    local source="$1"
    local destination="$2"
    local expected="$3"
    local stage

    stage="$(mktemp "${destination}.pending.XXXXXX")"
    cp -p -- "$source" "$stage"
    verify_hash "$stage" "$expected" "backup temporal"

    # A hard link publishes the verified file without ever replacing an
    # existing path. Both files live in the same destination directory.
    if ! ln -- "$stage" "$destination"; then
        rm -f -- "$stage"
        die "no se pudo publicar el backup sin sobrescribir: $destination"
    fi
    rm -f -- "$stage"
    verify_hash "$destination" "$expected" "backup publicado"
}

ensure_backup() {
    local target="$1"
    local backup="$2"
    local expected="$3"
    local description="$4"
    local existing=""

    if [[ -e "$backup" ]]; then
        verify_hash "$backup" "$expected" "$description"
        printf 'Backup verificado: %s\n' "$backup"
        return
    fi

    if [[ -f "$target" ]] && [[ "$(sha256_file "$target")" == "$expected" ]]; then
        say "Creando $description"
        publish_backup "$target" "$backup" "$expected"
        printf 'Backup creado: %s\n' "$backup"
        return
    fi

    if existing="$(find_original_backup "$target" "$expected")"; then
        say "Normalizando $description existente"
        publish_backup "$existing" "$backup" "$expected"
        printf 'Backup reutilizado desde: %s\n' "$existing"
        return
    fi

    die "el archivo instalado no es el original soportado y no hay un $description verificable: $target"
}

ensure_backups() {
    [[ ! -L "$ASSET_TARGET" ]] || die "el asset instalado no puede ser un enlace simbólico"
    [[ ! -L "$DLL_TARGET" ]] || die "el DLL instalado no puede ser un enlace simbólico"
    ensure_backup "$ASSET_TARGET" "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" \
        "backup original de sharedassets0.assets"
    ensure_backup "$DLL_TARGET" "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" \
        "backup original de Assembly-CSharp.dll"
}

game_is_running() {
    pgrep -fi '[g]nosia\.exe' >/dev/null 2>&1
}

require_game_closed() {
    require_command pgrep
    if game_is_running; then
        die "GNOSIA está abierto; ciérralo antes de instalar o restaurar"
    fi
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
    mv -T -- "$stage" "$STATE_FILE"
}

load_state_hashes() {
    LAST_ASSET_SHA=""
    LAST_DLL_SHA=""
    [[ -f "$STATE_FILE" ]] || return 0

    local key value
    while IFS=' ' read -r key value; do
        case "$key" in
            asset_sha256) LAST_ASSET_SHA="$value" ;;
            dll_sha256) LAST_DLL_SHA="$value" ;;
        esac
    done <"$STATE_FILE"
}

ensure_known_installed_pair() {
    local asset_sha dll_sha

    [[ -f "$ASSET_TARGET" ]] || die "falta el asset instalado: $ASSET_TARGET"
    [[ -f "$DLL_TARGET" ]] || die "falta el DLL instalado: $DLL_TARGET"
    asset_sha="$(sha256_file "$ASSET_TARGET")"
    dll_sha="$(sha256_file "$DLL_TARGET")"

    if [[ "$asset_sha" == "$ORIGINAL_ASSET_SHA256" ]] && \
       [[ "$dll_sha" == "$ORIGINAL_DLL_SHA256" ]]; then
        return
    fi

    load_state_hashes
    if [[ -n "$LAST_ASSET_SHA" ]] && [[ -n "$LAST_DLL_SHA" ]] && \
       [[ "$asset_sha" == "$LAST_ASSET_SHA" ]] && [[ "$dll_sha" == "$LAST_DLL_SHA" ]]; then
        return
    fi

    die "la pareja instalada es desconocida o está mezclada; usa --restore o verifica los archivos con Steam"
}

make_stage() {
    local source="$1"
    local target="$2"
    local expected="$3"
    local mode_reference="$target"
    local stage

    [[ -f "$source" ]] || die "artefacto de instalación ausente: $source"
    [[ -f "$mode_reference" ]] || mode_reference="$source"
    stage="$(mktemp "${target}.traductor_es-stage.XXXXXX")"
    cp -p -- "$source" "$stage"
    chmod --reference="$mode_reference" -- "$stage"
    verify_hash "$stage" "$expected" "archivo preparado"
    printf '%s\n' "$stage"
}

restore_originals_low_level() {
    local asset_stage dll_stage

    verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup original del asset"
    verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup original del DLL"
    asset_stage="$(make_stage "$ASSET_BACKUP" "$ASSET_TARGET" "$ORIGINAL_ASSET_SHA256")"
    dll_stage="$(make_stage "$DLL_BACKUP" "$DLL_TARGET" "$ORIGINAL_DLL_SHA256")"

    mv -T -- "$asset_stage" "$ASSET_TARGET"
    if ! mv -T -- "$dll_stage" "$DLL_TARGET"; then
        printf 'ERROR CRÍTICO: no se pudo completar la restauración del DLL; el journal se conserva.\n' >&2
        return 1
    fi
    verify_hash "$ASSET_TARGET" "$ORIGINAL_ASSET_SHA256" "asset restaurado"
    verify_hash "$DLL_TARGET" "$ORIGINAL_DLL_SHA256" "DLL restaurado"
}

rollback_on_signal() {
    local status="$1"

    trap - INT TERM HUP
    printf '\nInterrupción durante la instalación; restaurando los originales...\n' >&2
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

    require_game_closed
    verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup original del asset"
    verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup original del DLL"

    PENDING_ASSET_STAGE="$(make_stage "$asset_source" "$ASSET_TARGET" "$asset_sha")"
    PENDING_DLL_STAGE="$(make_stage "$dll_source" "$DLL_TARGET" "$dll_sha")"

    journal_stage="$(mktemp "${JOURNAL_FILE}.pending.XXXXXX")"
    {
        printf 'asset_sha256 %s\n' "$asset_sha"
        printf 'dll_sha256 %s\n' "$dll_sha"
    } >"$journal_stage"
    mv -T -- "$journal_stage" "$JOURNAL_FILE"

    trap 'rollback_on_signal 130' INT
    trap 'rollback_on_signal 143' TERM
    trap 'rollback_on_signal 129' HUP

    if ! mv -T -- "$PENDING_ASSET_STAGE" "$ASSET_TARGET"; then
        rm -f -- "$PENDING_DLL_STAGE" "$JOURNAL_FILE"
        trap - INT TERM HUP
        die "no se pudo instalar el asset; no se sustituyó el DLL"
    fi
    PENDING_ASSET_STAGE=""

    if ! mv -T -- "$PENDING_DLL_STAGE" "$DLL_TARGET"; then
        trap - INT TERM HUP
        printf 'Fallo al instalar el DLL; restaurando ambos originales...\n' >&2
        rm -f -- "$PENDING_DLL_STAGE"
        restore_originals_low_level || die "falló también la recuperación; conserva el journal"
        write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored-after-error"
        rm -f -- "$JOURNAL_FILE"
        die "la instalación se canceló y se restauraron los originales"
    fi
    PENDING_DLL_STAGE=""

    if ! hash_matches "$ASSET_TARGET" "$asset_sha" || \
       ! hash_matches "$DLL_TARGET" "$dll_sha"; then
        trap - INT TERM HUP
        printf 'La verificación final falló; restaurando ambos originales...\n' >&2
        restore_originals_low_level || die "falló también la recuperación; conserva el journal"
        write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "restored-after-error"
        rm -f -- "$JOURNAL_FILE"
        die "la instalación no superó la verificación final"
    fi

    trap - INT TERM HUP
    write_state "$asset_sha" "$dll_sha" "$status"
    rm -f -- "$JOURNAL_FILE"
}

recover_pending_install() {
    [[ -e "$JOURNAL_FILE" ]] || return 0
    say "Detectada una instalación interrumpida; recuperando originales"
    require_game_closed
    restore_originals_low_level
    write_state "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" "recovered"
    rm -f -- "$JOURNAL_FILE"
}

run_steam_deck_helper() {
    local operation="$1"
    local payload_dir="$2"
    local output_asset_sha="$3"
    local output_dll_sha="$4"
    local remote_command="bash -s --"
    local argument quoted
    local arguments=(
        "$operation"
        "$DECK_GAME_DIR"
        "$payload_dir"
        "$ORIGINAL_ASSET_SHA256"
        "$ORIGINAL_DLL_SHA256"
        "$output_asset_sha"
        "$output_dll_sha"
        "$LEGACY_ASSET_SHA256"
    )

    [[ -f "$STEAM_DECK_HELPER" ]] || die "falta el helper Steam Deck: $STEAM_DECK_HELPER"
    for argument in "${arguments[@]}"; do
        printf -v quoted '%q' "$argument"
        remote_command+=" $quoted"
    done
    ssh "${SSH_OPTIONS[@]}" -- "$STEAM_DECK_DEST" "$remote_command" <"$STEAM_DECK_HELPER"
}

steam_deck_preflight() {
    local operation="preflight-install"

    require_command ssh
    [[ "$ACTION" == "restore" ]] && operation="preflight-restore"
    say "Comprobando Steam Deck por SSH (solo lectura)"
    run_steam_deck_helper "$operation" "-" "-" "-"
}

create_remote_payload_dir() {
    REMOTE_PAYLOAD_DIR="$(
        ssh "${SSH_OPTIONS[@]}" -- "$STEAM_DECK_DEST" \
            'umask 077; mkdir -p -- "$HOME/.cache/traductor_es"; mktemp -d "$HOME/.cache/traductor_es/deploy.XXXXXXXX"'
    )"
    [[ "$REMOTE_PAYLOAD_DIR" == /* ]] || die "la Steam Deck devolvió una ruta temporal inválida"
    [[ "$REMOTE_PAYLOAD_DIR" != *$'\n'* ]] || die "la Steam Deck devolvió varias rutas temporales"
    [[ "$REMOTE_PAYLOAD_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]] || die "ruta temporal remota no permitida"
    [[ "$(basename -- "$REMOTE_PAYLOAD_DIR")" == deploy.* ]] || die "nombre temporal remoto no permitido"
    REMOTE_PAYLOAD_ACTIVE=1
}

cleanup_remote_payload() {
    local cleanup_command
    local remote_file
    local quoted

    [[ "$REMOTE_PAYLOAD_ACTIVE" -eq 1 ]] || return 0
    cleanup_command="rm -f --"
    for remote_file in \
        "$REMOTE_PAYLOAD_DIR/original-sharedassets0.assets" \
        "$REMOTE_PAYLOAD_DIR/original-Assembly-CSharp.dll" \
        "$REMOTE_PAYLOAD_DIR/translated-sharedassets0.assets" \
        "$REMOTE_PAYLOAD_DIR/translated-Assembly-CSharp.dll"; do
        printf -v quoted '%q' "$remote_file"
        cleanup_command+=" $quoted"
    done
    printf -v quoted '%q' "$REMOTE_PAYLOAD_DIR"
    cleanup_command+="; rmdir -- $quoted 2>/dev/null || true"
    ssh "${SSH_OPTIONS[@]}" -- "$STEAM_DECK_DEST" "$cleanup_command" >/dev/null 2>&1 || true
    REMOTE_PAYLOAD_ACTIVE=0
}

copy_to_steam_deck() {
    local source="$1"
    local remote_name="$2"

    scp -q "${SSH_OPTIONS[@]}" -- "$source" "$STEAM_DECK_DEST:$REMOTE_PAYLOAD_DIR/$remote_name"
}

install_on_steam_deck() {
    require_command ssh
    require_command scp
    create_remote_payload_dir
    trap cleanup_remote_payload EXIT

    say "Transfiriendo originales de recuperación y artefactos validados"
    copy_to_steam_deck "$ASSET_BACKUP" "original-sharedassets0.assets"
    copy_to_steam_deck "$DLL_BACKUP" "original-Assembly-CSharp.dll"
    copy_to_steam_deck "$ASSET_OUTPUT" "translated-sharedassets0.assets"
    copy_to_steam_deck "$DLL_OUTPUT" "translated-Assembly-CSharp.dll"

    say "Publicando en la Steam Deck"
    run_steam_deck_helper \
        "install" "$REMOTE_PAYLOAD_DIR" "$BUILT_ASSET_SHA" "$BUILT_DLL_SHA"
    REMOTE_PAYLOAD_ACTIVE=0
    trap - EXIT
}

ensure_python_environment() {
    if [[ ! -x "$VENV_PYTHON" ]]; then
        require_command python3
        say "Creando entorno virtual"
        python3 -m venv "$VENV_DIR"
    fi

    if ! "$VENV_PYTHON" -c 'import UnityPy, TypeTreeGeneratorAPI' >/dev/null 2>&1; then
        say "Instalando dependencias de Python"
        "$VENV_PYTHON" -m ensurepip --upgrade
        "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
    fi
}

build_translation() {
    local source_manifest work_manifest replacements_manifest
    local patcher_args=()

    require_command mcs
    require_command mono
    [[ -z "$CECIL_PATH" || -f "$CECIL_PATH" ]] || die "Mono.Cecil.dll no existe: $CECIL_PATH"
    [[ -d "$BUNDLE_DIR" ]] || die "no se encontró el directorio de bundles: $BUNDLE_DIR"

    BUILD_DIR="$(mktemp -d "$TMP_ROOT/install-$(date +%Y%m%d-%H%M%S).XXXXXXXX")"
    source_manifest="$BUILD_DIR/out/manifest.json"
    work_manifest="$BUILD_DIR/work/manifest.json"
    replacements_manifest="$BUILD_DIR/reconstructed/replacements.json"
    ASSET_OUTPUT="$BUILD_DIR/sharedassets0.assets"
    DLL_OUTPUT="$BUILD_DIR/Assembly-CSharp.dll"

    say "Extrayendo una fuente limpia"
    "$VENV_PYTHON" "$SCRIPT_DIR/extractor.py" \
        --asset "$ASSET_BACKUP" \
        --bundle-dir "$BUNDLE_DIR" \
        --out-dir "$BUILD_DIR/out"

    say "Aplicando parches versionados"
    "$VENV_PYTHON" "$SCRIPT_DIR/aplicar_parches.py" \
        --source-manifest "$source_manifest" \
        --patch-dir "$SCRIPT_DIR/parches" \
        --work-dir "$BUILD_DIR/work"

    say "Ejecutando auditorías"
    "$VENV_PYTHON" "$SCRIPT_DIR/auditar_traduccion.py" \
        --source-manifest "$source_manifest" \
        --work-manifest "$work_manifest" \
        --report-dir "$BUILD_DIR/audit"
    "$VENV_PYTHON" "$SCRIPT_DIR/auditar_consistencia.py" \
        --source-manifest "$source_manifest" \
        --work-manifest "$work_manifest" \
        --report-dir "$BUILD_DIR/consistency"
    "$VENV_PYTHON" "$SCRIPT_DIR/cobertura_traduccion.py" \
        --source-manifest "$source_manifest" \
        --work-manifest "$work_manifest" \
        --json-out "$BUILD_DIR/coverage.json"

    say "Reconstruyendo sharedassets0.assets"
    "$VENV_PYTHON" "$SCRIPT_DIR/reconstructor.py" \
        --asset "$ASSET_BACKUP" \
        --manifest "$work_manifest" \
        --out-dir "$BUILD_DIR/reconstructed"
    "$VENV_PYTHON" "$SCRIPT_DIR/reempacador.py" \
        --asset "$ASSET_BACKUP" \
        --manifest "$work_manifest" \
        --replacements-manifest "$replacements_manifest" \
        --output-asset "$ASSET_OUTPUT"

    say "Parcheando Assembly-CSharp.dll"
    patcher_args=(
        --input "$DLL_BACKUP"
        --output "$DLL_OUTPUT"
    )
    if [[ -n "$CECIL_PATH" ]]; then
        patcher_args+=(--cecil "$CECIL_PATH")
    fi
    "$VENV_PYTHON" "$SCRIPT_DIR/parchear_assembly.py" "${patcher_args[@]}"

    say "Validando la build completa"
    "$VENV_PYTHON" "$SCRIPT_DIR/validar.py" \
        --mode edited \
        --asset "$ASSET_BACKUP" \
        --bundle-dir "$BUNDLE_DIR" \
        --manifest "$work_manifest" \
        --replacements-manifest "$replacements_manifest" \
        --repacked-asset "$ASSET_OUTPUT" \
        --localized-bundles-output-dir "$BUILD_DIR/localized_bundles"

    [[ -s "$ASSET_OUTPUT" ]] || die "el asset generado está vacío"
    [[ -s "$DLL_OUTPUT" ]] || die "el DLL generado está vacío"
    BUILT_ASSET_SHA="$(sha256_file "$ASSET_OUTPUT")"
    BUILT_DLL_SHA="$(sha256_file "$DLL_OUTPUT")"
    [[ "$BUILT_ASSET_SHA" != "$ORIGINAL_ASSET_SHA256" ]] || die "el asset generado no contiene cambios"
    [[ "$BUILT_DLL_SHA" != "$ORIGINAL_DLL_SHA256" ]] || die "el DLL generado no contiene cambios"
}

require_command sha256sum
require_command cut
require_command cp
require_command mv
require_command ln
require_command mktemp
require_command flock
require_command date
require_command basename
mkdir -p -- "$TMP_ROOT"

exec 9>"$TMP_ROOT/instalar.lock"
flock -n 9 || die "ya hay otro instalar.bash en ejecución"

if [[ -n "$STEAM_DECK_DEST" ]]; then
    steam_deck_preflight
    if [[ "$ACTION" == "restore" ]]; then
        say "Restaurando originales en la Steam Deck"
        run_steam_deck_helper "restore" "-" "-" "-"
        printf '\nRestauración remota completada y verificada.\n'
        exit 0
    fi

    ensure_backups
    ensure_python_environment
    build_translation
    printf '\nBuild validada:\n'
    printf '  asset: %s (sha256=%s)\n' "$ASSET_OUTPUT" "$BUILT_ASSET_SHA"
    printf '  DLL:   %s (sha256=%s)\n' "$DLL_OUTPUT" "$BUILT_DLL_SHA"

    if [[ "$ACTION" == "build-only" ]]; then
        printf '\nNo se modificó la Steam Deck (--build-only).\n'
        exit 0
    fi

    install_on_steam_deck
    printf '\nInstalación en Steam Deck completada y verificada.\n'
    printf 'Para restaurarla: bash %q --steam-deck %q --restore\n' \
        "$SCRIPT_DIR/instalar.bash" "$STEAM_DECK_DEST"
    exit 0
fi

ensure_backups
recover_pending_install

if [[ "$ACTION" == "restore" ]]; then
    say "Restaurando archivos originales"
    commit_pair \
        "$ASSET_BACKUP" "$DLL_BACKUP" \
        "$ORIGINAL_ASSET_SHA256" "$ORIGINAL_DLL_SHA256" \
        "restored"
    printf '\nRestauración completada y verificada. Los backups se conservan.\n'
    exit 0
fi

if [[ "$ACTION" == "install" ]]; then
    ensure_known_installed_pair
fi

ensure_python_environment
build_translation

printf '\nBuild validada:\n'
printf '  asset: %s (sha256=%s)\n' "$ASSET_OUTPUT" "$BUILT_ASSET_SHA"
printf '  DLL:   %s (sha256=%s)\n' "$DLL_OUTPUT" "$BUILT_DLL_SHA"

if [[ "$ACTION" == "build-only" ]]; then
    printf '\nNo se modificaron los archivos activos del juego (--build-only).\n'
    exit 0
fi

say "Instalando los dos artefactos validados"
verify_hash "$ASSET_BACKUP" "$ORIGINAL_ASSET_SHA256" "backup original del asset"
verify_hash "$DLL_BACKUP" "$ORIGINAL_DLL_SHA256" "backup original del DLL"
ensure_known_installed_pair
commit_pair "$ASSET_OUTPUT" "$DLL_OUTPUT" "$BUILT_ASSET_SHA" "$BUILT_DLL_SHA" "installed"

printf '\nInstalación completada y verificada. Ya puedes iniciar GNOSIA.\n'
printf 'Para volver al original: bash %q --restore\n' "$SCRIPT_DIR/instalar.bash"
