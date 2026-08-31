#!/usr/bin/env python3
"""kb.py — outreach knowledge base (SQLite): event log + knowledge graph.

Single source of memory for the outreach strategist. EVERYTHING gets logged:
sends, replies, social interactions, signals, research findings, decisions,
bookings, suppressions. Query before acting on any contact/company so the
agent connects dots instead of repeating itself.

DB: skills/outreach-strategist/knowledge/outreach.db (created on first use).
Vocabulary + size caps: skills/outreach-strategist/knowledge/kb-config.yaml
(override the path with $OUTREACH_KB_CONFIG; unset uses the shipped file).

Usage:
  kb.py init
  kb.py log --type reply --campaign revenue-context --stream interviews \
      --contact "jane.doe@acme.com" --company "Acme" \
      --summary "positive, asked for Tuesday slots" --url "" --data '{"raw":"..."}' \
      [--tag test] [--allow-new-type]
      (types come from kb-config.yaml's event_types list; --allow-new-type
       is an escape hatch that accepts+logs an unrecognized type instead of
       rejecting it)
  kb.py edge --src "person:jane.doe@acme.com" --rel works_at --dst "company:Acme"
      (nodes are 'kind:key' strings; edges upsert; --rel must be a
       kb-config.yaml edge_relations value)
  kb.py contact <email-or-name>     # full history for a contact (joins edges)
  kb.py company <name>              # events + people for a company
  kb.py recent [--days 7] [--type reply] [--campaign slug]
  kb.py stats                       # per-campaign/stream/type counts
  kb.py purge [--tag T | --ids 1,2,3 | --before <ts> --like <SQL-LIKE-pattern>] [--confirm]
      (selector-based cleanup; DEFAULT IS DRY-RUN — reports the row count it
       would delete and deletes nothing unless --confirm is passed; refuses
       to run with no selector at all, since that would mean "delete
       everything")
All output is plain text tables; exit 0 with "none" when empty.
"""
import argparse, json, os, re, sqlite3, sys, datetime

DB = os.environ.get(
    "OUTREACH_KB_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "outreach.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  type TEXT NOT NULL,
  campaign TEXT, stream TEXT, contact TEXT, company TEXT,
  summary TEXT NOT NULL, url TEXT, data TEXT
);
CREATE INDEX IF NOT EXISTS ev_contact ON events(contact);
CREATE INDEX IF NOT EXISTS ev_company ON events(company);
CREATE INDEX IF NOT EXISTS ev_type_ts ON events(type, ts);
CREATE TABLE IF NOT EXISTS edges(
  src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  note TEXT, PRIMARY KEY (src, rel, dst)
);
"""


# ---------------------------------------------------------------------------
# kb-config.yaml — minimal stdlib parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

class KbConfigError(RuntimeError):
    """Raised for any missing/unreadable/corrupt kb-config.yaml. Always
    printed as a single fail-loud message naming the config path — never a
    silent fallback to built-in defaults."""


_TOP_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(#.*)?$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(\S+)\s*$")
_MAP_ENTRY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(\d+)\s*$")
_TOP_LEVEL_KEYS = ("event_types", "edge_relations", "size_caps")


def _parse_kb_config_text(text, path):
    event_types, edge_relations, size_caps = [], [], {}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[:1].isspace():
            m = _TOP_KEY_RE.match(line)
            if not m or m.group(1) not in _TOP_LEVEL_KEYS:
                raise KbConfigError(
                    f"corrupt kb-config {path}: unrecognized line: {raw_line!r}"
                )
            current = m.group(1)
            continue
        if current in ("event_types", "edge_relations"):
            m = _LIST_ITEM_RE.match(line)
            if not m:
                raise KbConfigError(
                    f"corrupt kb-config {path}: expected a list item under "
                    f"{current!r}, got: {raw_line!r}"
                )
            (event_types if current == "event_types" else edge_relations).append(m.group(1))
        elif current == "size_caps":
            m = _MAP_ENTRY_RE.match(line)
            if not m:
                raise KbConfigError(
                    f"corrupt kb-config {path}: expected an integer mapping "
                    f"under 'size_caps', got: {raw_line!r}"
                )
            size_caps[m.group(1)] = int(m.group(2))
        else:
            raise KbConfigError(
                f"corrupt kb-config {path}: indented content before any "
                f"top-level key: {raw_line!r}"
            )
    if not event_types:
        raise KbConfigError(f"corrupt kb-config {path}: 'event_types' is missing or empty")
    if not edge_relations:
        raise KbConfigError(f"corrupt kb-config {path}: 'edge_relations' is missing or empty")
    if "summary" not in size_caps:
        raise KbConfigError(f"corrupt kb-config {path}: 'size_caps.summary' is missing")
    return {"event_types": event_types, "edge_relations": edge_relations, "size_caps": size_caps}


def _default_kb_config_path():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "kb-config.yaml"
    )


def load_kb_config():
    path = os.environ.get("OUTREACH_KB_CONFIG") or _default_kb_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise KbConfigError(f"kb-config unreadable at {path}: {e}") from e
    return _parse_kb_config_text(text, path)


# ---------------------------------------------------------------------------
# DB connection: WAL + busy_timeout (concurrent cron writers), tag migration
# ---------------------------------------------------------------------------

def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    # PRAGMAs per research/outreach-policy-defaults.md Q3: WAL keeps readers
    # and writers from blocking each other; busy_timeout makes the retry
    # window explicit (not an implicit stdlib default a future refactor could
    # drop); synchronous=NORMAL is the standard safe pairing with WAL.
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA busy_timeout=5000;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.executescript(SCHEMA)
    cols = {row[1] for row in c.execute("PRAGMA table_info(events)").fetchall()}
    if "tag" not in cols:
        c.execute("ALTER TABLE events ADD COLUMN tag TEXT")
        c.commit()
    return c


def rows_out(rows, headers):
    if not rows:
        print("none"); return
    print(" | ".join(headers))
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))


def _check_size(value, cap, field_name):
    if value is None or cap is None:
        return
    if len(value) > cap:
        print(
            f"error: --{field_name} exceeds configured cap of {cap} characters "
            f"(got {len(value)})",
            file=sys.stderr,
        )
        sys.exit(1)


def _purge_conditions(a):
    conditions, params = [], []
    if a.ids:
        try:
            ids = [int(x.strip()) for x in a.ids.split(",") if x.strip()]
        except ValueError:
            print("error: --ids must be a comma-separated list of integers", file=sys.stderr)
            sys.exit(1)
        if not ids:
            print("error: --ids must not be empty", file=sys.stderr)
            sys.exit(1)
        conditions.append(f"id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    if a.tag:
        conditions.append("tag = ?")
        params.append(a.tag)
    if a.before:
        conditions.append("ts < ?")
        params.append(a.before)
    if a.like:
        conditions.append("summary LIKE ?")
        params.append(a.like)
    return conditions, params


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    lp = sub.add_parser("log")
    for a in ("type", "summary"):
        lp.add_argument("--" + a, required=True)
    for a in ("campaign", "stream", "contact", "company", "url", "data", "tag"):
        lp.add_argument("--" + a, default=None)
    lp.add_argument("--allow-new-type", action="store_true")
    ep = sub.add_parser("edge")
    ep.add_argument("--src", required=True); ep.add_argument("--rel", required=True)
    ep.add_argument("--dst", required=True); ep.add_argument("--note", default=None)
    cp = sub.add_parser("contact"); cp.add_argument("key")
    op = sub.add_parser("company"); op.add_argument("key")
    rp = sub.add_parser("recent")
    rp.add_argument("--days", type=int, default=7)
    rp.add_argument("--type", default=None); rp.add_argument("--campaign", default=None)
    sub.add_parser("stats")
    pp = sub.add_parser("purge")
    pp.add_argument("--tag", default=None)
    pp.add_argument("--ids", default=None)
    pp.add_argument("--before", default=None)
    pp.add_argument("--like", default=None)
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--confirm", action="store_true")
    a = p.parse_args()

    try:
        cfg = load_kb_config()
    except KbConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    c = db()

    if a.cmd == "init":
        print(f"ok db={DB}")
    elif a.cmd == "log":
        new_type_notice = None
        if a.type not in cfg["event_types"]:
            if not a.allow_new_type:
                valid = ", ".join(cfg["event_types"])
                print(
                    f"error: unknown event type {a.type!r}; valid types: {valid} "
                    f"(pass --allow-new-type to accept a new type ad hoc)",
                    file=sys.stderr,
                )
                sys.exit(1)
            new_type_notice = (
                f"new event type accepted: {a.type} (not in kb-config.yaml; "
                f"consider promoting it there)"
            )

        _check_size(a.summary, cfg["size_caps"].get("summary"), "summary")
        _check_size(a.url, cfg["size_caps"].get("url"), "url")
        _check_size(a.data, cfg["size_caps"].get("data"), "data")

        if a.data:
            try:
                json.loads(a.data)
            except json.JSONDecodeError as e:
                print(f"error: --data is not valid JSON: {e.msg}", file=sys.stderr)
                sys.exit(1)

        c.execute(
            "INSERT INTO events(type,campaign,stream,contact,company,summary,url,data,tag) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (a.type, a.campaign, a.stream, a.contact, a.company, a.summary, a.url, a.data, a.tag),
        )
        c.commit()
        if new_type_notice:
            print(new_type_notice)
        print("logged")
    elif a.cmd == "edge":
        if a.rel not in cfg["edge_relations"]:
            valid = ", ".join(cfg["edge_relations"])
            print(
                f"error: unknown edge relation {a.rel!r}; valid relations: {valid}",
                file=sys.stderr,
            )
            sys.exit(1)
        c.execute(
            "INSERT INTO edges(src,rel,dst,note) VALUES (?,?,?,?) "
            "ON CONFLICT(src,rel,dst) DO UPDATE SET ts=strftime('%Y-%m-%dT%H:%M:%SZ','now'), note=excluded.note",
            (a.src, a.rel, a.dst, a.note),
        )
        c.commit(); print("edge ok")
    elif a.cmd == "contact":
        k = f"%{a.key}%"
        rows_out(c.execute(
            "SELECT ts,type,campaign,stream,summary,url FROM events WHERE contact LIKE ? ORDER BY ts DESC LIMIT 100", (k,)
        ).fetchall(), ["ts", "type", "campaign", "stream", "summary", "url"])
        print("-- edges --")
        rows_out(c.execute(
            "SELECT src,rel,dst,note FROM edges WHERE src LIKE ? OR dst LIKE ? LIMIT 50", (k, k)
        ).fetchall(), ["src", "rel", "dst", "note"])
    elif a.cmd == "company":
        k = f"%{a.key}%"
        rows_out(c.execute(
            "SELECT ts,type,campaign,stream,contact,summary FROM events WHERE company LIKE ? ORDER BY ts DESC LIMIT 100", (k,)
        ).fetchall(), ["ts", "type", "campaign", "stream", "contact", "summary"])
        print("-- edges --")
        rows_out(c.execute(
            "SELECT src,rel,dst,note FROM edges WHERE src LIKE ? OR dst LIKE ? LIMIT 50", (k, k)
        ).fetchall(), ["src", "rel", "dst", "note"])
    elif a.cmd == "recent":
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = "SELECT ts,type,campaign,stream,contact,company,summary FROM events WHERE ts>=?"
        args = [since]
        if a.type: q += " AND type=?"; args.append(a.type)
        if a.campaign: q += " AND campaign=?"; args.append(a.campaign)
        rows_out(c.execute(q + " ORDER BY ts DESC LIMIT 200", args).fetchall(),
                 ["ts", "type", "campaign", "stream", "contact", "company", "summary"])
    elif a.cmd == "stats":
        rows_out(c.execute(
            "SELECT campaign,stream,type,COUNT(*) FROM events GROUP BY campaign,stream,type ORDER BY campaign,stream,type"
        ).fetchall(), ["campaign", "stream", "type", "count"])
    elif a.cmd == "purge":
        conditions, params = _purge_conditions(a)
        if not conditions:
            print(
                "error: purge requires at least one selector "
                "(--tag, --ids, --before, and/or --like) — refusing to run "
                "unscoped (that would mean 'delete everything')",
                file=sys.stderr,
            )
            sys.exit(1)
        where = " AND ".join(conditions)
        count = c.execute(f"SELECT COUNT(*) FROM events WHERE {where}", params).fetchone()[0]
        do_delete = bool(a.confirm) and not a.dry_run
        if do_delete:
            c.execute(f"DELETE FROM events WHERE {where}", params)
            c.commit()
            print(f"deleted {count} row(s)")
        else:
            print(f"[dry-run] would delete {count} row(s) (pass --confirm to delete)")

if __name__ == "__main__":
    main()
