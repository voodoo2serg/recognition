# Архитектура

## Цель

Система принимает аудиофайлы, записанные на Android, распознаёт русскую речь на self-hosted сервере и возвращает текстовые `.md` файлы обратно на телефон.

Главные требования:

- бесплатно по программному обеспечению;
- без внешних STT API;
- локальная обработка на сервере;
- устойчивость к длинным файлам и временным файлам Syncthing;
- возможность расширения до нескольких телефонов или ПК.

## Поток данных

```text
Fossify Voice Recorder
  writes audio
      |
      v
Android Syncthing folder: recordings, Send Only
      |
      v
Server Syncthing folder: ~/sync/audio_in, Receive Only
      |
      v
systemd path/timer starts recognition-worker.sh
      |
      v
worker copies stable files to ~/.local/share/recognition/jobs
      |
      v
ffmpeg splits/transcodes to 16 kHz mono WAV chunks
      |
      v
GigaSTT REST API: http://127.0.0.1:9876/v1/transcribe
      |
      v
worker writes Markdown transcript atomically
      |
      v
Server Syncthing folder: ~/sync/audio_out, Send Only
      |
      v
Ollama post-processor writes *_abstract.md and *_executive.md
      |
      v
Android Syncthing folder: transcripts, Receive Only
```

## Серверные компоненты

### GigaSTT

GigaSTT работает в Docker и слушает только `127.0.0.1:9876`. Внешний интернет не может напрямую отправлять аудио в STT-сервис. Доступ нужен только локальному worker.

`docker-compose.yml` собирает GigaSTT из crates.io, чтобы не зависеть от наличия готового Docker-образа. Если вы хотите использовать готовый GHCR-образ, есть альтернативный `docker-compose.ghcr.yml`.

### Worker

`scripts/recognition-worker.sh` является основным обработчиком:

- сканирует `AUDIO_IN_DIR`;
- пропускает файлы, изменённые менее `STABLE_SECONDS` назад;
- пропускает временные `.syncthing*`;
- копирует файл в локальный job-каталог;
- режет запись на фрагменты по `MAX_CHUNK_SECONDS`;
- отправляет каждый фрагмент в GigaSTT;
- собирает Markdown с таймкодами;
- пишет результат через временный файл и `mv`;
- сохраняет SHA-256 в state-файл.

State завязан на относительный путь и хеш файла. Если файл с тем же именем изменится, он будет обработан снова.

### Obsidian post-processing

`scripts/obsidian-processor.py` обрабатывает готовые Markdown-расшифровки через локальную Ollama.

События отслеживает `incron`:

```text
~/sync/audio_out      IN_CLOSE_WRITE,IN_MOVED_TO
~/sync/obsidian-main  IN_CLOSE_WRITE,IN_MOVED_TO
```

Wrapper `obsidian-process-one.sh` берёт `flock`, поэтому одновременно выполняется только один запрос к Ollama. Это удерживает память под контролем и не даёт нескольким файлам одновременно загрузить модель.

Процессор:

- игнорирует `*_abstract.md`, `*_executive.md`, временные и Syncthing-файлы;
- извлекает скилл из строки `Используй скилл: name` или `Используй_скилл: name`;
- извлекает модель из строки `Используй модель: name`, `Используй_модель: name` или `Модель: name`;
- сопоставляет голосовой алиас модели с безопасным списком `MODEL_ALIASES`;
- грузит системный промпт из `~/obsidian_processor/skills/name.system`;
- при отсутствии скилла использует `default.system`;
- отправляет исходный текст в Ollama REST API `/api/chat`;
- требует JSON с полями `label`, `abstract` и `executive`;
- запускает рефлексивный цикл: генерация, критика результата, повтор с замечаниями до порога качества или лимита попыток;
- чистит `label` и обрезает его до 12 символов;
- пишет результаты атомарно в ту же папку как `исходник_<label>_abstract.md` и `исходник_<label>_executive.md`.

На текущем CPU-сервере есть два практичных режима:

- `qwen2.5:3b` - быстрый и лёгкий режим для регулярной обработки;
- `hf.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF:Q4_K_M` - более крупная русскоязычная модель для сравнения качества.

Операционный дефолт - `qwen2.5:3b`. Фраза `Используй модель: vikhr` или естественная диктовка `используем модель вихрь` переключает обработку на Vikhr, а `Используй модель: qwen` - на Qwen. Переключение происходит на уровне запроса к Ollama и не требует перезапуска Docker или других серверных процессов.

Чтобы при переключении моделей сервер не держал в памяти обе LLM слишком долго, `OLLAMA_KEEP_ALIVE` рекомендуется держать коротким (`1m`).

### systemd

Используются два механизма:

- `recognition-worker.path` запускает обработку при изменении папки;
- `recognition-worker.timer` запускает скан каждые 2 минуты, чтобы не зависеть от идеальности событий файловой системы.

## Масштабирование

Базовая версия запускает один worker за раз через `flock`. Это сознательный выбор: GigaSTT и `ffmpeg` могут сильно нагружать CPU, а последовательная очередь проще и надёжнее.

Для масштабирования можно:

- увеличить `MAX_CHUNK_SECONDS` или уменьшить его под лимит памяти;
- поднять несколько серверов и развести папки Syncthing по устройствам;
- заменить worker на очередь `Redis/RQ`, `Celery` или `systemd` template units;
- использовать сервер с NVIDIA GPU и CUDA-сборкой GigaSTT;
- добавить отдельную постобработку Markdown: суммаризацию, заголовки, задачи.

## Безопасность

- GigaSTT не публикуется наружу, только `127.0.0.1`.
- Syncthing UI лучше открывать через SSH tunnel:

```bash
ssh -L 8384:127.0.0.1:8384 user@server
```

- Не храните `audio_out` в публичном веб-каталоге.
- Если записи чувствительные, включите шифрование диска или хотя бы ограничьте права на `~/sync` и `~/.local/share/recognition`.
