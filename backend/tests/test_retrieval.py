from types import SimpleNamespace

import numpy as np
import pytest

from app import retrieval
from app.extraction import stable


def test_faiss_scope_applied_before_ranking(tmp_path, monkeypatch):
    pytest.importorskip("faiss")

    class Encoder:
        def encode(self, texts, **kwargs):
            return np.array([[1, 0] if "match" in text else [0, 1] for text in texts], dtype=np.float32)

    monkeypatch.setattr(retrieval.settings, "dense_retrieval", True)
    monkeypatch.setattr(retrieval, "index_dir", tmp_path)
    monkeypatch.setattr(retrieval, "neural_model", lambda _: Encoder())
    key = stable("document")
    test_items = sorted([(stable("near"), "match"), (stable("far"), "other")])
    retrieval.build_index(
        key, 1, [{"id": identifier, "normalized": text} for identifier, text in test_items]
    )
    docs = {key: SimpleNamespace(extraction_version=1)}
    evidence = [SimpleNamespace(id=identifier, document_id=key) for identifier, _ in test_items]
    permitted = {next(identifier for identifier, text in test_items if text == "other")}
    assert retrieval.dense_ranking("match", docs, evidence, permitted, 1) == list(permitted)
    retrieval.clean_indexes(key)
    assert not list(tmp_path.iterdir())


def test_neural_stack_with_local_test_weights(tmp_path, monkeypatch):
    pytest.importorskip("faiss")
    pytest.importorskip("sentence_transformers")
    from transformers import BertConfig, BertForSequenceClassification, BertModel, BertTokenizer

    vocab = {
        token: i
        for i, token in enumerate(
            [
                "[PAD]",
                "[UNK]",
                "[CLS]",
                "[SEP]",
                "[MASK]",
                "revenue",
                "cash",
                "income",
                "growth",
            ]
        )
    }
    tokenizer = BertTokenizer(vocab=vocab, model_max_length=64)
    common = dict(
        vocab_size=len(vocab),
        hidden_size=16,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=24,
        max_position_embeddings=64,
    )
    embedding_path = tmp_path / "encoder"
    reranking_path = tmp_path / "reranker"
    BertModel(BertConfig(**common)).save_pretrained(embedding_path)
    BertForSequenceClassification(BertConfig(**common, num_labels=1)).save_pretrained(reranking_path)
    tokenizer.save_pretrained(embedding_path)
    tokenizer.save_pretrained(reranking_path)
    monkeypatch.setattr(retrieval.settings, "embedding_model", str(embedding_path))
    monkeypatch.setattr(retrieval.settings, "reranker_model", str(reranking_path))
    monkeypatch.setattr(retrieval.settings, "dense_retrieval", True)
    monkeypatch.setattr(retrieval, "index_dir", tmp_path)
    key = stable("neural test document")
    evidence = sorted([(stable("revenue"), "revenue growth"), (stable("cash"), "cash income")])
    documents = {key: SimpleNamespace(extraction_version=1)}
    items = [SimpleNamespace(id=identifier, document_id=key) for identifier, _ in evidence]
    try:
        retrieval.build_index(
            key, 1, [{"id": identifier, "normalized": text} for identifier, text in evidence]
        )
        ranked = retrieval.dense_ranking("revenue", documents, items, {item.id for item in items}, 2)
        assert set(ranked) == {item.id for item in items}
        scores = retrieval.reranker_model().predict([("revenue", text) for _, text in evidence])
        assert len(scores) == 2 and np.isfinite(scores).all()
    finally:
        retrieval.embedding_model.cache_clear()
        retrieval.reranker_model.cache_clear()
