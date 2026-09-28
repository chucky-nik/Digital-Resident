# Цифровой Ординатор

Прототип **Agentic/RAG** СППР и симулятора пациента по КР
**«Артериальная гипертензия у взрослых» 2024** (РКО / Минздрав РФ, ID 62_3).

> Не является медицинской рекомендацией. Пациенты и сценарии — синтетические.

## Почему такой пайплайн (RAG + цепочки промптов / tools)

Медицинская СППР не должна «вспоминать» протокол из весов модели: нужна **трассируемая** опора на утверждённый документ. Поэтому:

1. **Hybrid RAG** по одному реальному КР (PDF → чанки с `section`/`page` → Chroma + keyword + must-include curated chunks). План и replan ссылаются только на `[1]…[N]` из текущего контекста; `citations.py` валидирует ссылки.
2. **LangGraph-цепочка** `rag → plan → simulate → replan → audit`, а не один «всё-в-одном» промпт:
   - `plan` — протокол под пациента;
   - `simulate` — детерминированные контрольные точки **каждый день** госпитализации (1…N);
   - `replan` — при флаге отклонения (напр. гиперкалиемия) пересчёт тактики снова через RAG;
   - `audit` — LLM-аудитор + **rule-based tools** (`safety.py`: drug–drug, согласие, СКФ/K+).
3. Разделение **скрипт / LLM** снижает галлюцинации на критичных правилах (иАПФ при ангиоотёке, двойная блокада РААС и т.п.), а LLM остаётся для клинического текста и поиска дефектов.
4. **Формуляр доз** (`dosing.py`): числовые мг, диапазоны, запрет «начальная доза»; при K+≥5.5 — жёсткий `action=stop` иРААС (не «отмена или снижение»).
5. **Симуляция чувствительна к терапии**: тяжёлая hyperK на день 3 — только при активном иРААС; при ХБП K+ растёт быстрее на иРААС.

Стек: Python 3.12, LangGraph, Chroma, Streamlit; LLM Neural Deep (`qwen3.8-27b-noreason`) + embeddings `bge-m3`, fallback llm7.

## Локальный запуск (подробно)

### Требования

- **macOS / Linux / Windows** (на Windows удобнее WSL или Git Bash; в cmd/PowerShell команды ниже те же, с заменой `source` → `.venv\Scripts\activate` и `export` → `set`)
- **Python 3.12** (`python3.12 --version`; в `pyproject.toml` указано ≥3.11)
- API-ключ **Neural Deep** (для **живого** СППР и векторного RAG). Без ключа:
когорта / история стационара / ноутбук / **сохранённые** `data/result_*.json` и keyword-RAG по `chunks.json` работают; кнопка «Запустить в фоне» недоступна.

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

#### Как проверяющему протестировать (без «зашитых» ключей)

**Не кладите реальные ключи в репозиторий** — их сразу вытащат боты, ключ отзовут, счёт могут выставить вам.

| Что нужно проверить | Как без своего ключа | Как с ключом |
|---|---|---|
| UI, когорта, стационар | `streamlit run …` — ключ не нужен | то же |
| 3 кейса ТЗ (план, динамика, аудитор, RAG-хиты) | вкладка **Кейсы** → **Показать сохранённый результат** (`data/result_*.json`) или `notebooks/demo.ipynb` | **Запустить в фоне** — живой прогон |
| Keyword-RAG по КР | есть `data/guidelines/chunks.json` — поиск без embeddings | hybrid vector+keyword после `build_rag.py` |
| Живой LLM plan/replan/audit | нужен ключ | `NEURAL_DEEP_API_KEY` в локальном `.env` |

Практичный вариант для сдачи: в письме/чате проверяющему **один раз** передать временный ключ (или доступ к Neural Deep), а в репозитории оставить только `.env.example`. Либо проверяющий смотрит сохранённые прогоны + UI — этого достаточно, чтобы увидеть качество пайплайна.

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

- эмблема **МЗ** (слева вверху) — возврат на начальный вид когорты;
- **＋ Новый пациент** — карточка с плейсхолдерами и генерацией стационарной истории;
- вкладка **Когорта** — поиск / выбор пациента, карточка, заметки, запуск СППР в фоне;
  - **история стационара**: дни **1…N** (N = длительность), таблица АД/ЧСС/вес/лаб/осмотр/заметки;
  - ручная запись дня: поле «День» с **±**, текст осмотра → при **＋** добавляется новая строка без сброса прежних правок; **Сохранить историю** пишет таблицу как есть;
- вкладка **Кейсы задания** — 3 кейса ТЗ, кнопка «Запустить в фоне»;
- сайдбар — статус фонового расчёта СППР.

Остановка: `Ctrl+C` в терминале.

### 8. Проверки (опционально)

```bash
# офлайн: ward 1…N, notes, safety, simulation, citations, импорты (без LLM)
python scripts/test_regression.py

# клиническое качество: формуляр доз, hard-stop hyperK, golden-классы
python scripts/test_clinical_quality.py

# живой стресс: 3 кейса × несколько прогонов → data/stress_report.json
python scripts/stress_cases.py
```

### 9. Ноутбук без API (опционально)

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
| «＋» в истории не добавляет день | Обновите страницу после обновления кода; текст осмотра берётся из поля под таблицей |

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
app/streamlit_app.py          # UI (когорта, кейсы, редактор стационара)
notebooks/demo.ipynb          # демо без API
scripts/
  build_rag.py | run_case.py
  test_regression.py          # офлайн-регрессия
  test_clinical_quality.py    # формуляр доз / hyperK / golden
  stress_cases.py             # живой стресс 3 кейсов
src/digital_resident/
  agents/graph.py             # LangGraph: rag→plan→simulate→replan→audit
  dosing.py                   # формуляр мг + hard-stop hyperK
  rag/ | safety.py | simulation.py | citations.py | patients.py | cases.py | jobs.py
data/
  guidelines/                 # PDF КР, txt, chunks.json
  patients/                   # когорта + карточки SYN-AG-*
  result_*.json               # сохранённые прогоны кейсов
  jobs/ | patient_runs/       # фоновые задания UI
```

Учебный прототип. КР — правообладатели Минздрав РФ / РКО.
