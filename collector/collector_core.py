from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import sqlite3
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CFG_PATH = (
    Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    / "Trove"
    / "ModCfgs"
    / "Redesigned - Leaderboard.cfg"
)
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "leaderboard_catalog_unique.tsv"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "leaderboard_collector.sqlite3"
SNAPSHOT_UPLOAD_PATH = "/api/collector/leaderboard/snapshots"
LEGACY_UPLOAD_PATH = "/api/collector/leaderboard/daily"
DEFAULT_UPLOAD_URL = ""
MIN_COLLECTOR_TOKEN_LENGTH = 32

ENTRY_COLUMNS = [
    "rank",
    "name",
    "score",
    "scoreType",
    "scoreName",
    "isCurrentPlayer",
    "isFriend",
]

BATCH_SEPARATOR = "[@@TROVEBBS_DATA@@]"
TROVE_MASTERY_LEADERBOARD_ID = "1"
GEODE_MASTERY_LEADERBOARD_ID = "20"
TOTAL_MASTERY_LEADERBOARD_ID = "100"


@dataclass(frozen=True)
class ImportSummary:
    imported: int
    skipped: int
    errors: tuple[str, ...]
    pending: int = 0


@dataclass(frozen=True)
class CatalogImportSummary:
    full_rows: int
    unique_rows: int
    source: str
    errors: tuple[str, ...] = ()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def timestamp_ms_to_iso(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return str(ms)


def decode_cfg_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "mbcs"):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def read_text(path: Path) -> str:
    return decode_cfg_bytes(path.read_bytes())


def parse_cfg_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("[") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_bool(value: str | int | None) -> int:
    return 1 if str(value or "").strip().lower() in {"1", "true", "yes"} else 0


def parse_int(value: str | int | None, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_float(value: str | float | int | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def get_mastery_requirement(level: int, cap: int) -> int:
    if level >= cap or level < 1:
        return 0
    if level < 5:
        return 25
    if level < 10:
        return 50
    if level < 20:
        return 75
    if level < 300:
        return 100
    return (level + 2) // 2


def format_compact_number(value: float | int) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.5f}".rstrip("0").rstrip(".")


def get_mastery_level(value: str | float | int | None, cap: int) -> dict[str, float | int] | None:
    score = parse_float(value)
    if score is None:
        return None

    level = 1
    remaining = score
    required = get_mastery_requirement(level, cap)
    while remaining >= required and required != 0:
        remaining -= required
        level += 1
        required = get_mastery_requirement(level, cap)

    return {"level": level, "remaining": remaining, "required": required}


def format_mastery_level_parts(level: int, remaining: float | int, required: int) -> str:
    return f"Lv {format_compact_number(level)} ({format_compact_number(remaining)}/{format_compact_number(required)})"


def format_mastery_level(value: str | float | int | None, cap: int) -> dict[str, object] | None:
    result = get_mastery_level(value, cap)
    if result is None:
        return None
    level = int(result["level"])
    remaining = result["remaining"]
    required = int(result["required"])
    return {
        "level": level,
        "progress": remaining,
        "required": required,
        "text": format_mastery_level_parts(level, remaining, required),
    }


def format_total_mastery_level(
    trove_score: str | float | int | None,
    geode_score: str | float | int | None,
) -> dict[str, object] | None:
    trove = get_mastery_level(trove_score, 1000)
    geode = get_mastery_level(geode_score, 100)
    if trove is None or geode is None:
        return None

    level = int(trove["level"]) + int(geode["level"])
    text = (
        f"Lv {format_compact_number(level)} "
        f"({format_compact_number(trove['remaining'])}/{format_compact_number(trove['required'])} + "
        f"{format_compact_number(geode['remaining'])}/{format_compact_number(geode['required'])})"
    )
    return {
        "level": level,
        "trove_level": int(trove["level"]),
        "geode_level": int(geode["level"]),
        "text": text,
    }


def infer_total_mastery_component_scores(
    total_score: str | float | int | None,
    trove_score: str | float | int | None,
    geode_score: str | float | int | None,
) -> tuple[str | float | int | None, str | float | int | None]:
    total = parse_float(total_score)
    trove = parse_float(trove_score)
    geode = parse_float(geode_score)
    if total is None:
        return trove_score, geode_score

    if trove is None and geode is not None and total >= geode:
        trove_score = format_compact_number(total - geode)
    if geode is None and trove is not None and total >= trove:
        geode_score = format_compact_number(total - trove)
    return trove_score, geode_score


def parse_meta(meta: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in meta.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def split_batch_blob(batch: str) -> tuple[str, str]:
    if not batch or BATCH_SEPARATOR not in batch:
        return "", ""
    meta, data = batch.split(BATCH_SEPARATOR, 1)
    return meta.strip(), data.strip()


def parse_dump_rows(data: str) -> list[dict[str, str]]:
    rows = data.split("||")
    if not rows:
        return []

    header = rows[0].split("\t")
    if header != ENTRY_COLUMNS:
        header = ENTRY_COLUMNS

    parsed: list[dict[str, str]] = []
    for row in rows[1:]:
        if not row.strip():
            continue
        cols = row.split("\t")
        cols.extend([""] * (len(header) - len(cols)))
        parsed.append(dict(zip(header, cols[: len(header)])))
    return parsed


def rows_match_progress(rows: list[dict[str, str]], expected_entries: int | None) -> bool:
    if expected_entries is None or expected_entries <= 0:
        return True
    return len(rows) == expected_entries


def parse_catalog_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = read_text(path)
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows: list[dict[str, str]] = []
    for row in reader:
        leaderboard_id = (row.get("leaderboardId") or "").strip()
        if not leaderboard_id:
            continue
        rows.append(
            {
                "category_id": (row.get("categoryId") or "").strip(),
                "category": (row.get("category") or "").strip(),
                "leaderboard_id": leaderboard_id,
                "name_key": (row.get("leaderboardKey") or row.get("name") or "").strip(),
                "name": (row.get("displayName") or row.get("leaderboardDisplayName") or row.get("name") or "").strip(),
                "score_type": (row.get("scoreType") or "").strip(),
                "is_default": (row.get("isDefault") or "").strip(),
                "icon_path": (row.get("param5") or row.get("param4") or "").strip(),
            }
        )
    return rows


def parse_catalog_blob(catalog: str) -> list[dict[str, str]]:
    rows = catalog.split("||")
    parsed: list[dict[str, str]] = []

    for index, row in enumerate(rows[1:], start=1):
        if not row.strip():
            continue
        cols = row.split("\t")
        cols.extend([""] * (10 - len(cols)))
        if cols[0] != "leaderboard":
            continue
        name_key = cols[4]
        display_name = cols[9] or name_key
        parsed.append(
            {
                "row_order": index,
                "category_id": cols[1],
                "category": cols[2],
                "leaderboard_id": cols[3],
                "name_key": name_key,
                "name": display_name,
                "param4": cols[5],
                "param5": cols[6],
                "score_type": cols[7],
                "is_default": cols[8],
                "icon_path": cols[6] or cols[5],
            }
        )
    return parsed


def unique_catalog_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in rows:
        leaderboard_id = row["leaderboard_id"]
        if not leaderboard_id or leaderboard_id in seen:
            continue
        seen.add(leaderboard_id)
        unique.append(row)
    return unique


def init_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog (
            leaderboard_id TEXT PRIMARY KEY,
            category_id TEXT,
            category TEXT,
            name_key TEXT,
            name TEXT,
            score_type TEXT,
            is_default TEXT,
            icon_path TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_full (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_order INTEGER NOT NULL,
            category_id TEXT,
            category TEXT,
            leaderboard_id TEXT,
            name_key TEXT,
            name TEXT,
            score_type TEXT,
            is_default TEXT,
            param4 TEXT,
            param5 TEXT,
            icon_path TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leaderboard_id TEXT NOT NULL,
            source_hash TEXT NOT NULL UNIQUE,
            dump_run TEXT,
            range_start INTEGER,
            range_end INTEGER,
            total_saved INTEGER,
            entries INTEGER,
            expected INTEGER,
            complete INTEGER NOT NULL DEFAULT 0,
            saved_at_ms INTEGER,
            cfg_mtime_ns INTEGER,
            imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dump_batches (
            source_hash TEXT PRIMARY KEY,
            snapshot_id INTEGER NOT NULL,
            leaderboard_id TEXT NOT NULL,
            dump_run TEXT,
            range_start INTEGER,
            range_end INTEGER,
            entries INTEGER,
            imported_at TEXT NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            snapshot_id INTEGER NOT NULL,
            leaderboard_id TEXT NOT NULL,
            entry_index INTEGER NOT NULL DEFAULT 0,
            rank INTEGER,
            player_name TEXT,
            score REAL,
            score_raw TEXT,
            score_type INTEGER,
            score_name TEXT,
            is_current_player INTEGER NOT NULL DEFAULT 0,
            is_friend INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (snapshot_id, entry_index),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
        )
        """
    )
    migrate_entries_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_state (
            snapshot_id INTEGER PRIMARY KEY,
            upload_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            uploaded_at TEXT,
            last_attempt_at TEXT,
            last_error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            response_code INTEGER,
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_leaderboard ON snapshots(leaderboard_id, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_leaderboard ON entries(leaderboard_id, rank)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_full_leaderboard ON catalog_full(leaderboard_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_upload_state_status ON upload_state(status, last_attempt_at)")
    ensure_column(conn, "catalog", "category_id", "TEXT")
    ensure_column(conn, "catalog", "name_key", "TEXT")
    ensure_column(conn, "catalog_full", "name_key", "TEXT")
    ensure_column(conn, "snapshots", "dump_run", "TEXT")
    ensure_column(conn, "snapshots", "range_start", "INTEGER")
    ensure_column(conn, "snapshots", "range_end", "INTEGER")
    ensure_column(conn, "snapshots", "total_saved", "INTEGER")
    conn.execute("UPDATE catalog SET name_key = name WHERE (name_key IS NULL OR name_key = '')")
    conn.execute("UPDATE catalog_full SET name_key = name WHERE (name_key IS NULL OR name_key = '')")
    conn.commit()
    return conn


def migrate_entries_schema(conn: sqlite3.Connection) -> None:
    table_info = list(conn.execute("PRAGMA table_info(entries)"))
    primary_key_columns = [
        row["name"]
        for row in sorted((row for row in table_info if row["pk"]), key=lambda row: row["pk"])
    ]
    if primary_key_columns == ["snapshot_id", "entry_index"]:
        return

    conn.execute("ALTER TABLE entries RENAME TO entries_legacy")
    conn.execute(
        """
        CREATE TABLE entries (
            snapshot_id INTEGER NOT NULL,
            leaderboard_id TEXT NOT NULL,
            entry_index INTEGER NOT NULL DEFAULT 0,
            rank INTEGER,
            player_name TEXT,
            score REAL,
            score_raw TEXT,
            score_type INTEGER,
            score_name TEXT,
            is_current_player INTEGER NOT NULL DEFAULT 0,
            is_friend INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (snapshot_id, entry_index),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO entries (
            snapshot_id, leaderboard_id, entry_index, rank, player_name, score,
            score_raw, score_type, score_name, is_current_player, is_friend
        )
        SELECT
            snapshot_id,
            leaderboard_id,
            ROW_NUMBER() OVER (
                PARTITION BY snapshot_id
                ORDER BY rank ASC, rowid ASC
            ) AS entry_index,
            rank,
            player_name,
            score,
            score_raw,
            score_type,
            score_name,
            is_current_player,
            is_friend
        FROM entries_legacy
        """
    )
    conn.execute("DROP TABLE entries_legacy")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def replace_catalog(conn: sqlite3.Connection, full_rows: list[dict[str, str]], source: str) -> CatalogImportSummary:
    unique_rows = unique_catalog_rows(full_rows)
    stamp = now_iso()
    with conn:
        conn.execute("DELETE FROM catalog_full")
        conn.execute("DELETE FROM catalog")
        for row in full_rows:
            conn.execute(
                """
                INSERT INTO catalog_full (
                    row_order, category_id, category, leaderboard_id, name_key, name,
                    score_type, is_default, param4, param5, icon_path, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("row_order"),
                    row.get("category_id", ""),
                    row.get("category", ""),
                    row.get("leaderboard_id", ""),
                    row.get("name_key", row.get("name", "")),
                    row.get("name", ""),
                    row.get("score_type", ""),
                    row.get("is_default", ""),
                    row.get("param4", ""),
                    row.get("param5", ""),
                    row.get("icon_path", ""),
                    stamp,
                ),
            )
        for row in unique_rows:
            conn.execute(
                """
                INSERT INTO catalog (
                    leaderboard_id, category_id, category, name_key, name, score_type,
                    is_default, icon_path, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("leaderboard_id", ""),
                    row.get("category_id", ""),
                    row.get("category", ""),
                    row.get("name_key", row.get("name", "")),
                    row.get("name", ""),
                    row.get("score_type", ""),
                    row.get("is_default", ""),
                    row.get("icon_path", ""),
                    stamp,
                ),
            )
    return CatalogImportSummary(len(full_rows), len(unique_rows), source)


def import_catalog_from_cfg(conn: sqlite3.Connection, cfg_path: Path = DEFAULT_CFG_PATH) -> CatalogImportSummary:
    if not cfg_path.exists():
        return CatalogImportSummary(0, 0, "cfg", (f"找不到配置文件: {cfg_path}",))

    try:
        values = parse_cfg_values(read_text(cfg_path))
    except OSError as exc:
        return CatalogImportSummary(0, 0, "cfg", (f"读取配置文件失败: {exc}",))

    catalog = values.get("leaderboard_catalog", "")
    if not catalog:
        return CatalogImportSummary(0, 0, "cfg", ("配置文件里没有 leaderboard_catalog，请先在游戏内输入 @paiming。",))

    full_rows = parse_catalog_blob(catalog)
    if not full_rows:
        return CatalogImportSummary(0, 0, "cfg", ("leaderboard_catalog 存在，但没有解析到排行榜目录。",))

    return replace_catalog(conn, full_rows, "cfg")


def sync_catalog(conn: sqlite3.Connection, cfg_path: Path = DEFAULT_CFG_PATH) -> CatalogImportSummary:
    summary = import_catalog_from_cfg(conn, cfg_path)
    if summary.unique_rows > 0:
        return summary

    fallback_rows = parse_catalog_tsv(DEFAULT_CATALOG_PATH)
    if fallback_rows:
        full_rows = [
            {
                "row_order": index,
                "category_id": row["category_id"],
                "category": row["category"],
                "leaderboard_id": row["leaderboard_id"],
                "name_key": row.get("name_key", row["name"]),
                "name": row["name"],
                "param4": "",
                "param5": row["icon_path"],
                "score_type": row["score_type"],
                "is_default": row["is_default"],
                "icon_path": row["icon_path"],
            }
            for index, row in enumerate(fallback_rows, start=1)
        ]
        fallback_summary = replace_catalog(conn, full_rows, "tsv")
        return CatalogImportSummary(
            fallback_summary.full_rows,
            fallback_summary.unique_rows,
            fallback_summary.source,
            summary.errors,
        )

    return summary


def upsert_catalog(conn: sqlite3.Connection, catalog_path: Path = DEFAULT_CATALOG_PATH) -> int:
    rows = parse_catalog_tsv(catalog_path)
    full_rows = [
        {
            "row_order": index,
            "category_id": row["category_id"],
            "category": row["category"],
            "leaderboard_id": row["leaderboard_id"],
            "name_key": row.get("name_key", row["name"]),
            "name": row["name"],
            "param4": "",
            "param5": row["icon_path"],
            "score_type": row["score_type"],
            "is_default": row["is_default"],
            "icon_path": row["icon_path"],
        }
        for index, row in enumerate(rows, start=1)
    ]
    return replace_catalog(conn, full_rows, "tsv").unique_rows


def count_catalog_full(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM catalog_full").fetchone()
    return int(row["count"]) if row else 0


def source_hash(meta: str, data: str) -> str:
    digest = hashlib.sha256()
    digest.update(meta.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(data.encode("utf-8", errors="replace"))
    return digest.hexdigest()


def iter_dump_keys(values: dict[str, str]) -> Iterable[tuple[str, str, str]]:
    batch_meta, batch_data = split_batch_blob(values.get("leaderboard_batch", ""))
    if batch_meta and batch_data:
        metadata = parse_meta(batch_meta)
        yield metadata.get("leaderboard") or metadata.get("leaderboardId", ""), batch_meta, batch_data

    for key, batch in values.items():
        match = re.fullmatch(r"leaderboard_batch_(\d+)", key)
        if not match:
            continue
        meta, data = split_batch_blob(batch)
        if meta and data:
            metadata = parse_meta(meta)
            yield metadata.get("leaderboard") or metadata.get("leaderboardId", match.group(1)), meta, data

    if not (batch_meta and batch_data) and ("data" in values or "leaderboard_progress" in values or "meta" in values):
        progress = values.get("leaderboard_progress") or values.get("meta", "")
        metadata = parse_meta(progress)
        yield metadata.get("leaderboard") or metadata.get("leaderboardId", ""), progress, values.get("data", "")

    if not (batch_meta and batch_data):
        for key, data in values.items():
            match = re.fullmatch(r"(\d+)_data", key)
            if not match:
                continue
            leaderboard_id = match.group(1)
            yield leaderboard_id, values.get(f"{leaderboard_id}_meta", ""), data


def import_cfg_dump(conn: sqlite3.Connection, cfg_path: Path = DEFAULT_CFG_PATH) -> ImportSummary:
    if not cfg_path.exists():
        return ImportSummary(0, 0, (f"找不到配置文件: {cfg_path}",))

    try:
        stat = cfg_path.stat()
        raw = cfg_path.read_bytes()
    except OSError as exc:
        return ImportSummary(0, 0, (f"读取配置文件失败: {exc}",))

    return import_cfg_bytes(conn, raw, stat.st_mtime_ns)


def import_cfg_bytes(conn: sqlite3.Connection, raw: bytes, cfg_mtime_ns: int | None = None) -> ImportSummary:
    return import_cfg_text(conn, decode_cfg_bytes(raw), cfg_mtime_ns)


def import_cfg_text(conn: sqlite3.Connection, text: str, cfg_mtime_ns: int | None = None) -> ImportSummary:
    return import_cfg_values(conn, parse_cfg_values(text), cfg_mtime_ns)


def import_cfg_values(
    conn: sqlite3.Connection,
    values: dict[str, str],
    cfg_mtime_ns: int | None = None,
) -> ImportSummary:
    imported = 0
    skipped = 0
    pending = 0
    errors: list[str] = []

    with conn:
        for fallback_id, meta_text, data_text in iter_dump_keys(values):
            metadata = parse_meta(meta_text)
            leaderboard_id = metadata.get("leaderboard") or metadata.get("leaderboardId", fallback_id)
            if not leaderboard_id:
                skipped += 1
                continue
            if not data_text.strip() or parse_bool(metadata.get("cleared")):
                skipped += 1
                continue

            digest = source_hash(meta_text, data_text)
            existing_batch = conn.execute("SELECT source_hash FROM dump_batches WHERE source_hash = ?", (digest,)).fetchone()
            if existing_batch:
                skipped += 1
                continue

            existing = conn.execute("SELECT id FROM snapshots WHERE source_hash = ?", (digest,)).fetchone()
            if existing:
                skipped += 1
                continue

            rows = parse_dump_rows(data_text)
            if not rows:
                errors.append(f"{leaderboard_id}: 没有解析到排行榜数据")
                continue

            dump_run = metadata.get("run", "")
            range_start = parse_int(metadata.get("start"))
            range_end = parse_int(metadata.get("end"))
            metadata_entries = parse_int(metadata.get("entries"))
            if not rows_match_progress(rows, metadata_entries):
                pending += 1
                continue
            total_saved = parse_int(metadata.get("saved"))
            expected = parse_int(metadata.get("expected"), len(rows))
            complete = parse_bool(metadata.get("complete"))
            saved_at_ms = parse_int(metadata.get("savedAt"))

            if dump_run:
                snapshot = conn.execute(
                    """
                    SELECT id FROM snapshots
                    WHERE leaderboard_id = ? AND dump_run = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (leaderboard_id, dump_run),
                ).fetchone()
                if snapshot:
                    snapshot_id = int(snapshot["id"])
                    conn.execute(
                        """
                        UPDATE snapshots
                        SET entries = (
                                SELECT COUNT(*) FROM entries WHERE snapshot_id = ?
                            ),
                            expected = ?,
                            complete = ?,
                            saved_at_ms = COALESCE(?, saved_at_ms),
                            cfg_mtime_ns = ?,
                            range_start = COALESCE(range_start, ?),
                            range_end = MAX(COALESCE(range_end, 0), COALESCE(?, 0)),
                            total_saved = COALESCE(?, total_saved),
                            imported_at = ?
                        WHERE id = ?
                        """,
                        (
                            snapshot_id,
                            expected,
                            complete,
                            saved_at_ms,
                            cfg_mtime_ns,
                            range_start,
                            range_end,
                            total_saved,
                            now_iso(),
                            snapshot_id,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO snapshots (
                            leaderboard_id, source_hash, dump_run, range_start, range_end,
                            total_saved, entries, expected, complete, saved_at_ms,
                            cfg_mtime_ns, imported_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            leaderboard_id,
                            f"run:{dump_run}",
                            dump_run,
                            range_start,
                            range_end,
                            total_saved,
                            0,
                            expected,
                            complete,
                            saved_at_ms,
                            cfg_mtime_ns,
                            now_iso(),
                        ),
                    )
                    snapshot_id = int(cursor.lastrowid)
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO snapshots (
                        leaderboard_id, source_hash, range_start, range_end, total_saved,
                        entries, expected, complete, saved_at_ms, cfg_mtime_ns, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        leaderboard_id,
                        digest,
                        range_start,
                        range_end,
                        total_saved,
                        parse_int(metadata.get("entries"), len(rows)),
                        expected,
                        complete,
                        saved_at_ms,
                        cfg_mtime_ns,
                        now_iso(),
                    ),
                )
                snapshot_id = int(cursor.lastrowid)

            entry_base = range_start if range_start is not None and range_start > 0 else 1
            for offset, row in enumerate(rows):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO entries (
                        snapshot_id, leaderboard_id, entry_index, rank, player_name, score,
                        score_raw, score_type, score_name, is_current_player, is_friend
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        leaderboard_id,
                        entry_base + offset,
                        parse_int(row.get("rank")),
                        row.get("name", ""),
                        parse_float(row.get("score")),
                        row.get("score", ""),
                        parse_int(row.get("scoreType")),
                        row.get("scoreName", ""),
                        parse_bool(row.get("isCurrentPlayer")),
                        parse_bool(row.get("isFriend")),
                    ),
                )
            conn.execute(
                """
                INSERT INTO dump_batches (
                    source_hash, snapshot_id, leaderboard_id, dump_run,
                    range_start, range_end, entries, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    digest,
                    snapshot_id,
                    leaderboard_id,
                    dump_run,
                    range_start,
                    range_end,
                    len(rows),
                    now_iso(),
                ),
            )
            if dump_run:
                conn.execute(
                    """
                    UPDATE snapshots
                    SET entries = (
                            SELECT COUNT(*) FROM entries WHERE snapshot_id = ?
                        ),
                        complete = CASE
                            WHEN ? = 1
                                AND ? IS NOT NULL
                                AND (
                                    SELECT COUNT(*) FROM entries WHERE snapshot_id = ?
                                ) >= ?
                            THEN 1
                            ELSE 0
                        END,
                        range_end = MAX(COALESCE(range_end, 0), COALESCE(?, 0)),
                        total_saved = COALESCE(?, total_saved),
                        imported_at = ?
                    WHERE id = ?
                    """,
                    (
                        snapshot_id,
                        complete,
                        expected,
                        snapshot_id,
                        expected,
                        range_end,
                        total_saved,
                        now_iso(),
                        snapshot_id,
                    ),
                )
            imported += 1

    return ImportSummary(imported, skipped, tuple(errors), pending)


def get_leaderboard_status(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                c.leaderboard_id,
                c.category_id,
                c.category,
                c.name,
                c.score_type,
                c.icon_path,
                s.id AS snapshot_id,
                s.entries,
                s.expected,
                s.complete,
                s.saved_at_ms,
                s.imported_at
            FROM catalog c
            LEFT JOIN snapshots s ON s.id = (
                SELECT id
                FROM snapshots
                WHERE leaderboard_id = c.leaderboard_id
                ORDER BY COALESCE(saved_at_ms, 0) DESC, id DESC
                LIMIT 1
            )
            ORDER BY c.category, CAST(c.leaderboard_id AS INTEGER), c.name
            """
        )
    )


def clear_leaderboard_data(conn: sqlite3.Connection, leaderboard_id: str) -> dict[str, int]:
    counts = {
        "entries": conn.execute(
            "SELECT COUNT(*) FROM entries WHERE leaderboard_id = ?",
            (leaderboard_id,),
        ).fetchone()[0],
        "dump_batches": conn.execute(
            "SELECT COUNT(*) FROM dump_batches WHERE leaderboard_id = ?",
            (leaderboard_id,),
        ).fetchone()[0],
        "snapshots": conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE leaderboard_id = ?",
            (leaderboard_id,),
        ).fetchone()[0],
        "upload_state": conn.execute(
            """
            SELECT COUNT(*)
            FROM upload_state
            WHERE snapshot_id IN (
                SELECT id FROM snapshots WHERE leaderboard_id = ?
            )
            """,
            (leaderboard_id,),
        ).fetchone()[0],
    }
    with conn:
        conn.execute(
            """
            DELETE FROM upload_state
            WHERE snapshot_id IN (
                SELECT id FROM snapshots WHERE leaderboard_id = ?
            )
            """,
            (leaderboard_id,),
        )
        conn.execute("DELETE FROM entries WHERE leaderboard_id = ?", (leaderboard_id,))
        conn.execute("DELETE FROM dump_batches WHERE leaderboard_id = ?", (leaderboard_id,))
        conn.execute("DELETE FROM snapshots WHERE leaderboard_id = ?", (leaderboard_id,))
    return counts


def clear_all_collected_data(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {
        "entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        "dump_batches": conn.execute("SELECT COUNT(*) FROM dump_batches").fetchone()[0],
        "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "upload_state": conn.execute("SELECT COUNT(*) FROM upload_state").fetchone()[0],
    }
    with conn:
        conn.execute("DELETE FROM upload_state")
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM dump_batches")
        conn.execute("DELETE FROM snapshots")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", ("snapshots",))
    return counts


def delete_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict[str, int]:
    counts = {
        "entries": conn.execute(
            "SELECT COUNT(*) FROM entries WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0],
        "dump_batches": conn.execute(
            "SELECT COUNT(*) FROM dump_batches WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0],
        "upload_state": conn.execute(
            "SELECT COUNT(*) FROM upload_state WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0],
        "snapshots": conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()[0],
    }
    with conn:
        conn.execute("DELETE FROM upload_state WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM entries WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM dump_batches WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
    return counts


def get_snapshots(conn: sqlite3.Connection, leaderboard_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, entries, expected, complete, saved_at_ms, imported_at, range_start, range_end
            FROM snapshots
            WHERE leaderboard_id = ?
            ORDER BY COALESCE(saved_at_ms, 0) DESC, id DESC
            """,
            (leaderboard_id,),
        )
    )


def get_snapshot_entries(conn: sqlite3.Connection, snapshot_id: int, limit: int = 500) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT entry_index, rank, player_name, score_raw, score_type, score_name, is_current_player, is_friend
            FROM entries
            WHERE snapshot_id = ?
            ORDER BY entry_index ASC
            LIMIT ?
            """,
            (snapshot_id, limit),
        )
    )


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def normalize_upload_url(value: str | None) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return DEFAULT_UPLOAD_URL
    if normalized.lower().endswith(LEGACY_UPLOAD_PATH):
        return f"{normalized[: -len(LEGACY_UPLOAD_PATH)]}{SNAPSHOT_UPLOAD_PATH}"
    return normalized


def validate_upload_url(value: str) -> str:
    normalized = normalize_upload_url(value)
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("上传地址格式不正确。") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or not parsed.path.endswith(SNAPSHOT_UPLOAD_PATH)):
        raise ValueError("请填写完整的 HTTP(S) 快照接口地址，不要包含账号、密码、查询参数或片段。")
    return normalized


def get_upload_url(conn: sqlite3.Connection) -> str:
    configured = get_setting(conn, "upload_url", DEFAULT_UPLOAD_URL)
    normalized = normalize_upload_url(configured)
    if normalized != configured:
        set_setting(conn, "upload_url", normalized)
    return normalized


def set_upload_url(conn: sqlite3.Connection, value: str) -> str:
    normalized = normalize_upload_url(value)
    set_setting(conn, "upload_url", normalized)
    return normalized


def get_collector_token(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "leaderboard_collector_token").strip()


def set_collector_token(conn: sqlite3.Connection, value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < MIN_COLLECTOR_TOKEN_LENGTH:
        raise ValueError(f"采集密钥至少需要 {MIN_COLLECTOR_TOKEN_LENGTH} 个字符。")
    set_setting(conn, "leaderboard_collector_token", normalized)
    return normalized


def list_upload_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                s.id AS snapshot_id,
                s.leaderboard_id,
                COALESCE(NULLIF(c.name_key, ''), c.name, s.leaderboard_id) AS leaderboard_key,
                COALESCE(c.name, s.leaderboard_id) AS leaderboard_name,
                c.category,
                s.entries,
                s.expected,
                s.complete,
                s.saved_at_ms,
                s.imported_at,
                s.range_start,
                s.range_end,
                COALESCE(u.status, 'pending') AS upload_status,
                u.upload_url,
                u.uploaded_at,
                u.last_attempt_at,
                u.last_error,
                COALESCE(u.retry_count, 0) AS retry_count,
                u.response_code
            FROM snapshots s
            LEFT JOIN catalog c ON c.leaderboard_id = s.leaderboard_id
            LEFT JOIN upload_state u ON u.snapshot_id = s.id
            ORDER BY COALESCE(s.saved_at_ms, 0) DESC, s.id DESC
            """
        )
    )


def list_latest_complete_upload_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            WITH latest AS (
                SELECT s1.id
                FROM snapshots s1
                WHERE s1.complete = 1
                    AND s1.id = (
                        SELECT s2.id
                        FROM snapshots s2
                        WHERE s2.leaderboard_id = s1.leaderboard_id
                            AND s2.complete = 1
                        ORDER BY COALESCE(s2.saved_at_ms, 0) DESC, s2.id DESC
                        LIMIT 1
                    )
            )
            SELECT
                s.id AS snapshot_id,
                s.leaderboard_id,
                COALESCE(NULLIF(c.name_key, ''), c.name, s.leaderboard_id) AS leaderboard_key,
                COALESCE(c.name, s.leaderboard_id) AS leaderboard_name,
                c.category,
                s.entries,
                s.expected,
                s.complete,
                s.saved_at_ms,
                s.imported_at,
                s.range_start,
                s.range_end,
                COALESCE(u.status, 'pending') AS upload_status,
                u.upload_url,
                u.uploaded_at,
                u.last_attempt_at,
                u.last_error,
                COALESCE(u.retry_count, 0) AS retry_count,
                u.response_code
            FROM latest
            JOIN snapshots s ON s.id = latest.id
            LEFT JOIN catalog c ON c.leaderboard_id = s.leaderboard_id
            LEFT JOIN upload_state u ON u.snapshot_id = s.id
            ORDER BY c.category, CAST(s.leaderboard_id AS INTEGER), s.leaderboard_id
            """
        )
    )


def reset_upload_state(conn: sqlite3.Connection, snapshot_ids: list[int]) -> int:
    if not snapshot_ids:
        return 0
    stamp = now_iso()
    with conn:
        for snapshot_id in snapshot_ids:
            conn.execute(
                """
                INSERT INTO upload_state (
                    snapshot_id, status, uploaded_at, last_attempt_at,
                    last_error, retry_count, response_code
                )
                VALUES (?, 'pending', NULL, ?, NULL, 0, NULL)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    status = 'pending',
                    uploaded_at = NULL,
                    last_attempt_at = excluded.last_attempt_at,
                    last_error = NULL,
                    retry_count = 0,
                    response_code = NULL
                """,
                (snapshot_id, stamp),
            )
    return len(snapshot_ids)


def mark_upload_success(
    conn: sqlite3.Connection,
    snapshot_id: int,
    upload_url: str,
    response_code: int | None = None,
) -> None:
    stamp = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO upload_state (
                snapshot_id, upload_url, status, uploaded_at,
                last_attempt_at, last_error, retry_count, response_code
            )
            VALUES (?, ?, 'uploaded', ?, ?, NULL, 0, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                upload_url = excluded.upload_url,
                status = 'uploaded',
                uploaded_at = excluded.uploaded_at,
                last_attempt_at = excluded.last_attempt_at,
                last_error = NULL,
                response_code = excluded.response_code
            """,
            (snapshot_id, upload_url, stamp, stamp, response_code),
        )


def mark_upload_failure(
    conn: sqlite3.Connection,
    snapshot_id: int,
    upload_url: str,
    error: str,
    response_code: int | None = None,
) -> None:
    stamp = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO upload_state (
                snapshot_id, upload_url, status, uploaded_at,
                last_attempt_at, last_error, retry_count, response_code
            )
            VALUES (?, ?, 'failed', NULL, ?, ?, 1, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                upload_url = excluded.upload_url,
                status = 'failed',
                last_attempt_at = excluded.last_attempt_at,
                last_error = excluded.last_error,
                retry_count = upload_state.retry_count + 1,
                response_code = excluded.response_code
            """,
            (snapshot_id, upload_url, stamp, error[:1000], response_code),
        )


def build_upload_payload(conn: sqlite3.Connection, snapshot_id: int) -> dict[str, object]:
    snapshot = conn.execute(
        """
        SELECT
            s.id,
            s.leaderboard_id,
            s.saved_at_ms,
            s.imported_at,
            COALESCE(NULLIF(c.name_key, ''), c.name, s.leaderboard_id) AS leaderboard_key,
            COALESCE(c.name, s.leaderboard_id) AS leaderboard_name
        FROM snapshots s
        LEFT JOIN catalog c ON c.leaderboard_id = s.leaderboard_id
        WHERE s.id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    if snapshot is None:
        raise RuntimeError(f"snapshot {snapshot_id} not found")

    collected_at = timestamp_ms_to_iso(snapshot["saved_at_ms"])
    if not collected_at:
        collected_at = snapshot["imported_at"] or now_iso()

    leaderboard_id = str(snapshot["leaderboard_id"])
    total_mastery_scores: dict[str, tuple[str | None, str | None]] = {}
    if leaderboard_id == TOTAL_MASTERY_LEADERBOARD_ID:
        total_mastery_scores = get_total_mastery_component_scores(conn)

    entries = []
    for row in conn.execute(
        """
        SELECT rank, player_name, score_raw
        FROM entries
        WHERE snapshot_id = ?
        ORDER BY entry_index ASC
        """,
        (snapshot_id,),
    ):
        item: dict[str, object] = {
            "rank": row["rank"],
            "player_name": row["player_name"],
            "score": row["score_raw"],
        }
        mastery = build_upload_mastery_fields(
            leaderboard_id,
            row["score_raw"],
            row["player_name"],
            total_mastery_scores,
        )
        item.update(mastery)
        entries.append(item)
    if not entries:
        raise RuntimeError(f"snapshot {snapshot_id} has no entries")

    return {
        "snapshot_id": snapshot_id,
        "leaderboard_id": snapshot["leaderboard_id"],
        "leaderboard_type": snapshot["leaderboard_key"],
        "leaderboard_key": snapshot["leaderboard_key"],
        "leaderboard_name": snapshot["leaderboard_name"],
        "collected_at": collected_at,
        "items": entries,
    }


def get_snapshot_leaderboard_id(conn: sqlite3.Connection, snapshot_id: int) -> str:
    row = conn.execute(
        "SELECT leaderboard_id FROM snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"snapshot {snapshot_id} not found")
    return str(row["leaderboard_id"])


def load_latest_score_by_player(conn: sqlite3.Connection, leaderboard_id: str) -> dict[str, str]:
    snapshot_id = latest_snapshot_id(conn, leaderboard_id)
    if snapshot_id is None:
        return {}
    return {
        str(row["player_name"]).strip().lower(): row["score_raw"]
        for row in conn.execute(
            """
            SELECT player_name, score_raw
            FROM entries
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )
        if row["player_name"]
    }


def get_total_mastery_component_scores(conn: sqlite3.Connection) -> dict[str, tuple[str | None, str | None]]:
    trove_scores = load_latest_score_by_player(conn, TROVE_MASTERY_LEADERBOARD_ID)
    geode_scores = load_latest_score_by_player(conn, GEODE_MASTERY_LEADERBOARD_ID)
    players = set(trove_scores) | set(geode_scores)
    return {
        player: (trove_scores.get(player), geode_scores.get(player))
        for player in players
    }


def build_upload_mastery_fields(
    leaderboard_id: str,
    score: str | None,
    player_name: str | None,
    total_mastery_scores: dict[str, tuple[str | None, str | None]],
) -> dict[str, object]:
    if leaderboard_id == TROVE_MASTERY_LEADERBOARD_ID:
        mastery = format_mastery_level(score, 1000)
    elif leaderboard_id == GEODE_MASTERY_LEADERBOARD_ID:
        mastery = format_mastery_level(score, 100)
    elif leaderboard_id == TOTAL_MASTERY_LEADERBOARD_ID:
        key = str(player_name or "").strip().lower()
        trove_score, geode_score = total_mastery_scores.get(key, (None, None))
        trove_score, geode_score = infer_total_mastery_component_scores(score, trove_score, geode_score)
        mastery = format_total_mastery_level(trove_score, geode_score)
    else:
        mastery = None

    if mastery is None:
        return {}

    fields: dict[str, object] = {
        "mastery_level": mastery["level"],
        "mastery_level_text": mastery["text"],
    }
    if leaderboard_id == TOTAL_MASTERY_LEADERBOARD_ID:
        fields["trove_mastery_level"] = mastery["trove_level"]
        fields["geode_mastery_level"] = mastery["geode_level"]
    return fields


def latest_snapshot_id(conn: sqlite3.Connection, leaderboard_id: str) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM snapshots
        WHERE leaderboard_id = ?
        ORDER BY COALESCE(saved_at_ms, 0) DESC, id DESC
        LIMIT 1
        """,
        (leaderboard_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def export_latest_csv(conn: sqlite3.Connection, leaderboard_id: str, output_dir: Path) -> Path:
    snapshot_id = latest_snapshot_id(conn, leaderboard_id)
    if snapshot_id is None:
        raise RuntimeError(f"排行榜 {leaderboard_id} 还没有采集数据")

    return export_snapshot_csv(conn, leaderboard_id, snapshot_id, output_dir)


def export_snapshot_csv(
    conn: sqlite3.Connection,
    leaderboard_id: str,
    snapshot_id: int,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = "snapshot"
    row = conn.execute("SELECT saved_at_ms, imported_at FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if row:
        stamp = format_saved_at(row["saved_at_ms"]).replace(":", "").replace(" ", "_") or row["imported_at"].replace(":", "")
    path = output_dir / f"leaderboard_{safe_filename(leaderboard_id)}_{safe_filename(stamp)}.csv"
    rows = get_snapshot_entries(conn, snapshot_id, limit=1_000_000)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "name", "score", "scoreType", "scoreName", "isCurrentPlayer", "isFriend"])
        for row in rows:
            writer.writerow(
                [
                    row["rank"],
                    row["player_name"],
                    row["score_raw"],
                    row["score_type"],
                    row["score_name"],
                    row["is_current_player"],
                    row["is_friend"],
                ]
            )
    return path


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "unknown"


def format_saved_at(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(ms)
