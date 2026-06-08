#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

if [[ -z "${HOME:-}" ]]; then
  current_user="$(id -un)"
  if [[ "${current_user}" == "root" ]]; then
    HOME="/root"
  else
    HOME="/home/${current_user}"
  fi
  export HOME
fi

PROCESSOR_HOME="${OBSIDIAN_PROCESSOR_HOME:-${HOME}/obsidian_processor}"
CONFIG_FILE="${OBSIDIAN_PROCESSOR_CONFIG:-${PROCESSOR_HOME}/processor.env}"

if [[ -r "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "${CONFIG_FILE}"
  set +a
fi

expand_home() {
  local value="$1"
  value="${value//%h/${HOME}}"
  value="${value/#\~/${HOME}}"
  printf '%s\n' "${value}"
}

PROCESSOR_HOME="$(expand_home "${PROCESSOR_HOME:-${HOME}/obsidian_processor}")"
LOG_FILE="$(expand_home "${LOG_FILE:-${PROCESSOR_HOME}/processing.log}")"
LOCK_FILE="${PROCESSOR_HOME}/processor.lock"

mkdir -p "${PROCESSOR_HOME}" "$(dirname "${LOG_FILE}")"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*" >>"${LOG_FILE}"
}

if ! command -v python3 >/dev/null 2>&1; then
  log "ERROR missing python3"
  exit 127
fi

if [[ "${1:-}" != "--scan" && "${1:-}" != "--force" ]]; then
  case "${1:-}" in
    ""|*.tmp|*.part|*.swp|*.bak|*/.*.tmp.*|*/.syncthing*|*_abstract.md|*_executive.md)
      exit 0
      ;;
  esac
fi

exec 9>"${LOCK_FILE}"
flock 9

python3 "${PROCESSOR_HOME}/bin/obsidian-processor.py" "$@"
