from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, delete, select
from sqlalchemy.engine import Connection


def _pair_hash(left: str, right: str | None = None) -> str:
    right_value = right or left
    payload = f"{left}:{right_value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_merkle_root(leaf_hashes: list[str]) -> str:
    if not leaf_hashes:
        return ""
    level = list(leaf_hashes)
    while len(level) > 1:
        next_level: list[str] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else None
            next_level.append(_pair_hash(left, right))
        level = next_level
    return level[0]


def register_merkle_tables(metadata: MetaData) -> tuple[Table, Table]:
    nodes = Table(
        "ic_merkle_nodes",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("node_level", Integer, nullable=False),
        Column("node_index", Integer, nullable=False),
        Column("hash_value", String(64), nullable=False),
        Column("record_id", String(255), nullable=True),
        Column("record_type", String(64), nullable=True),
        Column("left_child_hash", String(64), nullable=True),
        Column("right_child_hash", String(64), nullable=True),
        Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
        extend_existing=True,
    )
    meta = Table(
        "ic_merkle_meta",
        metadata,
        Column("tree_id", String(32), primary_key=True),
        Column("root_hash", String(64), nullable=False, default=""),
        Column("record_count", Integer, nullable=False, default=0),
        Column("updated_at", DateTime, nullable=False, default=datetime.utcnow),
        Column("metadata", JSON, nullable=False, default=dict),
        extend_existing=True,
    )
    return nodes, meta


class MerkleAuditManager:
    def __init__(self, nodes_table: Table, meta_table: Table) -> None:
        self._nodes = nodes_table
        self._meta = meta_table

    def append_leaf(
        self,
        connection: Connection,
        record_hash: str,
        record_id: str,
        record_type: str,
    ) -> dict[str, Any]:
        existing_meta = connection.execute(
            select(self._meta).where(self._meta.c.tree_id == "default")
        ).mappings().first()
        leaf_index = int(existing_meta["record_count"]) if existing_meta else 0

        connection.execute(
            self._nodes.insert().values(
                node_level=0,
                node_index=leaf_index,
                hash_value=record_hash,
                record_id=record_id,
                record_type=record_type,
                left_child_hash=None,
                right_child_hash=None,
                created_at=datetime.utcnow(),
            )
        )

        self._rebuild_internal_nodes(connection)
        leaf_hashes = self._leaf_hashes(connection)
        root_hash = compute_merkle_root(leaf_hashes)
        meta_values = {
            "tree_id": "default",
            "root_hash": root_hash,
            "record_count": len(leaf_hashes),
            "updated_at": datetime.utcnow(),
            "metadata": {"last_record_id": record_id, "last_record_type": record_type},
        }

        if existing_meta:
            connection.execute(
                self._meta.update().where(self._meta.c.tree_id == "default").values(**meta_values)
            )
        else:
            connection.execute(self._meta.insert().values(**meta_values))

        return meta_values

    def cached_root(self, connection: Connection) -> dict[str, Any]:
        row = connection.execute(
            select(self._meta).where(self._meta.c.tree_id == "default")
        ).mappings().first()
        return dict(row) if row else {"tree_id": "default", "root_hash": "", "record_count": 0}

    def verify(self, connection: Connection) -> dict[str, Any]:
        cached = self.cached_root(connection)
        leaf_hashes = self._leaf_hashes(connection)
        recomputed = compute_merkle_root(leaf_hashes)
        return {
            "cached_root_hash": cached["root_hash"],
            "recomputed_root_hash": recomputed,
            "record_count": len(leaf_hashes),
            "valid": cached["root_hash"] == recomputed,
            "verified_at": datetime.utcnow(),
        }

    def _leaf_hashes(self, connection: Connection) -> list[str]:
        rows = connection.execute(
            select(self._nodes.c.hash_value)
            .where(self._nodes.c.node_level == 0)
            .order_by(self._nodes.c.node_index.asc())
        ).all()
        return [row[0] for row in rows]

    def _rebuild_internal_nodes(self, connection: Connection) -> None:
        connection.execute(delete(self._nodes).where(self._nodes.c.node_level > 0))
        leaf_rows = connection.execute(
            select(
                self._nodes.c.hash_value,
                self._nodes.c.node_index,
            )
            .where(self._nodes.c.node_level == 0)
            .order_by(self._nodes.c.node_index.asc())
        ).all()
        current_level = [(row.hash_value, row.node_index) for row in leaf_rows]
        level_index = 1

        while len(current_level) > 1:
            next_level: list[tuple[str, int]] = []
            for index in range(0, len(current_level), 2):
                left_hash, left_idx = current_level[index]
                right_hash = current_level[index + 1][0] if index + 1 < len(current_level) else None
                node_hash = _pair_hash(left_hash, right_hash)
                parent_index = index // 2
                connection.execute(
                    self._nodes.insert().values(
                        node_level=level_index,
                        node_index=parent_index,
                        hash_value=node_hash,
                        record_id=None,
                        record_type=None,
                        left_child_hash=left_hash,
                        right_child_hash=right_hash,
                        created_at=datetime.utcnow(),
                    )
                )
                next_level.append((node_hash, parent_index))
            current_level = next_level
            level_index += 1

