from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from digital_resident.agents import run_case, run_patient
from digital_resident.cases import get_case, list_cases
from digital_resident.config import has_llm_api_key
from digital_resident.jobs import (
    latest_active_job,
    load_job_result,
    read_job,
    start_job,
)
from digital_resident.patients import (
    build_ward_history,
    delete_patient,
    format_note_day_label,
    format_sex_ru,
    get_patient,
    is_case_record,
    list_patients,
    load_cohort,
    normalize_ward_entry,
    parse_list_field,
    rows_to_ward_history,
    scenario_label,
    seed_cohort,
    upsert_patient,
    ward_history_to_rows,
)
from digital_resident.patients import _note_sort_key
from digital_resident.rag import GuidelineRAG

st.set_page_config(
    page_title="Цифровой Ординатор | СППР",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded",
)

MZ_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');
:root {
  --mz-blue:#2F65A3; --mz-blue-action:#4E80B4; --mz-blue-dark:#1E4A7A;
  --mz-red:#C93B4E; --mz-bg:#F2F2F2; --mz-white:#fff; --mz-text:#1A1A1A;
  --mz-muted:#6B7280; --mz-border:#D7DEE8; --mz-ok:#2E7D4F; --mz-warn:#B78103;
}
html, body, [class*="css"] { font-family:"Source Sans 3", Arial, Helvetica, sans-serif !important; color:var(--mz-text); }
.stApp { background: var(--mz-bg); }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
/* только Deploy — не трогаем кнопку раскрытия сайдбара */
.stDeployButton,
[data-testid="stAppDeployButton"] {
  display: none !important;
}
/* кнопка раскрытия свёрнутого сайдбара всегда видна */
[data-testid="stSidebarCollapsedControl"],
button[kind="headerNoPadding"],
[data-testid="stExpandSidebarButton"] {
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  z-index: 999999 !important;
}
/* свёрнутый сайдбар: только кнопка >>, без вертикального текста */
section[data-testid="stSidebar"][aria-expanded="false"] {
  width: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
  overflow: hidden !important;
  border: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
section[data-testid="stSidebar"][aria-expanded="false"] > div {
  display: none !important;
}
.mz-topbar { background:var(--mz-blue); color:#fff; margin:-1rem -1rem 1.1rem -1rem; padding:.85rem 1.4rem;
  display:flex; justify-content:space-between; align-items:center; border-bottom:3px solid var(--mz-red); }
.mz-topbar h1 { margin:0; font-size:1.1rem; text-transform:uppercase; }
.mz-topbar .sub { margin:0; font-size:.78rem; opacity:.9; }
.mz-emblem { width:42px; height:42px; border:2px solid rgba(255,255,255,.7); border-radius:50%;
  display:grid; place-items:center; font-weight:700; margin-right:.8rem;
  color:#fff !important; text-decoration:none !important; cursor:pointer;
  transition: background .15s ease, border-color .15s ease; }
a.mz-emblem:hover { border-color:#fff; background:rgba(255,255,255,.14); color:#fff !important; }
.mz-brand { display:flex; align-items:center; }
.mz-panel { background:#fff; border:1px solid var(--mz-border); padding:1rem 1.1rem; margin-bottom:1rem; border-radius:0; }
.mz-panel h3 { margin:0 0 .7rem; font-size:1rem; color:var(--mz-blue-dark); border-bottom:2px solid var(--mz-blue);
  padding-bottom:.35rem; text-transform:uppercase; letter-spacing:.03em; }
.mz-h4 {
  margin: 0.8rem 0 0.35rem;
  color: #1E4A7A;
  font-size: 1rem;
  font-weight: 700;
}
.mz-kv { display:grid; grid-template-columns:150px 1fr; gap:.3rem .7rem; font-size:.9rem; }
.mz-kv .k { color:var(--mz-muted); } .mz-kv .v { font-weight:600; }
.mz-badge { display:inline-block; padding:.12rem .45rem; font-size:.7rem; font-weight:700; text-transform:uppercase; color:#fff; background:var(--mz-blue-action); margin-right:.3rem; }
.mz-badge.high { background:var(--mz-red);} .mz-badge.medium{background:var(--mz-warn);} .mz-badge.ok{background:var(--mz-ok);}
.mz-finding { border-left:4px solid var(--mz-blue); background:#F7FAFC; padding:.65rem .8rem; margin-bottom:.5rem; }
.mz-finding.high { border-left-color:var(--mz-red);} .mz-finding.medium{border-left-color:var(--mz-warn);}
.mz-day, .mz-cite { border:1px solid var(--mz-border); padding:.6rem .75rem; margin-bottom:.45rem; background:#fff; }
.mz-banner { background:linear-gradient(90deg,var(--mz-blue),var(--mz-blue-action)); color:#fff; padding:.85rem 1rem;
  margin-bottom:1rem; border-radius:999px; display:flex; gap:.7rem; align-items:center; }
.mz-banner .bar { width:4px; align-self:stretch; background:#E67E22; }
.mz-banner strong { display:block; margin-bottom:.15rem; }
.mz-banner span { display:block; opacity:.92; font-size:.9rem; }
.mz-note { border-left:3px solid var(--mz-blue-action); padding:.35rem .6rem; margin:.25rem 0; background:#F8FBFF; font-size:.88rem; }
.mz-note .mz-day-tag {
  display:inline-block; min-width:7.5rem; margin-right:.35rem;
  font-weight:700; color:var(--mz-blue-dark); white-space:nowrap;
}
.mz-note .mz-day-num {
  display:inline-block; min-width:2.2rem; text-align:center;
  margin-right:.5rem; padding:.05rem .35rem;
  border:1px solid var(--mz-border); border-radius:3px;
  background:#fff; color:var(--mz-blue-dark);
  font-size:.8rem; font-weight:700;
}
.mz-footer { margin-top:1.2rem; padding-top:.7rem; border-top:1px solid var(--mz-border); color:var(--mz-muted); font-size:.76rem; }
section[data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--mz-border); }
div.stButton > button { border-radius:0 !important; font-weight:700 !important; text-transform:uppercase !important; }
div.stButton > button[kind="primary"] { background:var(--mz-blue-action) !important; color:#fff !important; }
.stTabs [aria-selected="true"] { color:var(--mz-blue-dark) !important; border-bottom:3px solid var(--mz-blue) !important; }

/* убрать «Press Enter to submit form» у полей в формах */
div[data-testid="InputInstructions"],
[data-testid="stForm"] div[data-testid="InputInstructions"],
.stTextInput div[data-testid="InputInstructions"],
.stNumberInput div[data-testid="InputInstructions"],
.stTextArea div[data-testid="InputInstructions"] {
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
  overflow: hidden !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

/* убрать иконку «ссылка на заголовок» у h1–h6 */
div[data-testid="stMarkdownContainer"] a[href^="#"] { display: none !important; }
h1 a, h2 a, h3 a, h4 a, h5 a, h6 a,
[data-testid="stHeaderActionElements"],
div[data-testid="stHeadingWithActionElements"] a {
  display: none !important;
  visibility: hidden !important;
}

/* Чёткие рамки у полей ввода */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stDateInput"] input,
div[data-testid="stTimeInput"] input {
  border: 2px solid var(--mz-blue) !important;
  border-radius: 4px !important;
  background: #fff !important;
  box-shadow: none !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
  border-color: var(--mz-blue-dark) !important;
  box-shadow: 0 0 0 2px rgba(47,101,163,0.22) !important;
  outline: none !important;
}
/* select / combobox — явная рамка (как у полей ввода) */
div[data-testid="stSelectbox"],
div[data-testid="stMultiSelect"] {
  border: 2px solid var(--mz-blue) !important;
  border-radius: 4px !important;
  background: #fff !important;
  padding: 0 !important;
  overflow: hidden;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
  border: none !important;
  border-radius: 0 !important;
  background: #fff !important;
  box-shadow: none !important;
  min-height: 2.4rem;
}
div[data-testid="stSelectbox"]:focus-within,
div[data-testid="stMultiSelect"]:focus-within {
  border-color: var(--mz-blue-dark) !important;
  box-shadow: 0 0 0 2px rgba(47,101,163,0.22) !important;
}
/* number input: без кнопок ± — только ручной ввод */
div[data-testid="stNumberInput"] button {
  display: none !important;
}
div[data-testid="stNumberInput"] > div {
  border: none !important;
}
/* список пациентов */
.mz-plist-item {
  border: 1px solid var(--mz-border);
  border-left: 3px solid var(--mz-blue);
  padding: 0.45rem 0.65rem;
  margin-bottom: 0.35rem;
  background: #fff;
  font-size: 0.9rem;
}
.mz-plist-item.active {
  background: #E8F1FB;
  border-left-color: var(--mz-red);
}
</style>
"""


def inject() -> None:
    st.markdown(MZ_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="mz-topbar"><div class="mz-brand">
        <a class="mz-emblem" href="?home=1" title="На начальную страницу">МЗ</a>
        <div><h1>Цифровой Ординатор</h1>
        <p class="sub">СППР · когорта · форма нового пациента · КР АГ 2024</p></div></div>
        <div style="text-align:right;font-size:.75rem;opacity:.92">Тестовый стенд<br/>синтетические данные</div></div>
        """,
        unsafe_allow_html=True,
    )


def go_home_if_requested() -> None:
    """Клик по «МЗ» → сброс к начальному виду когорты."""
    try:
        home = st.query_params.get("home")
    except Exception:
        home = None
    if home != "1":
        return
    st.session_state.pop("selected_patient_id", None)
    st.session_state.pop("focus_patient_id", None)
    st.session_state["results"] = {}
    st.session_state["active_main_tab"] = "cohort"
    # сбросить поиск/выбор в виджетах когорты
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and (
            k.startswith("search_cohort")
            or k.startswith("cohort_patient_select")
            or k.startswith("search_")
        ):
            st.session_state.pop(k, None)
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()


def init_state() -> None:
    defaults = {
        "results": {},  # scope -> result
        "active_job_id": None,
        "consumed_job_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def store_result(scope: str, result: dict) -> None:
    st.session_state["results"][scope] = result


def get_result(scope: str) -> dict | None:
    return st.session_state.get("results", {}).get(scope)


def any_job_running() -> bool:
    jid = st.session_state.get("active_job_id")
    if not jid:
        return False
    job = read_job(jid)
    return bool(job and job.get("status") == "running")


def ensure_rag() -> None:
    rag = GuidelineRAG()
    if rag.count == 0 and not rag._all_chunks():
        rag.build()


def launch_patient_job(scope: str, label: str, patient: dict) -> None:
    if any_job_running():
        st.warning("Уже выполняется расчёт СППР. Дождитесь завершения.")
        return
    if not has_llm_api_key():
        st.error(
            "Нет API-ключа в `.env`. Живой СППР недоступен — откройте вкладку "
            "«Кейсы задания» → «Показать сохранённый результат» или положите ключ в `.env`."
        )
        return

    patient_copy = dict(patient)

    def _target():
        ensure_rag()
        return run_patient(patient_copy)

    job_id = start_job(kind=scope, label=label, target=_target)
    st.session_state["active_job_id"] = job_id
    st.session_state["consumed_job_id"] = None
    st.toast(f"Запущен расчёт: {label}", icon="⏳")


def launch_case_job(scope: str, case_id: str, label: str) -> None:
    if any_job_running():
        st.warning("Уже выполняется расчёт СППР. Дождитесь завершения.")
        return
    if not has_llm_api_key():
        st.error(
            "Нет API-ключа. Используйте кнопку «Показать сохранённый результат» "
            "или задайте `NEURAL_DEEP_API_KEY` в `.env`."
        )
        return

    def _target():
        ensure_rag()
        result = run_case(case_id)
        path = ROOT / "data" / f"result_{case_id}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    job_id = start_job(kind=scope, label=label, target=_target)
    st.session_state["active_job_id"] = job_id
    st.session_state["consumed_job_id"] = None
    st.toast(f"Запущен расчёт: {label}", icon="⏳")


def load_cached_case_result(case_id: str) -> dict | None:
    path = ROOT / "data" / f"result_{case_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.fragment(run_every=2)
def job_status_panel() -> None:
    jid = st.session_state.get("active_job_id")
    job = read_job(jid) if jid else None
    # If session lost the id but a job is still running, recover it.
    if not job:
        cand = latest_active_job()
        if cand and cand.get("status") == "running":
            job = cand
            st.session_state["active_job_id"] = cand["id"]
    if not job:
        st.caption("Нет активных расчётов СППР.")
        return

    status = job.get("status")
    label = job.get("label", "задача")
    if status == "running":
        st.info(f"⏳ СППР: **{label}**\n\nФормы и поиск доступны.")
        st.progress(0.55, text="RAG → план → симуляция → аудит…")
        return

    if status == "done":
        if st.session_state.get("consumed_job_id") != job["id"]:
            result = load_job_result(job)
            if result:
                store_result(job.get("kind") or "cohort", result)
                st.session_state["consumed_job_id"] = job["id"]
                st.session_state["active_job_id"] = None
                st.rerun()
            else:
                st.session_state["active_job_id"] = None
        else:
            st.session_state["active_job_id"] = None
            st.caption("Нет активных расчётов СППР.")
        return

    if status == "error":
        st.error(f"Ошибка: {label}")
        st.code((job.get("error") or "")[:2000])
        if st.button("Сбросить статус", key="btn_clear_job_err"):
            st.session_state["active_job_id"] = None
            st.session_state["consumed_job_id"] = job["id"]
            st.rerun()


def patient_search_query(key: str, *, label: str = "🔍 Поиск") -> str:
    return st.text_input(
        label,
        placeholder="ФИО, ID, диагноз, коморбидность…",
        key=key,
        label_visibility="collapsed",
    ).strip()


def filter_cohort(query: str) -> list[dict]:
    cohort = [p for p in load_cohort() if not is_case_record(p)]
    if not query:
        return cohort
    q = query.lower()
    out = []
    for p in cohort:
        blob = " ".join(
            [
                p.get("synthetic_id", ""),
                p.get("full_name", ""),
                p.get("diagnosis", ""),
                p.get("icd10", ""),
                " ".join(p.get("comorbidities") or []),
                " ".join(p.get("allergies") or []),
                " ".join(p.get("current_meds") or []),
                p.get("notes") or "",
                p.get("scenario") or "",
            ]
        ).lower()
        if q in blob:
            out.append(p)
    return out


def render_patient_chooser(
    *,
    key_prefix: str,
    selected_id: str | None = None,
    show_heading: bool = True,
) -> str | None:
    """Поиск и выбор пациента в одном блоке."""
    if show_heading:
        st.markdown("##### Пациент")
    chosen: str | None = None
    box = st.container(border=True)
    with box:
        c_search, c_pick = st.columns([1.1, 1.6], gap="medium")
        with c_search:
            st.caption("Поиск")
            q = patient_search_query(f"search_{key_prefix}")
        patients = filter_cohort(q)
        with c_pick:
            st.caption("Выбор из списка")
            if not patients:
                st.warning("Никого не найдено")
            else:
                ids = [p["synthetic_id"] for p in patients]
                by_id = {p["synthetic_id"]: p for p in patients}
                widget_key = f"{key_prefix}_patient_select"
                if selected_id not in by_id:
                    selected_id = ids[0]
                if st.session_state.get(widget_key) not in by_id:
                    st.session_state[widget_key] = selected_id

                def _label(pid: str) -> str:
                    p = by_id[pid]
                    dx = str(p.get("diagnosis") or "")[:48]
                    name = p.get("full_name") or pid
                    return f"{name} · {dx}" if dx else str(name)

                chosen = st.selectbox(
                    "Пациент",
                    options=ids,
                    index=ids.index(selected_id),
                    format_func=_label,
                    key=widget_key,
                    label_visibility="collapsed",
                )
        total = len([p for p in load_cohort() if not is_case_record(p)])
        st.caption(
            f"{len(patients)} из {total}"
            + (f" · фильтр «{q}»" if q else "")
        )
    return chosen


def render_patient_card(p: dict, *, key_prefix: str = "card") -> None:
    labs = p.get("labs_day0") or {}
    hist = p.get("ward_history") or []
    stay = int(p.get("ward_stay_days") or (hist[-1].get("day") if hist else 14) or 14)
    notes = [
        n
        for n in (p.get("health_notes") or [])
        if isinstance(n, dict) and str(n.get("text") or "").strip()
    ]
    # сверху вниз: day1 → dayN (день = номер строки таблицы)
    notes = sorted(notes, key=lambda n: _note_sort_key(str(n.get("date") or "")))
    note_blocks: list[str] = []
    for n in notes:
        date_raw = str(n.get("date") or "")
        label = format_note_day_label(date_raw, stay_days=stay)
        note_blocks.append(
            f'<div class="mz-note">'
            f'<span class="mz-day-tag">{html.escape(label)}</span> — '
            f'{html.escape(str(n.get("text") or ""))}</div>'
        )
    notes_html = "".join(note_blocks) or '<div class="mz-note">Нет заметок</div>'
    exams = p.get("examinations") or []
    exams_html = "".join(
        f"<li><b>{html.escape(str(e.get('name')))}</b> ({html.escape(str(e.get('date','')))}): "
        f"{html.escape(str(e.get('result')))}</li>"
        for e in exams
        if isinstance(e, dict)
    )
    consent = "получено" if p.get("consent_invasive", True) else "НЕ получено"
    ccls = "ok" if p.get("consent_invasive", True) else "high"
    n_notes = len(notes)
    st.markdown(
        f"""
        <div class="mz-panel"><h3>Пациент {html.escape(str(p.get('full_name')))}</h3>
        <div class="mz-kv">
          <div class="k">Возраст/пол</div><div class="v">{p.get('age')} / {html.escape(format_sex_ru(p.get('sex')))}</div>
          <div class="k">Диагноз</div><div class="v">{html.escape(str(p.get('diagnosis') or ''))}</div>
          <div class="k">АД / ЧСС</div><div class="v">{p.get('bp_office')} · {p.get('hr')} уд/мин</div>
          <div class="k">рСКФ / K+</div><div class="v">{labs.get('egfr')} · {labs.get('k_mmol_l')}</div>
          <div class="k">Аллергии</div><div class="v">{html.escape(', '.join(p.get('allergies') or []) or 'нет')}</div>
          <div class="k">Коморбидность</div><div class="v">{html.escape(', '.join(p.get('comorbidities') or []) or 'нет')}</div>
          <div class="k">Сценарий</div><div class="v">{html.escape(scenario_label(p.get('scenario')))}</div>
          <div class="k">Согласие</div><div class="v"><span class="mz-badge {ccls}">{consent}</span></div>
          <div class="k">Стационар</div><div class="v">{stay} сут · {len(hist)} точек осмотра</div>
        </div>
        <div class="mz-h4">Обследования</div>
        <ul>{exams_html or '<li>—</li>'}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(f"Заметки о состоянии · {n_notes}", expanded=False):
        st.caption('Дни с заполненной колонкой «Заметки» (текст отличается от «Осмотр»)')
        st.markdown(notes_html, unsafe_allow_html=True)
    with st.expander(f"Вся история стационара · {len(hist)} записей", expanded=False):
        if not hist:
            if key_prefix == "cases" or is_case_record(p):
                st.caption("У кейсов задания стационарная история не ведётся — только во вкладке «Когорта».")
            else:
                st.info("История ещё не заполнена — откройте редактор ниже.")
        for h in hist:
            labs_h = h.get("labs") or {}
            with st.container(border=True):
                st.markdown(
                    f"**{html.escape(str(h.get('label') or ('День ' + str(h.get('day')))))}** · "
                    f"АД **{html.escape(str(h.get('bp') or '—'))}** · ЧСС {h.get('hr')} · "
                    f"K+ {labs_h.get('k_mmol_l')} · рСКФ {labs_h.get('egfr')}"
                )
                if h.get("exam"):
                    st.write(h["exam"])
                if h.get("results"):
                    st.caption(f"Результаты: {h['results']}")
                if h.get("notes"):
                    st.caption(f"Заметки: {h['notes']}")

    render_guidelines_for_diagnosis(p, key_prefix=key_prefix)


def render_guidelines_for_diagnosis(p: dict, *, key_prefix: str = "card") -> None:
    """Документы КР под диагноз; подгрузка только по кнопке (без автозапроса)."""
    from digital_resident.rag.catalog import diagnosis_fingerprint, docs_for_diagnosis

    pid = p.get("synthetic_id") or "case"
    scope = f"{key_prefix}_{pid}"
    dx_key = f"kr_dx_edit_{scope}"
    fp_key = f"kr_fp_{scope}"
    hits_key = f"kr_hits_{scope}"
    allow_persist = not is_case_record(p) and bool(p.get("synthetic_id")) and key_prefix != "cases"

    with st.expander("Документы КР по диагнозу", expanded=False):
        st.caption(
            "Нажмите «Подгрузить КР» после выбора или смены диагноза. "
            "В индексе — КР АГ 2024."
        )
        new_dx = st.text_input(
            "Диагноз для подбора КР",
            value=str(p.get("diagnosis") or ""),
            key=dx_key,
            help="Измените диагноз и нажмите «Подгрузить КР».",
        )
        comorbid = list(p.get("comorbidities") or [])
        allergies = list(p.get("allergies") or [])
        fp = diagnosis_fingerprint(new_dx, comorbid, allergies)

        docs = docs_for_diagnosis(new_dx, comorbid)
        for d in docs:
            mark = " (базовый для стенда)" if d.get("fallback") else ""
            st.markdown(
                f"**{d['title']}**{mark} · {d.get('org')} · ID {d.get('doc_id')}  \n"
                f"`{d.get('pdf')}`" + (" · файл есть" if d.get("exists") else " · файл не найден")
            )

        stale = hits_key in st.session_state and st.session_state.get(fp_key) != fp
        c1, c2 = st.columns([1, 3])
        with c1:
            force = st.button("Подгрузить КР", type="primary", key=f"kr_reload_{scope}")
        with c2:
            if hits_key in st.session_state and not stale:
                st.caption("Фрагменты актуальны для текущего диагноза.")
            elif stale:
                st.caption("Диагноз изменился — нажмите «Подгрузить КР».")
            else:
                st.caption("Фрагменты ещё не загружены.")

        if force and (new_dx or "").strip():
            try:
                with st.spinner("Подгрузка фрагментов КР под диагноз…"):
                    rag = GuidelineRAG()
                    probe = {
                        **p,
                        "diagnosis": new_dx.strip(),
                        "comorbidities": comorbid,
                        "allergies": allergies,
                    }
                    hits = rag.search_for_patient(probe, k=6)
                st.session_state[hits_key] = hits
                st.session_state[fp_key] = fp
                if (
                    allow_persist
                    and new_dx.strip()
                    and new_dx.strip() != str(p.get("diagnosis") or "").strip()
                ):
                    upsert_patient({**p, "diagnosis": new_dx.strip()})
                    st.toast("Диагноз обновлён, КР перезагружены", icon="📄")
                st.rerun()
            except Exception as e:
                st.warning(f"Не удалось загрузить КР: {e}")
                return
        elif force and not (new_dx or "").strip():
            st.info("Укажите диагноз, чтобы подобрать документы КР.")
            return

        hits = st.session_state.get(hits_key) or []
        if st.session_state.get(fp_key) != fp:
            hits = []
        if not hits:
            st.info("Нажмите «Подгрузить КР», чтобы увидеть фрагменты протокола.")
            return

        st.markdown(f"**Фрагменты под диагноз** ({len(hits)}):")
        for i, h in enumerate(hits, 1):
            title = h.get("section") or h.get("citation") or "Фрагмент КР"
            page = h.get("page", "?")
            with st.expander(f"[{i}] {title} · стр. {page}", expanded=(i == 1)):
                st.caption(
                    f"{h.get('chunk_id') or h.get('id') or ''} · "
                    f"{h.get('source') or 'КР АГ 2024'}"
                )
                text = (h.get("text") or "").strip()
                st.write(text[:900] + ("…" if len(text) > 900 else ""))



def render_ward_history_editor(
    patient: dict,
    *,
    key_prefix: str,
    allow_save: bool = True,
) -> list[dict] | None:
    """Редактируемая стационарная динамика: длительность, таблица, свободный текст состояния."""
    pid = patient.get("synthetic_id", "new")
    ed_key = f"ward_ed_{key_prefix}_{pid}"
    flash_key = f"ward_flash_{key_prefix}_{pid}"
    stay_default = int(patient.get("ward_stay_days") or 14)
    stay_key = f"ward_stay_{key_prefix}_{pid}"
    applied_key = f"ward_stay_applied_{key_prefix}_{pid}"
    day_key = f"ward_manual_day_{key_prefix}_{pid}"
    day_anchor = f"ward_manual_day_anchor_{key_prefix}_{pid}"
    text_key = f"ward_manual_text_{key_prefix}_{pid}"
    bump_key = f"ward_stay_bump_{key_prefix}_{pid}"
    pending_manual_key = f"ward_pending_manual_{key_prefix}_{pid}"

    st.markdown("#### Стационарная история — редактор")
    st.caption(
        "Длительность госпитализации, правки АД/лаборатории. "
        "± добавляет/убирает сутки, сохраняя уже введённые строки."
    )

    flash = st.session_state.pop(flash_key, None)
    if flash:
        st.success(flash)

    def _merge_extend(old_hist: list[dict], new_stay: int, pending: str) -> list[dict]:
        """Сохранить старые дни, добавить новые; pending → в последний день."""
        old_sorted = sorted(
            [normalize_ward_entry(e) for e in (old_hist or [])],
            key=lambda x: int(x.get("day") or 0),
        )
        old_by = {int(e["day"]): dict(e) for e in old_sorted}
        fresh = build_ward_history(
            {**patient, "ward_stay_days": new_stay},
            stay_days=new_stay,
        )
        out: list[dict] = []
        for e in fresh:
            d = int(e.get("day") or 0)
            if d in old_by:
                kept = dict(old_by[d])
                kept["day"] = d
                out.append(normalize_ward_entry(kept))
            else:
                out.append(normalize_ward_entry(e))
        text = (pending or "").strip()
        if text:
            for e in out:
                if int(e.get("day") or 0) == int(new_stay):
                    e["exam"] = text
                    e["notes"] = text
                    e["label"] = f"День {new_stay}"
                    break
        return out

    def _shrink_hist(old_hist: list[dict], new_stay: int) -> list[dict]:
        old_sorted = sorted(
            [normalize_ward_entry(e) for e in (old_hist or [])],
            key=lambda x: int(x.get("day") or 0),
        )
        kept = [e for e in old_sorted if 1 <= int(e.get("day") or 0) <= new_stay]
        if len(kept) == new_stay and [int(e["day"]) for e in kept] == list(range(1, new_stay + 1)):
            return kept
        fresh = build_ward_history(
            {**patient, "ward_stay_days": new_stay},
            stay_days=new_stay,
        )
        by = {int(e["day"]): e for e in kept}
        return [normalize_ward_entry(by.get(int(e["day"]), e)) for e in fresh]

    # ± обрабатываем до виджетов
    if bump_key in st.session_state:
        delta = int(st.session_state.pop(bump_key))
        pending = ""
        if delta > 0:
            pending = str(st.session_state.pop(pending_manual_key, "") or "").strip()
            if not pending:
                pending = str(st.session_state.get(text_key, "") or "").strip()
        else:
            st.session_state.pop(pending_manual_key, None)

        old_hist = list(patient.get("ward_history") or [])
        old_stay = max(
            len(old_hist),
            int(patient.get("ward_stay_days") or stay_default),
            int(st.session_state.get(applied_key) or stay_default),
        )
        new_stay = max(2, min(60, old_stay + delta))
        if delta > 0:
            rebuilt = _merge_extend(old_hist, new_stay, pending)
            msg = f"Добавлен день {new_stay}" + (" · из текста осмотра" if pending else "")
        else:
            rebuilt = _shrink_hist(old_hist, new_stay)
            msg = f"Убран день, осталось {new_stay} сут"

        if allow_save and patient.get("synthetic_id"):
            upsert_patient(
                {
                    **patient,
                    "ward_stay_days": new_stay,
                    "ward_history": rebuilt,
                }
            )
        patient["ward_stay_days"] = new_stay
        patient["ward_history"] = rebuilt
        st.session_state[stay_key] = new_stay
        st.session_state[applied_key] = new_stay
        st.session_state[day_key] = new_stay
        st.session_state[day_anchor] = new_stay
        if pending:
            st.session_state[text_key] = ""
        st.session_state.pop(ed_key, None)
        st.session_state[flash_key] = msg
        st.rerun()

    if applied_key not in st.session_state:
        st.session_state[applied_key] = stay_default
    if stay_key not in st.session_state:
        st.session_state[stay_key] = stay_default

    sc1, sc2 = st.columns([1.4, 1])
    with sc1:
        stay_days = int(
            st.number_input(
                "Длительность стационара (сут)",
                min_value=2,
                max_value=60,
                step=1,
                key=stay_key,
                help="Введите число суток вручную — старые строки сохранятся.",
            )
        )
    with sc2:
        st.metric("Точек сейчас", len(patient.get("ward_history") or []))

    if int(st.session_state.get(applied_key, stay_default)) != stay_days:
        old_hist = list(patient.get("ward_history") or [])
        old_n = len(old_hist)
        if stay_days > old_n:
            rebuilt = _merge_extend(old_hist, stay_days, "")
        else:
            rebuilt = _shrink_hist(old_hist, stay_days)
        if allow_save and patient.get("synthetic_id"):
            upsert_patient(
                {
                    **patient,
                    "ward_stay_days": stay_days,
                    "ward_history": rebuilt,
                }
            )
        patient["ward_stay_days"] = stay_days
        patient["ward_history"] = rebuilt
        st.session_state[applied_key] = stay_days
        st.session_state[day_key] = stay_days
        st.session_state[day_anchor] = stay_days
        st.session_state.pop(ed_key, None)
        st.session_state[flash_key] = (
            f"Длительность {stay_days} сут · {len(rebuilt)} точек (правки сохранены)"
        )
        st.rerun()

    hist = patient.get("ward_history") or build_ward_history(patient, stay_days=stay_days)

    df = pd.DataFrame(ward_history_to_rows(hist))
    edited = st.data_editor(
        df,
        num_rows="fixed",
        use_container_width=True,
        key=ed_key,
        column_config={
            "День": st.column_config.NumberColumn("День", min_value=1, max_value=60, step=1, width="small"),
            "АД": st.column_config.TextColumn("АД", width="small"),
            "ЧСС": st.column_config.NumberColumn("ЧСС", min_value=40, max_value=180, step=1, width="small"),
            "Вес": st.column_config.NumberColumn("Вес", format="%.1f", width="small"),
            "K+": st.column_config.NumberColumn("K+", format="%.2f", width="small"),
            "рСКФ": st.column_config.NumberColumn("рСКФ", format="%.1f", width="small"),
            "Креатинин": st.column_config.NumberColumn("Креатинин", format="%.1f", width="small"),
            "Глюкоза": st.column_config.NumberColumn("Глюкоза", format="%.1f", width="small"),
            "Осмотр": st.column_config.TextColumn("Осмотр", width="large"),
            "Результаты": st.column_config.TextColumn("Результаты", width="large"),
            "Заметки": st.column_config.TextColumn("Заметки о состоянии", width="medium"),
        },
        hide_index=True,
    )

    try:
        new_hist = rows_to_ward_history(edited.to_dict(orient="records"))
    except Exception as e:
        st.error(f"Не удалось прочитать таблицу: {e}")
        new_hist = hist

    st.markdown("##### Записать состояние вручную (добавить/обновить день)")
    n_rows = max(2, len(hist) or int(stay_days))
    if day_key not in st.session_state or st.session_state.get(day_anchor) != n_rows:
        st.session_state[day_key] = n_rows
        st.session_state[day_anchor] = n_rows

    def _bump_stay(delta: int) -> None:
        st.session_state[bump_key] = int(delta)
        if delta > 0:
            typed = str(st.session_state.get(text_key, "") or "").strip()
            if typed:
                st.session_state[pending_manual_key] = typed
            else:
                st.session_state.pop(pending_manual_key, None)
        else:
            st.session_state.pop(pending_manual_key, None)

    mc_m, mc_d, mc_p, mc2 = st.columns([0.45, 0.9, 0.45, 3.2])
    with mc_m:
        st.write("")
        st.write("")
        st.button(
            "−",
            key=f"ward_manual_minus_{key_prefix}_{pid}",
            help="Убрать последние сутки",
            use_container_width=True,
            on_click=_bump_stay,
            args=(-1,),
        )
    with mc_d:
        manual_day = int(
            st.number_input(
                "День",
                min_value=1,
                max_value=60,
                step=1,
                key=day_key,
                help="По умолчанию — число строк. ± добавляет/убирает сутки без сброса таблицы.",
            )
        )
    with mc_p:
        st.write("")
        st.write("")
        st.button(
            "＋",
            key=f"ward_manual_plus_{key_prefix}_{pid}",
            help="Добавить сутки; текст осмотра попадёт в новую строку",
            use_container_width=True,
            on_click=_bump_stay,
            args=(1,),
        )
    with mc2:
        manual_text = st.text_area(
            "Текст осмотра / состояния",
            placeholder="Например: Жалобы на головокружение, АД 165/100, отёков нет…",
            key=text_key,
            height=80,
        )

    save_clicked = allow_save and st.button(
        "Сохранить историю",
        type="primary",
        use_container_width=True,
        key=f"ward_save_{key_prefix}_{pid}",
        help="Сохраняет таблицу как есть и при необходимости обновляет выбранный день из текста.",
    )

    if save_clicked:
        if not patient.get("synthetic_id"):
            st.error("Сначала сохраните карточку пациента")
        else:
            try:
                hist_to_save = [normalize_ward_entry(e) for e in (new_hist or hist or [])]
                parts = ["таблица"]
                text = (manual_text or "").strip()
                if text:
                    by_day = {int(e["day"]): dict(e) for e in hist_to_save}
                    entry = by_day.get(int(manual_day)) or {
                        "day": int(manual_day),
                        "bp": patient.get("bp_office") or "140/90",
                        "hr": patient.get("hr") or 75,
                        "weight_kg": patient.get("weight_kg") or 80,
                        "labs": dict(patient.get("labs_day0") or {}),
                        "exam": "",
                        "results": "",
                        "notes": "",
                    }
                    entry["exam"] = text
                    entry["notes"] = text
                    entry["label"] = f"День {int(manual_day)}"
                    by_day[int(manual_day)] = normalize_ward_entry(entry)
                    hist_to_save = [by_day[d] for d in sorted(by_day)]
                    parts.append(f"день {int(manual_day)} обновлён")

                if not hist_to_save:
                    st.error("Таблица пуста — нечего сохранять")
                else:
                    last_day = max((e.get("day") or 0) for e in hist_to_save)
                    upsert_patient(
                        {
                            **patient,
                            "ward_stay_days": max(int(stay_days), int(last_day)),
                            "ward_history": hist_to_save,
                        }
                    )
                    st.session_state.pop(ed_key, None)
                    st.session_state[text_key] = ""
                    st.session_state[flash_key] = (
                        f"История сохранена · {len(hist_to_save)} записей · "
                        + ", ".join(parts)
                        + f" · {patient.get('full_name')}"
                    )
                    st.toast("История сохранена", icon="✅")
                    st.rerun()
            except Exception as e:
                st.error(f"Ошибка сохранения: {e}")

    return new_hist



def _parse_bp(bp: str) -> tuple[float | None, float | None]:
    try:
        s, d = str(bp).replace(" ", "").split("/")
        return float(s), float(d)
    except Exception:
        return None, None


def trajectory_frame(traj: list) -> pd.DataFrame:
    rows = []
    for p in traj or []:
        labs = p.get("labs") or {}
        sbp, dbp = _parse_bp(p.get("bp") or "")
        rows.append(
            {
                "День": int(p.get("day") or 0),
                "САД": sbp,
                "ДАД": dbp,
                "K+": labs.get("k_mmol_l"),
                "рСКФ": labs.get("egfr"),
                "Креатинин": labs.get("creatinine_umol_l"),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("День").set_index("День")


def render_dynamics(traj: list) -> None:
    st.markdown("### Контрольные точки и графики")
    df = trajectory_frame(traj)
    if df.empty:
        st.info("Нет данных траектории.")
        return

    g1, g2 = st.columns(2)
    with g1:
        st.caption("Артериальное давление, мм рт.ст.")
        bp_df = df[["САД", "ДАД"]].dropna(how="all")
        if not bp_df.empty:
            st.line_chart(bp_df, height=260, color=["#2F65A3", "#C93B4E"])
        else:
            st.warning("Нет данных АД для графика")
    with g2:
        st.caption("Калий (ммоль/л) и рСКФ")
        lab_df = df[["K+", "рСКФ"]].dropna(how="all")
        if not lab_df.empty:
            st.line_chart(lab_df, height=260, color=["#B78103", "#2E7D4F"])
        else:
            st.warning("Нет лабораторных данных для графика")

    st.caption("Креатинин, мкмоль/л")
    creat = df[["Креатинин"]].dropna(how="all")
    if not creat.empty:
        st.line_chart(creat, height=200, color=["#4E80B4"])

    st.markdown("#### Дневник наблюдения")
    for p in traj or []:
        labs = p.get("labs") or {}
        flags = ", ".join(p.get("flags") or []) or "нет"
        events = "; ".join(p.get("events") or []) or "—"
        with st.container(border=True):
            st.markdown(
                f"**День {p.get('day')}** · АД **{html.escape(str(p.get('bp') or '—'))}**"
            )
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("K+", labs.get("k_mmol_l", "—"))
            m2.metric("рСКФ", labs.get("egfr", "—"))
            m3.metric("Креатинин", labs.get("creatinine_umol_l", "—"))
            m4.metric("Флаги", len(p.get("flags") or []))
            st.write(events)
            st.caption(f"Флаги: {flags}")


def render_result(result: dict, key_prefix: str) -> None:
    plan = result.get("plan") or {}
    audit = result.get("audit") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("RAG", len(result.get("rag_hits") or []))
    c2.metric("Аудитор", len(audit.get("findings") or []))
    c3.metric("Replan", "да" if result.get("revised_plan") else "нет")
    c4.metric(
        "Цитаты OK",
        "да"
        if (plan.get("citation_validation") or {}).get("invalid_removed", 0) == 0
        else "нет",
    )

    t1, t2, t3, t4 = st.tabs(["План", "Динамика", "Аудитор", "RAG"])
    with t1:
        meds = plan.get("medications") or []
        st.markdown(f"**Кратко:** {plan.get('summary') or '—'}")
        for m in meds:
            if not isinstance(m, dict):
                st.write(f"- {m}")
                continue
            with st.container(border=True):
                st.markdown(f"**{m.get('name', '')}** — {m.get('dose', '')}")
                st.write(m.get("rationale") or "")
        if result.get("revised_plan"):
            with st.expander("Пересмотренный план", expanded=False):
                st.json(result["revised_plan"])
    with t2:
        render_dynamics(result.get("trajectory") or [])
    with t3:
        findings = audit.get("findings") or []
        if not findings:
            st.success("Критических дефектов не выявлено.")
        for f in findings:
            sev = (f.get("severity") or "low").lower()
            icon = {"high": "🔴", "medium": "🟠", "low": "🔵"}.get(sev, "⚪")
            with st.container(border=True):
                st.markdown(f"{icon} **{f.get('title', '')}**")
                st.write(f.get("detail") or "")
                st.caption(f"Рекомендация: {f.get('recommendation') or '—'}")
        if audit.get("caught_example"):
            example = str(audit.get("caught_example") or "").replace(
                "consent_invasive=false — ", ""
            ).replace("consent_invasive=false", "")
            st.info(example.strip())
    with t4:
        for i, h in enumerate(result.get("rag_hits") or [], 1):
            with st.expander(
                f"[{i}] {h.get('section') or h.get('citation')} · стр. {h.get('page')}"
            ):
                st.caption(f"{h.get('chunk_id')} · via={h.get('via')}")
                st.write(h.get("text") or "")

    pid = (result.get("patient") or {}).get("synthetic_id", "patient")
    st.download_button(
        "Скачать протокол JSON",
        data=json.dumps(result, ensure_ascii=False, indent=2),
        file_name=f"run_{pid}_{key_prefix}.json",
        mime="application/json",
        use_container_width=True,
        key=f"dl_{key_prefix}_{pid}",
    )


def page_cohort() -> None:
    seed_cohort(force=False)
    n = len(load_cohort())
    st.markdown(
        f'<div class="mz-banner"><div class="bar"></div><div>'
        f"<strong>Когорта: {n} {_patients_word(n)}</strong>"
        f"<span>Поиск и выбор пациента — в одном блоке ниже</span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )
    selected = st.session_state.get("selected_patient_id")
    pid = render_patient_chooser(key_prefix="cohort", selected_id=selected)
    if pid:
        st.session_state["selected_patient_id"] = pid

    if not pid:
        return

    patient = get_patient(pid)
    render_patient_card(patient, key_prefix="cohort")
    busy = any_job_running()
    b1, b2 = st.columns(2)
    with b1:
        if st.button(
            "Запустить СППР по пациенту",
            type="primary",
            use_container_width=True,
            key="btn_cohort_run",
            disabled=busy,
        ):
            launch_patient_job("cohort", f"Когорта · {patient.get('full_name')}", patient)
    with b2:
        cached = ROOT / "data" / "patient_runs" / f"{pid}_{patient.get('scenario')}.json"
        if cached.exists() and st.button(
            "Показать сохранённый прогон",
            key="btn_cohort_cached",
            use_container_width=True,
        ):
            store_result("cohort", json.loads(cached.read_text(encoding="utf-8")))
            st.rerun()

    with st.expander("Удалить пациента", expanded=False):
        st.caption(f"Будет удалён: **{patient.get('full_name')}** из когорты и файла JSON.")
        confirm = st.checkbox(
            "Подтверждаю удаление",
            key=f"del_confirm_{pid}",
        )
        if st.button(
            "Удалить безвозвратно",
            type="primary",
            key=f"btn_delete_{pid}",
            disabled=not confirm,
            use_container_width=True,
        ):
            name = patient.get("full_name")
            if delete_patient(pid):
                st.session_state.pop("selected_patient_id", None)
                st.session_state.get("results", {}).pop("cohort", None)
                for k in list(st.session_state.keys()):
                    if isinstance(k, str) and pid in k and k.startswith("ward_"):
                        st.session_state.pop(k, None)
                st.toast(f"Удалён: {name}", icon="🗑️")
                st.rerun()
            else:
                st.error("Пациент не найден или уже удалён")

    res = get_result("cohort")
    if res:
        st.divider()
        render_result(res, key_prefix="cohort")
    form_res = get_result("form")
    if form_res and not res:
        st.divider()
        render_result(form_res, key_prefix="form")

    st.divider()
    render_ward_history_editor(patient, key_prefix="cohort", allow_save=True)



def _patients_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "пациент"
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return "пациента"
    return "пациентов"


@st.dialog("Новый пациент", width="large")
def new_patient_dialog() -> None:
    st.caption(
        "После сохранения создаётся стационарная история "
        "(ежедневный осмотр и анализы). Откроется вкладка «Когорта»."
    )
    with st.form("new_patient_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            full_name = st.text_input(
                "ФИО (синтетическое)",
                value="",
                placeholder="Иванов Иван Иванович",
            )
            age = st.number_input("Возраст", 18, 100, 55)
            sex_ui = st.selectbox(
                "Пол",
                ["М", "Ж"],
                key="form_sex",
            )
            sex = "F" if sex_ui == "Ж" else "M"
            bp = st.text_input("АД офисное", value="", placeholder="158/96")
            hr = st.number_input("ЧСС", 40, 160, 76)
        with c2:
            diagnosis = st.text_input(
                "Диагноз",
                value="",
                placeholder="Артериальная гипертензия, 2 степень",
            )
            icd10 = st.text_input("МКБ-10", value="", placeholder="I10")
            weight = st.number_input("Вес, кг", 40.0, 200.0, 80.0)
            height = st.number_input("Рост, см", 140.0, 220.0, 170.0)
            consent = st.checkbox("Информированное согласие на инвазивные получено", True)
        with c3:
            egfr = st.number_input("рСКФ", 5.0, 150.0, 85.0)
            k = st.number_input("Калий, ммоль/л", 2.5, 7.0, 4.2, step=0.1)
            creat = st.number_input("Креатинин, мкмоль/л", 40.0, 400.0, 90.0)
            glucose = st.number_input("Глюкоза", 3.0, 20.0, 5.5)
            scenario_opts = {
                "Автоматически по данным пациента": "auto",
                "Типичное течение АГ": "baseline",
                "Коморбидность с ХБП": "comorbid_ckd",
                "Осложнение: рост калия на 2–4 день": "hyperkalemia_day3",
            }
            scenario_ui = st.selectbox(
                "Сценарий динамики",
                list(scenario_opts.keys()),
                help="Как моделировать стационарную динамику АД и лаборатории",
            )
            scenario = scenario_opts[scenario_ui]

        allergies = st.text_area(
            "Аллергии (через ;)",
            value="",
            placeholder="ангиоотек на иАПФ; пенициллин",
        )
        comorbidities = st.text_area(
            "Коморбидности (через ;)",
            value="",
            placeholder="ХБП С3а; сахарный диабет 2 типа",
        )
        current_meds = st.text_area(
            "Текущие препараты (через ;)",
            value="",
            placeholder="амлодипин 5 мг; индапамид 1.5 мг",
        )
        exams_raw = st.text_area(
            "Обследования (каждая строка: Название | результат | дата)",
            value="",
            placeholder="ЭКГ | Синусовый ритм | day0\nЭхоКГ | ФВ 58% | day0",
        )
        notes_raw = st.text_area(
            "Заметки о состоянии (каждая строка: дата | текст)",
            value="",
            placeholder="day1 | Поступление. Курение отрицает. Готов к терапии.",
            help="Заметка day1 (день поступления) синхронизируется с таблицей. День = номер строки.",
        )
        force_compl = st.checkbox("Форсировать осложнение на день 3 (гиперкалиемия)", False)
        stay_days_form = st.number_input(
            "Длительность стационара (сут)",
            min_value=2,
            max_value=60,
            value=14,
            step=1,
            help="История ежедневных осмотров до дня выписки",
        )
        gen_ward = st.checkbox("Сгенерировать стационарную историю", True)
        run_after = st.checkbox("Сразу запустить СППР после сохранения", False)
        submitted = st.form_submit_button("Сохранить пациента", type="primary")

    if not submitted:
        return

    full_name = (full_name or "").strip() or "Новый пациент"
    bp = (bp or "").strip() or "158/96"
    diagnosis = (diagnosis or "").strip() or "Артериальная гипертензия, 2 степень"
    icd10 = (icd10 or "").strip() or "I10"
    if not (exams_raw or "").strip():
        exams_raw = "ЭКГ | Синусовый ритм | day0\nЭхоКГ | ФВ 58% | day0"
    if not (notes_raw or "").strip():
        notes_raw = "day1 | Поступление в стационар. Первичный осмотр, готов к терапии."

    exams = []
    for line in exams_raw.splitlines():
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split("|")]
        exams.append(
            {
                "name": parts[0] if parts else "Обследование",
                "result": parts[1] if len(parts) > 1 else "",
                "date": parts[2] if len(parts) > 2 else "day1",
            }
        )
    notes = []
    for line in notes_raw.splitlines():
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split("|", 1)]
        if len(parts) == 1:
            notes.append({"date": "day1", "text": parts[0]})
        else:
            notes.append({"date": parts[0], "text": parts[1]})
    note_dates = {str(n.get("date") or "").strip().lower() for n in notes}
    if "day1" not in note_dates and "day0" not in note_dates:
        notes.append(
            {
                "date": "day1",
                "text": "Поступление в стационар. Первичный осмотр, готов к терапии.",
            }
        )

    raw = {
        "synthetic_id": f"SYN-AG-{uuid4().hex[:6].upper()}",
        "full_name": full_name,
        "age": age,
        "sex": sex,
        "diagnosis": diagnosis,
        "icd10": icd10,
        "bp_office": bp,
        "hr": hr,
        "weight_kg": weight,
        "height_cm": height,
        "allergies": parse_list_field(allergies),
        "comorbidities": parse_list_field(comorbidities),
        "current_meds": parse_list_field(current_meds),
        "labs_day0": {
            "egfr": egfr,
            "k_mmol_l": k,
            "creatinine_umol_l": creat,
            "glucose_mmol_l": glucose,
        },
        "examinations": exams,
        "health_notes": notes,
        "consent_invasive": consent,
        "force_complication": force_compl,
        "scenario": "" if scenario == "auto" else scenario,
        "ward_stay_days": int(stay_days_form),
        "source": "form",
    }
    if not gen_ward:
        raw["ward_history"] = []
        raw["skip_ward_history"] = True
    patient = upsert_patient(raw)
    if gen_ward:
        if not patient.get("ward_history"):
            patient["ward_history"] = build_ward_history(patient, stay_days=int(stay_days_form))
        # day1 из формы → в таблицу; таблица → обратно в шапку
        day1_text = next(
            (
                str(n.get("text") or "").strip()
                for n in (patient.get("health_notes") or [])
                if str(n.get("date") or "").strip().lower() in {"day1", "day0"}
            ),
            "Поступление в стационар. Первичный осмотр, готов к терапии.",
        )
        for e in patient.get("ward_history") or []:
            if int(e.get("day") or -1) == 1:
                e["notes"] = day1_text
                break
        from digital_resident.patients import sync_state_notes

        patient = sync_state_notes(patient)
        patient = upsert_patient(patient)

    st.session_state["selected_patient_id"] = patient["synthetic_id"]
    st.session_state["active_main_tab"] = "cohort"
    st.session_state.pop("focus_patient_id", None)
    if run_after:
        launch_patient_job("form", f"Новый · {patient.get('full_name')}", patient)
    st.toast(
        f"Сохранён {patient.get('full_name')} · {scenario_label(patient['scenario'])}",
        icon="✅",
    )
    st.rerun()


def page_assignment_cases() -> None:
    cases = list_cases()
    labels = {c["id"]: c["title"] for c in cases}
    st.caption(
        f"Три демонстрационных кейса ТЗ — у каждого свой синтетический пациент "
        f"({len(cases)} шт.). Выберите кейс ниже и запустите СППР "
        f"(или откройте уже сохранённый прогон без API)."
    )
    case_id = st.selectbox(
        "Кейс задания",
        list(labels.keys()),
        format_func=lambda x: labels[x],
        key="case_select",
    )
    case = get_case(case_id)
    render_patient_card(
        {
            **case["patient"],
            "full_name": case["title"],
            "scenario": case["scenario"],
            "health_notes": [{"date": "case", "text": case["description"]}],
            "examinations": case["patient"].get("examinations") or [],
            "source": "assignment_case",
        },
        key_prefix="cases",
    )
    busy = any_job_running()
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Запустить в фоне",
            type="primary",
            key="btn_case_run",
            disabled=busy or not has_llm_api_key(),
            help="Нужен NEURAL_DEEP_API_KEY в .env",
        ):
            launch_case_job("cases", case_id, f"Кейс · {case['title']}")
    with c2:
        if st.button(
            "Показать сохранённый результат",
            key="btn_case_cached",
            help="Читает data/result_<case>.json — API не нужен",
        ):
            cached = load_cached_case_result(case_id)
            if not cached:
                st.error(f"Нет файла data/result_{case_id}.json")
            else:
                st.session_state["cached_case_view"] = cached
                st.toast(f"Загружен сохранённый прогон: {case_id}", icon="📄")

    res = get_result("cases")
    if res:
        render_result(res, key_prefix="cases")
    elif st.session_state.get("cached_case_view"):
        render_result(st.session_state["cached_case_view"], key_prefix="cases_cached")


def main() -> None:
    init_state()
    go_home_if_requested()
    inject()
    seed_cohort(force=False)

    # если сайдбар был свёрнут — кнопка раскрытия вверху слева;
    # дублируем быстрый доступ к пациентам и на главной
    with st.sidebar:
        st.markdown("### Статус СППР")
        if not has_llm_api_key():
            st.info(
                "Режим без API: когорта и UI доступны; "
                "кейсы — через «Показать сохранённый результат»; "
                "живой план/аудит — после `.env` с ключом."
            )
        job_status_panel()
        st.divider()
        sel = st.session_state.get("selected_patient_id")
        if sel:
            p = get_patient(sel)
            if p:
                st.caption("Выбран")
                st.markdown(f"**{p.get('full_name') or sel}**")
        st.caption("Поиск и выбор — во вкладке «Когорта».")
        st.divider()
        st.caption("Если меню слева пропало: нажмите «›» / иконку в левом верхнем углу.")

    n = len(load_cohort())
    _, head_r = st.columns([3, 1])
    with head_r:
        if st.button("＋ Новый пациент", type="primary", use_container_width=True, key="btn_open_new_patient"):
            new_patient_dialog()

    # Streamlit tabs не дают программный switch — держим только Когорта / Кейсы;
    # после сохранения из модалки остаёмся на когорте (первая вкладка).
    tab_cohort, tab_cases = st.tabs(
        [f"Когорта ({n} {_patients_word(n)})", "Кейсы задания"]
    )
    with tab_cohort:
        page_cohort()
    with tab_cases:
        page_assignment_cases()

    st.markdown(
        '<div class="mz-footer">Синтетические данные. Не является медицинской рекомендацией.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
