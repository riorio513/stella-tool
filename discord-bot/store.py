"""データの保存と検索（RAGの中核）。

- どのチャンネルを知識ソースに登録したか（sources）
- 取り込んだメッセージ本文とその埋め込みベクトル（documents）
を SQLite に保存し、質問時はコサイン類似度で関連メッセージを取り出す。

外部のベクトルDB（Chroma等）を使わず numpy だけで完結させているので、
依存が少なく、無料ホスティングでも軽量に動く。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

import llm

DB_PATH = os.getenv("DB_PATH", "data/stella_bot.sqlite3")

_lock = threading.Lock()


@dataclass
class Hit:
    content: str
    author: str
    channel_id: int
    score: float


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                message_id INTEGER PRIMARY KEY,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                author     TEXT,
                content    TEXT NOT NULL,
                embedding  BLOB NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_guild ON documents(guild_id)"
        )


# --- ソース（知識にするチャンネル）の管理 ---

def add_source(guild_id: int, channel_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sources(guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )


def remove_source(guild_id: int, channel_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM sources WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        conn.execute(
            "DELETE FROM documents WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )


def list_sources(guild_id: int) -> List[int]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT channel_id FROM sources WHERE guild_id=?", (guild_id,)
        ).fetchall()
    return [r["channel_id"] for r in rows]


def is_source(guild_id: int, channel_id: int) -> bool:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sources WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
    return row is not None


# --- メッセージ（文書）の管理 ---

def _embedding_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def upsert_documents(
    guild_id: int,
    channel_id: int,
    rows: List[tuple],  # (message_id, author, content)
) -> int:
    """メッセージ本文を埋め込みに変換して保存。保存できた件数を返す。"""
    if not rows:
        return 0
    contents = [r[2] for r in rows]
    vectors = llm.embed_texts(contents, is_query=False)
    with _lock, _connect() as conn:
        for (message_id, author, content), vec in zip(rows, vectors):
            conn.execute(
                """
                INSERT OR REPLACE INTO documents
                    (message_id, guild_id, channel_id, author, content, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, guild_id, channel_id, author, content,
                 _embedding_to_blob(vec)),
            )
    return len(rows)


def count_documents(guild_id: int, channel_id: Optional[int] = None) -> int:
    with _lock, _connect() as conn:
        if channel_id is None:
            row = conn.execute(
                "SELECT COUNT(*) c FROM documents WHERE guild_id=?", (guild_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) c FROM documents WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            ).fetchone()
    return row["c"]


def search(guild_id: int, query: str, top_k: int = 8) -> List[Hit]:
    """質問に近いメッセージを類似度順に top_k 件返す。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT channel_id, author, content, embedding FROM documents WHERE guild_id=?",
            (guild_id,),
        ).fetchall()
    if not rows:
        return []

    matrix = np.vstack([_blob_to_embedding(r["embedding"]) for r in rows])
    qvec = llm.embed_texts([query], is_query=True)[0]
    # 文書・クエリとも単位長に正規化済みなので内積＝コサイン類似度
    scores = matrix @ qvec

    k = min(top_k, len(rows))
    top_idx = np.argsort(-scores)[:k]
    hits: List[Hit] = []
    for i in top_idx:
        r = rows[int(i)]
        hits.append(
            Hit(
                content=r["content"],
                author=r["author"] or "不明",
                channel_id=r["channel_id"],
                score=float(scores[int(i)]),
            )
        )
    return hits
