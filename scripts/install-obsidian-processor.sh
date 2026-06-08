#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROCESSOR_HOME="${OBSIDIAN_PROCESSOR_HOME:-${HOME}/obsidian_processor}"
CONFIG_FILE="${PROCESSOR_HOME}/processor.env"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

expand_home() {
  local value="$1"
  value="${value//%h/${HOME}}"
  value="${value/#\~/${HOME}}"
  printf '%s\n' "${value}"
}

PROCESSOR_HOME="$(expand_home "${PROCESSOR_HOME}")"
CONFIG_FILE="${PROCESSOR_HOME}/processor.env"

mkdir -p "${PROCESSOR_HOME}/bin" "${PROCESSOR_HOME}/skills"

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" apt-get install -y curl jq incron python3 util-linux
fi

install -m 0755 "${REPO_DIR}/scripts/obsidian-processor.py" "${PROCESSOR_HOME}/bin/obsidian-processor.py"
install -m 0755 "${REPO_DIR}/scripts/obsidian-process-one.sh" "${PROCESSOR_HOME}/bin/obsidian-process-one.sh"

for source_skill in "${REPO_DIR}"/skills/*.system; do
  target_skill="${PROCESSOR_HOME}/skills/$(basename "${source_skill}")"
  if [[ -f "${target_skill}" ]]; then
    install -m 0644 "${source_skill}" "${target_skill}.dist"
  else
    install -m 0644 "${source_skill}" "${target_skill}"
  fi
done

if [[ ! -f "${CONFIG_FILE}" ]]; then
  sed "s#%h#${HOME}#g" "${REPO_DIR}/config/obsidian-processor.env.example" >"${CONFIG_FILE}"
fi

set -a
# shellcheck source=/dev/null
. "${CONFIG_FILE}"
set +a

WATCH_DIRS="${WATCH_DIRS:-${HOME}/sync/audio_out:${HOME}/sync/obsidian-main}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
OLLAMA_FALLBACK_MODEL="${OLLAMA_FALLBACK_MODEL:-qwen2.5:3b}"

if command -v ollama >/dev/null 2>&1; then
  if ! id ollama >/dev/null 2>&1; then
    "${SUDO[@]}" useradd --system --home-dir /usr/share/ollama --shell /usr/sbin/nologin ollama
  fi

  "${SUDO[@]}" mkdir -p /usr/share/ollama/models
  "${SUDO[@]}" chown -R ollama:ollama /usr/share/ollama

  if ! systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    "${SUDO[@]}" install -m 0644 "${REPO_DIR}/systemd/system/ollama.service" /etc/systemd/system/ollama.service
    "${SUDO[@]}" systemctl daemon-reload
  fi
fi

if systemctl list-unit-files ollama.service >/dev/null 2>&1; then
  "${SUDO[@]}" systemctl enable --now ollama
fi

if command -v ollama >/dev/null 2>&1; then
  if ! ollama list | awk 'NR > 1 {print $1}' | grep -qx "${OLLAMA_MODEL}"; then
    if ! ollama pull "${OLLAMA_MODEL}"; then
      if [[ "${OLLAMA_FALLBACK_MODEL}" != "${OLLAMA_MODEL}" ]]; then
        ollama pull "${OLLAMA_FALLBACK_MODEL}"
        if grep -q '^OLLAMA_MODEL=' "${CONFIG_FILE}"; then
          sed -i "s#^OLLAMA_MODEL=.*#OLLAMA_MODEL=\"${OLLAMA_FALLBACK_MODEL}\"#" "${CONFIG_FILE}"
        else
          printf 'OLLAMA_MODEL="%s"\n' "${OLLAMA_FALLBACK_MODEL}" >>"${CONFIG_FILE}"
        fi
        OLLAMA_MODEL="${OLLAMA_FALLBACK_MODEL}"
      else
        exit 1
      fi
    fi
  fi
fi

IFS=':,' read -r -a watch_dirs <<<"${WATCH_DIRS}"
for watch_dir in "${watch_dirs[@]}"; do
  watch_dir="$(expand_home "${watch_dir}")"
  [[ -n "${watch_dir}" ]] || continue
  mkdir -p "${watch_dir}"
done

if [[ -e /etc/incron.allow ]] && ! grep -qx "${USER}" /etc/incron.allow; then
  printf '%s\n' "${USER}" | "${SUDO[@]}" tee -a /etc/incron.allow >/dev/null
fi

"${SUDO[@]}" systemctl enable --now incron

tmp_incron="$(mktemp)"
if incrontab -l >/dev/null 2>&1; then
  incrontab -l | grep -v "${PROCESSOR_HOME}/bin/obsidian-process-one.sh" >"${tmp_incron}" || true
fi

for watch_dir in "${watch_dirs[@]}"; do
  watch_dir="$(expand_home "${watch_dir}")"
  [[ -n "${watch_dir}" ]] || continue
  printf '%s IN_CLOSE_WRITE,IN_MOVED_TO %s/bin/obsidian-process-one.sh $@/$#\n' "${watch_dir}" "${PROCESSOR_HOME}" >>"${tmp_incron}"
done

incrontab "${tmp_incron}"
rm -f "${tmp_incron}"

"${PROCESSOR_HOME}/bin/obsidian-process-one.sh" --scan || true

printf '\nInstalled Obsidian processor.\n'
printf 'Config: %s\n' "${CONFIG_FILE}"
printf 'Log: %s\n' "${PROCESSOR_HOME}/processing.log"
printf 'Model: %s\n' "${OLLAMA_MODEL}"
