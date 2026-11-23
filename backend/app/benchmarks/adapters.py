import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import ijson

from ..extraction import stable
from .catalog import Dataset
from .schemas import Passage, Record

FILING_NAME = re.compile(r"[A-Za-z0-9_. -]{1,160}")


def read_rows(path: Path, file_type: str) -> Iterator[dict]:
    if file_type == "parquet":
        from pyarrow.parquet import ParquetFile

        with ParquetFile(path) as parquet:
            for batch in parquet.iter_batches(batch_size=8):
                yield from batch.to_pylist()
        return
    if file_type == "jsonl":
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        return
    with path.open("rb") as stream:
        first = next(ijson.parse(stream), None)
        if first != ("", "start_array", None):
            raise ValueError("The original split must contain a JSON array of records.")
        stream.seek(0)
        yield from ijson.items(stream, "item", use_float=True)


def spans(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for part in value for item in spans(part)]
    if isinstance(value, dict):
        for key in ("text", "content", "evidence_text", "paragraph", "passage", "snippet"):
            if key in value:
                return spans(value[key])
    return []


def text_passages(prefix: str, values: list[str]) -> list[Passage]:
    return [
        Passage(id=f"{prefix}_{i}", text=value)
        for i, value in enumerate(values)
        if isinstance(value, str) and value.strip()
    ]


def table_passages(table: list) -> list[Passage]:
    if not table or not isinstance(table[0], list):
        return []
    headers = [str(cell) for cell in table[0]]
    if len(headers) > 1 and not headers[0].strip():
        headers[0] = "Row label"
    result = []
    for i, row in enumerate(table):
        if not isinstance(row, list) or not row:
            continue
        if i == 0:
            text = " | ".join(headers)
        else:
            label = str(row[0])
            values = [
                f"{headers[j]}: {value}" if j < len(headers) and headers[j] else str(value)
                for j, value in enumerate(row[1:], 1)
            ]
            text = " | ".join([label, *values])
        if text.strip():
            result.append(Passage(id=f"table_{i}", kind="table", text=text))
    return result


def contexts(row: dict) -> tuple[list[Passage], list]:
    table = row.get("table") or []
    if not isinstance(table, list):
        raise ValueError("Expected a tabular array in the original record.")
    text = list(row.get("pre_text") or []) + list(row.get("post_text") or [])
    return text_passages("text", text) + table_passages(table), [
        row.get("table_ori") or table
    ] if table else []


def labels(qa: dict) -> tuple[list[Passage], list[str]]:
    gold = qa.get("gold_inds") or {}
    if not isinstance(gold, dict):
        raise ValueError("Expected indexed evidence annotations.")
    return [
        Passage(id=key, text=text, kind="table" if key.startswith("table_") else "text")
        for key, text in gold.items()
        if isinstance(text, str) and text.strip()
    ], list(gold)


def raw_record(dataset: Dataset, split: str, uid: str, question: str, **fields) -> Record:
    if uid is None or not str(uid).strip():
        raise ValueError("The publisher record is missing its identifier.")
    return Record(dataset_id=dataset.id, split=split, question_id=str(uid), question=question, **fields)


def finqa(dataset, split, row, _extras):
    qa = row["qa"]
    context, tables = contexts(row)
    evidence, relevant_ids = labels(qa)
    yield raw_record(
        dataset,
        split,
        row["id"],
        qa["question"],
        context=context,
        tables=tables,
        evidence=evidence,
        relevant_ids=relevant_ids,
        gold_answer=qa.get("answer") if split != "private_test" else None,
        program=qa.get("program") if split != "private_test" else None,
        answer_type="numeric" if isinstance(qa.get("exe_ans"), (int, float)) else None,
        source={"filing": row.get("filename")},
        metadata={"publisher": row, "execution_answer": qa.get("exe_ans")},
    )


def tatqa(dataset, split, row, _extras):
    table = row["table"]["table"]
    paragraphs = row["paragraphs"]
    context = [
        Passage(id=f"text_{item['order']}", text=item["text"])
        for item in paragraphs
        if item["text"].strip()
    ] + table_passages(table)
    for item in row["questions"]:
        annotated = {f"text_{index}" for index in item.get("rel_paragraphs", [])}
        yield raw_record(
            dataset,
            split,
            item["uid"],
            item["question"],
            gold_answer=item.get("answer"),
            answer_type=item.get("answer_type"),
            program=item.get("derivation"),
            context=context,
            tables=[table],
            evidence=[passage for passage in context if passage.id in annotated],
            source={"table_id": row["table"].get("uid")},
            metadata={"scale": item.get("scale"), "publisher": item, "paragraphs": paragraphs},
        )


def convfinqa(dataset, split, row, _extras):
    context, tables = contexts(row)
    annotation = row["annotation"]
    questions = annotation["dialogue_break"]
    answers = annotation.get("exe_ans_list") or []
    programs = annotation.get("turn_program") or []
    if not isinstance(questions, list) or not questions:
        raise ValueError("A conversation must have an ordered list of questions.")
    for i, question in enumerate(questions):
        yield raw_record(
            dataset,
            split,
            f"{row['id']}:{i + 1}",
            question,
            context=context,
            tables=tables,
            previous_questions=questions[:i],
            gold_answer=answers[i] if i < len(answers) and split != "test" else None,
            answer_type="numeric",
            program=programs[i] if i < len(programs) and split != "test" else None,
            source={"filing": row.get("filename")},
            metadata={
                "conversation_id": row["id"],
                "turn": i + 1,
                "turn_count": len(questions),
                "publisher": row,
            },
        )


def pdf_url(dataset, document):
    if not isinstance(document, str) or not FILING_NAME.fullmatch(document) or document in {".", ".."}:
        raise ValueError("Invalid FinanceBench filing identifier.")
    return dataset.raw(f"pdfs/{quote(document, safe='')}.pdf")


def financebench(dataset, split, row, extras):
    if row["dataset_subset_label"] != "OPEN_SOURCE":
        raise ValueError("Only the official open-source FinanceBench release is supported.")
    document = row["doc_name"]
    evidence = []
    documents = {document}
    for item in row["evidence"]:
        # The released JSONL uses doc_name. The README also documents evidence_doc_name.
        name = item.get("doc_name") or item.get("evidence_doc_name") or document
        index = item["evidence_page_num"]
        if not isinstance(index, int) or index < 0:
            raise ValueError("Invalid zero-based FinanceBench PDF page annotation.")
        documents.add(name)
        evidence.append(
            Passage(
                id=f"{name}:{index}",
                text=item["evidence_text"],
                kind="pdf_page",
                document=name,
                page_index=index,
            )
        )
    yield raw_record(
        dataset,
        split,
        row["financebench_id"],
        row["question"],
        gold_answer=row["answer"],
        answer_type=row.get("question_type"),
        evidence=evidence,
        relevant_ids=list(dict.fromkeys(item.id for item in evidence)),
        source={
            "filing": document,
            "company": row.get("company"),
            "filings": [
                {"id": name, "pdf_url": pdf_url(dataset, name), **extras.get(name, {})}
                for name in sorted(documents)
            ],
        },
        metadata={"publisher": row},
    )


def exported_field(row, *names):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def hub_identifier(row: dict, split: str, question: str):
    identifier = exported_field(row, "id", "question_id", "uid", "query_id")
    return (
        identifier
        if identifier is not None
        else stable(split, question, json.dumps(row, sort_keys=True, default=str))
    )


def finder(dataset, split, row, _extras):
    row_lower = {key.casefold(): value for key, value in row.items()}
    question = exported_field(row_lower, "question", "query")
    answer = exported_field(row_lower, "answer", "reference_answer", "gold_answer", "answers")
    annotations = exported_field(
        row_lower,
        "evidence",
        "supporting_evidence",
        "evidences",
        "context",
        "relevant_passages",
        "supporting_facts",
        "gold_evidence",
    )
    evidence = spans(annotations)
    if not isinstance(question, str) or answer is None or not evidence:
        raise ValueError("Expected FinDER questions, reference answers, and text evidence in the export.")
    yield raw_record(
        dataset,
        split,
        hub_identifier(row_lower, split, question),
        question,
        gold_answer=answer,
        evidence=text_passages("annotated", evidence),
        source={
            key: row_lower[key]
            for key in ("doc_name", "document_id", "company", "source_url", "ticker")
            if key in row_lower
        },
        metadata={"publisher": row},
    )


def docfinqa(dataset, split, row, _extras):
    qa = row["qa"] if isinstance(row.get("qa"), dict) else row
    question = qa["question"]
    context, tables = contexts(row)
    text = exported_field(
        row, "doc", "document", "doc_text", "document_text", "long_text", "context", "filing"
    )
    long_text = "\n".join(spans(text))
    if long_text:
        context = text_passages(
            "document", [long_text[offset : offset + 1800] for offset in range(0, len(long_text), 1600)]
        ) + [item for item in context if item.kind == "table"]
    if not context:
        raise ValueError("Expected source context or financial table segments in the DocFinQA export.")
    evidence, relevant_ids = labels(qa) if isinstance(qa.get("gold_inds"), dict) else ([], [])
    yield raw_record(
        dataset,
        split,
        hub_identifier(row, split, question),
        question,
        gold_answer=exported_field(qa, "answer", "gold_answer", "exe_ans"),
        answer_type="numeric",
        program=qa.get("program"),
        context=context,
        tables=tables,
        evidence=evidence,
        relevant_ids=relevant_ids,
        source={
            key: row[key] for key in ("filename", "doc_name", "document_id", "source_url") if key in row
        },
        metadata={"publisher": row, "execution_answer": qa.get("exe_ans")},
    )


def multihiertt(dataset, split, row, _extras):
    qa = row["qa"]
    paragraphs = row["paragraphs"]
    descriptions = row["table_description"]
    tables = row["tables"]
    if (
        not isinstance(paragraphs, list)
        or not isinstance(descriptions, dict)
        or not isinstance(tables, list)
    ):
        raise ValueError("Expected MultiHiertt paragraphs, table cell descriptions, and source tables.")
    context = text_passages("text", paragraphs) + [
        Passage(id=f"table_{key}", kind="table", text=value)
        for key, value in descriptions.items()
        if isinstance(value, str) and value.strip()
    ]
    relevant = {f"text_{key}" for key in qa.get("text_evidence") or []}
    relevant.update(f"table_{key}" for key in qa.get("table_evidence") or [])
    yield raw_record(
        dataset,
        split,
        row["uid"],
        qa["question"],
        gold_answer=qa.get("answer"),
        answer_type="numeric",
        program=qa.get("program"),
        context=context,
        tables=tables,
        evidence=[p for p in context if p.id in relevant],
        relevant_ids=sorted(relevant),
        metadata={"publisher": row},
    )


ADAPTERS = {
    "finqa": finqa,
    "tatqa": tatqa,
    "financebench": financebench,
    "convfinqa": convfinqa,
    "finder": finder,
    "docfinqa": docfinqa,
    "multihiertt": multihiertt,
}
