#!/usr/bin/env python3
"""Fast, safe administration for the canonical Zhao SQLite database."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


RECORD_COLUMNS = ("ID", "Scene_ID", "Event_ID", "Name", "Character")


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sheet_specs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT position, sheet_name, table_name FROM _sheets ORDER BY position"
    ).fetchall()


def column_specs(
    connection: sqlite3.Connection, sheet_name: str
) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT position, original_header, sqlite_column "
        "FROM _columns WHERE sheet_name = ? ORDER BY position",
        (sheet_name,),
    ).fetchall()


def resolve_sheet(connection: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT position, sheet_name, table_name "
        "FROM _sheets WHERE sheet_name = ? OR table_name = ?",
        (name, name),
    ).fetchone()
    if row is None:
        raise SystemExit(f"Unknown data table: {name}")
    return row


def record_column(columns: list[sqlite3.Row]) -> str | None:
    mapping = {row["original_header"]: row["sqlite_column"] for row in columns}
    return next((mapping[name] for name in RECORD_COLUMNS if name in mapping), None)


def content_expression(prefix: str, columns: list[sqlite3.Row]) -> str:
    pieces = [
        f"COALESCE(NULLIF({prefix}.{quote(row['sqlite_column'])}, '') "
        f"|| ' | ', '')"
        for row in columns
    ]
    if not pieces:
        return "''"
    return "trim(" + " || ".join(pieces) + ", ' |')"


def refresh_sheet_stats(
    connection: sqlite3.Connection, sheet_name: str, table_name: str
) -> None:
    maximum, count = connection.execute(
        f"SELECT COALESCE(MAX(_row_number), 1), COUNT(*) FROM {quote(table_name)}"
    ).fetchone()
    connection.execute(
        "UPDATE _sheets SET source_rows = ?, data_rows = ? WHERE sheet_name = ?",
        (maximum, count, sheet_name),
    )


def rebuild_search(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM search_index")
    for spec in sheet_specs(connection):
        columns = column_specs(connection, spec["sheet_name"])
        record = record_column(columns)
        record_sql = quote(record) if record else "NULL"
        select_columns = ", ".join(
            quote(row["sqlite_column"]) for row in columns
        )
        rows = connection.execute(
            f"SELECT _row_number"
            + (f", {select_columns}" if select_columns else "")
            + f" FROM {quote(spec['table_name'])} ORDER BY _row_number"
        ).fetchall()
        names = [row["sqlite_column"] for row in columns]
        record_index = names.index(record) + 1 if record else None
        search_rows = []
        for row in rows:
            values = [None if value is None else str(value) for value in row[1:]]
            content = " | ".join(value for value in values if value)
            record_id = row[record_index] if record_index is not None else None
            search_rows.append(
                (spec["sheet_name"], row["_row_number"], record_id, content)
            )
        connection.executemany(
            "INSERT INTO search_index("
            "sheet_name, row_number, record_id, content"
            ") VALUES (?, ?, ?, ?)",
            search_rows,
        )
        refresh_sheet_stats(
            connection, spec["sheet_name"], spec["table_name"]
        )


def install_sync_triggers(connection: sqlite3.Connection) -> None:
    for spec in sheet_specs(connection):
        sheet = spec["sheet_name"]
        table = spec["table_name"]
        columns = column_specs(connection, sheet)
        record = record_column(columns)
        record_new = f"NEW.{quote(record)}" if record else "NULL"
        content_new = content_expression("NEW", columns)
        safe_name = re.sub(r"[^0-9A-Za-z_]+", "_", table)
        for suffix in ("ai", "au", "ad"):
            connection.execute(
                f"DROP TRIGGER IF EXISTS {quote(f'trg_{safe_name}_{suffix}')}"
            )
        stats_sql = (
            "UPDATE _sheets SET "
            f"source_rows = (SELECT COALESCE(MAX(_row_number), 1) FROM {quote(table)}), "
            f"data_rows = (SELECT COUNT(*) FROM {quote(table)}) "
            f"WHERE sheet_name = {sql_literal(sheet)};"
        )
        connection.executescript(
            f"""
            CREATE TRIGGER {quote(f'trg_{safe_name}_ai')}
            AFTER INSERT ON {quote(table)}
            BEGIN
                DELETE FROM search_index
                WHERE sheet_name = {sql_literal(sheet)}
                  AND row_number = NEW._row_number;
                INSERT INTO search_index(
                    sheet_name, row_number, record_id, content
                ) VALUES (
                    {sql_literal(sheet)},
                    NEW._row_number,
                    {record_new},
                    {content_new}
                );
                {stats_sql}
            END;

            CREATE TRIGGER {quote(f'trg_{safe_name}_au')}
            AFTER UPDATE ON {quote(table)}
            BEGIN
                DELETE FROM search_index
                WHERE sheet_name = {sql_literal(sheet)}
                  AND row_number IN (OLD._row_number, NEW._row_number);
                INSERT INTO search_index(
                    sheet_name, row_number, record_id, content
                ) VALUES (
                    {sql_literal(sheet)},
                    NEW._row_number,
                    {record_new},
                    {content_new}
                );
                {stats_sql}
            END;

            CREATE TRIGGER {quote(f'trg_{safe_name}_ad')}
            AFTER DELETE ON {quote(table)}
            BEGIN
                DELETE FROM search_index
                WHERE sheet_name = {sql_literal(sheet)}
                  AND row_number = OLD._row_number;
                {stats_sql}
            END;
            """
        )


def initialize(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO _meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [
            ("canonical_source", "sqlite"),
            ("source_file", "zhao-roleplay.db"),
            ("workflow", "database-first"),
        ],
    )
    rebuild_search(connection)
    install_sync_triggers(connection)
    connection.execute("PRAGMA optimize")


def validate(connection: sqlite3.Connection) -> dict[str, Any]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    sheets = []
    errors: list[str] = []
    for spec in sheet_specs(connection):
        table = spec["table_name"]
        columns = column_specs(connection, spec["sheet_name"])
        actual_columns = {
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({quote(table)})"
            ).fetchall()
        }
        missing = [
            row["sqlite_column"]
            for row in columns
            if row["sqlite_column"] not in actual_columns
        ]
        data_rows = connection.execute(
            f"SELECT COUNT(*) FROM {quote(table)}"
        ).fetchone()[0]
        search_rows = connection.execute(
            "SELECT COUNT(*) FROM search_index WHERE sheet_name = ?",
            (spec["sheet_name"],),
        ).fetchone()[0]
        if missing:
            errors.append(f"{spec['sheet_name']}: missing columns {missing}")
        if data_rows != search_rows:
            errors.append(
                f"{spec['sheet_name']}: {data_rows} data rows but "
                f"{search_rows} search rows"
            )
        sheets.append(
            {
                "sheet_name": spec["sheet_name"],
                "table_name": table,
                "data_rows": data_rows,
                "columns": len(columns),
                "search_rows": search_rows,
            }
        )
    canonical = connection.execute(
        "SELECT value FROM _meta WHERE key = 'canonical_source'"
    ).fetchone()
    if canonical is None or canonical[0] != "sqlite":
        errors.append("canonical_source is not sqlite")
    if integrity != "ok":
        errors.append(f"integrity_check: {integrity}")
    return {
        "ok": not errors,
        "integrity_check": integrity,
        "canonical_source": canonical[0] if canonical else None,
        "sheets": sheets,
        "errors": errors,
    }


def summary(connection: sqlite3.Connection, database: Path) -> dict[str, Any]:
    result = validate(connection)
    return {
        "source": str(database),
        "canonical_source": result["canonical_source"],
        "integrity_check": result["integrity_check"],
        "sheets": [
            {
                "sheet_name": row["sheet_name"],
                "table_name": row["table_name"],
                "data_rows": row["data_rows"],
                "columns": row["columns"],
            }
            for row in result["sheets"]
        ],
    }


def parse_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit("JSON payload must be an object")
    return value


def validate_payload(
    columns: list[sqlite3.Row], payload: dict[str, Any]
) -> dict[str, Any]:
    allowed = {row["sqlite_column"] for row in columns}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise SystemExit(f"Unknown columns: {', '.join(unknown)}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("zhao-roleplay.db"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("validate")
    subparsers.add_parser("reindex")
    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--output", type=Path)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)

    insert_parser = subparsers.add_parser("insert")
    insert_parser.add_argument("table")
    insert_parser.add_argument("--data", required=True)

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("table")
    locator = update_parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--row", type=int)
    locator.add_argument("--id")
    update_parser.add_argument("--set", dest="payload", required=True)

    args = parser.parse_args()
    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        if args.command == "init":
            with connection:
                initialize(connection)
            print(json.dumps(validate(connection), ensure_ascii=False, indent=2))
        elif args.command == "validate":
            result = validate(connection)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(0 if result["ok"] else 1)
        elif args.command == "reindex":
            with connection:
                rebuild_search(connection)
                install_sync_triggers(connection)
            print(json.dumps(validate(connection), ensure_ascii=False, indent=2))
        elif args.command == "summary":
            payload = json.dumps(
                summary(connection, args.db), ensure_ascii=False, indent=2
            )
            if args.output:
                args.output.write_text(payload + "\n", encoding="utf-8")
            else:
                print(payload)
        elif args.command == "search":
            rows = connection.execute(
                "SELECT sheet_name, row_number, record_id, content "
                "FROM search_index WHERE search_index MATCH ? LIMIT ?",
                (args.query, args.limit),
            ).fetchall()
            print(
                json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2)
            )
        elif args.command == "insert":
            spec = resolve_sheet(connection, args.table)
            columns = column_specs(connection, spec["sheet_name"])
            payload = validate_payload(columns, parse_object(args.data))
            next_row = connection.execute(
                f"SELECT COALESCE(MAX(_row_number), 1) + 1 "
                f"FROM {quote(spec['table_name'])}"
            ).fetchone()[0]
            names = list(payload)
            sql_columns = ["_row_number"] + names
            values = [next_row] + [payload[name] for name in names]
            with connection:
                connection.execute(
                    f"INSERT INTO {quote(spec['table_name'])} "
                    f"({', '.join(quote(name) for name in sql_columns)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    values,
                )
            print(json.dumps({"table": spec["sheet_name"], "row": next_row}))
        elif args.command == "update":
            spec = resolve_sheet(connection, args.table)
            columns = column_specs(connection, spec["sheet_name"])
            payload = validate_payload(columns, parse_object(args.payload))
            if not payload:
                raise SystemExit("Nothing to update")
            if args.row is not None:
                where_sql = "_row_number = ?"
                where_value: Any = args.row
            else:
                key = record_column(columns)
                if key is None:
                    raise SystemExit("This table has no record ID column; use --row")
                matches = connection.execute(
                    f"SELECT COUNT(*) FROM {quote(spec['table_name'])} "
                    f"WHERE {quote(key)} = ?",
                    (args.id,),
                ).fetchone()[0]
                if matches != 1:
                    raise SystemExit(
                        f"Expected one row for ID {args.id!r}, found {matches}; "
                        "use --row for an exact update"
                    )
                where_sql = f"{quote(key)} = ?"
                where_value = args.id
            assignments = ", ".join(f"{quote(name)} = ?" for name in payload)
            values = [payload[name] for name in payload] + [where_value]
            with connection:
                cursor = connection.execute(
                    f"UPDATE {quote(spec['table_name'])} SET {assignments} "
                    f"WHERE {where_sql}",
                    values,
                )
            if cursor.rowcount != 1:
                raise SystemExit(f"Expected one updated row, found {cursor.rowcount}")
            print(json.dumps({"table": spec["sheet_name"], "updated": 1}))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
