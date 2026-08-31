#!/usr/bin/env python3
"""kb.py — outreach knowledge base (SQLite): event log + knowledge graph.

Single source of memory for the outreach strategist. EVERYTHING gets logged:
sends, replies, social interactions, signals, research findings, decisions,
bookings, suppressions. Query before acting on any contact/company so the
agent connects dots instead of repeating itself.

DB: skills/outreach-strategist/knowledge/outreach.db (created on first use).

Usage:
  kb.py init
  kb.py log --type reply --campaign revenue-context --stream interviews \
      --contact "jane.doe@acme.com" --company "Acme" \
      --summary "positive, asked for Tuesday slots" --url "" --data '{"raw":"..."}'
      (types: send|reply|signal|social|research|decision|booking|suppression|incident|learning)
  kb.py edge --src "person:jane.doe@acme.com" --rel works_at --dst "company:Acme"
      (nodes are 'kind:key' strings; edges upsert)
  kb.py contact <email-or-name>     # full history for a contact (joins edges)
  kb.py company <name>              # events + people for a company
  kb.py recent [--days 7] [--type reply] [--campaign slug]
  kb.py stats                       # per-campaign/stream/type counts
All output is plain text tables; exit 0 with "none" when empty.
"""
import argparse, json, os, sqlite3, sys, datetime

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

def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c

def rows_out(rows, headers):
    if not rows:
        print("none"); return
    print(" | ".join(headers))
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    lp = sub.add_parser("log")
    for a in ("type", "summary"):
        lp.add_argument("--" + a, required=True)
    for a in ("campaign", "stream", "contact", "company", "url", "data"):
        lp.add_argument("--" + a, default=None)
    ep = sub.add_parser("edge")
    ep.add_argument("--src", required=True); ep.add_argument("--rel", required=True)
    ep.add_argument("--dst", required=True); ep.add_argument("--note", default=None)
    cp = sub.add_parser("contact"); cp.add_argument("key")
    op = sub.add_parser("company"); op.add_argument("key")
    rp = sub.add_parser("recent")
    rp.add_argument("--days", type=int, default=7)
    rp.add_argument("--type", default=None); rp.add_argument("--campaign", default=None)
    sub.add_parser("stats")
    a = p.parse_args()
    c = db()

    if a.cmd == "init":
        print(f"ok db={DB}")
    elif a.cmd == "log":
        if a.data:
            json.loads(a.data)  # validate
        c.execute(
            "INSERT INTO events(type,campaign,stream,contact,company,summary,url,data) VALUES (?,?,?,?,?,?,?,?)",
            (a.type, a.campaign, a.stream, a.contact, a.company, a.summary, a.url, a.data),
        )
        c.commit(); print("logged")
    elif a.cmd == "edge":
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

if __name__ == "__main__":
    main()
