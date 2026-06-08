# Установка сервера

Инструкция рассчитана на Ubuntu/Debian.

## 1. Клонировать проект

```bash
git clone <repository-url>
cd recognition
```

## 2. Установить зависимости и сервисы

```bash
./scripts/install-server.sh
```

Скрипт установит:

- `docker.io`;
- `docker-compose-plugin`;
- `ffmpeg`;
- `jq`;
- `curl`;
- `syncthing`;
- `util-linux` для `flock`.

Также будут созданы папки:

```text
~/sync/audio_in
~/sync/audio_out
~/.local/share/recognition
~/.config/recognition/recognition.env
```

## 3. Проверить GigaSTT

```bash
curl http://127.0.0.1:9876/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

Первый запуск скачает модель GigaAM примерно на 850 МБ. Это может занять время.

## 4. Проверить worker

```bash
./scripts/healthcheck.sh
systemctl --user status recognition-worker.timer
systemctl --user status recognition-worker.path
```

Ручной запуск скана:

```bash
./scripts/recognition-worker.sh
```

## 5. Открыть Syncthing UI

На сервере UI обычно слушает `127.0.0.1:8384`. Безопаснее открыть через SSH tunnel:

```bash
ssh -L 8384:127.0.0.1:8384 user@server
```

Затем открыть в браузере:

```text
http://127.0.0.1:8384
```

## 6. Настроить конфиг

Файл:

```text
~/.config/recognition/recognition.env
```

Основные параметры:

```bash
AUDIO_IN_DIR=/home/user/sync/audio_in
AUDIO_OUT_DIR=/home/user/sync/audio_out
WORK_DIR=/home/user/.local/share/recognition
GIGASTT_URL=http://127.0.0.1:9876
MAX_CHUNK_SECONDS=120
STABLE_SECONDS=20
OUTPUT_TIMESTAMPS=1
```

После изменения:

```bash
systemctl --user restart recognition-worker.timer recognition-worker.path
```
