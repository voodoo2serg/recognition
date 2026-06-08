#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${HOME}/.config/recognition"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
CONFIG_FILE="${CONFIG_DIR}/recognition.env"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

mkdir -p "${CONFIG_DIR}" "${SYSTEMD_DIR}" "${HOME}/sync/audio_in" "${HOME}/sync/audio_out" "${HOME}/.local/share/recognition"

if command -v apt-get >/dev/null 2>&1; then
  packages=(
    ca-certificates
    curl
    ffmpeg
    jq
    syncthing
    util-linux
  )

  if ! command -v docker >/dev/null 2>&1; then
    packages+=(docker.io docker-compose-plugin)
  elif ! docker compose version >/dev/null 2>&1; then
    packages+=(docker-compose-plugin)
  fi

  export DEBIAN_FRONTEND=noninteractive
  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" apt-get install -y "${packages[@]}"
else
  printf 'apt-get not found. Install docker, docker compose plugin, ffmpeg, jq, curl, syncthing, util-linux manually.\n' >&2
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  sed "s#%h#${HOME}#g" "${REPO_DIR}/config/recognition.env.example" >"${CONFIG_FILE}"
fi

install_template() {
  local source_file="$1"
  local target_file="$2"
  sed \
    -e "s#__REPO_DIR__#${REPO_DIR}#g" \
    -e "s#%h#${HOME}#g" \
    "${source_file}" >"${target_file}"
}

install_template "${REPO_DIR}/systemd/user/recognition-worker.service" "${SYSTEMD_DIR}/recognition-worker.service"
install_template "${REPO_DIR}/systemd/user/recognition-worker.path" "${SYSTEMD_DIR}/recognition-worker.path"
install_template "${REPO_DIR}/systemd/user/recognition-worker.timer" "${SYSTEMD_DIR}/recognition-worker.timer"

chmod +x "${REPO_DIR}/scripts/recognition-worker.sh" "${REPO_DIR}/scripts/healthcheck.sh" "${REPO_DIR}/scripts/install-server.sh"

if systemctl list-unit-files docker.service >/dev/null 2>&1; then
  "${SUDO[@]}" systemctl enable --now docker
fi

if command -v loginctl >/dev/null 2>&1; then
  "${SUDO[@]}" loginctl enable-linger "${USER}" || true
fi

mkdir -p "${REPO_DIR}/data/gigastt"
"${SUDO[@]}" chown -R 10001:10001 "${REPO_DIR}/data/gigastt"

docker compose -f "${REPO_DIR}/docker-compose.yml" up -d --build

systemctl --user daemon-reload
systemctl --user enable --now syncthing
systemctl --user enable --now recognition-worker.path recognition-worker.timer

printf '\nInstalled recognition.\n'
printf 'Config: %s\n' "${CONFIG_FILE}"
printf 'Syncthing UI: http://127.0.0.1:8384 on the server, or SSH tunnel: ssh -L 8384:127.0.0.1:8384 user@server\n'
printf 'GigaSTT health: curl http://127.0.0.1:9876/health\n'
