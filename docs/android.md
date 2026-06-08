# Android

## Приложения

Установите:

- Fossify Voice Recorder;
- Syncthing-Fork;
- Markor или любой редактор Markdown.

## Папки на телефоне

Создайте две папки:

```text
Recognition/Recordings
Recognition/Transcripts
```

В Fossify Voice Recorder выберите `Recognition/Recordings` как папку записей.

Рекомендации по формату:

- `m4a` или `mp3` удобны по размеру;
- `wav` проще, но быстро занимает место;
- для лекций лучше избегать слишком агрессивного шумоподавления.

Worker на сервере принимает `wav`, `mp3`, `m4a`, `aac`, `ogg`, `opus`, `flac`, `webm` и сам приводит звук к 16 kHz mono WAV перед распознаванием.

## Syncthing-Fork

Добавьте сервер как устройство по Device ID.

Папка 1:

- путь на телефоне: `Recognition/Recordings`;
- путь на сервере: `~/sync/audio_in`;
- режим телефона: `Send Only`;
- режим сервера: `Receive Only`.

Папка 2:

- путь на телефоне: `Recognition/Transcripts`;
- путь на сервере: `~/sync/audio_out`;
- режим телефона: `Receive Only`;
- режим сервера: `Send Only`.

## Рабочий цикл

1. Запишите аудио в Fossify Voice Recorder.
2. Syncthing-Fork отправит файл на сервер.
3. Worker распознает запись и создаст `.md`.
4. Syncthing-Fork получит `.md` в `Recognition/Transcripts`.
5. Откройте файл в Markor.

## Важно

Не настраивайте одну и ту же папку и для аудио, и для расшифровок. Две отдельные папки сильно упрощают права Syncthing и не смешивают большие записи с маленькими `.md`.
