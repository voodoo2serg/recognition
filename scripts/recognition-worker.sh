#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

CONFIG_FILE="${RECOGNITION_CONFIG:-${HOME}/.config/recognition/recognition.env}"
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

AUDIO_IN_DIR="$(expand_home "${AUDIO_IN_DIR:-${HOME}/sync/audio_in}")"
AUDIO_OUT_DIR="$(expand_home "${AUDIO_OUT_DIR:-${HOME}/sync/audio_out}")"
WORK_DIR="$(expand_home "${WORK_DIR:-${HOME}/.local/share/recognition}")"
GIGASTT_URL="${GIGASTT_URL:-http://127.0.0.1:9876}"
MAX_CHUNK_SECONDS="${MAX_CHUNK_SECONDS:-120}"
STABLE_SECONDS="${STABLE_SECONDS:-20}"
CURL_MAX_TIME_SECONDS="${CURL_MAX_TIME_SECONDS:-1800}"
OUTPUT_TIMESTAMPS="${OUTPUT_TIMESTAMPS:-1}"

STATE_DIR="${WORK_DIR}/state"
JOBS_DIR="${WORK_DIR}/jobs"
LOG_DIR="${WORK_DIR}/logs"

mkdir -p "${AUDIO_IN_DIR}" "${AUDIO_OUT_DIR}" "${STATE_DIR}" "${JOBS_DIR}" "${LOG_DIR}"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "${LOG_DIR}/worker.log" >&2
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    log "Missing required command: ${name}"
    exit 127
  fi
}

for command_name in curl ffmpeg ffprobe find flock jq sha256sum stat; do
  require_command "${command_name}"
done

exec 9>"${STATE_DIR}/worker.lock"
if ! flock -n 9; then
  log "Another worker is already running; exiting."
  exit 0
fi

safe_name() {
  printf '%s' "$1" | tr '/[:space:]' '__' | tr -cd 'A-Za-z0-9._-'
}

sha256_of_text() {
  printf '%s' "$1" | sha256sum | awk '{print $1}'
}

file_checksum() {
  sha256sum "$1" | awk '{print $1}'
}

file_age_seconds() {
  local file="$1"
  local now
  local mtime
  now="$(date +%s)"
  mtime="$(stat -c '%Y' "${file}")"
  printf '%s\n' "$((now - mtime))"
}

is_supported_audio() {
  local path="${1,,}"
  case "${path}" in
    *.wav|*.mp3|*.m4a|*.aac|*.ogg|*.opus|*.flac|*.webm) return 0 ;;
    *) return 1 ;;
  esac
}

format_seconds() {
  local total="$1"
  local hours=$((total / 3600))
  local minutes=$(((total % 3600) / 60))
  local seconds=$((total % 60))
  printf '%02d:%02d:%02d' "${hours}" "${minutes}" "${seconds}"
}

audio_duration_seconds() {
  local file="$1"
  local duration
  duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "${file}" 2>/dev/null || true)"
  if [[ -z "${duration}" ]]; then
    printf '0\n'
    return
  fi
  printf '%.0f\n' "${duration}"
}

make_chunks() {
  local input_file="$1"
  local chunk_dir="$2"

  case "${chunk_dir}" in
    "${JOBS_DIR}"/*/chunks) rm -rf "${chunk_dir}" ;;
    *) log "Refusing to remove unexpected chunk directory: ${chunk_dir}"; return 1 ;;
  esac

  mkdir -p "${chunk_dir}"

  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "${input_file}" \
    -vn -ac 1 -ar 16000 \
    -f segment -segment_time "${MAX_CHUNK_SECONDS}" -reset_timestamps 1 \
    "${chunk_dir}/chunk_%04d.wav"
}

transcribe_chunk() {
  local chunk_file="$1"
  local response_file="$2"

  curl --silent --show-error --fail-with-body \
    --retry 3 --retry-delay 2 --retry-connrefused \
    --max-time "${CURL_MAX_TIME_SECONDS}" \
    -X POST "${GIGASTT_URL%/}/v1/transcribe" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"${chunk_file}" \
    -o "${response_file}"
}

write_markdown() {
  local output_file="$1"
  local original_rel="$2"
  local checksum="$3"
  local duration="$4"
  local text_file="$5"
  local chunk_count="$6"
  local tmp_file="${output_file}.tmp"

  mkdir -p "$(dirname "${output_file}")"

  {
    printf '# Расшифровка: %s\n\n' "$(basename "${original_rel}")"
    printf -- '- Исходный файл: `%s`\n' "${original_rel}"
    printf -- '- SHA-256: `%s`\n' "${checksum}"
    printf -- '- Длительность: `%s`\n' "$(format_seconds "${duration}")"
    printf -- '- Фрагментов: `%s`\n' "${chunk_count}"
    printf -- '- Создано: `%s`\n' "$(date -Is)"
    printf -- '- Движок: `GigaSTT`\n\n'
    printf '## Текст\n\n'
    cat "${text_file}"
    printf '\n'
  } >"${tmp_file}"

  mv "${tmp_file}" "${output_file}"
}

process_file() {
  local audio_file="$1"

  if [[ "$(basename "${audio_file}")" == .syncthing* ]]; then
    return 0
  fi

  if ! is_supported_audio "${audio_file}"; then
    return 0
  fi

  if [[ "$(file_age_seconds "${audio_file}")" -lt "${STABLE_SECONDS}" ]]; then
    log "Skipping fresh file for now: ${audio_file}"
    return 0
  fi

  local rel_path="${audio_file#${AUDIO_IN_DIR}/}"
  local output_rel="${rel_path%.*}.md"
  local output_file="${AUDIO_OUT_DIR}/${output_rel}"
  local state_key
  local state_file
  local checksum

  state_key="$(sha256_of_text "${rel_path}")"
  state_file="${STATE_DIR}/${state_key}.sha256"
  checksum="$(file_checksum "${audio_file}")"

  if [[ -f "${state_file}" && -f "${output_file}" && "$(cat "${state_file}")" == "${checksum}" ]]; then
    return 0
  fi

  local safe_job
  local job_dir
  local job_audio
  local chunk_dir
  local text_file
  safe_job="$(safe_name "${state_key}-$(basename "${rel_path}")")"
  job_dir="${JOBS_DIR}/${safe_job}"
  job_audio="${job_dir}/input.${audio_file##*.}"
  chunk_dir="${job_dir}/chunks"
  text_file="${job_dir}/text.md"

  case "${job_dir}" in
    "${JOBS_DIR}"/*) rm -rf "${job_dir}" ;;
    *) log "Refusing to remove unexpected job directory: ${job_dir}"; return 1 ;;
  esac

  mkdir -p "${job_dir}"

  log "Processing ${rel_path}"
  cp -p "${audio_file}" "${job_audio}"

  local duration
  duration="$(audio_duration_seconds "${job_audio}")"
  make_chunks "${job_audio}" "${chunk_dir}"

  : >"${text_file}"

  local index=0
  local chunk
  local response_file
  local chunk_text
  local chunk_duration
  local chunk_count=0

  while IFS= read -r -d '' chunk; do
    response_file="${job_dir}/response_${index}.json"
    if ! transcribe_chunk "${chunk}" "${response_file}"; then
      log "Transcription request failed for ${rel_path}, chunk ${index}; response saved at ${response_file}"
      if [[ -s "${response_file}" ]]; then
        log "GigaSTT response: $(head -c 300 "${response_file}")"
      fi
      return 1
    fi
    chunk_text="$(jq -r '.text // empty' "${response_file}")"

    if [[ -z "${chunk_text}" ]]; then
      log "Empty transcription for ${chunk}; response saved at ${response_file}"
      chunk_text="[Нет распознанного текста в этом фрагменте]"
    fi

    if [[ "${OUTPUT_TIMESTAMPS}" == "1" ]]; then
      printf '### %s\n\n%s\n\n' "$(format_seconds "$((index * MAX_CHUNK_SECONDS))")" "${chunk_text}" >>"${text_file}"
    else
      printf '%s\n\n' "${chunk_text}" >>"${text_file}"
    fi

    chunk_duration="$(audio_duration_seconds "${chunk}")"
    if [[ "${chunk_duration}" -gt 0 ]]; then
      duration=$((index * MAX_CHUNK_SECONDS + chunk_duration))
    fi

    index=$((index + 1))
    chunk_count="${index}"
  done < <(find "${chunk_dir}" -maxdepth 1 -type f -name 'chunk_*.wav' -print0 | sort -z)

  if [[ "${chunk_count}" -eq 0 ]]; then
    log "No chunks were produced for ${rel_path}"
    return 1
  fi

  write_markdown "${output_file}" "${rel_path}" "${checksum}" "${duration}" "${text_file}" "${chunk_count}"
  printf '%s\n' "${checksum}" >"${state_file}"
  log "Done ${rel_path} -> ${output_file}"
}

main() {
  if ! curl --silent --show-error --fail "${GIGASTT_URL%/}/health" >/dev/null; then
    log "GigaSTT is not healthy at ${GIGASTT_URL}; start it first."
    exit 1
  fi

  local failures=0
  local audio_files=()
  local audio_file

  while IFS= read -r -d '' audio_file; do
    audio_files+=("${audio_file}")
  done < <(find "${AUDIO_IN_DIR}" -type f -print0 | sort -z)

  for audio_file in "${audio_files[@]}"; do
    if ! process_file "${audio_file}"; then
      failures=$((failures + 1))
      log "Failed to process ${audio_file}; continuing with the rest of the queue."
    fi
  done

  if [[ "${failures}" -gt 0 ]]; then
    log "Worker finished with ${failures} failed file(s). They will be retried on the next scan."
  fi
}

main "$@"
