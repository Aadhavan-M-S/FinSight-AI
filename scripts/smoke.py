"""Exercise a running instance with the FY2022 Apple and Microsoft public 10-Ks."""

import argparse
import time
from pathlib import Path

import httpx


def run(url, paths):
    with httpx.Client(base_url=url.rstrip("/") + "/api/v1", timeout=90) as client:
        def request(method, path, **kwargs):
            return client.request(method, path, **kwargs).raise_for_status().json()

        assert request("GET", "/health")["database"] == "ok"
        ids = []
        for file, company in zip(paths, ("Apple Inc.", "Microsoft Corporation")):
            with file.open("rb") as source:
                upload = request("POST", "/documents/upload", files={"files": (file.name, source)},
                                 data={"company": company, "year": 2022})
            assert not upload["errors"], upload
            ids.append(upload["documents"][0]["id"])
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            states = [request("GET", f"/documents/{key}/status") for key in ids]
            assert all(state["status"] != "failed" for state in states), states
            if all(state["status"] == "completed" for state in states):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Reports did not finish ingesting within four minutes")

        single = request("POST", "/chat/sessions", json={
            "title": "Apple filing smoke", "mode": "single", "document_ids": ids[:1],
        })
        research = request("POST", "/chat/sessions", json={
            "title": "Apple and Microsoft filing smoke", "mode": "research", "document_ids": ids,
        })

        def answer(session, question):
            payload = request("POST", f"/chat/sessions/{session['id']}/query", json={"question": question})
            result = payload["assistant"]["details"]
            assert result["answer_status"] == "answered", result["missing_information"]
            return result

        revenue = answer(single, "What was Apple revenue in FY2022?")
        assert revenue["numeric_answer"] == "394328000000", revenue["answer"]
        assert {source["page"] for source in revenue["citations"]} == {32}
        assert answer(single, "How much did it grow compared with the previous year?")["numeric_answer"] == "7.793788"
        growth = answer(research, "Compare Apple and Microsoft revenue growth between FY2021 and FY2022.")
        assert {source["document_id"] for source in growth["citations"]} == set(ids)
        assert {item["result"] for item in growth["calculations"]} == {"7.793788", "17.956071"}, growth["answer"]
        results = request("POST", "/retrieval/search", json={
            "query": "net sales statements of operations", "document_ids": ids[:1],
        })["results"]
        assert results and all(source["document_id"] == ids[0] for source in results)
        print("Public 10-K smoke passed: ingestion, revenue, follow-up, comparison, and scoped retrieval.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apple", type=Path)
    parser.add_argument("microsoft", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    run(args.url, (args.apple, args.microsoft))
