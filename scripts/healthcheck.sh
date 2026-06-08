#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_FILE="${RECOGNITION_CONFIG:-${HOME}/.config/recognition/recognition.env}"
if [[ -r "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "${CONFIG_FILE}"
  set +a
fi

GIGASTT_URL="${GIGASTT_URL:-http://127.0.0.1:9876}"

missing=0
for command_name in curl docker ffmpeg ffprobe jq sha256sum; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'missing: %s\n' "${command_name}"
    missing=1
  else
    printf 'ok: %s\n' "${command_name}"
  fi
done

if curl --silent --show-error --fail "${GIGASTT_URL%/}/health" >/dev/null; then
  printf 'ok: GigaSTT health at %s\n' "${GIGASTT_URL}"
else
  printf 'failed: GigaSTT health at %s\n' "${GIGASTT_URL}"
  missing=1
fi

exit "${missing}"
