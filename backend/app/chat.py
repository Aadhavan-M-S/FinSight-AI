import logging
import re
from decimal import Decimal, DecimalException
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from .config import settings
from .database import Session, now, transaction
from .financial import LABELS, MARGINS, calculate, find_facts, resolve_facts, serialize_fact
from .generation import ProviderError, provider, verified_claims
from .models import ChatMessage, ChatSession, Company, Evidence
from .retrieval import SearchRequest, scoped_documents, search

router = APIRouter(prefix="/chat/sessions", tags=["chat"])
logger = logging.getLogger("finsight.chat")
Mode = Literal["single", "research"]
STATUS = {
    "insufficient_evidence": "The selected documents do not provide enough evidence to answer this question.",
    "conflicting_evidence": "The selected disclosures contain conflicting or differently defined figures.",
    "calculation_unavailable": "A comparable calculation could not be completed.",
    "processing_error": "The answer provider could not complete this request.",
}
METRIC_QUERY = {
    "net_profit_margin": r"\bnet (?:income |profit )?margin\b",
    "operating_margin": r"\boperating (?:profit )?margin\b",
    "gross_margin": r"\bgross margin\b",
    "operating_cash_flow": r"\b(?:operating cash flow|cash flow from operations)\b",
    "operating_expenses": r"\boperating expenses?\b",
    "operating_profit": r"\boperating (?:income|profit|loss)\b",
    "net_profit": r"\bnet (?:income|profit|earnings|loss)\b",
    "gross_profit": r"\bgross profit\b",
    "revenue": r"\b(?:revenue|net sales|total sales)\b",
    "ebitda": r"\bebitda\b",
    "assets": r"\b(?:total )?assets\b",
    "liabilities": r"\b(?:total )?liabilities\b",
    "capital_expenditure": r"\b(?:capital expenditure[s]?|capex)\b",
    "diluted_eps": r"\bdiluted (?:earnings per share|eps)\b",
    "earnings_per_share": r"\b(?:earnings per share|eps)\b",
}


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    mode: Mode
    document_ids: list[str] = Field(min_length=1, max_length=30)


class SessionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=160)
    document_ids: list[str] | None = Field(None, min_length=1, max_length=30)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=3000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value):
        if not value.strip():
            raise ValueError("Enter a question.")
        return value.strip()


def get_session(db, identifier):
    session = db.get(ChatSession, identifier)
    if not session:
        raise HTTPException(404, "Research session not found.")
    return session


def session_data(session):
    return {
        key: getattr(session, key)
        for key in (
            "id",
            "title",
            "mode",
            "document_ids",
            "created_at",
            "updated_at",
        )
    }


def message_data(message):
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "details": message.details,
    }


def verify_scope(db, mode, identifiers):
    if mode == "single" and len(identifiers) != 1:
        raise HTTPException(422, "Single-document chat needs exactly one ready PDF.")
    if mode == "research" and len(identifiers) < 2:
        raise HTTPException(422, "Research mode needs at least two ready PDFs.")
    return scoped_documents(db, identifiers)


@router.post("", status_code=201)
def create(request: SessionCreate):
    with transaction() as db:
        verify_scope(db, request.mode, request.document_ids)
        session = ChatSession(**request.model_dump())
        db.add(session)
        db.flush()
        return session_data(session)


@router.get("")
def list_sessions():
    with Session() as db:
        return [
            session_data(session)
            for session in db.scalars(select(ChatSession).order_by(ChatSession.updated_at.desc()))
        ]


@router.get("/{identifier}")
def read(identifier: str):
    with Session() as db:
        return session_data(get_session(db, identifier))


@router.patch("/{identifier}")
def update(identifier: str, request: SessionUpdate):
    with transaction() as db:
        session = get_session(db, identifier)
        if request.document_ids is not None:
            verify_scope(db, session.mode, request.document_ids)
            session.document_ids = request.document_ids
        if request.title is not None:
            session.title = request.title
        session.updated_at = now()
        return session_data(session)


@router.delete("/{identifier}", status_code=204)
def remove(identifier: str):
    with transaction() as db:
        db.delete(get_session(db, identifier))


@router.get("/{identifier}/messages")
def messages(identifier: str):
    with Session() as db:
        get_session(db, identifier)
        return [
            message_data(message)
            for message in db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == identifier)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ]


def answer(status, **fields):
    payload = dict(
        answer=STATUS.get(status, ""),
        answer_status=status,
        answer_type="qualitative",
        numeric_answer=None,
        currency=None,
        unit=None,
        calculations=[],
        supporting_evidence_ids=[],
        citations=[],
        supporting_claims=[],
        missing_information=[],
        limitations=[],
        provider=settings.llm_provider,
    )
    payload.update(fields)
    payload["supporting_evidence_ids"] = list(dict.fromkeys(item["id"] for item in payload["citations"]))
    return payload


def years_in(text):
    return sorted({int(year) for year in re.findall(r"\b(?:FY\s*)?(20\d{2}|19\d{2})\b", text, re.I)})


def plan(question, history):
    query = question.casefold()
    metric = next((key for key, pattern in METRIC_QUERY.items() if re.search(pattern, query)), None)
    years = years_in(question)
    operation = (
        "cagr"
        if re.search(r"\bcagr\b|compound annual", query)
        else "growth"
        if re.search(r"\bgrow(?:th)?\b|\b(?:year.over.year|yoy|percentage change)\b", query)
        else "subtract"
        if re.search(r"\babsolute change\b|\bchange\b|\bdifference\b", query)
        else None
    )
    antecedent = history[-1] if history else ""
    if not metric and re.search(r"\b(it|that|this|they|them|previous|same|last year)\b", query):
        metric = next(
            (key for key, pattern in METRIC_QUERY.items() if re.search(pattern, antecedent, re.I)), None
        )
        years = years or years_in(antecedent)
    if operation and len(years) == 1 and re.search(r"prior|previous|year.over.year|\byoy\b", query):
        years = [years[0] - 1, years[0]]
    if metric in MARGINS and not operation:
        operation = metric
    return metric, operation, years


def company_groups(question, documents):
    groups = {}
    for document in documents.values():
        key = document.company_id or document.id
        groups.setdefault(key, []).append(document)
    matching = {
        key: group for key, group in groups.items() if mentions_company(question, group[0].company_name)
    }
    return matching or groups


def mentions_company(question, name):
    if not name:
        return False
    alias = re.sub(r"\s+(?:inc\.?|corporation|limited|ltd\.?|plc|llc)$", "", name, flags=re.I)
    return bool(re.search(rf"\b{re.escape(alias.casefold())}\b", question.casefold()))


def financial_answer(db, question, documents, metric, operation, years):
    metric_inputs = [metric]
    if operation in MARGINS:
        metric_inputs.extend([MARGINS[operation], "revenue"])
    rows = find_facts(db, documents, metric_inputs, years)
    groups = company_groups(question, documents)
    requested_comparison = re.search(r"\b(?:compare|versus|vs\.?|higher|lower)\b", question, re.I)
    if (
        requested_comparison
        and len(groups) < 2
        and len(years) < 2
        and operation not in {"growth", "cagr", "subtract"}
    ):
        return answer(
            "insufficient_evidence",
            missing_information=["Select the comparison companies or reporting years."],
        )
    facts, calculations = [], []
    try:
        for group_docs in groups.values():
            ids = {document.id for document in group_docs}
            matches = [row for row in rows if row[0].document_id in ids]
            available = sorted({row[0].year for row in matches}, reverse=True)
            chronological = operation in {"growth", "cagr", "subtract"}
            target_years = sorted(years, reverse=True) if years else available[: 2 if chronological else 1]
            if not target_years:
                return answer(
                    "insufficient_evidence",
                    missing_information=[f"No sourced {LABELS[metric].lower()} values."],
                )
            if chronological and len(target_years) != 2:
                return answer(
                    "calculation_unavailable",
                    missing_information=["Two annual reporting years are required."],
                )

            def pick(metric_name, year, candidates=matches):
                return resolve_facts(
                    [row for row in candidates if row[0].metric == metric_name and row[0].year == year]
                )

            if chronological:
                calculations.append(calculate(operation, [pick(metric, year) for year in target_years]))
            elif operation in MARGINS:
                for year in target_years:
                    reported = [
                        row for row in matches if row[0].metric == operation and row[0].year == year
                    ]
                    if reported:
                        facts.append(serialize_fact(*resolve_facts(reported)))
                    else:
                        calculations.append(
                            calculate(operation, [pick(MARGINS[operation], year), pick("revenue", year)])
                        )
            else:
                facts.extend(serialize_fact(*pick(metric, year)) for year in target_years)
    except (ValueError, DecimalException) as error:
        message = str(error) or "The calculation exceeded supported precision."
        status = (
            "conflicting_evidence"
            if message.startswith("Conflicting")
            else "calculation_unavailable"
            if operation
            else "insufficient_evidence"
        )
        return answer(status, missing_information=[message])

    citations = {}
    statements = []
    source_facts = facts + [fact for calculation in calculations for fact in calculation["inputs"]]
    signatures = {(fact["currency"], fact["unit"], fact["basis"], fact["period"]) for fact in source_facts}
    if (
        requested_comparison
        and len(groups) > 1
        and (
            len(signatures) != 1
            or any(
                fact["basis"] == "unknown" or (fact["unit"] != "percent" and not fact["currency"])
                for fact in source_facts
            )
        )
    ):
        return answer(
            "calculation_unavailable",
            missing_information=[
                "Cross-company comparison requires compatible reporting periods, bases, currencies, and units.",
            ],
        )
    for fact in facts:
        cite = fact["citation"]
        citations[cite["id"]] = cite
        value = fact["normalized_value"] if fact["currency"] else fact["value"]
        unit = fact["currency"] or ("%" if fact["unit"] == "percent" else "source units")
        statements.append(
            f"{fact['company'] or cite['document_name']} · FY{fact['year']} · {LABELS[metric]}: {value} {unit}."
        )
    for calculation in calculations:
        inputs = calculation["inputs"]
        for source in inputs:
            cite = source["citation"]
            citations[cite["id"]] = cite
        period = (
            f"FY{inputs[1]['year']}–FY{inputs[0]['year']}"
            if inputs[0]["year"] != inputs[1]["year"]
            else f"FY{inputs[0]['year']}"
        )
        label = calculation["operation"].replace("_", " ").capitalize()
        statements.append(
            f"{inputs[0]['company'] or 'Selected report'} · {period} · {label}: "
            f"{calculation['result']} {calculation['unit']}."
        )
    if requested_comparison and len(groups) > 1:
        ranking = []
        if calculations and not facts and len(calculations) == len(groups):
            periods = {
                tuple(fact["year"] for fact in calculation["inputs"]) for calculation in calculations
            }
            if len(periods) == 1:
                ranking = [(Decimal(item["result"]), item["inputs"][0]["company"]) for item in calculations]
        elif (
            facts
            and not calculations
            and len(facts) == len(groups)
            and len({fact["year"] for fact in facts}) == 1
        ):
            ranking = [(Decimal(fact["normalized_value"]), fact["company"]) for fact in facts]
        if ranking and all(name for _, name in ranking):
            use_lower = bool(re.search(r"\b(?:lower|lowest)\b", question, re.I))
            best = (min if use_lower else max)(value for value, _ in ranking)
            winners = [name for value, name in ranking if value == best]
            if len(winners) == 1:
                statements.append(
                    f"{winners[0]} had the {'lowest' if use_lower else 'highest'} comparable result."
                )
    single = calculations[0] if len(calculations) == 1 and not facts else None
    return answer(
        "answered",
        answer="\n".join(statements),
        answer_type="calculation" if calculations else "financial_fact",
        numeric_answer=single["result"]
        if single
        else (facts[0]["normalized_value"] if len(facts) == 1 else None),
        currency=facts[0]["currency"] if len(facts) == 1 else None,
        unit=single["unit"] if single else (facts[0]["unit"] if len(facts) == 1 else None),
        citations=list(citations.values()),
        calculations=calculations,
    )


def bounded_evidence(db, question, history, documents, years):
    query = question
    if history and re.search(r"\b(?:it|they|that|previous|those|same)\b", question, re.I):
        query = f"{history[-1][:800]} {question}"[:3000]
    queries = [query]
    if len(years) > 1:
        queries += [f"{query[:2500]} FY{year}" for year in years[:2]]
    elif len(documents) > 1 and re.search(r"\b(?:compare|contrast|versus)\b", query, re.I):
        queries.extend(
            f"{query[:2500]} {name}"
            for name in list(
                dict.fromkeys((doc.company_name or doc.filename)[:150] for doc in documents.values())
            )[:2]
        )
    results = {}
    for text in queries:
        for item in search(db, SearchRequest(query=text, document_ids=list(documents), top_k=6)):
            results.setdefault(item["id"], item)
            for context in item["context"]:
                results.setdefault(context["id"], context)
    passages = {}
    excerpts = []
    remaining = settings.evidence_budget_chars
    seen = set()
    for item in results.values():
        limit = min(remaining, 2400)
        text = item["text"][:limit]
        if limit < 120:
            break
        if text in seen:
            continue
        seen.add(text)
        passages[item["id"]] = item
        excerpts.append({"id": item["id"], "text": text})
        remaining -= len(text)
    return passages, excerpts


def verify_citations(db, documents, response):
    for citation in response["citations"]:
        item = db.get(Evidence, citation["id"])
        document = documents.get(item.document_id) if item else None
        if not document or not 1 <= item.page <= document.page_count:
            return answer(
                "processing_error",
                limitations=["A source could not be resolved to an authorized PDF page."],
            )
        if citation["document_id"] != item.document_id or citation["page"] != item.page:
            return answer(
                "processing_error", limitations=["A source page did not match its evidence record."]
            )
    return response


def respond(db, question, history, documents):
    metric, operation, years = plan(question, history)
    selected_companies = {document.company_id for document in documents.values()}
    if any(
        company.id not in selected_companies and mentions_company(question, company.name)
        for company in db.scalars(select(Company))
    ):
        return answer(
            "insufficient_evidence",
            missing_information=["A company named in the question is outside this session's report scope."],
        )
    exploratory = re.search(r"\b(?:why|explain|summarize|reasons?|risk|impact)\b", question, re.I)
    if metric and (operation or not exploratory):
        return verify_citations(
            db,
            documents,
            financial_answer(
                db,
                question,
                documents,
                metric,
                operation,
                years,
            ),
        )
    passages, excerpts = bounded_evidence(db, question, history, documents, years)
    if not excerpts:
        return answer("insufficient_evidence")
    try:
        context_question = question
        if history and re.search(r"\b(?:it|they|that|previous|those|same)\b", question, re.I):
            context_question = "Prior user topic: " + history[-1][:800] + "\nQuestion: " + question
        generated = provider().generate(context_question, excerpts)
        claims = verified_claims(generated, excerpts)
    except ProviderError as error:
        return answer("processing_error", limitations=[str(error)])
    if not claims:
        return answer("insufficient_evidence", missing_information=generated.missing_information)
    citations = [passages[key] for key in dict.fromkeys(claim.evidence_id for claim in claims)]
    result = answer(
        "answered",
        answer="\n".join(claim.text for claim in claims),
        citations=citations,
        supporting_claims=[claim.model_dump() for claim in claims],
        missing_information=generated.missing_information,
        limitations=["Mock provider excerpt"]
        if settings.llm_provider == "mock"
        else ["Cited quotations were checked against extracted source text."],
    )
    return verify_citations(db, documents, result)


@router.post("/{identifier}/query")
def query(identifier: str, body: Question):
    with Session() as db:
        session = get_session(db, identifier)
        scope = list(session.document_ids)
        documents = verify_scope(db, session.mode, scope)
        versions = {key: document.extraction_version for key, document in documents.items()}
        history = list(
            reversed(
                list(
                    db.scalars(
                        select(ChatMessage.content)
                        .where(
                            ChatMessage.session_id == identifier,
                            ChatMessage.role == "user",
                        )
                        .order_by(ChatMessage.created_at.desc())
                        .limit(4)
                    )
                )
            )
        )
        response = respond(db, body.question, history, documents)
    with transaction() as db:
        session = get_session(db, identifier)
        if session.document_ids != scope:
            raise HTTPException(
                409, "The session scope changed while answering. Submit the question again."
            )
        documents = verify_scope(db, session.mode, scope)
        if versions != {key: document.extraction_version for key, document in documents.items()}:
            raise HTTPException(
                409, "A selected document changed while answering. Submit the question again."
            )
        response = verify_citations(db, documents, response)
        response["document_ids"] = scope
        user = ChatMessage(session_id=identifier, role="user", content=body.question, created_at=now())
        assistant = ChatMessage(
            session_id=identifier,
            role="assistant",
            content=response["answer"],
            details=response,
            created_at=now(),
        )
        session.updated_at = assistant.created_at
        db.add_all([user, assistant])
        db.flush()
        return {"user": message_data(user), "assistant": message_data(assistant)}
