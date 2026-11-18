"""Local accumulation storage; validation here does not certify chemistry."""
import copy
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit


def _json(value):
    def check(v):
        if type(v) is dict:
            if any(type(k) is not str for k in v):
                raise ValueError("JSON keys must be strings")
            for item in v.values():
                check(item)
        elif type(v) is list:
            for item in v:
                check(item)
        elif type(v) not in (str, int, float, bool, type(None)):
            raise ValueError("Expected JSON data")
    try:
        check(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid JSON data") from exc


def _row(row):
    if type(row) is not dict:
        raise ValueError("Expected an object")
    try:
        result = copy.deepcopy(row)
        _json(result).encode("utf-8")
    except (TypeError, RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid JSON data") from exc
    return result


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("Expected a nonempty string")
    return value


def _ids(value):
    if type(value) is not list:
        raise ValueError("Expected an ID list")
    for item in value:
        _text(item)
    if len(set(value)) != len(value):
        raise ValueError("Repeated ID")
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    return tuple(map(_freeze, value)) if isinstance(value, list) else value


def _official(source):
    try:
        raw = source.get("url", "")
        if not raw.startswith("https://") or any(c.isspace() or c == "\\" for c in raw):
            return False
        url = urlsplit(raw)
        return (url.scheme == "https" and url.hostname in {
            "iupac.qmul.ac.uk", "iupac.org", "publications.iupac.org"}
            and url.username is None and url.password is None
            and url.port in (None, 443))
    except ValueError:
        return False


class GrowthStore:
    KINDS = {"rule", "fragment", "topic"}
    STATUSES = {"DRAFT", "SOURCE_CHECKED", "ACTIVE_SCOPED", "DEFERRED", "WITHDRAWN"}

    def __init__(self, root):
        self.path = Path(root) / "data" / "chemistry_growth" / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                BEGIN;
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,kind TEXT NOT NULL,json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,json TEXT NOT NULL,sha256 TEXT NOT NULL,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                COMMIT;
            """)

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def _put(self, table, row):
        _text(row.get("id"))
        row["updated_at"] = _now()
        with self._db(True) as db:
            if table == "cards":
                db.execute("INSERT INTO cards VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,json=excluded.json",
                           (row["id"], row["kind"], _json(row)))
            else:
                db.execute(f"INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json",
                           (row["id"], _json(row)))

    def register_source(self, row):
        row = _row(row)
        for field in ("title", "url", "sha256", "fetched_path"):
            if field in row and type(row[field]) is not str:
                raise ValueError("Source fields must be strings")
        self._put("sources", row)

    def put_card(self, row):
        row = _row(row)
        if row.get("kind") not in tuple(self.KINDS) or row.get("status") not in tuple(self.STATUSES):
            raise ValueError("Invalid card kind or status")
        for field in ("title", "family"):
            _text(row.get(field))
        _ids(row.get("source_ids"))
        if not isinstance(row.get("locator"), (str, dict)) or not row["locator"] or type(row.get("body")) is not dict:
            raise ValueError("Card requires locator and body")
        self._put("cards", row)

    def put_task(self, row):
        self._put("tasks", _row(row))

    def record_cases(self, rows):
        if type(rows) is not list:
            raise ValueError("Expected a list of cases")
        records = []
        for item in rows:
            row = _row(item)
            identity = [_text(row.get(k)) for k in ("source_sha256", "owner_ref", "revision", "result_sha256")]
            _text(row.get('status'))
            source=row.get('src')
            if not ((isinstance(source,str) and source.strip()) or (isinstance(source,list) and all(isinstance(x,str) and x for x in source))):
                raise ValueError('Case source must be a locator or locator list')
            if type(row.get("names")) is not list or any(type(n) is not str for n in row["names"]):
                raise ValueError("Case names must be a string list")
            row.update(id=_hash(identity), case_id=_hash(identity), created_at=_now(),
                       approved_for_rules=False, training_data_eligible=False, independent_review="NOT_REVIEWED")
            records.append(row)
        added = 0
        with self._db(True) as db:
            for row in records:
                added += db.execute("INSERT OR IGNORE INTO cases VALUES(?,?)", (row["id"], _json(row))).rowcount
        return {"added": added, "duplicates": len(records) - added}

    @staticmethod
    def _get(db, table, identity):
        found = db.execute(f"SELECT json FROM {table} WHERE id=?", (identity,)).fetchone()
        if found is None:
            raise ValueError(f"Missing {table} record: {identity}")
        return json.loads(found[0])

    @staticmethod
    def _save_release(db, release):
        encoded, digest = _json(release), _hash(release)
        old = db.execute("SELECT json,sha256 FROM releases WHERE id=?", (release["id"],)).fetchone()
        if old and old != (encoded, digest):
            raise ValueError("Release ID already has different content")
        db.execute("INSERT OR IGNORE INTO releases VALUES(?,?,?,?)", (release["id"], encoded, digest, _now()))
        db.execute("INSERT INTO meta VALUES('current_release',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (release["id"],))
        return {"id": release["id"], "sha256": digest}

    def publish(self, release):
        release = _row(release)
        if set(release) - {"id", "version", "scope", "validation", "independent_review", "rule_ids", "fragment_ids"}:
            raise ValueError("Unexpected release fields")
        if not re.fullmatch(r"CK-[A-Za-z0-9._-]+", _text(release.get("id"))):
            raise ValueError("Invalid release ID")
        _text(release.get("version"))
        if type(release.get("scope")) not in (str, list, dict) or not release["scope"]:
            raise ValueError("Explicit scope required")
        validation = release.get("validation")
        if type(validation) is not dict or release.get("independent_review") != "NOT_REVIEWED":
            raise ValueError("Explicit unreviewed validation required")
        if type(validation.get("tests_exit")) is not int or validation["tests_exit"] != 0:
            raise ValueError("Tests must pass")
        for key in ("positive_count", "negative_count"):
            if type(validation.get(key)) is not int or validation[key] <= 0:
                raise ValueError("Positive and negative evidence required")
        _text(validation.get("source_checked_by"))
        with self._db(True) as db:
            cards, sources = [], {}
            for kind in ("rule", "fragment"):
                for identity in _ids(release.get(kind + "_ids")):
                    card = self._get(db, "cards", identity)
                    if card["kind"] != kind or card["status"] != "ACTIVE_SCOPED":
                        raise ValueError("Selected card must be ACTIVE_SCOPED with matching kind")
                    refs = [self._get(db, "sources", sid) for sid in card["source_ids"]]
                    if not any(_official(source) for source in refs):
                        raise ValueError("Selected card requires an IUPAC source URL")
                    body = card["body"]
                    if kind == "rule":
                        _text(body.get("entry_point"))
                        if type(body.get("supported_scope")) not in (str, list, dict) or not body["supported_scope"]:
                            raise ValueError("Rule supported_scope required")
                    elif (type(body.get("graph")) is not dict or type(body.get("port_count")) is not int
                          or body["port_count"] < 0 or body.get("identity_kind") not in
                          ("finite_molecule", "bound_residue", "constitutive_subunit")):
                        raise ValueError("Invalid fragment role")
                    cards.append(card)
                    sources.update({source["id"]: source for source in refs})
            release.update(cards=cards, sources=[sources[k] for k in sorted(sources)])
            return self._save_release(db, release)

    def _current(self, db):
        pointer = db.execute("SELECT value FROM meta WHERE key='current_release'").fetchone()
        if not pointer:
            return None
        row = db.execute("SELECT json,sha256 FROM releases WHERE id=?", pointer).fetchone()
        if not row or hashlib.sha256(row[0].encode("utf-8")).hexdigest() != row[1]:
            raise ValueError("Release integrity verification failed")
        release = json.loads(row[0])
        if release.get("id") != pointer[0]:
            raise ValueError("Release pointer mismatch")
        return release

    def current(self):
        with self._db() as db:
            return _freeze(self._current(db))

    def withdraw(self, card_id, reason):
        _text(card_id)
        _text(reason)
        with self._db(True) as db:
            release = self._current(db)
            if release is None or card_id not in release["rule_ids"] + release["fragment_ids"]:
                raise ValueError("Card is absent from current release")
            release.update(parent_release=release["id"], id="CK-" + uuid.uuid4().hex,
                           withdrawal={"card_id": card_id, "reason": reason, "created": _now()})
            for key in ("rule_ids", "fragment_ids"):
                release[key] = [i for i in release[key] if i != card_id]
            release["cards"] = [c for c in release["cards"] if c["id"] != card_id]
            return self._save_release(db, release)

    def recent_cases(self, limit=40):
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError("Case limit must be 1..1000")
        with self._db() as db:
            rows=db.execute("SELECT json FROM cases ORDER BY json_extract(json,'$.created_at') DESC,id DESC LIMIT ?",(limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def snapshot(self, query="", kind=None):
        if type(query) is not str or (kind is not None and kind not in tuple(self.KINDS)):
            raise ValueError("Invalid snapshot filter")
        result, totals, counts = {}, {}, {}
        with self._db() as db:
            db.execute("BEGIN")
            for table in ("sources", "cards", "cases", "tasks"):
                rows = [json.loads(r[0]) for r in db.execute(f"SELECT json FROM {table} ORDER BY id")]
                totals[table] = len(rows)
                fields = ("id", "title", "url", "kind", "family", "locator", "status", "names", "owner_ref", "revision", "src", "summary")
                rows = [r for r in rows if (table != "cards" or kind is None or r["kind"] == kind)
                        and query.casefold() in " ".join(str(r.get(k, "")) for k in fields).casefold()]
                counts[table] = len(rows)
                result[table] = rows[:300] if table == "cases" else rows
            result["releases"] = [dict(zip(("id", "sha256", "created"), r)) for r in db.execute("SELECT id,sha256,created FROM releases ORDER BY created,id")]
            pointer = db.execute("SELECT value FROM meta WHERE key='current_release'").fetchone()
        result["tasks"] = [({**{k: r[k] for k in ("id", "title", "status", "updated_at") if k in r}, "payload_omitted": True}
                            if len(_json(r).encode("utf-8")) > 4096 else r) for r in result["tasks"]]
        counts["releases"] = totals["releases"] = len(result["releases"])
        result.update(current_release=pointer[0] if pointer else None, counts=counts, totals=totals,
                      cases_truncated=counts["cases"] > 300)
        return result
