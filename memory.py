import json
import math
import sqlite3
import struct
from contextlib import closing
from datetime import datetime
from heapq import nlargest
from secrets import token_hex
from textwrap import wrap
from threading import Lock

from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage, SystemMessage

from main import KOREA_TIME, ROOT

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
MIN_SIMILARITY = 0.84
CHUNK_CHARS = 360
DIARY_VERSION = 1

FAREWELLS = {
    "종료", "잘 가", "잘가", "그만", "나중에 봐", "다음에 더 얘기하자",
    "다음에 또 얘기하자", "이제 그만 가봐야겠다", "나 이제 잘게", "나 이제 잘래",
    "나 이제 갈게", "피곤하다 자야겠어", "피곤하다, 자야겠어", "/exit",
}


def is_farewell(text):
    return " ".join(text.strip().rstrip(".!?…~。！？").split()) in FAREWELLS


def write_diary_summary(model, source):
    prompt = (ROOT / "MEMORYPROMPT.txt").read_text(encoding="utf-8-sig")
    summary = model.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=json.dumps(source, ensure_ascii=False)),
    ]).text.strip()
    if not summary:
        raise ValueError("대화 요약이 비어 있습니다.")
    return summary


class LocalEmbeddings(Embeddings):
    def __init__(self):
        self._model = None
        self._lock = Lock()

    def _load(self):
        if self._model is None:
            from langchain_huggingface import HuggingFaceEmbeddings

            self._model = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                cache_folder=str(ROOT / ".cache" / "embeddings"),
                model_kwargs={"device": "cpu", "model_kwargs": {"use_safetensors": True}},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
        return self._model

    def embed_documents(self, texts):
        with self._lock:
            return self._load().embed_documents([f"passage: {text}" for text in texts])

    def embed_query(self, text):
        with self._lock:
            return self._load().embed_query(f"query: {text}")


def transcript_lines(messages):
    return [f"{'사용자' if item['role'] == 'human' else '무무'}: {item['text']}" for item in messages]


def chunk_conversation(messages):
    turns = []
    for item, line in zip(messages, transcript_lines(messages)):
        speaker, separator, text = line.partition(": ")
        prefix = speaker + separator
        parts = [prefix + part for part in wrap(text, CHUNK_CHARS - len(prefix),
                                                replace_whitespace=False, drop_whitespace=False,
                                                expand_tabs=False)]
        if parts and item["role"] != "human" and turns and len(turns[-1]) + 1 + len(parts[0]) <= CHUNK_CHARS:
            turns[-1] += "\n" + parts.pop(0)
        turns.extend(parts)

    chunks, pending = [], []
    for part in turns:
        if pending and (len(pending) == 4 or len("\n".join([*pending, part])) > CHUNK_CHARS):
            chunks.append("\n".join(pending))
            previous = pending[-1]
            pending = [previous] if len(previous) + 1 + len(part) <= CHUNK_CHARS else []
        pending.append(part)
    if pending:
        chunks.append("\n".join(pending))
    return chunks


def unit_vector(values):
    values = tuple(values)
    norm = math.sqrt(sum(value * value for value in values))
    if not norm or not math.isfinite(norm):
        raise ValueError("유효한 임베딩 벡터가 필요합니다.")
    return tuple(value / norm for value in values)


def pack_vector(values):
    vector = unit_vector(values)
    return struct.pack(f"<{len(vector)}f", *vector)


class ConversationMemory:
    def __init__(self, path, embedder=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.embedder = LocalEmbeddings() if embedder is None else embedder
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_memory (
                    owner TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (owner, conversation_id)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_transcripts (
                    owner TEXT NOT NULL, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    transcript TEXT NOT NULL, PRIMARY KEY (owner, conversation_id)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_chunks (
                    owner TEXT NOT NULL, conversation_id TEXT NOT NULL, chunk_number INTEGER NOT NULL,
                    content TEXT NOT NULL, embedding_model TEXT NOT NULL, vector BLOB NOT NULL,
                    PRIMARY KEY (owner, conversation_id, chunk_number)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_display_summaries (
                    owner TEXT NOT NULL, conversation_id TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY (owner, conversation_id)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_diaries (
                    owner TEXT NOT NULL, conversation_id TEXT NOT NULL, source_kind TEXT NOT NULL,
                    content TEXT NOT NULL, format_version INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (owner, conversation_id, source_kind)
                )"""
            )
            diary_columns = {column[1] for column in db.execute("PRAGMA table_info(conversation_diaries)")}
            if "format_version" not in diary_columns:
                db.execute("ALTER TABLE conversation_diaries ADD COLUMN format_version INTEGER NOT NULL DEFAULT 0")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('session_secret', ?)", (token_hex(32),))
            (self.session_secret,) = db.execute(
                "SELECT value FROM settings WHERE name = 'session_secret'",
            ).fetchone()

    def save(self, owner, conversation_id, messages):
        with closing(sqlite3.connect(self.path)) as db:
            if db.execute(
                "SELECT 1 FROM conversation_transcripts WHERE owner = ? AND conversation_id = ?",
                (owner, conversation_id),
            ).fetchone():
                return
        chunks = chunk_conversation(messages)
        if not chunks:
            return
        vectors = self.embedder.embed_documents(chunks)
        chunk_rows = [
            (owner, conversation_id, number, text, EMBEDDING_MODEL, pack_vector(vector))
            for number, (text, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        created_at = datetime.now(KOREA_TIME).isoformat(timespec="seconds")
        with closing(sqlite3.connect(self.path)) as db, db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO conversation_transcripts VALUES (?, ?, ?, ?)",
                (owner, conversation_id, created_at, json.dumps(messages, ensure_ascii=False)),
            )
            if not inserted.rowcount:
                return
            db.executemany(
                "INSERT OR IGNORE INTO conversation_chunks VALUES (?, ?, ?, ?, ?, ?)",
                chunk_rows,
            )

    def list_records(self, owner):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                """SELECT conversation_id, created_at, 'transcript' AS kind, (
                       EXISTS (SELECT 1 FROM conversation_diaries AS d
                               WHERE d.owner = t.owner AND d.conversation_id = t.conversation_id
                               AND d.source_kind = 'transcript')
                       OR EXISTS (SELECT 1 FROM conversation_display_summaries AS s
                                  WHERE s.owner = t.owner AND s.conversation_id = t.conversation_id)
                   ) AS has_diary
                   FROM conversation_transcripts AS t WHERE owner = ?
                   UNION ALL
                   SELECT conversation_id, created_at, 'summary', 1 FROM conversation_memory WHERE owner = ?
                   ORDER BY created_at DESC, conversation_id DESC""",
                (owner, owner),
            ).fetchall()
        return [{"id": record_id, "date": date, "kind": kind, "has_diary": bool(has_diary)}
                for record_id, date, kind, has_diary in rows]

    def read_transcript(self, owner, record_id):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT transcript FROM conversation_transcripts WHERE owner = ? AND conversation_id = ?",
                (owner, record_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def read_diary(self, owner, record_id, kind):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                """SELECT content, format_version FROM conversation_diaries
                   WHERE owner = ? AND conversation_id = ? AND source_kind = ?""",
                (owner, record_id, kind),
            ).fetchone()

    def legacy_summary(self, owner, record_id, kind):
        queries = {
            "transcript": "SELECT content FROM conversation_display_summaries WHERE owner = ? AND conversation_id = ?",
            "summary": "SELECT summary FROM conversation_memory WHERE owner = ? AND conversation_id = ?",
        }
        if kind not in queries:
            return None
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(queries[kind], (owner, record_id)).fetchone()
        return row[0] if row else None

    def save_diary(self, owner, record_id, kind, summary):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """INSERT INTO conversation_diaries (owner, conversation_id, source_kind, content, format_version)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (owner, conversation_id, source_kind) DO UPDATE SET
                       content = excluded.content, format_version = excluded.format_version
                   WHERE conversation_diaries.format_version < excluded.format_version""",
                (owner, record_id, kind, summary, DIARY_VERSION),
            )

    def reindex_legacy(self, owner):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                """SELECT conversation_id, summary FROM conversation_memory
                   WHERE owner = ? AND embedding_model != ?""",
                (owner, EMBEDDING_MODEL),
            ).fetchall()
        if rows:
            vectors = self.embedder.embed_documents([summary for _, summary in rows])
            with closing(sqlite3.connect(self.path)) as db, db:
                db.executemany(
                    """UPDATE conversation_memory SET embedding_model = ?, vector = ?
                       WHERE owner = ? AND conversation_id = ?""",
                    ((EMBEDDING_MODEL, pack_vector(vector), owner, conversation_id)
                     for (conversation_id, _), vector in zip(rows, vectors, strict=True)),
                )

    def search(self, owner, text):
        self.reindex_legacy(owner)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                """SELECT t.created_at, c.content, c.vector, 'transcript'
                   FROM conversation_chunks c JOIN conversation_transcripts t USING (owner, conversation_id)
                   WHERE c.owner = ? AND c.embedding_model = ?
                   UNION ALL
                   SELECT created_at, summary, vector, 'summary' FROM conversation_memory
                   WHERE owner = ? AND embedding_model = ?""",
                (owner, EMBEDDING_MODEL, owner, EMBEDDING_MODEL),
            ).fetchall()
        if not rows:
            return []

        query = unit_vector(self.embedder.embed_query(text))
        vector = struct.Struct(f"<{len(query)}f")
        matches = []
        for date, content, packed, kind in rows:
            if len(packed) != vector.size:
                continue
            similarity = sum(a * b for a, b in zip(query, vector.unpack(packed)))
            if similarity >= MIN_SIMILARITY:
                matches.append((similarity, date, content, kind))
        matches = nlargest(3, matches)
        if not matches:
            return []
        cutoff = matches[0][0] - 0.035
        return [{"date": date, "text": content, "kind": kind}
                for similarity, date, content, kind in matches if similarity >= cutoff]
