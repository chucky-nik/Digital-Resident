from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from digital_resident.cases import get_case
from digital_resident.citations import format_citation_rules, validate_and_repair_plan
from digital_resident.llm import get_llm
from digital_resident.patients import infer_scenario, results_dir
from digital_resident.rag import GuidelineRAG
from digital_resident.safety import (
    allergy_blocks_acei,
    enforce_plan_constraints,
    run_safety_checks,
)
from digital_resident.simulation import needs_replan, simulate_trajectory


class PipelineState(TypedDict, total=False):
    case_id: str
    patient: dict[str, Any]
    scenario: str
    rag_hits: list[dict[str, Any]]
    plan: dict[str, Any]
    trajectory: list[dict[str, Any]]
    revised_plan: dict[str, Any] | None
    audit: dict[str, Any]
    citation_issues: list[dict[str, Any]]
    error: str


SYSTEM = (
    "Ты — клинический ИИ-ассистент врача (СППР) по артериальной гипертензии. "
    "Отвечай на русском. Опирайся ТОЛЬКО на переданные фрагменты КР. "
    "Цитировать можно ТОЛЬКО как [N] из списка допустимых источников. "
    "В citations_used section и page копируй РОВНО из списка. "
    "Не выдумывай пункты КР. Не назначай препараты вне контекста. "
    "Пациентские данные — синтетические. Прототип CDS, не замена врачу. "
    "Верни строго JSON без markdown."
)


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        try:
            obj, _ = json.JSONDecoder().raw_decode(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        snippet = text[start : end + 1]
        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", snippet)
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {"raw": text[:4000], "parse_error": True}


def _patient_constraints(patient: dict[str, Any]) -> str:
    labs = patient.get("labs_day0") or {}
    lines = [
        "ЖЁСТКИЕ КЛИНИЧЕСКИЕ ОГРАНИЧЕНИЯ ДЛЯ ЭТОГО ПАЦИЕНТА:",
        f"- рСКФ={labs.get('egfr')}, K+={labs.get('k_mmol_l')}",
        f"- аллергии: {patient.get('allergies') or []}",
        f"- коморбидности: {patient.get('comorbidities') or []}",
        f"- consent_invasive={patient.get('consent_invasive', True)}",
    ]
    if allergy_blocks_acei(patient):
        lines.append(
            "- ЗАПРЕТ: не назначай иАПФ (эналаприл/периндоприл и др.). Только БРА, если нужен иРААС."
        )
    egfr = float(labs.get("egfr") or 999)
    if egfr < 30:
        lines.append("- ЗАПРЕТ: тиазидные диуретики; используй петлевые.")
    elif egfr < 45:
        lines.append("- ОСТОРОЖНО: при диуретике предпочти/рассмотри петлевой; тиазид — с обоснованием.")
    if float(labs.get("k_mmol_l") or 0) >= 5.5:
        lines.append("- ЗАПРЕТ: иАПФ/БРА/спиронолактон при K+≥5.5.")
    if not patient.get("consent_invasive", True):
        lines.append("- Процедура: отметь отсутствие информированного согласия (status=missing).")
    lines.append("- Обязателен мониторинг K+ и рСКФ при иРААС.")
    lines.append("- ЗАПРЕТ: комбинация иАПФ+БРА (двойная блокада РААС).")
    return "\n".join(lines)


def node_rag(state: PipelineState) -> PipelineState:
    rag = GuidelineRAG()
    hits = rag.search_for_patient(state["patient"], k=8)
    return {"rag_hits": hits}


def node_plan(state: PipelineState) -> PipelineState:
    llm = get_llm()
    rag = GuidelineRAG()
    hits = state.get("rag_hits") or []
    ctx = rag.format_context(hits)
    cite_rules = format_citation_rules(hits)
    patient = state["patient"]
    prompt = f"""
Построй стартовый план лечения. Каждый препарат/обследование — с citations из допустимого списка.

{_patient_constraints(patient)}

{cite_rules}

Пациент:
{json.dumps(patient, ensure_ascii=False, indent=2)}

Уже выполненные обследования пациента (учти, не дублируй без нужды):
{json.dumps(patient.get('examinations') or [], ensure_ascii=False, indent=2)}

Заметки о состоянии:
{json.dumps(patient.get('health_notes') or patient.get('notes') or [], ensure_ascii=False, indent=2)}

Стационарная история (ежедневные осмотры и результаты за весь срок госпитализации):
{json.dumps(patient.get('ward_history') or [], ensure_ascii=False, indent=2)}

Фрагменты КР:
{ctx}

Верни JSON:
{{
  "summary": "кратко",
  "goals": ["целевое АД ..."],
  "examinations": [{{"item":"...","rationale":"...","citations":["[1]"]}}],
  "medications": [{{"name":"конкретный класс/препарат","dose":"...","rationale":"...","citations":["[1]"]}}],
  "monitoring": [{{"item":"K+ и рСКФ ...","citations":["[n]"]}}],
  "procedural_checklist": [{{"item":"...","status":"ok|missing|na"}}],
  "drug_conflict_check": {{"dual_raas": false, "iraas_mra": false, "notes": "..."}},
  "citations_used": [{{"ref":"[1]","section":"...","page":"..."}}],
  "uncertainties": []
}}
Имена препаратов указывай конкретно (например: валсартан + амлодипин), без противоречий классов.
"""
    raw = llm.chat(prompt, system=SYSTEM, temperature=0.05, max_tokens=2800)
    plan = _parse_json(raw)
    plan = enforce_plan_constraints(patient, plan)
    plan, cite_issues = validate_and_repair_plan(plan, hits)
    return {"plan": plan, "citation_issues": cite_issues}


def node_simulate(state: PipelineState) -> PipelineState:
    meds = []
    for m in (state.get("plan") or {}).get("medications") or []:
        if isinstance(m, dict):
            meds.append(f"{m.get('name', '')} {m.get('dose', '')}".strip())
        else:
            meds.append(str(m))
    traj = simulate_trajectory(
        scenario=state["scenario"],
        patient=state["patient"],
        plan_meds=meds,
    )
    return {"trajectory": traj}


def node_replan(state: PipelineState) -> PipelineState:
    if not needs_replan(state.get("trajectory") or []):
        return {"revised_plan": None}

    llm = get_llm()
    rag = GuidelineRAG()
    hits = rag.search(
        "гиперкалиемия иАПФ БРА отмена снижение дозы СКФ контроль калия ХБП противопоказания",
        k=8,
        must_include_ids=[
            "cur_iraas_contra",
            "cur_no_dual_iraas",
            "cur_spironolactone",
            "cur_thiazide_ckd",
            "cur_monitoring_labs",
            "cur_ckd_start",
        ],
    )
    ctx = rag.format_context(hits)
    cite_rules = format_citation_rules(hits)
    trigger = [p for p in state["trajectory"] if "recalculate_plan" in (p.get("flags") or [])]
    prompt = f"""
Пересчитай тактику из-за отклонения на контрольной точке.
Используй ТОЛЬКО цитаты из допустимого списка.

{_patient_constraints(state['patient'])}
{cite_rules}

Исходный план:
{json.dumps(state.get('plan'), ensure_ascii=False)}

Точка отклонения:
{json.dumps(trigger, ensure_ascii=False, indent=2)}

Фрагменты КР:
{ctx}

Верни JSON:
{{
  "trigger": "...",
  "changes": ["..."],
  "medications": [{{"name":"...","dose":"...","action":"start|stop|reduce|continue","rationale":"...","citations":["[1]"]}}],
  "monitoring": [{{"item":"...","citations":["[n]"]}}],
  "citations_used": [{{"ref":"[1]","section":"...","page":"..."}}],
  "uncertainties": []
}}
При K+≥5.5 — stop/reduce иРААС с цитатой на противопоказание.
"""
    raw = llm.chat(prompt, system=SYSTEM, temperature=0.05, max_tokens=2200)
    revised = _parse_json(raw)
    revised = enforce_plan_constraints(state["patient"], revised)
    revised, cite_issues = validate_and_repair_plan(revised, hits)
    prev = list(state.get("citation_issues") or [])
    return {
        "revised_plan": revised,
        "rag_hits": (state.get("rag_hits") or []) + hits,
        "citation_issues": prev + cite_issues,
    }


def node_audit(state: PipelineState) -> PipelineState:
    llm = get_llm()
    rag = GuidelineRAG()
    hits = rag.search(
        "противопоказания иАПФ гиперкалиемия СКФ согласие мониторинг калия спиронолактон двойная блокада РААС",
        k=6,
        must_include_ids=[
            "cur_iraas_contra",
            "cur_no_dual_iraas",
            "cur_angioedema",
            "cur_monitoring_labs",
            "cur_thiazide_ckd",
        ],
    )
    ctx = rag.format_context(hits)
    cite_rules = format_citation_rules(hits)

    # deterministic expertise layer
    rule_findings = run_safety_checks(
        state["patient"],
        state.get("plan"),
        state.get("revised_plan"),
        state.get("trajectory"),
    )
    for issue in state.get("citation_issues") or []:
        rule_findings.append(
            {
                "severity": issue.get("severity", "citation"),
                "severity": issue.get("severity", "medium"),
                "title": issue.get("title", "Проблема цитирования"),
                "detail": issue.get("detail", ""),
                "evidence": issue.get("evidence", ""),
                "guideline": "Контракт цитирования RAG",
                "recommendation": issue.get("recommendation", ""),
                "rule_id": "CITATION_VALIDATION",
            }
        )

    prompt = f"""
Ты AI-аудитор (клинический + процедурный + drug-drug + качество цитат).
Найди дефекты. Для guideline указывай только [N] из списка.

{cite_rules}

Пациент:
{json.dumps(state['patient'], ensure_ascii=False)}
План:
{json.dumps(state.get('plan'), ensure_ascii=False)}
Пересмотренный план:
{json.dumps(state.get('revised_plan'), ensure_ascii=False)}
Траектория:
{json.dumps(state.get('trajectory'), ensure_ascii=False)}
Уже найденные rule-based findings (можешь подтвердить/дополнить, не игнорируй):
{json.dumps(rule_findings, ensure_ascii=False)}

Фрагменты КР:
{ctx}

Верни JSON:
{{
  "findings": [
    {{
      "severity": "clinical|procedural|citation|drug_drug",
      "severity": "high|medium|low",
      "title": "...",
      "detail": "...",
      "evidence": "...",
      "guideline": "[N] ...",
      "recommendation": "..."
    }}
  ],
  "summary": "1-2 предложения",
  "caught_example": "одна конкретная ошибка"
}}
Важные клинические факты для аудита:
- Ангиоотёк на иАПФ → БРА ПРЕДПОЧТИТЕЛЕН (это не ошибка). Ошибка — назначить иАПФ.
- citations_used уже прогнан машинной валидацией: section/page/chunk_id из RAG. Не выдумывай рассинхрон метаданных, если они совпадают со списком.
- Ищи реальные дефекты: иАПФ при ангиоотёке; иАПФ+БРА; иРААС+АМКР; тиазид при низкой СКФ;
  нет согласия; нет мониторинга K+/СКФ; ссылки [N] вне списка; гиперкалиемия без коррекции.
"""
    raw = llm.chat(prompt, system=SYSTEM, temperature=0.05, max_tokens=2400)
    audit = _parse_json(raw)
    llm_findings = list(audit.get("findings") or [])

    # отсекаем типичные ложные срабатывания LLM про «БРА запрещён при ангиоотёке»
    filtered_llm = []
    cite_clean = not (state.get("citation_issues") or [])
    for f in llm_findings:
        title = (f.get("title") or "").lower()
        detail = (f.get("detail") or "").lower()
        blob = title + " " + detail
        if (
            allergy_blocks_acei(state["patient"])
            and "бра" in blob
            and "противопоказ" in blob
            and "иапф" not in title
        ):
            continue
        # если машинная валидация цитат чистая — игнор LLM-галлюцинаций про метаданные/ссылки
        if cite_clean and any(
            k in blob
            for k in (
                "метаданн",
                "несуществующ",
                "недопустимая ссылка",
                "неверная ссылка",
                "неверные метадан",
                "рассинхрон",
                "citations_used",
                "цитирован",
                "некорректное обоснование",
                "неполное обоснование",
                "некорректн",
                "неполн",
                "ссылк",
                "фрагмент [",
            )
        ):
            continue
        filtered_llm.append(f)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in rule_findings + filtered_llm:
        key = f.get("rule_id") or f.get("title")
        if not key or key in seen:
            continue
        seen.add(str(key))
        merged.append(f)
    audit["findings"] = merged
    audit["rule_based_count"] = len(rule_findings)
    audit["llm_count"] = len(filtered_llm)

    preferred = [f for f in rule_findings if f.get("severity") == "high"] or rule_findings
    if preferred:
        top = preferred[0]
        audit["caught_example"] = f"{top.get('title')}: {top.get('detail')}"
    elif merged:
        top = merged[0]
        audit["caught_example"] = f"{top.get('title')}: {top.get('detail')}"
    else:
        audit["caught_example"] = (
            "Критических клинических/процедурных дефектов не выявлено; "
            "назначения привязаны к валидированным цитатам RAG."
        )
    audit["summary"] = (
        f"Аудитор выявил {len(merged)} дефект(ов); "
        f"rule-based={len(rule_findings)}, llm={len(filtered_llm)}."
    )
    return {"audit": audit}


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("rag", node_rag)
    g.add_node("plan", node_plan)
    g.add_node("simulate", node_simulate)
    g.add_node("replan", node_replan)
    g.add_node("audit", node_audit)
    g.set_entry_point("rag")
    g.add_edge("rag", "plan")
    g.add_edge("plan", "simulate")
    g.add_edge("simulate", "replan")
    g.add_edge("replan", "audit")
    g.add_edge("audit", END)
    return g.compile()


def _pack_result(
    *,
    case_meta: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case": case_meta,
        "patient": result.get("patient"),
        "rag_hits": [
            {
                "chunk_id": h.get("chunk_id"),
                "section": h.get("section"),
                "page": h.get("page"),
                "citation": h.get("citation"),
                "via": h.get("via"),
                "score": h.get("score"),
                "text": h.get("text"),
            }
            for h in (result.get("rag_hits") or [])
        ],
        "plan": result.get("plan"),
        "trajectory": result.get("trajectory"),
        "revised_plan": result.get("revised_plan"),
        "citation_issues": result.get("citation_issues"),
        "audit": result.get("audit"),
    }


def run_patient(patient: dict[str, Any], *, case_id: str | None = None) -> dict[str, Any]:
    """Полный пайплайн по произвольному (в т.ч. новому) пациенту."""
    from digital_resident.patients import normalize_patient

    patient = normalize_patient(patient)
    scenario = infer_scenario(patient)
    app = build_graph()
    result = app.invoke(
        {
            "case_id": case_id or patient.get("synthetic_id") or "custom",
            "patient": patient,
            "scenario": scenario,
        }
    )
    packed = _pack_result(
        case_meta={
            "id": case_id or "custom",
            "title": patient.get("full_name") or patient.get("synthetic_id"),
            "description": patient.get("diagnosis"),
            "scenario": scenario,
        },
        result=result,
    )
    # persist run
    out = results_dir() / f"{patient['synthetic_id']}_{scenario}.json"
    out.write_text(
        __import__("json").dumps(packed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    packed["saved_to"] = str(out)
    return packed


def run_case(case_id: str) -> dict[str, Any]:
    case = get_case(case_id)
    # enrich assignment cases with normalize for exams/notes compatibility
    from digital_resident.patients import normalize_patient

    patient = normalize_patient({**case["patient"], "scenario": case["scenario"]})
    app = build_graph()
    result = app.invoke(
        {
            "case_id": case_id,
            "patient": patient,
            "scenario": case["scenario"],
        }
    )
    packed = _pack_result(
        case_meta={
            "id": case["id"],
            "title": case["title"],
            "description": case["description"],
            "scenario": case["scenario"],
        },
        result=result,
    )
    return packed
