# Эксплуатация

## Проверка состояния

```bash
./scripts/healthcheck.sh
docker compose ps
docker compose logs -f gigastt
systemctl --user status recognition-worker.timer
systemctl --user status recognition-worker.path
journalctl --user -u recognition-worker.service -n 100
```

Лог worker:

```text
~/.local/share/recognition/logs/worker.log
```

## Ручная обработка

Положите аудио в:

```text
~/sync/audio_in
```

Запустите:

```bash
./scripts/recognition-worker.sh
```

Результат появится в:

```text
~/sync/audio_out
```

## Если GigaSTT не стартует

Проверьте:

```bash
docker compose logs gigastt
docker compose build --no-cache gigastt
docker compose up -d
```

Первый запуск может быть долгим из-за скачивания модели.

## Если файл не распознаётся

Проверьте:

```bash
ffprobe ~/sync/audio_in/file.m4a
tail -n 100 ~/.local/share/recognition/logs/worker.log
```

Частые причины:

- Syncthing ещё пишет файл, worker отложил обработку;
- GigaSTT ещё не скачал модель;
- файл повреждён;
- не хватает диска в `~/.local/share/recognition`;
- нет `ffmpeg` или `jq`.

## Повторная обработка файла

Удалите соответствующий `.md` из `audio_out` и state-файл из:

```text
~/.local/share/recognition/state
```

Проще всего изменить имя исходного файла или положить его заново с новым именем.

## Обновление проекта

```bash
git pull
docker compose up -d --build
systemctl --user daemon-reload
systemctl --user restart recognition-worker.timer recognition-worker.path
```
