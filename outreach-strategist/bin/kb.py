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
  kb.py batch --ops-file <path-to-json>
      (Task `kb-writer-batching`: one process/one transaction for MANY log/
       edge ops instead of one subprocess per op. The file holds a JSON
       array; each entry is {"verb": "log", ...same fields as `log` above}
       or {"verb": "edge", ...same fields as `edge` above}. Each op is
       validated and committed INDEPENDENTLY -- one bad op degrades to
       {"ok": false, "error": "..."} in that op's own result slot, it does
       NOT abort the rest of the batch, exactly matching running each op as
       its own separate `kb.py log`/`kb.py edge` call would have. Prints a
       single JSON array to stdout, one result per input op, same order:
       {"ok": true, "message": "logged", "notice": null} or
       {"ok": false, "error": "..."}. Exit 0 whenever the batch itself ran
       (per-op failures are in the array, not the exit code); exit 1 only
       for an invocation-level problem (--ops-file missing/unreadable/not a
       JSON array).)
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

#: Resolved further down, once load_kb_config() exists (Task
#: config-driven-kb-path, coordinator addendum B, 2026-09-06) -- see
#: _resolve_db_path()'s own docstring for why the hardcoded in-repo
#: production default this used to fall back to is gone.
DB = None

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
#: A top-level SCALAR key with an inline value on the same line (e.g.
#: ``kb_db_relpath: "_kb/outreach.db"``) -- distinct from ``_TOP_KEY_RE``,
#: which matches only a bare ``key:`` block header. Task
#: config-driven-kb-path (coordinator addendum B, 2026-09-06): the first (and
#: so far only) consumer is ``kb_db_relpath``.
_TOP_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]+(\S.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(\S+)\s*$")
_MAP_ENTRY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(\d+)\s*$")
_TOP_LEVEL_KEYS = ("event_types", "edge_relations", "size_caps")
#: OPTIONAL top-level scalars -- absent entirely is fine (unlike
#: ``_TOP_LEVEL_KEYS``, which every shipped config must carry).
_TOP_LEVEL_SCALAR_KEYS = ("kb_db_relpath",)


def _unquote(raw):
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _parse_kb_config_text(text, path):
    event_types, edge_relations, size_caps = [], [], {}
    scalars = {}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[:1].isspace():
            m = _TOP_SCALAR_RE.match(line)
            if m and m.group(1) in _TOP_LEVEL_SCALAR_KEYS:
                scalars[m.group(1)] = _unquote(m.group(2))
                current = None
                continue
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
    return {"event_types": event_types, "edge_relations": edge_relations,
            "size_caps": size_caps, "kb_db_relpath": scalars.get("kb_db_relpath", "")}


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


def _resolve_db_path():
    """The KB's working DB path -- ``$OUTREACH_KB_DB`` override, else
    kb-config.yaml's ``kb_db_relpath`` resolved against
    ``$OUTREACH_RUNS_DIR``, else refuse.

    Task ``config-driven-kb-path`` (coordinator addendum B, 2026-09-06): this
    used to fall through unconditionally to a HARDCODED in-repo production
    default (``skills/outreach-strategist/knowledge/outreach.db``) the
    moment ``$OUTREACH_KB_DB`` was unset -- no refusal, no isolation,
    nothing stopping a stray invocation from writing (or a test harness from
    polluting) the real, shared knowledge base. Reads kb-config.yaml rather
    than ``config/knowledge-sources.yaml`` (the OTHER two consumers'
    source): kb.py is a standalone script deployed as part of the
    strategist skill bundle and has no reliable relative path back to the
    outreach-engine repo layout, but it already reads kb-config.yaml for its
    vocabulary/size caps, so this is one more key in a file it already
    trusts. A corrupt kb-config here does NOT block resolution (a config
    typo in the event-type vocabulary must not also break knowing where the
    database is) -- it just means ``kb_db_relpath`` is treated as unset.
    Exits (clean message, no traceback) rather than raising, matching every
    other fail-loud path in this CLI.
    """
    override = (os.environ.get("OUTREACH_KB_DB") or "").strip()
    if override:
        return override
    try:
        cfg = load_kb_config()
    except KbConfigError:
        cfg = {}
    relpath = str(cfg.get("kb_db_relpath") or "").strip()
    runs_dir = (os.environ.get("OUTREACH_RUNS_DIR") or "").strip()
    if relpath and runs_dir:
        return os.path.join(runs_dir, relpath)
    sys.exit(
        "kb.py: no knowledge-base path resolvable -- set $OUTREACH_KB_DB "
        "directly, or both $OUTREACH_RUNS_DIR and kb-config.yaml's "
        "'kb_db_relpath' key. No process may fall through to the in-repo "
        "production knowledge base by default."
    )


DB = _resolve_db_path()


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


def _do_log(c, cfg, ns):
    """The ``log`` verb's actual work, shared by the single-op CLI path and
    the ``batch`` verb below (Task ``kb-writer-batching``) so both run the
    EXACT same validation + insert, never two implementations that could
    drift. ``ns`` needs ``.type .summary .campaign .stream .contact .company
    .url .data .tag`` and an optional ``.allow_new_type`` (defaults False
    when absent, e.g. a batch op that omitted it).

    Returns ``(ok, message, notice)``: ``notice`` is the new-event-type
    warning line (or ``None``) kept SEPARATE from ``message`` so a caller
    that wants to print them can reproduce the original two-line CLI output
    exactly (notice first, then "logged"); ``message`` is the error text on
    failure or the literal string ``"logged"`` on success. Never raises;
    every failure mode here is a validation problem, returned, not thrown.
    """
    notice = None
    if ns.type not in cfg["event_types"]:
        if not getattr(ns, "allow_new_type", False):
            valid = ", ".join(cfg["event_types"])
            return False, (
                f"unknown event type {ns.type!r}; valid types: {valid} "
                f"(pass --allow-new-type to accept a new type ad hoc)"), None
        notice = (f"new event type accepted: {ns.type} (not in kb-config.yaml; "
                 f"consider promoting it there)")

    for field_name in ("summary", "url", "data"):
        val = getattr(ns, field_name, None)
        cap = cfg["size_caps"].get(field_name)
        if val is not None and cap is not None and len(val) > cap:
            return False, (
                f"--{field_name} exceeds configured cap of {cap} characters "
                f"(got {len(val)})"), None

    if ns.data:
        try:
            json.loads(ns.data)
        except json.JSONDecodeError as e:
            return False, f"--data is not valid JSON: {e.msg}", None

    c.execute(
        "INSERT INTO events(type,campaign,stream,contact,company,summary,url,data,tag) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ns.type, ns.campaign, getattr(ns, "stream", None), ns.contact, ns.company,
         ns.summary, ns.url, ns.data, getattr(ns, "tag", None)),
    )
    c.commit()
    return True, "logged", notice


def _do_edge(c, cfg, ns):
    """The ``edge`` verb's actual work, shared with ``batch`` exactly like
    :func:`_do_log`. ``ns`` needs ``.src .rel .dst .note``. Returns
    ``(ok, message)`` -- ``message`` is the error text on failure or the
    literal string ``"edge ok"`` on success."""
    if ns.rel not in cfg["edge_relations"]:
        valid = ", ".join(cfg["edge_relations"])
        return False, f"unknown edge relation {ns.rel!r}; valid relations: {valid}"
    c.execute(
        "INSERT INTO edges(src,rel,dst,note) VALUES (?,?,?,?) "
        "ON CONFLICT(src,rel,dst) DO UPDATE SET ts=strftime('%Y-%m-%dT%H:%M:%SZ','now'), note=excluded.note",
        (ns.src, ns.rel, ns.dst, ns.note),
    )
    c.commit()
    return True, "edge ok"


def _batch_op_namespace(op):
    """A ``log``/``edge`` op dict (from a ``batch --ops-file`` JSON array)
    turned into the same attribute shape :func:`_do_log`/:func:`_do_edge`
    read off an argparse ``Namespace`` -- so batch ops and single-op CLI
    calls run through IDENTICAL code. Missing fields default to ``None``
    (``allow_new_type`` to ``False``) rather than raising ``AttributeError``
    deep inside ``_do_log``/``_do_edge`` on a sloppy caller's op dict."""
    verb = op.get("verb")
    if verb == "log":
        return argparse.Namespace(
            type=op.get("type"), summary=op.get("summary"),
            campaign=op.get("campaign"), stream=op.get("stream"),
            contact=op.get("contact"), company=op.get("company"),
            url=op.get("url"), data=op.get("data"), tag=op.get("tag"),
            allow_new_type=bool(op.get("allow_new_type")))
    if verb == "edge":
        return argparse.Namespace(
            src=op.get("src"), rel=op.get("rel"), dst=op.get("dst"),
            note=op.get("note"))
    return None


def _run_batch_ops(c, cfg, ops):
    """One result dict per input op, SAME order, never raises: a malformed
    op degrades to ``{"ok": False, "error": ...}`` in its own slot rather
    than aborting the rest of the batch -- matching what running each op as
    its own separate ``kb.py log``/``kb.py edge`` call would have done
    (one op's failure never blocks a SIBLING's write).

    An ``edge`` op may carry ``"requires": <int>``, the 0-based index of an
    EARLIER op in this same batch whose success gates this edge -- restores
    the pre-batching invariant "no edge without its event" (kb_writer.py
    used to attempt an edge only after its own fact's event write
    succeeded; batching queues both up front, so without this the coupling
    would be lost). ``requires`` must reference an op that has ALREADY been
    processed (index < this op's own index) -- ops run strictly in order,
    one process/one pass, so that is exactly "the op it depends on already
    has a result". An out-of-range or forward-referencing ``requires`` is
    itself a batch-construction bug and fails that op closed rather than
    guessing."""
    results = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "verb" not in op:
            results.append({"ok": False, "error": f"op[{i}] missing 'verb'"})
            continue
        verb = op.get("verb")
        if verb == "log":
            if not op.get("type") or not op.get("summary") or not op.get("contact"):
                results.append({"ok": False,
                                "error": f"op[{i}] log missing required "
                                        f"type/summary/contact"})
                continue
            ns = _batch_op_namespace(op)
            ok, msg, notice = _do_log(c, cfg, ns)
            results.append({"ok": ok, "message" if ok else "error": msg,
                            "notice": notice})
        elif verb == "edge":
            requires = op.get("requires")
            if requires is not None:
                if (not isinstance(requires, int) or isinstance(requires, bool)
                        or requires < 0 or requires >= i):
                    results.append({"ok": False,
                                    "error": f"op[{i}] 'requires' index "
                                            f"{requires!r} does not reference "
                                            f"an earlier op in this batch"})
                    continue
                if not results[requires].get("ok"):
                    results.append({"ok": False,
                                    "error": f"skipped: required op[{requires}] "
                                            f"failed, so its edge is not written"})
                    continue
            if not op.get("src") or not op.get("rel") or not op.get("dst"):
                results.append({"ok": False,
                                "error": f"op[{i}] edge missing required "
                                        f"src/rel/dst"})
                continue
            ns = _batch_op_namespace(op)
            ok, msg = _do_edge(c, cfg, ns)
            results.append({"ok": ok, "message" if ok else "error": msg})
        else:
            results.append({"ok": False, "error": f"op[{i}] unknown verb {verb!r}"})
    return results


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
    bp = sub.add_parser("batch")
    bp.add_argument("--ops-file", required=True)
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
        ok, msg, notice = _do_log(c, cfg, a)
        if not ok:
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(1)
        if notice:
            print(notice)
        print(msg)
    elif a.cmd == "edge":
        ok, msg = _do_edge(c, cfg, a)
        if not ok:
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(1)
        print(msg)
    elif a.cmd == "batch":
        try:
            with open(a.ops_file, "r", encoding="utf-8") as f:
                ops = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: cannot read --ops-file {a.ops_file}: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(ops, list):
            print("error: --ops-file must contain a JSON array of ops", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(_run_batch_ops(c, cfg, ops)))
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
