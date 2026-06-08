# recognition

Локальная бесплатная система распознавания русской речи с Android-диктофона:

```text
Android/Fossify Voice Recorder
  -> Syncthing audio_in
  -> серверный worker
  -> GigaSTT
  -> Markdown transcript
  -> Ollama post-processing
  -> *_abstract.md + *_executive.md
  -> Syncthing audio_out
  -> Android/Markor или любой редактор
```

Проект рассчитан на self-hosted сервер и Android-телефон, без облачных STT API и платных сервисов.

## Архитектура проекта

Система состоит из двух связанных контуров:

```text
Контур распознавания:
Android-диктофон
  -> Syncthing Send Only
  -> серверная папка ~/sync/audio_in
  -> recognition-worker.sh
  -> GigaSTT REST API
  -> Markdown в ~/sync/audio_out
  -> Syncthing Receive Only на телефоне/ПК

Контур постобработки:
Markdown в ~/sync/audio_out или ~/sync/obsidian-main
  -> incron IN_CLOSE_WRITE / IN_MOVED_TO
  -> obsidian-process-one.sh + flock
  -> obsidian-processor.py
  -> Ollama /api/chat
  -> *_abstract.md и *_executive.md в той же папке
  -> Syncthing в Obsidian/Android/Windows
```

Связки:

- `Fossify Voice Recorder` пишет аудио на Android в локальную папку записей.
- `Syncthing-Fork` на Android отправляет эту папку на сервер как `audio_in`.
- Серверный `recognition-worker.sh` берёт только стабильные аудиофайлы, копирует их в локальную очередь, режет через `ffmpeg` и отправляет в локальный `GigaSTT`.
- `GigaSTT` возвращает распознанный русский текст, worker атомарно сохраняет Markdown в `audio_out`.
- `Syncthing` отправляет готовые Markdown-файлы обратно на Android, Windows и в Obsidian vault.
- `incron` следит за появлением Markdown-файлов и запускает постобработчик.
- `obsidian-processor.py` выбирает скилл по фразе `Используй скилл: ...`, выбирает модель по фразе `Используй модель: ...`, отправляет текст в локальную `Ollama` и сохраняет аннотацию и executive summary.

## Применяемые системы

| Система | Где используется | Роль | Источник |
| --- | --- | --- | --- |
| Fossify Voice Recorder | Android | Запись WAV/MP3/M4A в локальную папку | [GitHub](https://github.com/FossifyOrg/Voice-Recorder) |
| Syncthing | Android, сервер, Windows/ПК | Двусторонняя и односторонняя синхронизация папок | [GitHub](https://github.com/syncthing/syncthing) |
| Syncthing-Fork | Android | Android-обёртка Syncthing с фоновым режимом | [GitHub](https://github.com/researchxxl/syncthing-android) |
| GigaSTT | Сервер, Docker | Локальное русское STT через REST API | [GitHub](https://github.com/ekhodzitsky/gigastt) |
| Docker | Сервер | Изоляция GigaSTT, локальный порт `127.0.0.1:9876` | [GitHub](https://github.com/docker) |
| FFmpeg | Сервер | Нарезка и нормализация длинных аудиофайлов | [GitHub](https://github.com/FFmpeg/FFmpeg) |
| jq | Сервер | Разбор JSON-ответов GigaSTT | [GitHub](https://github.com/jqlang/jq) |
| incron | Сервер | Автозапуск обработки при появлении Markdown-файла | [GitHub](https://github.com/ar-/incron) |
| Ollama | Сервер | Локальная LLM-постобработка расшифровок | [GitHub](https://github.com/ollama/ollama) |
| Qwen 2.5 3B | Сервер, Ollama | Быстрая лёгкая модель для CPU-режима | [Ollama](https://ollama.com/library/qwen2.5) |
| Vikhr-YandexGPT-5-Lite-8B-it GGUF | Сервер, Ollama | Более крупная русскоязычная модель для сравнения качества | [Hugging Face](https://huggingface.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF) |
| Obsidian | Android, Windows/ПК | Чтение и ведение синхронизированных Markdown-заметок | [Официальный сайт](https://obsidian.md/) |
| Markor | Android | Лёгкий Markdown-ридер/редактор для папки расшифровок | [GitHub](https://github.com/gsantner/markor) |

## Что внутри

- `docker-compose.yml` - локальный GigaSTT, порт открыт только на `127.0.0.1`.
- `docker/gigastt/Dockerfile` - сборка GigaSTT из crates.io, без зависимости от внешнего Docker-образа.
- `scripts/recognition-worker.sh` - безопасный обработчик файлов:
  - не удаляет и не меняет папку Syncthing `audio_in`;
  - ждёт, пока файл перестанет записываться;
  - копирует аудио в локальную рабочую очередь;
  - режет длинные записи через `ffmpeg`;
  - отправляет куски в GigaSTT через REST `/v1/transcribe`;
  - парсит JSON через `jq`;
  - атомарно пишет `.md` в `audio_out`;
  - ведёт state по SHA-256, чтобы не распознавать тот же файл повторно.
- `systemd/user/*` - `path` + `timer`: мгновенный запуск при изменениях и периодический скан для пропущенных событий.
- `scripts/obsidian-processor.py` - постобработка Markdown через локальную Ollama: короткая метка имени файла, содержательная аннотация и executive summary с рефлексивной самопроверкой.
- `skills/*.system` - системные промпты для стилей обработки, выбираются фразой `Используй скилл: meeting`; доступен скилл `ocr-note-processor` для шумных STT/OCR-заметок.
- `docs/*` - инструкции по серверу, Android и эксплуатации.

## Голосовое управление обработкой

Фразы можно произнести в начале записи, и после распознавания они попадут в Markdown:

```text
Используй скилл: ocr-note-processor
Используй модель: vikhr
```

Поддерживаются синонимы модели из `MODEL_ALIASES`: `vikhr`, `вихрь`, `yandex`, `яндекс`, `qwen`, `кьювен`, `квен`. Длинное имя модели хранится в конфиге, поэтому его не нужно диктовать голосом.

Операционный дефолт - `qwen2.5:3b`, потому что он быстрее на CPU. Vikhr включается фразой `Используй модель: vikhr` или естественным вариантом `используем модель вихрь`.

Для длинных текстов включён предохранитель: если выбранная голосом тяжёлая модель получает вход больше 3000 символов, обработчик использует fallback `qwen`, чтобы очередь не зависала.

Результаты теперь получают содержательную метку в имени файла, не длиннее 12 символов: например, исходник `20260608_004256.md` может дать `20260608_004256_статья_наука_abstract.md` и `20260608_004256_статья_наука_executive.md`.

Постобработка делает рефлексивный цикл: генерация, критика качества, повторная генерация с замечаниями. По умолчанию до 3 попыток и порог 8/10.

Для сервера с 12–16 ГБ ОЗУ `OLLAMA_KEEP_ALIVE` держится коротким (`1m`), чтобы при переключении `vikhr`/`qwen` Ollama не держала обе модели в памяти слишком долго.

Все серверные скиллы содержат отдельное правило: вывод на русском языке, если в исходном тексте явно не указан другой язык.

Для сравнения качества можно сделать две записи с одинаковым текстом:

```text
Используй модель: vikhr
```

и

```text
Используй модель: qwen
```

В созданных `*_abstract.md` и `*_executive.md` будет строка `Модель`, `Метка`, `Оценка качества` и количество попыток, чтобы видеть, какой LLM был использован и прошла ли переработка самопроверку.

## Быстрый старт на сервере

```bash
git clone <repository-url>
cd recognition
./scripts/install-server.sh
```

После установки проверьте:

```bash
curl http://127.0.0.1:9876/health
./scripts/healthcheck.sh
```

Первый запуск GigaSTT скачает модель примерно на 850 МБ. Это бесплатно, но требует интернет на сервере.

## Папки синхронизации

По умолчанию:

- входящие записи с телефона: `~/sync/audio_in`;
- готовые расшифровки: `~/sync/audio_out`;
- Obsidian vault или дополнительная папка заметок: `~/sync/obsidian-main`;
- локальная очередь и state: `~/.local/share/recognition`.

`audio_in` и `audio_out` подключаются к Syncthing. Рабочая папка `~/.local/share/recognition` не синхронизируется.

## Android

На телефоне установите:

- Fossify Voice Recorder;
- Syncthing-Fork;
- Markor или любой редактор Markdown.

В Syncthing нужны две папки:

- папка записей диктофона -> сервер `audio_in`, режим телефона `Send Only`;
- папка расшифровок -> сервер `audio_out`, режим телефона `Receive Only`.

Подробно: [docs/android.md](docs/android.md).

## Почему не удаляем исходники на сервере

Серверная `audio_in` является receive-only папкой Syncthing. Если worker будет удалять файлы внутри неё, Syncthing получит локальное изменение там, где сервер должен только принимать данные. Поэтому worker копирует файл в локальную очередь и работает уже с копией.

## Документация

- [Архитектура](ARCHITECTURE.md)
- [Установка сервера](docs/server.md)
- [Настройка Android](docs/android.md)
- [Настройка Syncthing](docs/syncthing.md)
- [Постобработка Obsidian через Ollama](docs/obsidian-processor.md)
- [Эксплуатация и диагностика](docs/operations.md)

## Лицензии и стоимость

Система использует open-source компоненты и не требует платного STT API. Возможные расходы остаются инфраструктурными: электричество, сервер, трафик и диск.
