# Obsidian Processor

Этот модуль запускает локальную постобработку Markdown-расшифровок через Ollama.

Поток:

```text
Markdown transcript
  -> Syncthing folder on server
  -> incron IN_CLOSE_WRITE / IN_MOVED_TO
  -> obsidian-processor.py
  -> Ollama REST API generation
  -> Ollama REST API critic
  -> retry with feedback if quality is below threshold
  -> *_<label>_abstract.md and *_<label>_executive.md in the same folder
```

По умолчанию отслеживаются две папки:

- `~/sync/audio_out`
- `~/sync/obsidian-main`

Это можно изменить в `~/obsidian_processor/processor.env`.

## Установка

```bash
cd /opt/recognition
./scripts/install-obsidian-processor.sh
```

Installer:

- ставит `curl`, `jq`, `incron`, `python3`, `util-linux`;
- запускает `ollama.service`, если он установлен;
- скачивает модель из `OLLAMA_MODEL`, по умолчанию `qwen2.5:3b`;
- если основную модель скачать не удалось, пробует `OLLAMA_FALLBACK_MODEL`, по умолчанию `qwen2.5:3b`;
- создает `~/obsidian_processor`;
- добавляет правила `incron` для `IN_CLOSE_WRITE,IN_MOVED_TO`;
- выполняет первичный scan существующих `.md` файлов.

## Скиллы

Скилл выбирается строкой в исходном Markdown:

```text
Используй скилл: meeting
```

или:

```text
Используй_скилл: lecture
```

Файлы скиллов лежат в:

```bash
~/obsidian_processor/skills/
```

Имя скилла `meeting` соответствует файлу:

```bash
~/obsidian_processor/skills/meeting.system
```

Если фразы нет, используется `default.system`. Если скилл указан, но файл не найден, ошибка пишется в лог, а обработка продолжается через default.

Доступные базовые скиллы:

- `default` - универсальная аннотация и executive summary.
- `meeting` - встречи, созвоны, интервью и обсуждения.
- `lecture` - лекции, уроки, доклады и длинные объяснения.
- `ocr-note-processor` - шумные голосовые/OCR/STT-заметки, исследовательские и рабочие идеи, тематическая классификация.

Во всех скиллах есть отдельное правило: вывод всегда на русском языке, если в исходном тексте явно не указан другой язык.

## Выбор модели голосом

Модель можно выбрать строкой в исходном Markdown:

```text
Используй модель: vikhr
```

или:

```text
Используй_модель: qwen
```

Эту фразу можно произнести в начале аудиозаписи. После распознавания она попадёт в Markdown, процессор прочитает её и уберёт из текста, отправляемого в модель.

Распознаются и более естественные голосовые варианты без двоеточия, например:

```text
используем модель вихрь
выбери модель qwen
```

Алиасы задаются в `~/obsidian_processor/processor.env`:

```bash
MODEL_ALIASES="vikhr=hf.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF:Q4_K_M,вихрь=hf.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF:Q4_K_M,qwen=qwen2.5:3b,кьювен=qwen2.5:3b"
```

Для скиллов также есть алиасы. Например, слова `исследование`, `наука`, `статья`, `заметка` включают `ocr-note-processor`, а `встреча` и `созвон` включают `meeting`.

По умолчанию прямые имена моделей из текста запрещены (`ALLOW_DIRECT_MODEL_NAMES=0`), чтобы случайная фраза в диктовке не заставила процессор обращаться к неизвестной модели. Если алиас не найден, процессор пишет ошибку в лог и использует `OLLAMA_MODEL`.

Для защиты CPU-сервера длинные тексты с выбранной голосом тяжёлой моделью автоматически уходят на fallback, если длина текста больше `HEAVY_MODEL_MAX_INPUT_CHARS` (по умолчанию `3000`). Это позволяет проверять Vikhr на коротких важных заметках, но не блокировать очередь длинными расшифровками.

В каждом `*_abstract.md` и `*_executive.md` сохраняется строка `Модель`, поэтому можно сравнить качество `vikhr` и `qwen` на одинаковых текстах.

## Результаты

Для файла:

```text
20260608_004256.md
```

создаются:

```text
20260608_004256_статья_наука_abstract.md
20260608_004256_статья_наука_executive.md
```

Метка берется из поля `label`, которое модель возвращает вместе с `abstract` и `executive`. Процессор чистит метку и обрезает ее до `FILENAME_LABEL_MAX_CHARS` символов, по умолчанию до 12.

Файлы `*_abstract.md` и `*_executive.md` не обрабатываются повторно, чтобы не было бесконечного цикла.

## Рефлексивный цикл

Процессор делает не один вызов модели, а цикл:

1. Генерирует JSON с `label`, `abstract`, `executive`.
2. Отправляет результат критику через Ollama.
3. Сравнивает оценку с `QUALITY_THRESHOLD`.
4. Если оценка ниже порога, добавляет замечания критика в следующий prompt и повторяет генерацию.
5. Сохраняет лучший последний результат после `REFLECTION_MAX_ATTEMPTS`.

Есть также автоматическая проверка: она штрафует слишком короткий abstract, бедный executive, отсутствие Markdown-разделов, игнорирование терминов, календарных маркеров и открытых вопросов.

## Логи

```bash
tail -f ~/obsidian_processor/processing.log
```

## Модель и память

На CPU-сервере 7B-модель может отвечать несколько минут даже на коротких файлах. Для более легкого режима можно указать в `~/obsidian_processor/processor.env`:

```bash
OLLAMA_MODEL="qwen2.5:3b"
SKILL_ALIASES="default=default,основной=default,базовый=default,обычный=default,meeting=meeting,встреча=meeting,созвон=meeting,lecture=lecture,лекция=lecture,ocr=ocr-note-processor,исследование=ocr-note-processor,наука=ocr-note-processor,статья=ocr-note-processor,заметка=ocr-note-processor"
MODEL_ALIASES="vikhr=hf.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF:Q4_K_M,вихрь=hf.co/Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it_GGUF:Q4_K_M,qwen=qwen2.5:3b,кьювен=qwen2.5:3b"
OLLAMA_KEEP_ALIVE="1m"
HEAVY_MODEL_MAX_INPUT_CHARS="3000"
OLLAMA_TIMEOUT_SECONDS="1800"
OLLAMA_NUM_CTX="4096"
OLLAMA_NUM_PREDICT="1600"
OLLAMA_CRITIC_NUM_CTX="4096"
OLLAMA_CRITIC_NUM_PREDICT="700"
MAX_INPUT_CHARS="16000"
ABSTRACT_MIN_CHARS="650"
FILENAME_LABEL_MAX_CHARS="12"
REFLECTION_MAX_ATTEMPTS="3"
QUALITY_THRESHOLD="8"
```

После изменения `processor.env` перезапускать Docker или `ollama` не нужно: wrapper читает конфиг при каждом новом запуске обработки. Перезапуск `ollama` нужен только если сам сервис завис или был обновлён.

Если вы часто переключаете модели голосом, держите `OLLAMA_KEEP_ALIVE` коротким (`1m`): иначе Ollama может несколько минут держать в памяти и `qwen`, и `vikhr` одновременно.

## Ручная проверка

```bash
cat > ~/sync/obsidian-main/test_meeting.md <<'EOF'
Используй скилл: meeting
Используй модель: vikhr

Обсудили запуск проекта. Администратор отвечает за сервер. Срок проверки - завтра.
Решили добавить автоматическую аннотацию и executive summary.
EOF
```

Через несколько секунд должны появиться:

```text
~/sync/obsidian-main/test_meeting_<метка>_abstract.md
~/sync/obsidian-main/test_meeting_<метка>_executive.md
```
