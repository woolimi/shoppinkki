#!/usr/bin/env python3
"""Fill text embeddings using a sentence-transformers model (PostgreSQL).

Reads rows from PRODUCT_TEXT_EMBEDDING and ZONE_TEXT_EMBEDDING tables
and writes vector(384) embeddings using pgvector's native cast syntax.

Usage:
  python3 scripts/db/fill_product_embeddings.py --force
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EXPECTED_DIM = 384


def load_env_file() -> None:
    """Load .env values when env vars are not set."""
    # 컨테이너와 로컬 환경 모두에서 작동하도록 경로 조정
    current_dir = Path(__file__).resolve().parent
    env_path = current_dir / ".env"
    if not env_path.exists():
        env_path = current_dir.parent / ".env"
    if not env_path.exists():
        env_path = Path("/app/.env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("PG_USER", "shoppinkki"),
        password=os.environ.get("PG_PASSWORD", "shoppinkki"),
        dbname=os.environ.get("PG_DATABASE", "shoppinkki"),
    )


def process_table(table_name: str, model: SentenceTransformer, conn: psycopg2.extensions.connection, force: bool):
    print(f"\n>>> Processing table: {table_name}")
    select_cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    where_clause = "" if force else "WHERE embedding IS NULL"
    query = f"SELECT id, text FROM {table_name} {where_clause} ORDER BY id"
    
    select_cursor.execute(query)
    rows = select_cursor.fetchall()

    if not rows:
        print(f"No rows to update in {table_name}.")
        select_cursor.close()
        return

    ids = [row["id"] for row in rows]
    texts = [row["text"] for row in rows]
    print(f"Encoding {len(rows)} rows for {table_name}")

    embeddings = model.encode(
        texts,
        batch_size=16,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    print(f"Writing embeddings to {table_name}")
    update_cursor = conn.cursor()
    update_sql = f"""
        UPDATE {table_name}
        SET embedding = %s::vector,
            model_name = %s
        WHERE id = %s
    """
    payload = [
        ("[" + ", ".join(f"{v:.8f}" for v in embedding.tolist()) + "]", DEFAULT_MODEL, row_id)
        for row_id, embedding in zip(ids, embeddings, strict=True)
    ]
    update_cursor.executemany(update_sql, payload)
    conn.commit()
    print(f"Updated {update_cursor.rowcount} rows in {table_name}.")
    update_cursor.close()
    select_cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill text embeddings with sentence-transformers.")
    parser.add_argument("--force", action="store_true", help="rebuild embeddings for all rows")
    args = parser.parse_args()

    load_env_file()

    print(f"[1/3] Loading model: {DEFAULT_MODEL}")
    model = SentenceTransformer(DEFAULT_MODEL)

    dim = model.get_sentence_embedding_dimension()
    if dim != EXPECTED_DIM:
        raise ValueError(f"Model dimension {dim} does not match schema vector({EXPECTED_DIM}).")

    print("[2/3] Connecting to PostgreSQL")
    conn = get_connection()

    print("[3/3] Processing tables")
    process_table("PRODUCT_TEXT_EMBEDDING", model, conn, args.force)
    process_table("ZONE_TEXT_EMBEDDING", model, conn, args.force)

    conn.close()
    print("\nAll embedding tasks completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
