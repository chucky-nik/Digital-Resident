# Цифровой Ординатор

Прототип **Agentic/RAG** СППР и симулятора пациента по КР
**«Артериальная гипертензия у взрослых» 2024** (РКО / Минздрав РФ, ID 62_3).

> Не является медицинской рекомендацией. Пациенты и сценарии — синтетические.

## Почему такой пайплайн (RAG + цепочки промптов / tools)

Медицинская СППР не должна «вспоминать» протокол из весов модели: нужна **трассируемая** опора на утверждённый документ. Поэтому:

1. **Hybrid RAG** по одному реальному КР (PDF → чанки с `section`/`page` → Chroma + keyword + must-include curated chunks). План и replan ссылаются только на `[1]…[N]` из текущего контекста; `citations.py` валидирует ссылки.
2. **LangGraph-цепочка** `rag → plan → simulate → replan → audit`, а не один «всё-в-одном» промпт:
   - `plan` — протокол под пациента;
   - `simulate` — детерминированные контрольные точки **каждый день** госпитализации (0…N);
   - `replan` — при флаге отклонения (напр. гиперкалиемия) пересчёт тактики снова через RAG;
   - `audit` — LLM-аудитор + **rule-based tools** (`safety.py`: drug–drug, согласие, СКФ/K+).
3. Разделение **скрипт / LLM** снижает галлюцинации на критичных правилах (иАПФ при ангиоотёке, двойная блокада РААС и т.п.), а LLM остаётся для клинического текста и поиска дефектов.

Стек: Python 3.12, LangGraph, Chroma, Streamlit; LLM Neural Deep (`qwen3.8-27b-noreason`) + embeddings `bge-m3`, fallback llm7.

## Локальный запуск (подробно)

### Требования

- **macOS / Linux** (на Windows — через WSL или Git Bash)
- **Python 3.12** (`python3.12 --version`)
- API-ключ **Neural Deep** (для живого СППР и сборки эмбеддингов). Без ключа можно смотреть UI и сохранённые `data/result_*.json` / ноутбук.

### 1. Клонировать / открыть проект

```bash
cd "/path/to/Тестовый задание на ИИ-медицинский ассистент врача"
```

### 2. Виртуальное окружение и зависимости

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
```

Проверка: `python -c "import streamlit, langgraph, chromadb; print('ok')"`.

### 3. Переменные окружения (`.env`)

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

| Переменная | Обязательно | Назначение |
|---|---|---|
| `NEURAL_DEEP_API_KEY` | да (для LLM) | Ключ Neural Deep |
| `NEURAL_DEEP_BASE_URL` | нет | по умолчанию `https://api.neuraldeep.tech/v1` |
| `NEURAL_DEEP_MODEL` | нет | `qwen3.8-27b-noreason` |
| `EMBEDDING_MODEL` | нет | `bge-m3` |
| `LLM7_API_KEY` | нет | запасной провайдер, если Neural Deep недоступен |

Файл `.env` в git **не** коммитится.

### 4. PYTHONPATH

Код пакета лежит в `src/`. В **каждой** новой сессии терминала:

```bash
export PYTHONPATH=src
# Windows (cmd): set PYTHONPATH=src
```

Либо всегда запускайте так: `PYTHONPATH=src python ...` / `PYTHONPATH=src streamlit ...`.

### 5. Собрать RAG-индекс (один раз)

Нужен API-ключ (эмбеддинги `bge-m3`). Чанки уже есть в `data/guidelines/chunks.json`; индекс пишется в `data/chroma/` (локально, не в git).

```bash
source .venv/bin/activate
export PYTHONPATH=src
python scripts/build_rag.py --force
```

Без `--force` пересборка пропускается, если коллекция Chroma уже не пустая.

### 6. Прогнать кейс из CLI (проверка пайплайна)

```bash
python scripts/run_case.py --case baseline      # типичное течение
python scripts/run_case.py --case comorbid      # ХБП + противопоказание + согласие
python scripts/run_case.py --case complication  # гиперкалиемия день 3 → replan
```

Результаты: `data/result_<case>.json` (план, траектория, аудитор, RAG-хиты).

### 7. Запустить Streamlit UI

```bash
source .venv/bin/activate
export PYTHONPATH=src
streamlit run app/streamlit_app.py --server.port 8501
```

Откройте в браузере: **http://127.0.0.1:8501**

В UI:

- вкладка **Когорта** — поиск / выпадающий список пациентов, запуск СППР в фоне, история стационара;
- вкладка **Кейсы задания** — 3 кейса ТЗ, кнопка «Запустить в фоне»;
- сайдбар — статус фонового расчёта СППР.

Остановка: `Ctrl+C` в терминале.

### 8. Ноутбук без API (опционально)

```bash
pip install jupyter   # если ещё нет
jupyter notebook notebooks/demo.ipynb
```

Ячейки читают уже сохранённые `data/result_*.json` — API не нужен.

### Типичные проблемы

| Симптом | Что сделать |
|---|---|
| `ModuleNotFoundError: digital_resident` | Забыли `export PYTHONPATH=src` |
| Ошибка API / 401 | Проверьте `NEURAL_DEEP_API_KEY` в `.env` |
| Пустой RAG / мало хитов | `python scripts/build_rag.py --force` |
| Порт 8501 занят | `--server.port 8502` или завершите старый Streamlit |
| Streamlit «старый» код | Обновите страницу (R) или перезапустите процесс |

### Минимальная последовательность «с нуля»

```bash
cd <корень_проекта>
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # → вписать NEURAL_DEEP_API_KEY
export PYTHONPATH=src
python scripts/build_rag.py --force
streamlit run app/streamlit_app.py --server.port 8501
```

## Пример ошибки, пойманной AI-аудитором

**Кейс `comorbid`** (ХБП С3б, ангиоотёк на эналаприл в анамнезе, согласие на инвазивные процедуры не получено):

| Finding | Суть |
|---|---|
| `PROC_CONSENT` (high) | Процедурное упущение: нет информированного согласия до инвазивных вмешательств |
| `ACEI_ANGIOEDEMA` (high) | Клинический дефект: назначение иАПФ при анамнезе ангиоотёка — нужна замена на БРА |
| `PROC_GFR_K_MONITOR` | Нет явного плана контроля рСКФ/K+ при иРААС у пациента с ХБП |

В UI / JSON: вкладка **Аудитор**, поле `audit.caught_example`.  
Дополнительно кейс **`complication`**: день 3, K+=5.7 → автоматический `revised_plan` (stop/reduce иРААС) со ссылками на КР.

## Структура репозитория

```
app/streamlit_app.py       # UI
notebooks/demo.ipynb       # демо с выводом
scripts/build_rag.py | run_case.py
src/digital_resident/      # rag, agents/graph, safety, simulation, citations
data/guidelines/           # PDF КР + chunks.json
data/result_*.json         # сохранённые прогоны
```

Учебный прототип. КР — правообладатели Минздрав РФ / РКО.
