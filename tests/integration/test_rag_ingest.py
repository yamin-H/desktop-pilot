import pytest

from deskpilot.rag.embedder import EmbeddingError, HashingEmbedder
from deskpilot.rag.ingest import ingest_directory
from deskpilot.rag.store import DocumentStore, or_query


class Counting(HashingEmbedder):
    """Counts how often it is used, and can pretend to be a different model."""

    def __init__(self, name="hashing-384"):
        self.name = name
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


def write(folder, name, text):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def statuses(results):
    return {result.source: result.status for result in results}


async def test_new_files_are_added_with_their_source_path_and_title(pool, tmp_path):
    write(tmp_path, "a.md", "# Alpha\n\nAlpha text about withdrawals.")
    write(tmp_path, "sub/b.txt", "Plain text about limits.")
    store = DocumentStore(pool)

    results = await ingest_directory(store, Counting(), tmp_path)

    assert [(r.source, r.status, r.chunks) for r in results] == [
        ("a.md", "added", 1),
        ("sub/b.txt", "added", 1),
    ]
    assert [(d.source, d.title) for d in await store.list_documents()] == [
        ("a.md", "Alpha"),
        ("sub/b.txt", "b"),
    ]


async def test_ingesting_unchanged_files_again_does_no_work(pool, tmp_path):
    write(tmp_path, "a.md", "# Alpha\n\nSome text.")
    store, embedder = DocumentStore(pool), Counting()
    await ingest_directory(store, embedder, tmp_path)
    calls = embedder.calls

    results = await ingest_directory(store, embedder, tmp_path)

    assert statuses(results) == {"a.md": "unchanged"}
    assert embedder.calls == calls
    assert len(await store.list_documents()) == 1


async def test_a_changed_file_replaces_the_old_text(pool, tmp_path):
    write(tmp_path, "a.md", "# Alpha\n\nZebrafish are here.")
    store = DocumentStore(pool)
    await ingest_directory(store, Counting(), tmp_path)

    write(tmp_path, "a.md", "# Alpha\n\nPelicans are here.")
    results = await ingest_directory(store, Counting(), tmp_path)

    assert statuses(results) == {"a.md": "updated"}
    assert await store.text_search(or_query("zebrafish"), 5) == []
    assert len(await store.text_search(or_query("pelicans"), 5)) == 1


async def test_changed_chunk_settings_re_ingest_everything(pool, tmp_path):
    write(tmp_path, "a.md", "# Alpha\n\nSome text.")
    store = DocumentStore(pool)
    await ingest_directory(store, Counting(), tmp_path)
    results = await ingest_directory(store, Counting(), tmp_path, max_chars=500, overlap=50)
    assert statuses(results) == {"a.md": "updated"}


async def test_a_different_embedding_model_re_ingests_everything(pool, tmp_path):
    write(tmp_path, "a.md", "# Alpha\n\nSome text.")
    store = DocumentStore(pool)
    await ingest_directory(store, Counting("model-one"), tmp_path)
    results = await ingest_directory(store, Counting("model-two"), tmp_path)
    assert statuses(results) == {"a.md": "updated"}


async def test_a_bad_file_is_reported_and_does_not_stop_the_others(pool, tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"this is not a pdf")
    write(tmp_path, "empty.md", "   ")
    write(tmp_path, "ok.md", "# Fine\n\nGood text.")
    store = DocumentStore(pool)

    results = {r.source: r for r in await ingest_directory(store, Counting(), tmp_path)}

    assert results["ok.md"].status == "added"
    assert results["bad.pdf"].status == "failed"
    assert "PDF" in results["bad.pdf"].error
    assert results["empty.md"].status == "failed"
    assert "empty" in results["empty.md"].error
    assert [d.source for d in await store.list_documents()] == ["ok.md"]


async def test_other_file_types_and_hidden_files_are_ignored(pool, tmp_path):
    write(tmp_path, "notes.docx", "binary-ish")
    write(tmp_path, ".hidden.md", "# Hidden\n\ntext")
    write(tmp_path, ".git/config.md", "# Git\n\ntext")
    write(tmp_path, "visible.md", "# Visible\n\ntext")
    results = await ingest_directory(DocumentStore(pool), Counting(), tmp_path)
    assert statuses(results) == {"visible.md": "added"}


async def test_prune_removes_documents_whose_file_is_gone(pool, tmp_path):
    write(tmp_path, "keep.md", "# Keep\n\ntext")
    write(tmp_path, "gone.md", "# Gone\n\ntext")
    store = DocumentStore(pool)
    await ingest_directory(store, Counting(), tmp_path)
    (tmp_path / "gone.md").unlink()

    kept = await ingest_directory(store, Counting(), tmp_path)
    assert statuses(kept) == {"keep.md": "unchanged"}
    assert len(await store.list_documents()) == 2  # without prune, nothing is removed

    pruned = await ingest_directory(store, Counting(), tmp_path, prune=True)
    assert statuses(pruned) == {"keep.md": "unchanged", "gone.md": "removed"}
    assert [d.source for d in await store.list_documents()] == ["keep.md"]


async def test_a_failed_file_is_not_pruned(pool, tmp_path):
    write(tmp_path, "a.md", "# A\n\ntext")
    store = DocumentStore(pool)
    await ingest_directory(store, Counting(), tmp_path)
    write(tmp_path, "a.md", "   ")  # now unreadable as a document, but the file exists

    results = await ingest_directory(store, Counting(), tmp_path, prune=True)

    assert statuses(results) == {"a.md": "failed"}
    assert [d.source for d in await store.list_documents()] == ["a.md"]  # the old version stays


async def test_an_embedder_with_the_wrong_size_is_refused(pool, tmp_path):
    class Wrong(Counting):
        dimension = 768

    write(tmp_path, "a.md", "# A\n\ntext")
    with pytest.raises(EmbeddingError, match="768"):
        await ingest_directory(DocumentStore(pool), Wrong(), tmp_path)
