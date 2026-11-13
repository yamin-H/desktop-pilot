from pathlib import Path

import pytest

from deskpilot.rag.embedder import HashingEmbedder
from deskpilot.rag.ingest import ingest_directory
from deskpilot.rag.search import hybrid_search
from deskpilot.rag.store import DocumentStore

DOCS = Path(__file__).resolve().parents[2] / "data" / "docs"
EMBEDDER = HashingEmbedder()

CASES = [
    ("what do I do about a missing_in_ledger break", "runbooks/reconciliation.md"),
    ("how much clock drift is ignored", "runbooks/reconciliation.md"),
    ("how do feeds reconnect and how long do they wait", "runbooks/feed-outages.md"),
    ("recorder buffer overflow dropped ticks", "runbooks/feed-outages.md"),
    ("fee paid in coins instead of USDT", "notes/fees-and-accounting.md"),
    ("how is average cost affected when we sell", "notes/fees-and-accounting.md"),
    ("what happens to unrealized profit when a price is missing", "notes/fees-and-accounting.md"),
]


async def test_the_sample_documents_are_all_ingested(pool):
    results = await ingest_directory(DocumentStore(pool), EMBEDDER, DOCS)
    assert {r.status for r in results} == {"added"}
    assert sorted(r.source for r in results) == [
        "notes/fees-and-accounting.md",
        "runbooks/feed-outages.md",
        "runbooks/reconciliation.md",
    ]


@pytest.mark.parametrize(("query", "expected_source"), CASES)
async def test_the_right_document_is_among_the_top_three_passages(pool, query, expected_source):
    store = DocumentStore(pool)
    await ingest_directory(store, EMBEDDER, DOCS)
    hits = await hybrid_search(store, EMBEDDER, query, limit=3)
    assert expected_source in [hit.source for hit in hits]


async def test_the_best_passage_for_a_specific_question_cites_its_section(pool):
    store = DocumentStore(pool)
    await ingest_directory(store, EMBEDDER, DOCS)
    [top, *_] = await hybrid_search(store, EMBEDDER, "missing_in_ledger break approval")
    assert top.citation == (
        'Reconciliation runbook, section "Reconciliation runbook > Missing in ledger"'
    )
    assert "second person" in top.content
