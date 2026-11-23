import hashlib
import json
import threading
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.benchmarks import evaluation, sources
from app.benchmarks.catalog import MIB
from app.benchmarks.schemas import Passage, Record, RunRequest
from app.benchmarks.scoring import (
    Prediction,
    Step,
    evaluate_program,
    numeric_match,
    retrieval_metrics,
    tatqa_metrics,
)
from app.benchmarks.store import store
from app.main import app

API = "/api/v1"


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "benchmarks"
    monkeypatch.setattr(store, "root", root)
    monkeypatch.setattr(store, "path", root / "workspace.sqlite3")
    with TestClient(app) as client:
        yield client


def wait(client, endpoint, until):
    for _ in range(120):
        response = client.get(endpoint)
        assert response.is_success, response.text
        payload = response.json()
        if payload["state"] in until:
            return payload
        time.sleep(0.025)
    pytest.fail(f"Job did not reach a terminal state at {endpoint}")


def finqa_rows():
    return [
        {
            "id": f"Example/page_1.pdf-{i}",
            "filename": "Example/page_1.pdf",
            "pre_text": [
                "Revenue from continued operations was $125 million.",
                "The statement discussed an unrelated item.",
            ],
            "post_text": ["Notes to the consolidated statements."],
            "table": [["Metric", "2023", "2024"], ["Revenue", "100", "125"]],
            "qa": {
                "question": "What was the 2024 revenue?",
                "answer": "gold answer sentinel",
                "exe_ans": 125,
                "program": "reference program sentinel",
                "gold_inds": {"text_0": "annotation sentinel"},
            },
        }
        for i in range(1, 4)
    ]


def import_finqa(client):
    imported = client.post(
        f"{API}/benchmarks/finqa/import",
        data={"split": "dev"},
        files={"file": ("dev.json", json.dumps(finqa_rows()), "application/json")},
    )
    assert imported.status_code == 202, imported.text
    ready = wait(client, f"{API}/benchmarks/finqa/status", {"ready", "failed"})
    assert ready["state"] == "ready", ready
    return ready


def test_install_search_run_export_and_remove(library):
    client = library
    datasets = client.get(f"{API}/benchmarks").json()
    assert len(datasets) == 7
    assert all(dataset["state"] == "not_installed" for dataset in datasets)
    assert (
        client.post(f"{API}/benchmarks/financebench/install", json={"split": "open_source"}).status_code
        == 422
    )
    assert client.post(f"{API}/benchmarks/finqa/install", json={"split": "arbitrary"}).status_code == 422

    ready = import_finqa(client)
    assert ready["installations"][0]["revision"].startswith("local-import:")
    docs = client.get(f"{API}/documents").json()
    assert not docs
    browse = client.get(
        f"{API}/benchmarks/finqa/samples",
        params={
            "split": "dev",
            "q": "revenue",
            "limit": 1,
            "offset": 1,
        },
    ).json()
    assert browse["total"] == 3 and len(browse["items"]) == 1
    question = browse["items"][0]
    assert question["question_id"].endswith("-2") and "gold_answer" not in question
    sample = client.get(
        f"{API}/benchmarks/finqa/samples/{question['question_id']}", params={"split": "dev"}
    ).json()
    assert sample["evidence"][0]["text"] == "annotation sentinel"
    assert sample["program"] == "reference program sentinel"

    response = client.post(
        f"{API}/evaluations/run",
        json={
            "dataset_id": "finqa",
            "split": "dev",
            "task": "retrieval",
            "limit": 2,
            "top_k": 3,
        },
    )
    assert response.status_code == 202, response.text
    path = f"{API}/evaluations/{response.json()['id']}"
    report = wait(client, path, {"completed", "failed"})
    assert report["state"] == "completed", report
    assert report["attempted"] == report["completed"] == 2
    assert report["metric_counts"] == {"recall@3": 2, "mrr@3": 2, "ndcg@3": 2}
    results = client.get(path + "/results").json()
    assert "annotation sentinel" not in json.dumps([row["retrieved"] for row in results["items"]])
    assert client.get(path + "/export").json()["results"] == results["items"]
    assert client.get(path + "/export?format=csv").text.startswith("id,dataset_id,split,revision,task")
    assert evaluation.csv_cell(" =2+2").startswith("'")

    bad = client.post(
        f"{API}/benchmarks/finqa/import",
        data={"split": "dev"},
        files={"file": ("dev.json", "[123,]", "application/json")},
    )
    assert bad.status_code == 202
    failed = wait(client, f"{API}/benchmarks/finqa/status", {"failed"})
    assert failed["installations"][0]["record_count"] == 3
    assert client.delete(f"{API}/benchmarks/finqa/installation?split=dev").status_code == 204
    assert client.get(f"{API}/benchmarks/finqa/samples?split=dev").status_code == 404
    assert client.get(path + "/results").json()["total"] == 2
    store.initialize()
    assert client.get(path).json()["state"] == "completed"


def test_gold_isolation_and_checked_numeric_scoring():
    record = Record(
        dataset_id="finqa",
        split="dev",
        question_id="one",
        question="What was the difference?",
        gold_answer="gold sentinel",
        previous_questions=["What were the figures?"],
        context=[Passage(id="permitted", text="The difference was between values of 125 and 100.")],
        evidence=[Passage(id="hidden", text="gold evidence sentinel")],
        program="reference program sentinel",
        metadata={"execution_answer": 25, "publisher": {"answer": "another marker"}},
        relevant_ids=["hidden"],
    )

    class Provider:
        def structured(self, _instructions, request, schema, **_options):
            serialized = json.dumps(request)
            assert (
                "sentinel" not in serialized
                and "hidden" not in serialized
                and "25"
                not in json.dumps({key: value for key, value in request.items() if key != "excerpts"})
            )
            assert request["earlier_questions"] == record.previous_questions
            return schema(
                program=[Step(operation="subtract", operands=["125", "100"])],
                evidence_ids=["permitted", "unprovided"],
            )

    class Corpus:
        def for_record(self, item):
            return item.context

    result = evaluation.evaluate_record(
        record,
        RunRequest(
            dataset_id="finqa",
            split="dev",
            task="numerical",
            provider="groq",
        ),
        Corpus(),
        Provider(),
    )
    assert result.metrics == {"execution_value_match_5dp": 1}
    assert result.attributed_ids == ["permitted"]
    assert result.error_category == "unsupported_attribution"
    assert numeric_match("12.5%", "0.125") == 1
    assert numeric_match("$1577", "1.577 billion", question="What was capex (in USD millions)?") == 1
    assert numeric_match("USD 20", "EUR 20") == 0
    assert (
        evaluate_program(
            [Step(operation="add", operands=["1", "2"]), Step(operation="multiply", operands=["#0", "3"])]
        )
        == "9"
    )
    with pytest.raises(ValueError):
        evaluate_program([Step(operation="add", operands=["#0", "3"])])
    assert retrieval_metrics(["b", "a"], {"a", "c"}, 2) == {
        "recall@2": 0.5,
        "mrr@2": 0.5,
        "ndcg@2": pytest.approx(0.3868528072),
    }
    row = record.model_copy(update={"gold_answer": ["alpha", "beta"], "metadata": {"scale": ""}})
    assert tatqa_metrics(row, Prediction(answer=["beta", "alpha"]), ["beta", "alpha"]) == {
        "tatqa_em": 1,
        "tatqa_f1": 1,
    }


def test_cancel_and_interrupted_jobs(library, monkeypatch):
    client = library
    import_finqa(client)
    started = threading.Event()
    released = threading.Event()
    original = evaluation.evaluate_record

    def pause(*args):
        started.set()
        assert released.wait(5)
        return original(*args)

    monkeypatch.setattr(evaluation, "evaluate_record", pause)
    response = client.post(
        f"{API}/evaluations/run",
        json={
            "dataset_id": "finqa",
            "split": "dev",
            "task": "retrieval",
            "limit": 3,
        },
    )
    path = f"{API}/evaluations/{response.json()['id']}"
    try:
        assert started.wait(5)
        assert client.delete(f"{API}/benchmarks/finqa/installation?split=dev").status_code == 409
        assert client.get(path + "/export").status_code == 409
        assert client.post(path + "/cancel").status_code == 202
    finally:
        released.set()
    report = wait(client, path, {"cancelled", "failed", "completed"})
    assert report["state"] == "cancelled" and report["attempted"] == 1
    store.set_job("tatqa", "dev", "downloading")
    with store.connect() as connection:
        connection.execute("UPDATE runs SET state='running' WHERE id=?", (report["id"],))
    store.initialize()
    assert store.job("tatqa")["state"] == "failed"
    assert client.get(path).json()["state"] == "interrupted"
    assert client.get(path + "/results").json()["total"] == 1


def test_download_validation_and_archive_safety(tmp_path, monkeypatch):
    actual_client = httpx.Client
    body = b'{"release":"actual test response"}'

    def use_transport(handler):
        monkeypatch.setattr(
            sources.httpx,
            "Client",
            lambda **options: actual_client(**options, transport=httpx.MockTransport(handler)),
        )

    def fake(request):
        return httpx.Response(200, content=body, request=request)

    use_transport(fake)
    target = tmp_path / "release.json"
    url = "https://raw.githubusercontent.com/publisher/release/train.json"
    checksum = hashlib.sha256(body).hexdigest()
    info = sources.download(sources.Asset(url, "json", checksum=checksum), target, MIB)
    assert info["sha256"] == checksum and target.read_bytes() == body
    with pytest.raises(sources.SourceError, match="checksum"):
        sources.download(sources.Asset(url, "json", checksum="bad"), target, MIB)
    assert not target.exists()
    with pytest.raises(sources.SourceError, match="size limit"):
        sources.download(sources.Asset(url, "json"), target, 1)

    urls = []

    def redirect(request):
        urls.append(str(request.url))
        return httpx.Response(307, headers={"location": "http://127.0.0.1:8000/"}, request=request)

    use_transport(redirect)
    with pytest.raises(sources.SourceError, match="unapproved"):
        sources.download(sources.Asset(url, "json"), target, MIB)
    assert urls == [url]
    assert not target.exists()

    def offline(request):
        raise httpx.ProxyError("blocked", request=request)

    use_transport(offline)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    with pytest.raises(sources.SourceError, match="Check network access"):
        sources.download(sources.Asset(url, "json"), target, MIB)
    assert not target.exists()

    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "untrusted")
        z.writestr("data/dev.json", body)
    sources.unpack_split(archive, "data/dev.json", target, MIB)
    assert target.read_bytes() == body and not Path(tmp_path.parent / "escape").exists()
    with pytest.raises(sources.SourceError):
        sources.unpack_split(archive, "data/dev.json", target, 1)
