#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Iterable


SKILL_RE = re.compile(
    r"^\s*(?:Используй|Используем|Включи|Выбери|Поставь)(?:\s+|_)скилл\s*:?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SKILL_ANYWHERE_RE = re.compile(
    r"\b(?:Используй|Используем|Включи|Выбери|Поставь)\s+(?:скилл|режим)\s*:?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)",
    re.IGNORECASE,
)
SKILL_BEFORE_WORD_RE = re.compile(
    r"\b(?:Используй|Используем|Включи|Выбери|Поставь)\s+([A-Za-zА-Яа-яЁё0-9_.-]+)\s+(?:скилл|режим)\b",
    re.IGNORECASE,
)
SKILL_CONTEXT_RE = re.compile(
    r"\b(?:Используй|Используем|Включи|Выбери|Поставь).{0,80}\b(исследование|исследовательский|наука|науку|научный|научную|статья|статью|ocr|заметка|заметку)\b",
    re.IGNORECASE | re.DOTALL,
)
SAFE_SKILL_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_.-]+$")
MODEL_RE = re.compile(
    r"^\s*(?:Используй|Используем|Включи|Выбери|Поставь)(?:\s+|_)модель(?:\s*:|\s+)\s*([A-Za-zА-Яа-яЁё0-9_.:/-]+)\s*$|^\s*Модель(?:\s*:|\s+)\s*([A-Za-zА-Яа-яЁё0-9_.:/-]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MODEL_ANYWHERE_RE = re.compile(
    r"\b(?:Используй|Используем|Включи|Выбери|Поставь)\s+модель(?:\s*:|\s+)\s*([A-Za-zА-Яа-яЁё0-9_.:/-]+)",
    re.IGNORECASE,
)
SAFE_MODEL_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_.:/-]+$")

DEFAULT_SKILL_ALIASES = (
    "default=default,основной=default,базовый=default,обычный=default,"
    "meeting=meeting,встреча=meeting,встречу=meeting,созвон=meeting,интервью=meeting,"
    "lecture=lecture,лекция=lecture,лекцию=lecture,урок=lecture,доклад=lecture,"
    "ocr=ocr-note-processor,заметка=ocr-note-processor,заметку=ocr-note-processor,"
    "исследование=ocr-note-processor,исследовательский=ocr-note-processor,"
    "наука=ocr-note-processor,науку=ocr-note-processor,научный=ocr-note-processor,научную=ocr-note-processor,"
    "статья=ocr-note-processor,статью=ocr-note-processor"
)


def expand_path(value: str) -> Path:
    value = value.replace("%h", str(Path.home()))
    return Path(os.path.expanduser(value)).resolve()


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


PROCESSOR_HOME = expand_path(env_str("PROCESSOR_HOME", "%h/obsidian_processor"))
WATCH_DIRS_RAW = env_str("WATCH_DIRS", "%h/sync/audio_out:%h/sync/obsidian-main")
SKILLS_DIR = expand_path(env_str("SKILLS_DIR", "%h/obsidian_processor/skills"))
LOG_FILE = expand_path(env_str("LOG_FILE", "%h/obsidian_processor/processing.log"))
OLLAMA_URL = env_str("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = env_str("OLLAMA_MODEL", "vikhr:latest")
OLLAMA_FALLBACK_MODEL = env_str("OLLAMA_FALLBACK_MODEL", "")
SKILL_ALIASES_RAW = env_str("SKILL_ALIASES", DEFAULT_SKILL_ALIASES)
MODEL_ALIASES_RAW = env_str("MODEL_ALIASES", "")
ALLOW_DIRECT_MODEL_NAMES = env_str("ALLOW_DIRECT_MODEL_NAMES", "0").lower() in {"1", "true", "yes", "on"}
HEAVY_MODEL_MAX_INPUT_CHARS = env_int("HEAVY_MODEL_MAX_INPUT_CHARS", 3000)
OLLAMA_KEEP_ALIVE = env_str("OLLAMA_KEEP_ALIVE", "10m")
OLLAMA_TIMEOUT_SECONDS = env_int("OLLAMA_TIMEOUT_SECONDS", 900)
OLLAMA_NUM_CTX = env_int("OLLAMA_NUM_CTX", 4096)
OLLAMA_NUM_PREDICT = env_int("OLLAMA_NUM_PREDICT", 900)
OLLAMA_CRITIC_NUM_CTX = env_int("OLLAMA_CRITIC_NUM_CTX", 4096)
OLLAMA_CRITIC_NUM_PREDICT = env_int("OLLAMA_CRITIC_NUM_PREDICT", 500)
OLLAMA_TEMPERATURE = env_float("OLLAMA_TEMPERATURE", 0.2)
MAX_INPUT_CHARS = env_int("MAX_INPUT_CHARS", 12000)
ABSTRACT_MAX_CHARS = env_int("ABSTRACT_MAX_CHARS", 1200)
ABSTRACT_MIN_CHARS = env_int("ABSTRACT_MIN_CHARS", 650)
FILENAME_LABEL_MAX_CHARS = env_int("FILENAME_LABEL_MAX_CHARS", 12)
REFLECTION_MAX_ATTEMPTS = env_int("REFLECTION_MAX_ATTEMPTS", 3)
QUALITY_THRESHOLD = env_int("QUALITY_THRESHOLD", 8)
STABLE_DELAY_SECONDS = env_int("STABLE_DELAY_SECONDS", 2)

CRITIC_SYSTEM_PROMPT = """
Ты строгий редактор-критик русскоязычной постобработки STT/OCR.

Оцени результат по шкале 1-10 и верни строго JSON:
{
  "score": 8,
  "feedback": "конкретные замечания для улучшения следующей попытки"
}

Критерии:
- abstract должен быть содержательным сообщением для коллег, а не двумя общими предложениями.
- abstract для содержательного источника должен быть близок к 650-1200 знакам, но не длиннее заданного лимита.
- executive должен сохранять смысловой объем источника, а не вымывать детали.
- executive должен помогать пользователю структурировать поток мысли: выводы, определения, рабочие гипотезы, открытые вопросы, рекомендации и календарные маркеры должны появляться, когда они релевантны исходнику.
- Важные сомнительные термины STT/OCR нужно не игнорировать, а отмечать и предлагать вероятные варианты.
- Структура должна быть адаптивной, без пустых обязательных разделов и без бюрократического шаблона.
- Нельзя выдавать внешние догадки за факты исходника; аналитические дополнения допустимы только как интерпретации или рекомендации.

Если abstract слишком короткий, executive бедный, нет выводов/определений/вопросов при наличии смысловых оснований или игнорируются важные распознавательные неопределенности, ставь не выше 6.
"""


def watch_dirs() -> list[Path]:
    parts = []
    for chunk in WATCH_DIRS_RAW.replace(",", ":").split(":"):
        chunk = chunk.strip()
        if chunk:
            parts.append(expand_path(chunk))
    return parts


def log(level: str, message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {level.upper()} {message}\n")


def is_ignored_file(path: Path) -> bool:
    name = path.name
    lower = name.lower()
    if name.startswith("."):
        return True
    if ".stfolder" in path.parts or ".stversions" in path.parts:
        return True
    if lower.endswith(("_abstract.md", "_executive.md")):
        return True
    if lower.endswith((".tmp", ".part", ".swp", ".bak")):
        return True
    if lower.startswith(".syncthing"):
        return True
    return lower.endswith(".md") is False


def wait_until_stable(path: Path) -> bool:
    if STABLE_DELAY_SECONDS <= 0:
        return path.exists()

    try:
        first = path.stat()
    except FileNotFoundError:
        return False

    time.sleep(STABLE_DELAY_SECONDS)

    try:
        second = path.stat()
    except FileNotFoundError:
        return False

    return first.st_size == second.st_size and first.st_mtime_ns == second.st_mtime_ns


def parse_aliases(raw: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        alias, value = item.split("=", 1)
        alias = alias.strip().casefold()
        value = value.strip()
        if alias and value:
            aliases[alias] = value
    return aliases


def parse_model_aliases(raw: str) -> dict[str, str]:
    return parse_aliases(raw)


def clean_directive_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().strip("`\"'«».,;:!?")
    return cleaned or None


def find_skill_directive(text: str) -> str | None:
    for regex in (SKILL_RE, SKILL_ANYWHERE_RE, SKILL_CONTEXT_RE, SKILL_BEFORE_WORD_RE):
        match = regex.search(text)
        if not match:
            continue
        for group in match.groups():
            directive = clean_directive_value(group)
            if directive:
                return directive
    return None


def find_skill(text: str) -> str:
    directive = find_skill_directive(text)
    if not directive:
        return "default"

    aliases = parse_aliases(SKILL_ALIASES_RAW)
    alias_key = directive.casefold()
    if alias_key in aliases:
        return aliases[alias_key]

    if not SAFE_SKILL_RE.match(directive):
        log("ERROR", f"unsafe skill name ignored: {directive!r}")
        return "default"
    return directive


def find_model_directive(text: str) -> str | None:
    for regex in (MODEL_RE, MODEL_ANYWHERE_RE):
        match = regex.search(text)
        if not match:
            continue
        for group in match.groups():
            directive = clean_directive_value(group)
            if not directive:
                continue
            if not SAFE_MODEL_RE.match(directive):
                log("ERROR", f"unsafe model directive ignored: {directive!r}")
                return None
            return directive
    return None


def resolve_model(text: str) -> tuple[str, str]:
    directive = find_model_directive(text)
    if not directive:
        return OLLAMA_MODEL, "default"

    aliases = parse_model_aliases(MODEL_ALIASES_RAW)
    alias_key = directive.casefold()
    if alias_key in aliases:
        return aliases[alias_key], directive

    if directive == OLLAMA_MODEL or directive in aliases.values() or ALLOW_DIRECT_MODEL_NAMES:
        return directive, directive

    log("ERROR", f"unknown model alias '{directive}', falling back to {OLLAMA_MODEL}")
    return OLLAMA_MODEL, "default"


def load_skill(skill: str) -> tuple[str, str]:
    skill_path = SKILLS_DIR / f"{skill}.system"
    if skill_path.exists():
        return skill, skill_path.read_text(encoding="utf-8")

    if skill != "default":
        log("ERROR", f"skill '{skill}' not found at {skill_path}; falling back to default")

    default_path = SKILLS_DIR / "default.system"
    if not default_path.exists():
        raise FileNotFoundError(f"default skill not found: {default_path}")
    return "default", default_path.read_text(encoding="utf-8")


def trim_abstract(text: str) -> str:
    text = text.strip()
    if len(text) <= ABSTRACT_MAX_CHARS:
        return text
    suffix = "..."
    return text[: max(0, ABSTRACT_MAX_CHARS - len(suffix))].rstrip() + suffix


def abstract_min_chars_for(source_text: str) -> int:
    if len(source_text) < 800:
        return min(350, ABSTRACT_MAX_CHARS)
    return min(ABSTRACT_MIN_CHARS, max(350, ABSTRACT_MAX_CHARS - 100))


def strip_outer_code_fence(text: str) -> str:
    cleaned = text.strip()
    match = re.match(r"^```(?:markdown|md)?\s*(.*?)\s*```$", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned


def extract_json_object(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def sanitize_label(value: str | None, fallback: str) -> str:
    label = strip_outer_code_fence(value or "").strip().lower()
    label = unicodedata.normalize("NFKC", label).replace("ё", "е")
    label = re.sub(r"[^0-9a-zа-я_ -]+", "", label, flags=re.IGNORECASE)
    label = re.sub(r"[\s-]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    if not label:
        label = fallback
    label = label[: max(1, FILENAME_LABEL_MAX_CHARS)].rstrip("_")
    return label or "заметка"


def fallback_label(skill: str, source_text: str) -> str:
    text = source_text.casefold()
    if "стат" in text and ("наук" in text or skill == "ocr-note-processor"):
        return "статья_наука"
    if "исслед" in text:
        return "исслед"
    if "календар" in text or "срок" in text or "дедлайн" in text:
        return "календарь"
    if skill == "meeting":
        return "встреча"
    if skill == "lecture":
        return "лекция"
    if skill == "ocr-note-processor":
        return "заметка"
    return "итог"


def parse_generation_result(content: str, fallback: str) -> dict:
    result = extract_json_object(content)
    abstract = result.get("abstract")
    executive = result.get("executive")
    if not isinstance(abstract, str) or not abstract.strip():
        raise ValueError("Ollama JSON has no non-empty string field 'abstract'")
    if not isinstance(executive, str) or not executive.strip():
        raise ValueError("Ollama JSON has no non-empty string field 'executive'")

    label = result.get("label")
    if label is not None and not isinstance(label, str):
        label = None

    return {
        "label": sanitize_label(label, fallback),
        "abstract": trim_abstract(strip_outer_code_fence(abstract)),
        "executive": strip_outer_code_fence(executive),
    }


def ollama_chat_content(
    model: str,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = True,
    num_ctx: int | None = None,
    num_predict: int | None = None,
) -> str:
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": num_ctx or OLLAMA_NUM_CTX,
            "num_predict": num_predict or OLLAMA_NUM_PREDICT,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["format"] = "json"

    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8")

    outer = json.loads(raw)
    content = outer.get("message", {}).get("content", "")
    if not content:
        raise ValueError(f"Ollama response has no message.content: {raw[:500]}")

    return content


def ollama_chat(model: str, system_prompt: str, user_prompt: str, fallback: str) -> dict:
    content = ollama_chat_content(model, system_prompt, user_prompt, json_mode=True)
    return parse_generation_result(content, fallback)


def extract_transcript_body(text: str) -> str:
    match = re.search(r"(?im)^##\s+Текст\s*$", text)
    if match:
        body = text[match.end() :].strip()
        if body:
            return body
    return text.strip()


def strip_control_directives(text: str) -> str:
    text = SKILL_RE.sub("", text)
    text = SKILL_ANYWHERE_RE.sub("", text)
    text = SKILL_BEFORE_WORD_RE.sub("", text)
    text = MODEL_RE.sub("", text)
    text = MODEL_ANYWHERE_RE.sub("", text)
    return text.strip()


def truncate_source(text: str) -> str:
    if len(text) <= MAX_INPUT_CHARS:
        return text
    half = max(1000, MAX_INPUT_CHARS // 2)
    log("WARN", f"source text truncated from {len(text)} to {MAX_INPUT_CHARS} chars")
    return (
        text[:half].rstrip()
        + "\n\n[... середина длинного текста пропущена для ограничения контекста модели ...]\n\n"
        + text[-half:].lstrip()
    )


def build_user_prompt(source_name: str, source_text: str) -> str:
    abstract_min = abstract_min_chars_for(source_text)
    return f"""Обработай исходный Markdown-файл.

Верни строго один JSON-объект без пояснений и без Markdown code fences:
{{
  "label": "короткая метка для имени файла, не более {FILENAME_LABEL_MAX_CHARS} символов, например статья_наука",
  "abstract": "содержательная аннотация {abstract_min}-{ABSTRACT_MAX_CHARS} знаков с пробелами",
  "executive": "структурированный Markdown-документ"
}}

Требования:
- Поле label должно описывать содержание, а не тип файла. Используй 1-2 слова: статья_наука, исслед, встреча, календарь, идея. Не используй abstract/executive.
- Поле abstract - это не телеграфная выжимка. Это глобальное содержательное summary, которое можно отправить коллегам в мессенджере, чтобы они поняли суть, контекст, ценность, неопределенности и возможное решение.
- Abstract не должен быть короче {abstract_min} знаков, если исходник содержательный. Исключение - только совсем короткий источник без достаточного материала.
- Поле executive - это документ для пользователя: помоги придать форму сырому потоку речи, сохрани нюансы и добавь аналитическую структуру.
- Executive должен включать выводы, рабочие определения, важные термины, открытые вопросы, рекомендации и календарные/задачные маркеры, если они релевантны источнику.
- Рабочие определения должны быть содержательными: объясняй, как термин работает в этом материале. Не давай тавтологии вида "календарные задачи - это задачи в календаре".
- Если термин плохо распознан, но важен, не игнорируй его: предложи вероятное восстановление и отметь уровень уверенности.
- Структура executive должна быть адаптивной. Не создавай пустые одинаковые разделы только ради шаблона.
- Не создавай раздел "Рабочие определения", если можешь написать только очевидные или круговые определения.
- Даже для короткой заметки не возвращай executive одним неструктурированным абзацем, если в ней есть несколько смысловых ходов.
- Не используй Markdown code fences внутри значений JSON.
- Не упрощай и не вымывай авторский смысл. Сохраняй важные формулировки, метафоры, причинно-следственные связи и интеллектуальные ходы.
- Можно добавлять аналитические связки, рабочие определения и рекомендации из общего знания, но явно помечай их как интерпретацию, гипотезу или рекомендацию; не выдавай их за факт исходника.
- Если данных для какого-то вывода не хватает, не молчи: сформулируй открытый вопрос или условие проверки.

Имя исходного файла: {source_name}

Исходный текст:
--- BEGIN SOURCE ---
{truncate_source(source_text)}
--- END SOURCE ---
"""


def build_revision_prompt(base_prompt: str, feedback: str) -> str:
    return f"""{base_prompt}

Критик отклонил предыдущую версию. Исправь результат с учетом замечаний:
{feedback}

Сделай новую версию богаче, точнее и полезнее. Не отвечай на критику отдельно; верни только исправленный JSON с label, abstract, executive.
"""


def heuristic_quality(source_text: str, result: dict) -> tuple[int, str]:
    score = 10
    issues: list[str] = []
    abstract = result["abstract"].strip()
    executive = result["executive"].strip()
    label = result["label"].strip()
    source_lower = source_text.casefold()

    abstract_min = abstract_min_chars_for(source_text)
    if len(abstract) < abstract_min:
        score = min(score, 6)
        issues.append(
            f"abstract слишком короткий ({len(abstract)} знаков); нужен содержательный текст ближе к {abstract_min}-{ABSTRACT_MAX_CHARS} знакам"
        )
    if len(abstract) > ABSTRACT_MAX_CHARS:
        score = min(score, 7)
        issues.append(f"abstract длиннее лимита {ABSTRACT_MAX_CHARS} знаков")
    if len(label) > FILENAME_LABEL_MAX_CHARS:
        score = min(score, 7)
        issues.append(f"label длиннее {FILENAME_LABEL_MAX_CHARS} символов")
    if len(executive) < (1200 if len(source_text) > 1800 else 650):
        score = min(score, 6)
        issues.append("executive слишком бедный и короткий; нужно больше структуры, выводов и сохраненных деталей")
    if not re.search(r"(?m)^#{2,3}\s+\S+", executive):
        score = min(score, 7)
        issues.append("executive должен иметь Markdown-разделы второго или третьего уровня")
    if re.search(r"\b(определ|термин|поняти|концепт)\w*", source_lower) and not re.search(
        r"\b(определ|термин|поняти|концепт)\w*", executive.casefold()
    ):
        score = min(score, 7)
        issues.append("в источнике есть признаки терминов/определений, но executive их не выделяет")
    if re.search(r"\b(дата|срок|дедлайн|календар|завтра|недел|месяц|пятниц|понедельник)\w*", source_lower) and not re.search(
        r"\b(дата|срок|дедлайн|календар|задач|следующ)\w*", executive.casefold()
    ):
        score = min(score, 7)
        issues.append("в источнике есть календарные или задачные маркеры, но executive их не извлекает")
    if re.search(r"\b(неясно|уточн|провер|вопрос|сомн|может быть|плохо распозн)\b", source_lower) and not re.search(
        r"\b(вопрос|уточн|провер|неопредел|сомн|вариант)\w*", executive.casefold()
    ):
        score = min(score, 7)
        issues.append("источник содержит неопределенность, но executive не формулирует открытые вопросы или варианты")

    if not issues:
        return score, "Автоматическая проверка не нашла грубых нарушений."
    return score, "; ".join(issues)


def evaluate_quality(model: str, source_name: str, source_text: str, result: dict) -> tuple[int, str]:
    heuristic_score, heuristic_feedback = heuristic_quality(source_text, result)
    prompt = f"""Оцени качество постобработки.

Имя источника: {source_name}

Исходный текст:
--- BEGIN SOURCE ---
{truncate_source(source_text)}
--- END SOURCE ---

Сгенерированный label:
{result["label"]}

Сгенерированный abstract:
--- BEGIN ABSTRACT ---
{result["abstract"]}
--- END ABSTRACT ---

Сгенерированный executive:
--- BEGIN EXECUTIVE ---
{result["executive"]}
--- END EXECUTIVE ---

Верни JSON с полями score и feedback. Feedback должен быть конкретным: что добавить, что восстановить, какие разделы усилить, какие вопросы поставить.
"""
    try:
        content = ollama_chat_content(
            model,
            CRITIC_SYSTEM_PROMPT,
            prompt,
            json_mode=True,
            num_ctx=OLLAMA_CRITIC_NUM_CTX,
            num_predict=OLLAMA_CRITIC_NUM_PREDICT,
        )
        model_score, model_feedback = parse_critic_response(content)
    except Exception as exc:
        log("WARN", f"critic failed; using heuristic quality only: {exc}")
        model_score = heuristic_score
        model_feedback = ""

    score = min(heuristic_score, model_score)
    feedback_parts = []
    if heuristic_feedback:
        feedback_parts.append(f"Автопроверка: {heuristic_feedback}")
    if model_feedback:
        feedback_parts.append(f"Критик: {model_feedback}")
    feedback = "\n".join(feedback_parts).strip() or "Усиль полноту, структуру и сохранение смысла."
    return score, feedback


def parse_critic_response(content: str) -> tuple[int, str]:
    try:
        critique = extract_json_object(content)
        score = int(critique.get("score", 0))
        feedback = str(critique.get("feedback", "")).strip()
    except Exception:
        score_match = re.search(r'"?score"?\s*[:=]\s*"?(\d{1,2})', content, flags=re.IGNORECASE)
        if not score_match:
            score_match = re.search(r"ОЦЕНКА\s*[:=]\s*(\d{1,2})", content, flags=re.IGNORECASE)
        if not score_match:
            raise
        score = int(score_match.group(1))
        feedback_match = re.search(r'"?feedback"?\s*[:=]\s*"?(.*)', content, flags=re.IGNORECASE | re.DOTALL)
        if not feedback_match:
            feedback_match = re.search(r"ЗАМЕЧАНИЯ\s*[:=]\s*(.*)", content, flags=re.IGNORECASE | re.DOTALL)
        feedback = feedback_match.group(1).strip().strip('"} \n\r\t') if feedback_match else ""

    score = max(0, min(10, score))
    return score, feedback or "Критик не дал подробных замечаний."


def generate_with_reflection(model: str, system_prompt: str, base_prompt: str, source_name: str, source_text: str, fallback: str) -> dict:
    attempts = max(1, REFLECTION_MAX_ATTEMPTS)
    feedback = ""
    last_result: dict | None = None
    last_score = 0

    for attempt in range(1, attempts + 1):
        prompt = build_revision_prompt(base_prompt, feedback) if feedback else base_prompt
        log("INFO", f"generation attempt {attempt}/{attempts} for {source_name}")
        result = ollama_chat(model, system_prompt, prompt, fallback)
        last_result = result

        if attempts == 1:
            result["_quality_score"] = None
            result["_quality_feedback"] = ""
            result["_attempts"] = attempt
            return result

        score, feedback = evaluate_quality(model, source_name, source_text, result)
        last_score = score
        log("INFO", f"quality score for {source_name}: {score}/10; feedback: {feedback[:500]}")
        if score >= QUALITY_THRESHOLD:
            result["_quality_score"] = score
            result["_quality_feedback"] = feedback
            result["_attempts"] = attempt
            return result

    if last_result is None:
        raise ValueError("reflection cycle produced no result")

    log(
        "WARN",
        f"quality threshold {QUALITY_THRESHOLD}/10 was not reached for {source_name}; "
        f"using last result with score {last_score}/10",
    )
    last_result["_quality_score"] = last_score
    last_result["_quality_feedback"] = feedback
    last_result["_attempts"] = attempts
    return last_result


def output_paths(path: Path, label: str) -> tuple[Path, Path]:
    base = f"{path.stem}_{label}"
    return path.with_name(f"{base}_abstract.md"), path.with_name(f"{base}_executive.md")


def existing_output_pair(path: Path) -> tuple[Path, Path] | None:
    prefix = f"{path.stem}_"
    pairs: list[tuple[Path, Path]] = []
    for abstract_path in path.parent.glob(f"{path.stem}*_abstract.md"):
        if not abstract_path.name.startswith(prefix):
            continue
        executive_name = abstract_path.name[: -len("_abstract.md")] + "_executive.md"
        executive_path = abstract_path.with_name(executive_name)
        if executive_path.exists():
            pairs.append((abstract_path, executive_path))
    if not pairs:
        return None
    return max(pairs, key=lambda pair: min(pair[0].stat().st_mtime, pair[1].stat().st_mtime))


def should_skip(path: Path, existing_pair: tuple[Path, Path] | None, force: bool) -> bool:
    if force:
        return False
    if existing_pair is None:
        return False
    abstract_path, executive_path = existing_pair
    source_mtime = path.stat().st_mtime
    return abstract_path.stat().st_mtime >= source_mtime and executive_path.stat().st_mtime >= source_mtime


def write_atomic(path: Path, content: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def process_file(path: Path, force: bool = False) -> bool:
    path = path.resolve()

    if is_ignored_file(path):
        return False
    if not path.exists() or not path.is_file():
        return False
    if not wait_until_stable(path):
        log("WARN", f"file is not stable yet, skipped: {path}")
        return False

    existing_pair = existing_output_pair(path)

    if should_skip(path, existing_pair, force):
        existing_names = ", ".join(item.name for item in existing_pair) if existing_pair else ""
        log("INFO", f"already processed, skipped: {path} -> {existing_names}")
        return False

    log("INFO", f"processing started: {path}")
    source_text = path.read_text(encoding="utf-8", errors="replace")
    skill_name = find_skill(source_text)
    selected_model, model_selector = resolve_model(source_text)
    effective_skill, system_prompt = load_skill(skill_name)
    transcript_body = strip_control_directives(extract_transcript_body(source_text))
    if (
        OLLAMA_FALLBACK_MODEL
        and selected_model != OLLAMA_MODEL
        and HEAVY_MODEL_MAX_INPUT_CHARS > 0
        and len(transcript_body) > HEAVY_MODEL_MAX_INPUT_CHARS
    ):
        log(
            "WARN",
            f"selected model {selected_model} skipped for long input ({len(transcript_body)} chars); "
            f"using fallback {OLLAMA_FALLBACK_MODEL}",
        )
        selected_model = OLLAMA_FALLBACK_MODEL
        model_selector = f"{model_selector}->fallback-long-input"

    user_prompt = build_user_prompt(path.name, transcript_body)
    label_fallback = fallback_label(effective_skill, transcript_body)

    log("INFO", f"using skill={effective_skill} model={selected_model} selector={model_selector}")
    try:
        result = generate_with_reflection(
            selected_model, system_prompt, user_prompt, path.name, transcript_body, label_fallback
        )
    except Exception as exc:
        if not OLLAMA_FALLBACK_MODEL or selected_model == OLLAMA_FALLBACK_MODEL:
            raise
        log("ERROR", f"model {selected_model} failed for {path}: {exc}; retrying with fallback {OLLAMA_FALLBACK_MODEL}")
        selected_model = OLLAMA_FALLBACK_MODEL
        model_selector = f"{model_selector}->fallback-error"
        result = generate_with_reflection(
            selected_model, system_prompt, user_prompt, path.name, transcript_body, label_fallback
        )

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    abstract_path, executive_path = output_paths(path, result["label"])
    quality_score = result.get("_quality_score")
    quality_line = f"- Оценка качества: `{quality_score}/10`\n" if quality_score is not None else ""
    attempts_line = f"- Попыток генерации: `{result.get('_attempts', 1)}`\n"
    abstract_doc = (
        f"# Аннотация: {path.stem} / {result['label']}\n\n"
        f"- Исходник: `{path.name}`\n"
        f"- Метка: `{result['label']}`\n"
        f"- Скилл: `{effective_skill}`\n"
        f"- Модель: `{selected_model}`\n"
        f"{quality_line}"
        f"{attempts_line}"
        f"- Создано: `{created_at}`\n\n"
        f"{result['abstract'].strip()}\n"
    )
    executive_doc = (
        f"# Executive summary: {path.stem} / {result['label']}\n\n"
        f"- Исходник: `{path.name}`\n"
        f"- Метка: `{result['label']}`\n"
        f"- Скилл: `{effective_skill}`\n"
        f"- Модель: `{selected_model}`\n"
        f"{quality_line}"
        f"{attempts_line}"
        f"- Создано: `{created_at}`\n\n"
        f"{result['executive'].strip()}\n"
    )

    write_atomic(abstract_path, abstract_doc)
    write_atomic(executive_path, executive_doc)
    log("INFO", f"processing done: {path} -> {abstract_path.name}, {executive_path.name}")
    return True


def iter_markdown_files(dirs: Iterable[Path]) -> Iterable[Path]:
    for directory in dirs:
        if not directory.exists():
            log("WARN", f"watch directory does not exist: {directory}")
            continue
        for path in sorted(directory.glob("*.md")):
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-process Obsidian Markdown files with Ollama.")
    parser.add_argument("paths", nargs="*", help="Markdown files to process.")
    parser.add_argument("--scan", action="store_true", help="Scan configured WATCH_DIRS.")
    parser.add_argument("--force", action="store_true", help="Recreate outputs even when they are newer than source.")
    args = parser.parse_args()

    try:
        if args.scan:
            paths = list(iter_markdown_files(watch_dirs()))
        else:
            paths = [Path(value) for value in args.paths]

        if not paths:
            log("INFO", "nothing to process")
            return 0

        failures = 0
        for path in paths:
            try:
                process_file(path, force=args.force)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                failures += 1
                log("ERROR", f"Ollama request failed for {path}: {exc}")
            except Exception as exc:
                failures += 1
                log("ERROR", f"processing failed for {path}: {exc}")

        return 1 if failures else 0
    except Exception as exc:
        log("ERROR", f"fatal processor error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
