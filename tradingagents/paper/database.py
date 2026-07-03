"""SQLite persistence for Circuit paper trading."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dec_str(value: Decimal | float | int | str | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy TEXT NOT NULL,
    cash_balance TEXT NOT NULL,
    starting_balance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(name, strategy)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    qty TEXT NOT NULL,
    leverage TEXT NOT NULL,
    limit_price TEXT,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    portfolio_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT NOT NULL,
    slippage_bps TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    leverage TEXT NOT NULL,
    stop_loss TEXT,
    take_profits TEXT NOT NULL DEFAULT '[]',
    unrealized_pnl TEXT NOT NULL DEFAULT '0',
    realized_pnl TEXT NOT NULL DEFAULT '0',
    mark_price TEXT,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(portfolio_id, strategy, instrument),
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    equity TEXT NOT NULL,
    cash_balance TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    risk_json TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(strategy, snapshot_id)
);
"""


class PaperDatabase:
    """SQLite-backed paper trading store. Paths are expanded with ``expanduser``."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(os.path.expanduser(str(path))).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ---- portfolios --------------------------------------------------------
    def get_or_create_portfolio(
        self,
        *,
        name: str,
        strategy: str,
        starting_balance: Decimal,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        def _run(c: sqlite3.Connection) -> dict[str, Any]:
            row = c.execute(
                "SELECT * FROM portfolios WHERE name = ? AND strategy = ?",
                (name, strategy),
            ).fetchone()
            if row:
                return dict(row)
            now = _utc_now_iso()
            bal = _dec_str(starting_balance)
            cur = c.execute(
                """
                INSERT INTO portfolios (name, strategy, cash_balance, starting_balance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, strategy, bal, bal, now, now),
            )
            return dict(
                c.execute(
                    "SELECT * FROM portfolios WHERE id = ?", (cur.lastrowid,)
                ).fetchone()
            )

        if conn is not None:
            return _run(conn)
        with self.transaction() as c:
            return _run(c)

    def update_cash(
        self,
        portfolio_id: int,
        cash_balance: Decimal,
        *,
        conn: sqlite3.Connection,
    ) -> None:
        conn.execute(
            "UPDATE portfolios SET cash_balance = ?, updated_at = ? WHERE id = ?",
            (_dec_str(cash_balance), _utc_now_iso(), portfolio_id),
        )

    # ---- strategy runs (dedupe) --------------------------------------------
    def has_strategy_run(self, strategy: str, snapshot_id: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM strategy_runs WHERE strategy = ? AND snapshot_id = ?",
                (strategy, snapshot_id),
            ).fetchone()
            return row is not None

    def insert_strategy_run(
        self,
        *,
        strategy: str,
        snapshot_id: str,
        instrument: str,
        proposal_json: dict[str, Any],
        risk_json: dict[str, Any],
        execution_status: str,
        conn: sqlite3.Connection,
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO strategy_runs
            (strategy, snapshot_id, instrument, proposal_json, risk_json, execution_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy,
                snapshot_id,
                instrument,
                json.dumps(proposal_json, default=str),
                json.dumps(risk_json, default=str),
                execution_status,
                _utc_now_iso(),
            ),
        )
        return int(cur.lastrowid)

    # ---- orders / fills / positions ----------------------------------------
    def insert_order(self, fields: dict[str, Any], *, conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO orders (
                portfolio_id, strategy, snapshot_id, instrument, side, action,
                qty, leverage, limit_price, status, rejection_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["portfolio_id"],
                fields["strategy"],
                fields["snapshot_id"],
                fields["instrument"],
                fields["side"],
                fields["action"],
                _dec_str(fields["qty"]),
                _dec_str(fields["leverage"]),
                _dec_str(fields.get("limit_price")),
                fields["status"],
                fields.get("rejection_reason"),
                fields.get("created_at") or _utc_now_iso(),
            ),
        )
        return int(cur.lastrowid)

    def insert_fill(self, fields: dict[str, Any], *, conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO fills (
                order_id, portfolio_id, strategy, snapshot_id, instrument, side,
                qty, price, fee, slippage_bps, realized_pnl, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["order_id"],
                fields["portfolio_id"],
                fields["strategy"],
                fields["snapshot_id"],
                fields["instrument"],
                fields["side"],
                _dec_str(fields["qty"]),
                _dec_str(fields["price"]),
                _dec_str(fields["fee"]),
                _dec_str(fields["slippage_bps"]),
                _dec_str(fields["realized_pnl"]),
                fields.get("created_at") or _utc_now_iso(),
            ),
        )
        return int(cur.lastrowid)

    def upsert_position(
        self, fields: dict[str, Any], *, conn: sqlite3.Connection
    ) -> None:
        now = _utc_now_iso()
        existing = conn.execute(
            """
            SELECT id FROM positions
            WHERE portfolio_id = ? AND strategy = ? AND instrument = ?
            """,
            (fields["portfolio_id"], fields["strategy"], fields["instrument"]),
        ).fetchone()
        take_profits = fields.get("take_profits") or []
        tp_json = (
            json.dumps(take_profits) if isinstance(take_profits, list) else str(take_profits)
        )
        if existing:
            conn.execute(
                """
                UPDATE positions SET
                    side = ?, qty = ?, entry_price = ?, leverage = ?,
                    stop_loss = ?, take_profits = ?, unrealized_pnl = ?,
                    realized_pnl = ?, mark_price = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    fields["side"],
                    _dec_str(fields["qty"]),
                    _dec_str(fields["entry_price"]),
                    _dec_str(fields["leverage"]),
                    _dec_str(fields.get("stop_loss")),
                    tp_json,
                    _dec_str(fields.get("unrealized_pnl") or Decimal("0")),
                    _dec_str(fields.get("realized_pnl") or Decimal("0")),
                    _dec_str(fields.get("mark_price")),
                    now,
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO positions (
                    portfolio_id, strategy, instrument, side, qty, entry_price,
                    leverage, stop_loss, take_profits, unrealized_pnl, realized_pnl,
                    mark_price, opened_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["portfolio_id"],
                    fields["strategy"],
                    fields["instrument"],
                    fields["side"],
                    _dec_str(fields["qty"]),
                    _dec_str(fields["entry_price"]),
                    _dec_str(fields["leverage"]),
                    _dec_str(fields.get("stop_loss")),
                    tp_json,
                    _dec_str(fields.get("unrealized_pnl") or Decimal("0")),
                    _dec_str(fields.get("realized_pnl") or Decimal("0")),
                    _dec_str(fields.get("mark_price")),
                    now,
                    now,
                ),
            )

    def get_position(
        self,
        portfolio_id: int,
        strategy: str,
        instrument: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        def _run(c: sqlite3.Connection) -> dict[str, Any] | None:
            row = c.execute(
                """
                SELECT * FROM positions
                WHERE portfolio_id = ? AND strategy = ? AND instrument = ?
                """,
                (portfolio_id, strategy, instrument),
            ).fetchone()
            return dict(row) if row else None

        if conn is not None:
            return _run(conn)
        with self.connection() as c:
            return _run(c)

    def list_positions(
        self, portfolio_id: int, *, strategy: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if strategy:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE portfolio_id = ? AND strategy = ?",
                    (portfolio_id, strategy),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE portfolio_id = ?",
                    (portfolio_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def insert_equity_snapshot(
        self, fields: dict[str, Any], *, conn: sqlite3.Connection
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO equity_snapshots (
                portfolio_id, strategy, equity, cash_balance, unrealized_pnl,
                realized_pnl, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["portfolio_id"],
                fields["strategy"],
                _dec_str(fields["equity"]),
                _dec_str(fields["cash_balance"]),
                _dec_str(fields["unrealized_pnl"]),
                _dec_str(fields["realized_pnl"]),
                fields.get("created_at") or _utc_now_iso(),
            ),
        )
        return int(cur.lastrowid)

    def list_fills(self, portfolio_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM fills WHERE portfolio_id = ? ORDER BY id ASC",
                (portfolio_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_equity_snapshots(self, portfolio_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots WHERE portfolio_id = ? ORDER BY id ASC",
                (portfolio_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_portfolio(self, portfolio_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_portfolios(self, *, name: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if name:
                rows = conn.execute(
                    "SELECT * FROM portfolios WHERE name = ? ORDER BY strategy ASC",
                    (name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM portfolios ORDER BY strategy ASC"
                ).fetchall()
            return [dict(r) for r in rows]
