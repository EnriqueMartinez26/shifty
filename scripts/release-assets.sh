#!/usr/bin/env bash
# Immutable, host-backed frontend asset publication for deploy.sh.
set -euo pipefail

die() {
  printf 'release-assets: %s\n' "$*" >&2
  exit 1
}

usage() {
  die "uso: $0 {store|prepare|validate|capacity|capacity-bytes|import|verify|gc} ..."
}

valid_release() {
  [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]] && [[ "$1" != . ]] && [[ "$1" != .. ]]
}

valid_image_id() {
  [[ "$1" =~ ^sha256:[a-fA-F0-9]{64}$ ]]
}

valid_relative_path() {
  local path="$1" component
  local -a components=()
  [[ "$path" =~ ^[A-Za-z0-9._/+@-]+$ ]] || return 1
  [[ "$path" != /* && "$path" != */ && "$path" != *//* ]] || return 1
  local IFS=/
  read -r -a components <<<"$path"
  for component in "${components[@]}"; do
    [[ "$component" != . && "$component" != .. && "$component" != .* && -n "$component" ]] || return 1
  done
}

normalize_store() {
  local requested="$1" repo check_path
  [[ "$requested" = /* || "$requested" =~ ^[A-Za-z]:/ ]] || die "asset store debe ser una ruta absoluta: $requested"
  [[ "$requested" != *'/../'* && "$requested" != */.. ]] ||
    die "asset store no puede ser la raiz ni contener traversal: $requested"
  check_path="$requested"
  while [[ "$check_path" == */ && "$check_path" != / && ! "$check_path" =~ ^[A-Za-z]:/$ ]]; do
    check_path="${check_path%/}"
  done
  [[ ! -L "$check_path" ]] || die "asset store no puede ser un symlink: $requested"
  requested="$(realpath -m -- "$requested")" || die "no pude normalizar asset store: $requested"
  [[ "$requested" != / && ! "$requested" =~ ^[A-Za-z]:/?$ ]] ||
    die "asset store no puede ser la raiz ni contener traversal: $requested"
  if [[ -z "${SHIFTY_DIR:-}" ]]; then
    SHIFTY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  if [[ -n "${SHIFTY_DIR:-}" && -d "$SHIFTY_DIR" ]]; then
    repo="$(realpath -m -- "$SHIFTY_DIR")"
    case "$requested/" in
      "$repo/"*) die "asset store debe vivir fuera del checkout ($repo)" ;;
    esac
  fi
  printf '%s\n' "$requested"
}

prepare_store() {
  local requested="$1"
  requested="$(normalize_store "$requested")"
  if ! mkdir -p -- "$requested" 2>/dev/null || [[ ! -w "$requested" ]]; then
    die "no pude crear o escribir el asset store $requested (crearlo como root: install -d -o deploy -g deploy -m 0755 $requested)"
  fi
  requested="$(realpath -m -- "$requested")"
  [[ ! -L "$requested/assets" && ! -L "$requested/.manifests" && ! -L "$requested/.staging" ]] ||
    die "asset store contiene un directorio de primer nivel symlink"
  mkdir -p -- "$requested/assets" "$requested/.manifests" "$requested/.staging"
  # nginx workers need to traverse the bind-mounted public tree even if the
  # deploy user's login shell has a restrictive umask. Metadata and staging
  # stay private to the publisher.
  chmod 0755 -- "$requested/assets"
  chmod 0700 -- "$requested/.manifests" "$requested/.staging"
  STORE="$requested"
}

acquire_store_lock() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$STORE/.lock"
    chmod 0600 -- "$STORE/.lock" 2>/dev/null || true
    flock -w 60 9 || die "no pude adquirir lock del asset store: $STORE"
  elif [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || -n "${WINDIR:-}" ]]; then
    return 0
  else
    die "flock es obligatorio para serializar operaciones en $STORE"
  fi
}

trap_cleanup_signals() {
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

clear_cleanup_signals() {
  trap - EXIT INT TERM
}

source_files() {
  local source="${1%/}" path relative invalid
  [[ -d "$source" && ! -L "$source" ]] || die "directorio de assets invalido: $source"
  invalid="$(find -P "$source" -mindepth 1 ! -type d ! -type f -print -quit)"
  [[ -z "$invalid" ]] || die "asset no regular o symlink rechazado: ${invalid#"$source"/}"
  find -P "$source" -type f -print0 | LC_ALL=C sort -z
}

source_entries() {
  local source="${1%/}" list="$2" file relative hash size total=0 count=0
  source_files "$source" >"$list"
  while IFS= read -r -d '' file; do
    relative="${file#"$source"/}"
    valid_relative_path "$relative" || die "ruta de asset invalida: $relative"
    hash="$(sha256sum <"$file")"
    hash="${hash%% *}"
    size="$(wc -c <"$file" | tr -d '[:space:]')"
    [[ "$hash" =~ ^[a-fA-F0-9]{64}$ && "$size" =~ ^[0-9]+$ ]] ||
      die "no pude calcular hash/tamano de $relative"
    printf '%s\t%s\t%s\n' "$hash" "$size" "$relative"
    total=$((total + size))
    count=$((count + 1))
  done <"$list"
  [[ "$count" -gt 0 ]] || die "la imagen no contiene archivos en /usr/share/nginx/html/assets"
  printf 'count=%s\ntotal=%s\n' "$count" "$total" >&2
}

write_manifest() {
  local release="$1" image_id="$2" imported_at="$3" entries="$4" output="$5"
  local count total
  count="$(wc -l <"$entries" | tr -d '[:space:]')"
  total="$(awk -F '\t' '{ total += $2 } END { printf "%.0f", total }' "$entries")"
  {
    printf 'shifty-assets-v1\nrelease=%s\nimage=%s\nimported_at=%s\n' \
      "$release" "$image_id" "$imported_at"
    printf 'file_count=%s\ntotal_bytes=%s\nfiles_begin\n' "$count" "$total"
    cat -- "$entries"
  } >"$output"
}

parent_is_safe() {
  local root="$1" relative="$2" parent component dmode
  local -a components=()
  parent="${relative%/*}"
  [[ "$parent" != "$relative" ]] || return 0
  local IFS=/
  read -r -a components <<<"$parent"
  for component in "${components[@]}"; do
    root="$root/$component"
    if [[ -L "$root" || ( -e "$root" && ! -d "$root" ) ]]; then
      return 1
    fi
    if [[ -d "$root" ]]; then
      dmode="$(stat -c '%a' -- "$root" 2>/dev/null || true)"
      [[ "$dmode" =~ ^[0-7]+$ ]] || return 1
      (( (8#$dmode & 0005) == 0005 )) || return 1
    fi
  done
}

check_existing_asset() {
  local path="$1" expected_hash="$2" expected_size="$3" actual_hash actual_size
  [[ ! -L "$path" ]] || return 1
  [[ -f "$path" ]] || return 1
  actual_hash="$(sha256sum <"$path")"
  actual_hash="${actual_hash%% *}"
  actual_size="$(wc -c <"$path" | tr -d '[:space:]')"
  [[ "${actual_hash,,}" = "${expected_hash,,}" && "$actual_size" = "$expected_size" ]] || return 1
  local mode
  mode="$(stat -c '%a' -- "$path" 2>/dev/null || true)"
  [[ "$mode" =~ ^[0-7]+$ ]] || return 1
  (( (8#$mode & 0222) == 0 && (8#$mode & 0004) == 0004 )) || return 1
}

verify_manifest() {
  local store="$1" release="$2" expected_image="$3" manifest="$4"
  local line magic rel image imported count total marker hash size path file
  local seen=0 bytes=0
  [[ -f "$manifest" && ! -L "$manifest" ]] || die "manifest faltante o invalido: $manifest"
  local mode
  mode="$(stat -c '%a' -- "$manifest" 2>/dev/null || true)"
  [[ "$mode" =~ ^[0-7]+$ ]] || die "no pude verificar permisos del manifest: $manifest"
  (( (8#$mode & 0222) == 0 )) || die "manifest modificable rechazado: $manifest"
  {
    IFS= read -r magic || die "manifest truncado: $manifest"
    IFS= read -r line || die "manifest truncado: $manifest"; rel="${line#release=}"; [[ "$line" = "release=$rel" ]]
    IFS= read -r line || die "manifest truncado: $manifest"; image="${line#image=}"; [[ "$line" = "image=$image" ]]
    IFS= read -r line || die "manifest truncado: $manifest"; imported="${line#imported_at=}"; [[ "$line" = "imported_at=$imported" ]]
    IFS= read -r line || die "manifest truncado: $manifest"; count="${line#file_count=}"; [[ "$line" = "file_count=$count" ]]
    IFS= read -r line || die "manifest truncado: $manifest"; total="${line#total_bytes=}"; [[ "$line" = "total_bytes=$total" ]]
    IFS= read -r marker || die "manifest truncado: $manifest"
    [[ "$magic" = shifty-assets-v1 && "$rel" = "$release" ]] || die "manifest de release incorrecto: $manifest"
    [[ "$image" =~ ^sha256:[a-fA-F0-9]{64}$ ]] || die "image identity invalida en $manifest"
    [[ -z "$expected_image" || "$image" = "$expected_image" ]] || die "image identity distinta para release $release"
    [[ "$imported" =~ ^[0-9]+$ && "$count" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ && "$marker" = files_begin ]] ||
      die "cabecera invalida en $manifest"
    while IFS= read -r line || [[ -n "$line" ]]; do
      hash="${line%%$'\t'*}"
      [[ "$line" != "$hash" ]] || die "entrada sin tabuladores en $manifest"
      line="${line#*$'\t'}"
      size="${line%%$'\t'*}"
      [[ "$line" != "$size" ]] || die "entrada incompleta en $manifest"
      path="${line#*$'\t'}"
      [[ "$path" != *$'\t'* && "$hash" =~ ^[a-fA-F0-9]{64}$ && "$size" =~ ^[0-9]+$ ]] ||
        die "entrada invalida en $manifest"
      valid_relative_path "$path" || die "ruta invalida en $manifest: $path"
      parent_is_safe "$store/assets" "$path" || die "directorio de asset inseguro: $path"
      file="$store/assets/$path"
      check_existing_asset "$file" "$hash" "$size" || die "asset ausente, modificable o con hash distinto: $path"
      seen=$((seen + 1))
      bytes=$((bytes + size))
    done
  } <"$manifest"
  [[ "$seen" = "$count" && "$bytes" = "$total" && "$seen" -gt 0 ]] ||
    die "conteo/tamano no coincide en $manifest"
}

cmd_validate() {
  local store="$1" source="${2%/}" list entries
  prepare_store "$store"
  list="$(mktemp "$STORE/.staging/list.XXXXXX")"
  entries="$(mktemp "$STORE/.staging/entries.XXXXXX")"
  source_entries "$source" "$list" >"$entries"
  rm -f -- "$list" "$entries"
}

cmd_capacity() {
  local store="$1" min_free="$2" source list entries bytes=0 free_kb free_bytes need
  [[ "$min_free" =~ ^[0-9]+$ ]] || die "minimo de espacio libre invalido: $min_free"
  min_free=$((10#$min_free))
  prepare_store "$store"
  acquire_store_lock
  list="$(mktemp "$STORE/.staging/list.XXXXXX")"
  entries="$(mktemp "$STORE/.staging/entries.XXXXXX")"
  shift 2
  [[ "$#" -gt 0 ]] || die "capacity requiere al menos un directorio de assets"
  for source in "$@"; do
    source_entries "${source%/}" "$list" >"$entries"
    bytes=$((bytes + $(awk -F '\t' '{ total += $2 } END { printf "%.0f", total }' "$entries")))
  done
  free_kb="$(df -Pk -- "$STORE" | awk 'NR == 2 { print $4 }')"
  [[ "$free_kb" =~ ^[0-9]+$ ]] || die "no pude verificar el espacio libre del asset store"
  free_bytes=$((free_kb * 1024))
  need=$((bytes + min_free))
  rm -f -- "$list" "$entries"
  (( free_bytes >= need )) ||
    die "espacio insuficiente en $STORE: disponibles=${free_bytes} bytes, requeridos=${need} bytes; no se eliminaran releases protegidos"
  printf 'release-assets: capacidad ok (%s bytes requeridos, %s disponibles)\n' "$need" "$free_bytes" >&2
}

cmd_capacity_bytes() {
  local store="$1" min_free="$2" free_kb free_bytes need bytes total_bytes=0
  [[ "$min_free" =~ ^[0-9]+$ ]] || die "minimo de espacio libre invalido: $min_free"
  min_free=$((10#$min_free))
  shift 2
  [[ "$#" -gt 0 ]] || die "capacity-bytes requiere estimaciones de assets"
  for bytes in "$@"; do
    [[ "$bytes" =~ ^[0-9]+$ ]] || die "estimacion de bytes invalida: $bytes"
    total_bytes=$((total_bytes + 10#$bytes))
  done
  prepare_store "$store"
  acquire_store_lock
  # Idempotent verified releases add no files, so they do not need the reserve.
  if (( total_bytes == 0 )); then
    printf 'release-assets: capacidad ok (sin bytes nuevos)\n' >&2
    return 0
  fi
  free_kb="$(df -Pk -- "$STORE" | awk 'NR == 2 { print $4 }')"
  [[ "$free_kb" =~ ^[0-9]+$ ]] || die "no pude verificar el espacio libre del asset store"
  free_bytes=$((free_kb * 1024))
  need=$((total_bytes + min_free))
  (( free_bytes >= need )) ||
    die "espacio insuficiente en $STORE: disponibles=${free_bytes} bytes, requeridos=${need} bytes; no se eliminaran releases protegidos"
  printf 'release-assets: capacidad ok (%s bytes requeridos, %s disponibles)\n' "$need" "$free_bytes" >&2
}

IMPORT_LIST=""
IMPORT_ENTRIES=""
IMPORT_EXPECTED=""
IMPORT_PUBLISHED=""
IMPORT_MANIFEST=""
IMPORT_TEMP=""
IMPORT_MANIFEST_CREATED=0
IMPORT_SUCCEEDED=0

cleanup_import() {
  local temp_path relative dest
  if (( IMPORT_SUCCEEDED == 0 )); then
    if (( IMPORT_MANIFEST_CREATED == 1 )) && [[ -f "$IMPORT_MANIFEST" && -f "$IMPORT_EXPECTED" ]] &&
      cmp -s -- "$IMPORT_MANIFEST" "$IMPORT_EXPECTED"; then
      rm -f -- "$IMPORT_MANIFEST" || true
    fi
  fi
  if [[ -f "$IMPORT_PUBLISHED" ]]; then
    while IFS=$'\t' read -r temp_path relative; do
      [[ -n "$temp_path" && -n "$relative" ]] || continue
      if (( IMPORT_SUCCEEDED == 0 )); then
        if valid_relative_path "$relative"; then
          dest="$STORE/assets/$relative"
          # The temp hard link proves this invocation created the destination.
          # Leave it alone if another verified manifest now references it.
          if [[ -f "$temp_path" && -f "$dest" && ! -L "$dest" && "$temp_path" -ef "$dest" ]] &&
            ! path_referenced "$relative"; then
            rm -f -- "$dest" || true
          fi
        fi
      fi
      rm -f -- "$temp_path" 2>/dev/null || true
    done <"$IMPORT_PUBLISHED"
  fi
  [[ -z "$IMPORT_TEMP" ]] || rm -f -- "$IMPORT_TEMP" 2>/dev/null || true
  [[ -z "$IMPORT_LIST" ]] || rm -f -- "$IMPORT_LIST" 2>/dev/null || true
  [[ -z "$IMPORT_ENTRIES" ]] || rm -f -- "$IMPORT_ENTRIES" 2>/dev/null || true
  [[ -z "$IMPORT_EXPECTED" ]] || rm -f -- "$IMPORT_EXPECTED" 2>/dev/null || true
  [[ -z "$IMPORT_PUBLISHED" ]] || rm -f -- "$IMPORT_PUBLISHED" 2>/dev/null || true
}

cmd_import() {
  local store="$1" release="$2" image_id="$3" source="${4%/}"
  local list entries expected manifest file relative hash size dest temp parent component
  valid_release "$release" || die "release invalido: $release"
  valid_image_id "$image_id" || die "image identity invalida: $image_id"
  prepare_store "$store"
  acquire_store_lock
  list="$(mktemp "$STORE/.staging/list.XXXXXX")"
  entries="$(mktemp "$STORE/.staging/entries.XXXXXX")"
  expected="$(mktemp "$STORE/.staging/manifest.XXXXXX")"
  manifest="$STORE/.manifests/$release.manifest"
  IMPORT_LIST="$list"
  IMPORT_ENTRIES="$entries"
  IMPORT_EXPECTED="$expected"
  IMPORT_PUBLISHED="$(mktemp "$STORE/.staging/published.XXXXXX")"
  IMPORT_MANIFEST="$manifest"
  IMPORT_TEMP=""
  IMPORT_MANIFEST_CREATED=0
  IMPORT_SUCCEEDED=0
  trap cleanup_import EXIT
  trap_cleanup_signals
  source_entries "$source" "$list" >"$entries"
  if [[ -e "$manifest" || -L "$manifest" ]]; then
    local timestamp_line
    timestamp_line="$(sed -n '4s/^imported_at=//p' "$manifest")"
    [[ "$timestamp_line" =~ ^[0-9]+$ ]] || die "manifest existente invalido: $manifest"
    write_manifest "$release" "$image_id" "$timestamp_line" "$entries" "$expected"
    cmp -s -- "$manifest" "$expected" || die "release $release ya existe con otra imagen o contenido; no se sobreescribio"
    verify_manifest "$STORE" "$release" "$image_id" "$manifest"
    IMPORT_SUCCEEDED=1
    cleanup_import
    clear_cleanup_signals
    printf 'release-assets: %s ya estaba importado y verificado\n' "$release" >&2
    return 0
  fi

  # Validate every collision before publishing any new file. Existing assets
  # are never overwritten: identical bytes are shared; different bytes fail.
  while IFS=$'\t' read -r hash size relative; do
    valid_relative_path "$relative" || die "ruta de asset invalida: $relative"
    parent_is_safe "$STORE/assets" "$relative" || die "directorio de asset inseguro: $relative"
    dest="$STORE/assets/$relative"
    if [[ -e "$dest" || -L "$dest" ]]; then
      check_existing_asset "$dest" "$hash" "$size" || die "colision de asset; no se sobreescribio: $relative"
    fi
  done <"$entries"

  while IFS=$'\t' read -r hash size relative; do
    dest="$STORE/assets/$relative"
    parent="${relative%/*}"
    if [[ "$parent" != "$relative" ]]; then
      local current="$STORE/assets" component
      local -a components=()
      local IFS=/
      read -r -a components <<<"$parent"
      for component in "${components[@]}"; do
        current="$current/$component"
        [[ ! -L "$current" ]] || die "directorio de asset symlink rechazado: $current"
        [[ -d "$current" ]] || mkdir -- "$current"
        chmod 0755 -- "$current"
      done
    fi
    if [[ ! -e "$dest" ]]; then
      temp="$(mktemp "$STORE/.staging/file.XXXXXX")"
      IMPORT_TEMP="$temp"
      printf '%s\t%s\n' "$temp" "$relative" >>"$IMPORT_PUBLISHED"
      cp -- "$source/$relative" "$temp"
      chmod 0444 -- "$temp"
      if ! ln -- "$temp" "$dest" 2>/dev/null; then
        check_existing_asset "$dest" "$hash" "$size" || die "no pude publicar asset sin reemplazar: $relative"
      fi
      # Keep the hard link in staging until verification finishes so failure
      # cleanup can identify exactly which destination this import created.
    fi
  done <"$entries"

  write_manifest "$release" "$image_id" "$(date +%s)" "$entries" "$expected"
  chmod 0444 -- "$expected"
  if ! ln -- "$expected" "$manifest" 2>/dev/null; then
    cmp -s -- "$manifest" "$expected" || die "manifest concurrente o incompatible para $release"
  else
    IMPORT_MANIFEST_CREATED=1
  fi
  verify_manifest "$STORE" "$release" "$image_id" "$manifest"
  IMPORT_SUCCEEDED=1
  cleanup_import
  clear_cleanup_signals
  printf 'release-assets: importado y verificado %s (%s)\n' "$release" "$image_id" >&2
}

cmd_verify() {
  local store="$1" release="$2" image_id="${3:-}"
  valid_release "$release" || die "release invalido: $release"
  prepare_store "$store"
  acquire_store_lock
  verify_manifest "$STORE" "$release" "$image_id" "$STORE/.manifests/$release.manifest"
  printf 'release-assets: verificado %s\n' "$release" >&2
}

cmd_store() {
  [[ "$#" = 1 ]] || usage
  normalize_store "$1"
}

manifest_timestamp() {
  sed -n '4s/^imported_at=//p' "$1"
}

manifest_paths() {
  awk 'BEGIN { FS="\t" } /^files_begin$/ { entries=1; next } entries && NF == 3 { print $3 }' "$1"
}

path_referenced() {
  local target="$1" manifest
  for manifest in "$STORE"/.manifests/*.manifest; do
    [[ -f "$manifest" ]] || continue
    awk -F '\t' -v target="$target" '$3 == target { found=1; exit } END { exit !found }' "$manifest" && return 0
  done
  return 1
}

GC_INVENTORY=""
GC_ORDERED=""
GC_PATHS=""

cleanup_gc() {
  [[ -z "$GC_INVENTORY" ]] || rm -f -- "$GC_INVENTORY" 2>/dev/null || true
  [[ -z "$GC_ORDERED" ]] || rm -f -- "$GC_ORDERED" 2>/dev/null || true
  [[ -z "$GC_PATHS" ]] || rm -f -- "$GC_PATHS" 2>/dev/null || true
}

cmd_gc() {
  local store="$1" current="$2" previous="$3" age_seconds="$4" keep_min="$5"
  local manifest release image_id timestamp now cutoff path removed=0
  [[ "$age_seconds" =~ ^[0-9]+$ && "$keep_min" =~ ^[0-9]+$ ]] || die "politica GC invalida"
  age_seconds=$((10#$age_seconds))
  keep_min=$((10#$keep_min))
  (( age_seconds >= 1209600 && keep_min >= 3 )) ||
    die "GC exige al menos 14 dias y 3 releases; no se eliminara nada"
  prepare_store "$store"
  acquire_store_lock
  [[ -z "$current" || -f "$STORE/.manifests/$current.manifest" ]] || die "GC: falta manifest current $current"
  [[ -z "$previous" || -f "$STORE/.manifests/$previous.manifest" ]] || die "GC: falta manifest previous $previous"
  now="$(date +%s)"
  cutoff=$((now - age_seconds))
  local inventory ordered paths_to_check
  inventory="$(mktemp "$STORE/.staging/inventory.XXXXXX")"
  ordered="$(mktemp "$STORE/.staging/ordered.XXXXXX")"
  paths_to_check="$(mktemp "$STORE/.staging/paths.XXXXXX")"
  GC_INVENTORY="$inventory"
  GC_ORDERED="$ordered"
  GC_PATHS="$paths_to_check"
  trap cleanup_gc EXIT
  trap_cleanup_signals
  for manifest in "$STORE"/.manifests/*.manifest; do
    [[ -f "$manifest" ]] || continue
    release="${manifest##*/}"
    release="${release%.manifest}"
    image_id="$(sed -n '3s/^image=//p' "$manifest")"
    verify_manifest "$STORE" "$release" "$image_id" "$manifest"
    timestamp="$(manifest_timestamp "$manifest")"
    [[ "$timestamp" =~ ^[0-9]+$ ]] || die "GC: timestamp invalido en $manifest"
    printf '%s\t%s\n' "$timestamp" "$release" >>"$inventory"
  done
  LC_ALL=C sort -t $'\t' -k1,1nr -k2,2 "$inventory" >"$ordered"
  local -a keep_recent=()
  while IFS=$'\t' read -r timestamp release; do
    [[ -n "$release" ]] || continue
    if (( ${#keep_recent[@]} < keep_min )); then keep_recent+=("$release"); fi
  done <"$ordered"

  while IFS=$'\t' read -r timestamp release; do
    [[ -n "$release" ]] || continue
    (( timestamp <= cutoff )) || continue
    [[ "$release" != "$current" && "$release" != "$previous" ]] || continue
    case " ${DEPLOY_ASSET_PROTECTED_RELEASES:-} " in *" $release "*) continue ;; esac
    local recent protected
    protected=0
    for recent in "${keep_recent[@]}"; do [[ "$recent" = "$release" ]] && protected=1; done
    (( protected == 0 )) || continue
    manifest="$STORE/.manifests/$release.manifest"
    manifest_paths "$manifest" >>"$paths_to_check"
    rm -f -- "$manifest"
    removed=$((removed + 1))
  done <"$ordered"

  LC_ALL=C sort -u -o "$paths_to_check" "$paths_to_check"
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    valid_relative_path "$path" || die "GC: ruta invalida, no se elimina nada mas: $path"
    if ! path_referenced "$path"; then
      local asset="$STORE/assets/$path"
      [[ ! -L "$asset" ]] || die "GC: symlink de asset rechazado: $path"
      [[ ! -e "$asset" || -f "$asset" ]] || die "GC: tipo de asset invalido: $path"
      rm -f -- "$asset"
    fi
  done <"$paths_to_check"

  # Under exclusive store lock, also sweep orphaned unreferenced files in assets/
  # and stale staging artifacts left by killed (SIGKILL) imports.
  local extra extra_rel staged
  extra="$(find -P "$STORE/assets" -mindepth 1 ! -type d ! -type f -print -quit)"
  [[ -z "$extra" ]] || die "GC: asset no regular o symlink rechazado: ${extra#"$STORE/assets"/}"
  while IFS= read -r -d '' extra; do
    extra_rel="${extra#"$STORE/assets"/}"
    valid_relative_path "$extra_rel" || die "GC: ruta de asset invalida: $extra_rel"
    if ! path_referenced "$extra_rel"; then
      rm -f -- "$extra"
    fi
  done < <(find -P "$STORE/assets" -type f -print0 | LC_ALL=C sort -z)
  find "$STORE/assets" -mindepth 1 -depth -type d -empty -delete

  local staging_name
  while IFS= read -r -d '' staged; do
    [[ "$staged" != "$GC_INVENTORY" && "$staged" != "$GC_ORDERED" && "$staged" != "$GC_PATHS" ]] || continue
    staging_name="${staged##*/}"
    case "$staging_name" in
      shifty-assets.*) continue ;;
    esac
    rm -rf -- "$staged"
  done < <(find -P "$STORE/.staging" -mindepth 1 -maxdepth 1 -print0)

  while IFS= read -r -d '' staged; do
    rm -rf -- "$staged"
  done < <(find -P "$STORE/.staging" -mindepth 1 -maxdepth 1 -name 'shifty-assets.*' -mmin +60 -print0)

  cleanup_gc
  clear_cleanup_signals
  printf 'release-assets: GC removio %s manifests (minimo=%s, edad=%ss)\n' "$removed" "$keep_min" "$age_seconds" >&2
}

case "${1:-}" in
  store)
    [[ "$#" = 2 ]] || usage
    cmd_store "$2"
    ;;
  prepare)
    [[ "$#" = 2 ]] || usage
    prepare_store "$2"
    printf '%s\n' "$STORE"
    ;;
  validate)
    [[ "$#" = 3 ]] || usage
    cmd_validate "$2" "$3"
    ;;
  capacity)
    [[ "$#" -ge 4 ]] || usage
    cmd_capacity "$2" "$3" "${@:4}"
    ;;
  capacity-bytes)
    [[ "$#" -ge 4 ]] || usage
    cmd_capacity_bytes "$2" "$3" "${@:4}"
    ;;
  import)
    [[ "$#" = 5 ]] || usage
    cmd_import "$2" "$3" "$4" "$5"
    ;;
  verify)
    [[ "$#" = 3 || "$#" = 4 ]] || usage
    cmd_verify "$2" "$3" "${4:-}"
    ;;
  gc)
    [[ "$#" -ge 6 ]] || usage
    cmd_gc "$2" "$3" "$4" "$5" "$6"
    ;;
  *) usage ;;
esac
