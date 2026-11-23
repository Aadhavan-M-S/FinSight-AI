import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.generation import Claim, GroundedAnswer, verified_claims
from app.main import app
from app.retrieval import reciprocal_rank_fusion

API = "/api/v1"


def report(name, figures, note):
    pdf = pymupdf.open()
    page = pdf.new_page()
    for text, x, y in [
        (name, 65, 65),
        ("CONSOLIDATED STATEMENTS OF OPERATIONS", 65, 90),
        ("In millions of USD", 65, 110),
        ("2023", 345, 145),
        ("2024", 465, 145),
        ("Revenue", 65, 175),
        (str(figures[0]), 345, 175),
        (str(figures[1]), 465, 175),
        ("Operating income", 65, 200),
        (str(figures[2]), 345, 200),
        (str(figures[3]), 465, 200),
        (note, 65, 245),
    ]:
        page.insert_text((x, y), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def finish(client, doc_id):
    for _ in range(200):
        result = client.get(f"{API}/documents/{doc_id}/status").json()
        if result["status"] in {"completed", "failed"}:
            assert result["status"] == "completed", result
            return result
        time.sleep(0.05)
    pytest.fail("Ingestion did not finish")


def test_scoped_pdf_to_answer():
    with TestClient(app) as client:
        files = [
            (
                "files",
                (
                    "Northwind FY2024.pdf",
                    report(
                        "Northwind Inc.",
                        (100, 120, 20, 30),
                        "The company disclosed a supplier concentration risk.",
                    ),
                    "application/pdf",
                ),
            ),
            (
                "files",
                (
                    "Contoso FY2024.pdf",
                    report(
                        "Contoso Inc.",
                        (200, 210, 50, 60),
                        "The company disclosed currency exposure and credit risk.",
                    ),
                    "application/pdf",
                ),
            ),
            ("files", ("bad.pdf", b"invalid", "application/pdf")),
        ]
        uploaded = client.post(f"{API}/documents/upload", files=files)
        assert uploaded.status_code == 202
        assert len(uploaded.json()["errors"]) == 1
        first, second = [finish(client, item["id"])["id"] for item in uploaded.json()["documents"]]
        first_pdf = client.get(f"{API}/documents/{first}/file")
        assert first_pdf.status_code == 200 and first_pdf.content.startswith(b"%PDF")
        before = client.get(f"{API}/documents/{first}/pages/1").json()["evidence"]
        assert any(
            item["kind"] == "table" and item["structure"]["years"] == [2023, 2024] for item in before
        )
        lookup = client.post(
            f"{API}/retrieval/search", json={"query": "supplier concentration", "document_ids": [first]}
        )
        assert lookup.status_code == 200
        assert lookup.json()["results"] and all(
            item["document_id"] == first for item in lookup.json()["results"]
        )

        def session(mode, ids):
            return client.post(
                f"{API}/chat/sessions", json={"title": mode, "mode": mode, "document_ids": ids}
            )

        assert session("single", [first, second]).status_code == 422
        single = session("single", [first]).json()["id"]

        def ask(sid, question):
            response = client.post(f"{API}/chat/sessions/{sid}/query", json={"question": question})
            response.raise_for_status()
            return response.json()["assistant"]["details"]

        revenue = ask(single, "What was the revenue in FY2024?")
        assert revenue["numeric_answer"] == "120000000", revenue
        assert {source["document_id"] for source in revenue["citations"]} == {first}
        assert (
            ask(single, "How much did it grow compared with the previous year?")["numeric_answer"] == "20"
        )
        assert (
            ask(single, "What was Contoso's revenue in FY2024?")["answer_status"] == "insufficient_evidence"
        )
        mock = ask(single, "Explain the supplier concentration risk.")
        assert mock["provider"] == "mock" and mock["answer_status"] == "answered"
        sid = session("research", [first, second]).json()["id"]
        result = ask(sid, "Compare revenue growth between FY2023 and FY2024.")
        assert {item["result"] for item in result["calculations"]} == {"5", "20"}
        assert {source["document_id"] for source in result["citations"]} == {first, second}
        outside = next(source for source in result["citations"] if source["document_id"] == second)
        assert (
            client.get(f"{API}/evidence/{outside['id']}", params={"session_id": single}).status_code == 404
        )
        assert client.get(f"{API}/evidence/{outside['id']}", params={"session_id": sid}).status_code == 200
        assert len(client.get(f"{API}/chat/sessions/{single}/messages").json()) == 8
        assert (
            client.patch(f"{API}/chat/sessions/{single}", json={"document_ids": [second]}).status_code
            == 200
        )
        revised = ask(single, "What was FY2024 revenue?")
        assert revised["numeric_answer"] == "210000000"
        assert client.post(f"{API}/documents/{first}/reprocess").status_code == 202
        finish(client, first)
        after = client.get(f"{API}/documents/{first}/pages/1").json()["evidence"]
        assert {item["id"] for item in before} == {item["id"] for item in after}
        assert client.delete(f"{API}/documents/{second}").status_code == 204
        assert client.get(f"{API}/evidence/{outside['id']}").status_code == 404
        assert client.get(f"{API}/documents/{second}/file").status_code == 404
        assert client.get(f"{API}/chat/sessions/{single}/messages").json()[1]["details"]["citations"]


def test_verification_rejects_fabricated_quotes_and_numbers():
    excerpt = {"id": "in-scope", "text": "Total net sales of 394,328 were reported."}
    claims = [
        Claim(text="Net sales were 394,328", evidence_id="in-scope", quote=excerpt["text"]),
        Claim(text="Net sales were 500,000", evidence_id="in-scope", quote=excerpt["text"]),
        Claim(text="Net sales were 394,328", evidence_id="unknown", quote=excerpt["text"]),
    ]
    assert verified_claims(GroundedAnswer(claims=claims), [excerpt]) == claims[:1]
    assert reciprocal_rank_fusion(["a", "b"], ["c", "b"], constant=60)[0] == "b"
