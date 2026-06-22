"""Gemini API のラッパー。

埋め込み（ベクトル化）と回答生成をここに集約しているので、
別のLLMに差し替えたい場合はこのファイルだけ書き換えればよい。
"""
from __future__ import annotations

import os
from typing import List

import numpy as np
from google import genai
from google.genai import types

# --- 設定（環境変数で上書き可） ---
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
# 埋め込みの次元。小さくするほど省メモリ・高速（精度はわずかに低下）。
EMBED_DIM = int(os.getenv("GEMINI_EMBED_DIM", "768"))

_client: genai.Client | None = None


def _client_get() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("環境変数 GEMINI_API_KEY が設定されていません。")
        _client = genai.Client(api_key=api_key)
    return _client


def _normalize(vec: List[float]) -> np.ndarray:
    """ベクトルを単位長に正規化（cosine類似度を内積で計算できるようにする）。"""
    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return arr
    return arr / norm


def embed_texts(texts: List[str], *, is_query: bool = False) -> List[np.ndarray]:
    """テキスト群を埋め込みベクトルに変換して返す。

    is_query=True なら検索クエリ用、False なら蓄積する文書用の埋め込みになる。
    """
    if not texts:
        return []
    task = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
    client = _client_get()
    vectors: List[np.ndarray] = []
    # APIの1リクエスト上限に配慮してバッチ分割
    batch = 100
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        resp = client.models.embed_content(
            model=EMBED_MODEL,
            contents=chunk,
            config=types.EmbedContentConfig(
                task_type=task,
                output_dimensionality=EMBED_DIM,
            ),
        )
        for emb in resp.embeddings:
            vectors.append(_normalize(emb.values))
    return vectors


SYSTEM_PROMPT = (
    "あなたはDiscordサーバーの質疑応答アシスタントです。"
    "以下の『参考情報』はサーバー内の指定チャンネルから抽出した実際の発言です。"
    "ユーザーの質問には、必ずこの参考情報だけを根拠に、日本語で簡潔に回答してください。\n"
    "重要なルール:\n"
    "1. 参考情報に答えが含まれていない場合は、推測せず「提供された情報の中には見当たりませんでした」と正直に答える。\n"
    "2. 参考情報に書かれていないことを創作しない（ハルシネーション厳禁）。\n"
    "3. 回答の根拠にした発言があれば、誰の発言かを軽く添えるとよい。"
)


def generate_answer(question: str, context_blocks: List[str]) -> str:
    """参考情報(context)をもとに質問へ回答する。"""
    client = _client_get()
    if context_blocks:
        context = "\n\n".join(f"[参考{i+1}] {b}" for i, b in enumerate(context_blocks))
    else:
        context = "（関連する発言は見つかりませんでした）"

    prompt = (
        f"# 参考情報\n{context}\n\n"
        f"# 質問\n{question}\n\n"
        f"# 回答（参考情報のみを根拠に、日本語で）"
    )

    resp = client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,  # 低めにして事実重視・ブレを抑える
        ),
    )
    return (resp.text or "").strip() or "回答を生成できませんでした。"
