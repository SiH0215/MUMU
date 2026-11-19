import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from time import monotonic, sleep

from langchain_core.messages import AIMessage, AIMessageChunk

from app import create_app
from main import Conversation
from memory import ConversationMemory, chunk_conversation


class Embeddings:
    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [[1., 0.] for _ in texts]

    def embed_query(self, text):
        return [1., 0.]


class RegressionChecks(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "test.sqlite3"

    def test_concurrent_save_keeps_matching_transcript_and_chunks(self):
        barrier = Barrier(2)

        class ConcurrentEmbeddings(Embeddings):
            def embed_documents(self, texts):
                barrier.wait(timeout=4)
                return super().embed_documents(texts)

        store = ConversationMemory(self.path, ConcurrentEmbeddings())
        candidates = [
            [{"role": "human", "text": "short"}],
            [{"role": "human", "text": "long text " * 120}],
        ]
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(store.save, "owner", "record", items) for items in candidates]
            for future in futures:
                future.result(timeout=5)
        actual = store.read_transcript("owner", "record")
        self.assertIn(actual, candidates)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT content FROM conversation_chunks ORDER BY chunk_number"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], chunk_conversation(actual))

    def test_repeated_and_empty_saves_do_not_embed_again(self):
        embeddings = Embeddings()
        store = ConversationMemory(self.path, embeddings)
        store.save("owner", "empty", [])
        self.assertEqual(embeddings.calls, 0)
        items = [{"role": "human", "text": "hello"}]
        store.save("owner", "record", items)
        store.save("owner", "record", items)
        self.assertEqual(embeddings.calls, 1)
        self.assertIsNone(store.read_transcript("other", "record"))
        self.assertEqual(len(store.search("owner", "hello")), 1)

    def test_invalid_vectors_leave_no_partial_record(self):
        class InvalidEmbeddings(Embeddings):
            def embed_documents(self, texts):
                return [[0., 0.] for _ in texts]

        store = ConversationMemory(self.path, InvalidEmbeddings())
        with self.assertRaises(ValueError):
            store.save("owner", "record", [{"role": "human", "text": "hello"}])
        self.assertIsNone(store.read_transcript("owner", "record"))

    def test_search_preserves_top_three_order_and_owner(self):
        store = ConversationMemory(self.path, Embeddings())
        for number in range(6):
            store.save("owner", str(number), [{"role": "human", "text": f"item {number}"}])
        store.save("other", "private", [{"role": "human", "text": "private"}])
        results = store.search("owner", "query")
        self.assertEqual([item["text"] for item in results],
                         [f"사용자: item {number}" for number in (5, 4, 3)])

    def test_shared_client_preserves_separate_conversations_and_diary(self):
        loads = []
        requests = []

        class Model:
            def stream(self, messages):
                requests.append(messages)
                yield AIMessageChunk(content="hello ")
                yield AIMessageChunk(content="friend")

            def invoke(self, messages):
                return AIMessage(content="오늘 친구와 이야기했어.")

        def loader():
            loads.append(True)
            return Model(), "test"

        app = create_app(loader, memory_path=self.path, embedder=Embeddings())
        first, second = app.test_client(), app.test_client()
        first.get("/")
        second.get("/")
        self.assertEqual(first.post("/api/chat", json={"text": "first"}).status_code, 200)
        self.assertEqual(second.post("/api/chat", json={"text": "second"}).status_code, 200)
        self.assertEqual(len(loads), 1)
        self.assertNotIn("first", "".join(str(message.content) for message in requests[-1]))
        self.assertEqual(first.post("/api/chat/end", json={}).status_code, 200)
        deadline = monotonic() + 5
        while first.get("/api/chat").json["memory_state"] == "saving" and monotonic() < deadline:
            sleep(.01)
        self.assertEqual(first.get("/api/chat").json["memory_state"], "saved")
        record, = first.get("/api/chat/memories").json["memories"]
        detail = f'/api/chat/memories/transcript/{record["id"]}'
        self.assertEqual(first.post(detail + "/summary", json={}).status_code, 200)
        self.assertEqual(second.get(detail).status_code, 404)
        self.assertEqual(first.post("/api/chat/new", json={}).status_code, 200)
        self.assertEqual(first.post("/api/chat", json={"text": "new"}).status_code, 200)
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(requests[-1]), 2)
        self.assertEqual(json.loads(requests[-1][-1].content)["현재 사용자 입력"], "new")

    def test_cached_diary_does_not_wait_for_another_generation(self):
        started, release = Event(), Event()

        class Model:
            def invoke(self, messages):
                started.set()
                if not release.wait(4):
                    raise RuntimeError("test timeout")
                return AIMessage(content="오늘 친구와 이야기했어.")

        app = create_app(lambda: (Model(), "test"), memory_path=self.path, embedder=Embeddings())
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            owner = session["memory_owner"]
            cookies = dict(session)
        store = ConversationMemory(self.path, Embeddings())
        store.save_diary(owner, "cached", "transcript", "saved diary")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO conversation_display_summaries VALUES (?, ?, ?)",
                       (owner, "legacy", "old summary"))

        def generate():
            writer = app.test_client()
            with writer.session_transaction() as session:
                session.update(cookies)
            return writer.post("/api/chat/memories/transcript/legacy/summary", json={})

        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(generate)
            try:
                self.assertTrue(started.wait(4))
                response = client.post("/api/chat/memories/transcript/cached/summary", json={})
                self.assertEqual(response.json, {"summary": "saved diary"})
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5).status_code, 200)

    def test_failed_stream_leaves_history_unchanged(self):
        class Broken:
            def stream(self, messages):
                yield AIMessageChunk(content="partial")
                raise RuntimeError("test error")

        conversation = Conversation(Broken(), "test")
        chunks = []
        with self.assertRaises(RuntimeError):
            conversation.reply("hello", on_chunk=chunks.append)
        self.assertEqual(chunks, ["partial"])
        self.assertEqual(len(conversation.history), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
