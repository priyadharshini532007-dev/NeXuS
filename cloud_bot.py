#!/usr/bin/env python3
"""NEXUS cloud service: Telegram long-polling listener + persistent task queue + workers + scheduler.

Designed to run in a container on an always-on host. It needs NO laptop: state lives in NEXUS_DATA (a volume).
Every accepted command is stored, acknowledged with a task ID, executed by a background worker, and ends in a
result or an explicit failure message. Results are kept so `/result NX-12` can resend them.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required); ANTHROPIC_API_KEY (optional, deep research/blueprints);
     NEXUS_DATA, NEXUS_WORKERS (2), NEXUS_FETCH_HOURS (6), NEXUS_DIGEST_HOUR (7, container local time), TZ.
"""
import json, os, re, sqlite3, sys, threading, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nexus as N

CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
WORKERS = int(os.environ.get("NEXUS_WORKERS", "2"))
FETCH_H = float(os.environ.get("NEXUS_FETCH_HOURS", "6"))
DIGEST_H = int(os.environ.get("NEXUS_DIGEST_HOUR", "7"))
TDB = N.DATA / "tasks.db"
HEART = N.DATA / "heartbeat"
LOCK = threading.Lock()
STARTED = time.time()
STOP = threading.Event()  # set when a time-boxed run (GitHub Actions) is ending


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def tdb():
    c = sqlite3.connect(TDB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with tdb() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS updates(update_id INTEGER PRIMARY KEY, received TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, cmd TEXT, args TEXT, status TEXT,
          created TEXT, started TEXT, finished TEXT, error TEXT, result TEXT, delivered INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        """)
        # crash recovery: anything that was mid-run goes back in the queue
        c.execute("UPDATE tasks SET status='QUEUED' WHERE status='RUNNING'")


def kv_get(k, d=None):
    with tdb() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else d


def kv_set(k, v):
    with tdb() as c:
        c.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code(i):
    return f"NX-{i:03d}"


def say(msgs, retries=3):
    """Send with retry/backoff; returns True if delivered."""
    if isinstance(msgs, (str, dict)):
        msgs = [msgs]
    for attempt in range(retries):
        try:
            N.tg_send(CHAT, msgs)
            return True
        except Exception as e:  # noqa
            log("send failed:", str(e)[:120])
            time.sleep(2 ** attempt * 2)
    return False


# ------------------------------------------------------------------ commands
HELP = ("<b>NEXUS commands</b>\n"
        "/idea - project ideas with fresh news (tap Explore for a blueprint)\n"
        "/cyber [n] - cybersecurity ideas + top security news\n"
        "/briefing - short technology briefing\n"
        "/trend - topics rising in the last 3 days\n"
        "/problems - real-world problems behind today's ideas\n"
        "/opportunities - best matches between news and ideas\n"
        "/projects - ideas you've explored\n"
        "/knowledge &lt;words&gt; - search stored news\n"
        "/validate &lt;id&gt; - novelty checklist and prior-art searches\n"
        "/architecture &lt;id&gt; | /implement &lt;id&gt; | /github &lt;id&gt; - blueprint (PDF + MD)\n"
        "/compare &lt;id1&gt; &lt;id2&gt; - side by side\n"
        "/research &lt;topic&gt; | /deepdive &lt;topic&gt; - AI analysis (needs API key; no live web search)\n"
        "/result &lt;NX-id&gt; - resend a finished result\n"
        "/status - real health report\n/pause | /resume - scheduled digests\n\n"
        "Follow-ups work too: <code>explain idea 2</code> uses the last list I showed.")

QUEUED_CMDS = {"idea", "cyber", "briefing", "trend", "problems", "opportunities", "projects", "knowledge", "validate",
               "architecture", "implement", "github", "compare", "research", "deepdive", "explore", "result", "explain"}
ALIASES = {"ideas": "idea", "security": "cyber", "cybersecurity": "cyber", "daily": "briefing"}


def plans_by_id():
    return {p["id"]: p for p in N.match(N.load_plans(), N.load_items())}


def remember(msgs):
    ids = [m["id"] for m in msgs if isinstance(m, dict)]
    if ids:
        kv_set("last_ids", json.dumps(ids))


def run_command(cmd, args):
    """Execute one command; return list of Telegram messages (str or {'t','id'} cards) and optional files."""
    files = []
    a = args.split()
    num = next((int(x) for x in a if x.isdigit()), None)
    if cmd == "idea":
        m = N.build_msgs(None, min(num or 12, 30)); remember(m); return m, files
    if cmd == "cyber":
        m = N.build_msgs("security", min(num or 15, 30)); remember(m); return m, files
    if cmd == "briefing":
        m = N.build_msgs(None, 5); remember(m); return m, files
    if cmd == "trend":
        items = N.load_items(3); cnt = {}
        for it in items:
            for t in it["tags"]:
                cnt[t] = cnt.get(t, 0) + 1
        top = sorted(cnt.items(), key=lambda x: -x[1])[:10]
        return ["<b>Topics in the last 3 days</b> (item counts across %d items)\n" % len(items) +
                "\n".join(f"{t}: {n}" for t, n in top) + "\n<i>Counts show coverage, not importance.</i>"], files
    if cmd in ("problems", "opportunities"):
        ps = sorted(plans_by_id().values(), key=lambda p: -p["heat"])[:8]
        if cmd == "problems":
            body = "\n\n".join(f"<b>{N.esc(p['name'].split(':')[0])}</b>\n{N.esc(p['problem'])}\n<i>Verify:</i> {N.esc(p['verify'])}" for p in ps)
            return ["<b>Problems behind today's ideas</b> (evidence still to be checked)\n\n" + body], files
        body = "\n".join(f"{i}. <code>{p['id']}</code> heat {p['heat']} - {N.esc(p['name'].split(':')[0])}" for i, p in enumerate(ps, 1))
        return ["<b>Strongest news-to-idea matches</b>\n" + body], files
    if cmd == "projects":
        d = N.DATA / "projects"
        done = sorted(x.name for x in d.iterdir()) if d.exists() else []
        return ["<b>Explored ideas</b>\n" + ("\n".join(f"<code>{x}</code>" for x in done) or "none yet - tap Explore on an idea")], files
    if cmd == "knowledge":
        q = f"%{args.strip()}%"
        rows = N.db().execute("SELECT title,url,source,type FROM items WHERE title LIKE ? OR summary LIKE ? ORDER BY published DESC LIMIT 10", (q, q)).fetchall()
        if not args.strip():
            return ["Usage: <code>/knowledge secrets</code>"], files
        return ["<b>Stored items matching</b> " + N.esc(args) + "\n" + ("\n".join(
            f"{N.ICON.get(r[3], '')} <a href=\"{N.html.escape(r[1])}\">{N.esc(r[0][:90])}</a> - {N.esc(r[2])}" for r in rows) or "nothing found")], files
    if cmd in ("validate", "compare", "architecture", "implement", "github", "explore", "explain"):
        P = plans_by_id()
        ids = [x for x in a if x in P]
        if cmd == "explain" and num:
            last = json.loads(kv_get("last_ids", "[]"))
            ids = [last[num - 1]] if 0 < num <= len(last) else []
        if not ids:
            return [f"Which idea? Use its id, e.g. <code>/{cmd} secrets-leak-radar</code>"
                    + (" or say <code>explain idea 2</code> after a list." if cmd == "explain" else "")], files
        if cmd == "explain":
            return [{"t": card_text(P[ids[0]]), "id": ids[0]}], files
        if cmd == "validate":
            p = P[ids[0]]
            return [f"<b>Novelty check: {N.esc(p['name'])}</b>\n\n<b>Existing:</b> {N.esc(p['existing'])}\n\n<b>Hypothesis (unverified):</b> {N.esc(p['novelty'])}\n\n"
                    "<b>Searches to run before claiming anything:</b>\n" + "\n".join(f"- {N.esc(q)}" for q in p["prior_art"]) +
                    "\n\n<i>I have not searched patents or papers; this is a checklist, not a finding.</i>"], files
        if cmd == "compare":
            if len(ids) < 2:
                return ["Usage: <code>/compare id1 id2</code>"], files
            x, y = P[ids[0]], P[ids[1]]
            row = lambda k: f"<b>{k}</b>\n1) {N.esc(str(x[k]))}\n2) {N.esc(str(y[k]))}"
            return ["<b>Compare</b>\n1 = " + N.esc(x["name"]) + "\n2 = " + N.esc(y["name"]) + "\n\n" + "\n\n".join(row(k) for k in ("level", "fit", "cost", "stack", "risks", "metrics"))], files
        f, mode, pdf = N.explore(ids[0])
        if pdf:
            files.append((pdf, f"Blueprint PDF ({mode}) for {ids[0]}", "application/pdf"))
        files.append((f, f"Blueprint Markdown for {ids[0]}", "text/markdown"))
        return [f"Blueprint ready ({mode}) for <code>{ids[0]}</code>."], files
    if cmd in ("research", "deepdive"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return ["\U0001F6AB <b>Not configured:</b> /research needs ANTHROPIC_API_KEY on the server. Offline commands still work."], files
        if not args.strip():
            return [f"Usage: <code>/{cmd} post-quantum migration</code>"], files
        depth = "an exhaustive, first-principles" if cmd == "deepdive" else "a concise but technical"
        txt = N.llm(f"Give {depth} technical analysis of: {args}\nCover mechanism, existing solutions, limits, open problems, project angles. "
                    "You have NO web access: say what you are unsure of and do not cite sources you cannot verify.", N.SYS, 6000, 300)
        out = N.DATA / "research"; out.mkdir(exist_ok=True)
        f = out / (re.sub(r"\W+", "-", args.strip())[:40] + ".md"); f.write_text(txt, encoding="utf-8")
        files.append((f, "Analysis from model knowledge, not live research. Verify before relying on it.", "text/markdown"))
        return [N.esc(txt[:3500]) + ("\n\n(full text attached)" if len(txt) > 3500 else "")], files
    if cmd == "result":
        raise KeyError("handled elsewhere")
    return [f"Unsupported command: <code>{N.esc(cmd)}</code>. Send /help."], files


def card_text(p):
    first = p["problem"].split(". ")[0].rstrip(".") + "."
    return (f"<b>{N.esc(p['name'])}</b>\n<code>{p['id']}</code>\nLevel {p['level']}/5 | {p['fit']} | {N.esc(p['cost'])}\n\n"
            f"<b>Problem:</b> {N.esc(first)}\n<b>Idea:</b> {N.esc(p['idea'])}\n<b>Risks:</b> {N.esc(p['risks'])}")


# ------------------------------------------------------------------ status
def status_text():
    rows = []
    def chk(name, fn):
        try:
            rows.append(f"\U0001F7E2 {name}: {fn()}")
        except Exception as e:  # noqa
            rows.append(f"\U0001F534 {name}: unavailable ({N.esc(str(e)[:60])})")
    chk("Telegram API", lambda: "operational as @" + N.tg("getMe")["result"]["username"])
    chk("Database", lambda: f"{N.db().execute('SELECT COUNT(*) FROM items').fetchone()[0]} items stored")
    last = N.db().execute("SELECT MAX(last_ok) FROM health").fetchone()[0]
    ok = N.db().execute("SELECT COUNT(*) FROM health WHERE error IS NULL").fetchone()[0]
    bad = N.db().execute("SELECT COUNT(*) FROM health WHERE error IS NOT NULL").fetchone()[0]
    deg = "\U0001F7E1" if bad else "\U0001F7E2"
    rows.append(f"{deg} Sources: {ok} ok, {bad} failing; last success {last or 'never'}")
    with tdb() as c:
        q = {r[0]: r[1] for r in c.execute("SELECT status,COUNT(*) FROM tasks GROUP BY status")}
        lastok = c.execute("SELECT id,finished FROM tasks WHERE status='COMPLETED' ORDER BY id DESC LIMIT 1").fetchone()
        fails = c.execute("SELECT id,cmd,error FROM tasks WHERE status='FAILED' ORDER BY id DESC LIMIT 3").fetchall()
    rows.append(f"\U0001F7E2 Queue: queued {q.get('QUEUED', 0)}, running {q.get('RUNNING', 0)}, completed {q.get('COMPLETED', 0)}, failed {q.get('FAILED', 0)}")
    rows.append(f"Workers: {sum(t.is_alive() for t in THREADS)}/{WORKERS} alive; uptime {int((time.time() - STARTED) / 60)} min")
    rows.append("AI provider: " + ("configured (key present, not test-called)" if os.environ.get("ANTHROPIC_API_KEY") else "⚪ not configured"))
    rows.append(f"Scheduler: fetch every {FETCH_H:g} h, digest daily at {DIGEST_H:02d}:00; " + ("PAUSED" if kv_get("paused") == "1" else "active"))
    if lastok:
        rows.append(f"Last completed task: {code(lastok['id'])} at {lastok['finished']}")
    for f in fails:
        rows.append(f"Failed {code(f['id'])} /{f['cmd']}: {N.esc((f['error'] or '')[:80])}")
    return "<b>NEXUS status</b>\n" + "\n".join(rows)


# ------------------------------------------------------------------ queue + workers
def enqueue(cmd, args):
    with tdb() as c:
        cur = c.execute("INSERT INTO tasks(cmd,args,status,created) VALUES(?,?,?,?)", (cmd, args, "QUEUED", now()))
        return cur.lastrowid


def claim():
    with LOCK, tdb() as c:
        r = c.execute("SELECT * FROM tasks WHERE status='QUEUED' ORDER BY id LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE tasks SET status='RUNNING', started=?, attempts=attempts+1 WHERE id=?", (now(), r["id"]))
        return r


def finish(tid, status, result=None, error=None, delivered=0):
    with tdb() as c:
        c.execute("UPDATE tasks SET status=?, finished=?, result=?, error=?, delivered=? WHERE id=?",
                  (status, now(), json.dumps(result) if result is not None else None, error, delivered, tid))


def worker():
    while True:
        t = claim()
        if not t:
            if STOP.is_set():
                return
            time.sleep(1.5); continue
        tid, cmd, args = t["id"], t["cmd"], t["args"] or ""
        try:
            if cmd == "result":
                with tdb() as c:
                    r = c.execute("SELECT * FROM tasks WHERE id=?", (int(re.sub(r"\D", "", args) or 0),)).fetchone()
                msgs = (json.loads(r["result"]) if r and r["result"] else
                        [f"No stored result for <code>{N.esc(args)}</code>."])
                ok = say(msgs)
                finish(tid, "COMPLETED", None, None, 1 if ok else 0)
                continue
            msgs, files = run_command(cmd, args)
            finish(tid, "COMPLETED", msgs, None, 0)
            ok = say(msgs)
            for f, cap, mime in files:
                try:
                    N.tg_doc(CHAT, f, cap, mime)
                except Exception as e:  # noqa
                    log("file send failed:", e); ok = False
            say(f"✅ {code(tid)} /{cmd} done." if ok else f"⚠ {code(tid)} finished but delivery had problems; send <code>/result {code(tid)}</code>.")
            with tdb() as c:
                c.execute("UPDATE tasks SET delivered=? WHERE id=?", (1 if ok else 0, tid))
        except Exception as e:  # noqa
            log("task failed", tid, traceback.format_exc()[-400:])
            finish(tid, "FAILED", None, f"{type(e).__name__}: {e}")
            say(f"❌ {code(tid)} /{cmd} failed: {N.esc(str(e)[:200])}\nSend the command again to retry; completed work was kept.")


# ------------------------------------------------------------------ scheduler
def scheduler():
    last_fetch = float(kv_get("last_fetch", "0"))
    while True:
        try:
            if time.time() - last_fetch > FETCH_H * 3600:
                N.fetch_all(); N.build(); last_fetch = time.time(); kv_set("last_fetch", last_fetch)
                cut = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()  # keep state small
                with N.db() as c:
                    c.execute("DELETE FROM items WHERE fetched < ?", (cut,))
            today = datetime.now().strftime("%Y-%m-%d")
            if datetime.now().hour >= DIGEST_H and kv_get("last_digest") != today and kv_get("paused") != "1":
                m = N.build_msgs(None, 12); remember(m); say(m); kv_set("last_digest", today)
        except Exception as e:  # noqa
            log("scheduler error:", e)
            try:
                say(f"⚠ Scheduler error: {N.esc(str(e)[:150])}")
            except Exception:
                pass
        time.sleep(300)


# ------------------------------------------------------------------ polling / routing
def handle_update(u):
    with tdb() as c:
        try:
            c.execute("INSERT INTO updates VALUES(?,?)", (u["update_id"], now()))  # persist before acknowledging
        except sqlite3.IntegrityError:
            return  # duplicate delivery
    cq = u.get("callback_query")
    if cq:
        if str((cq.get("message") or {}).get("chat", {}).get("id")) != CHAT:
            return
        N.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Working on it...")
        d = str(cq.get("data", ""))
        if d.startswith("x:"):
            tid = enqueue("explore", d[2:])
            say(f"\U0001F50E NEXUS received your request.\nTask ID: <code>{code(tid)}</code>\nBuilding the blueprint for <code>{N.esc(d[2:])}</code> (PDF + Markdown).")
        return
    m = u.get("message") or {}
    if str(m.get("chat", {}).get("id")) != CHAT:
        if m:
            log("ignored unauthorised chat", m.get("chat", {}).get("id"))
        return
    text = (m.get("text") or "").strip()
    if not text:
        say("I can only read text commands. Send /help."); return
    words = text.split()
    first = words[0].split("@")[0].lower()
    if first.startswith("/"):
        cmd, args = ALIASES.get(first[1:], first[1:]), " ".join(words[1:])
    else:  # natural follow-ups
        low = text.lower()
        mm = re.search(r"(?:idea|number|no\.?|#)\s*(\d+)", low)
        if mm and any(k in low for k in ("explain", "tell", "show", "idea", "details")):
            cmd, args = "explain", mm.group(1)
        elif low.split()[0] in ("cyber", "security", "ideas", "idea", "briefing"):
            cmd, args = ALIASES.get(low.split()[0], low.split()[0]), " ".join(words[1:])
        else:
            say("I didn't understand that. Try /help, or say <code>explain idea 2</code> after a list."); return
    if cmd == "start":
        say("\U0001F7E2 <b>NEXUS is online</b> and running in the cloud.\n\n" + HELP); return
    if cmd == "help":
        say(HELP); return
    if cmd == "status":
        say(status_text()); return
    if cmd == "pause":
        kv_set("paused", "1"); say("⏸ Scheduled digests paused. Commands still work. /resume to restart."); return
    if cmd == "resume":
        kv_set("paused", "0"); say("▶ Scheduled digests resumed."); return
    if cmd == "alerts":
        say(f"Alerts: daily digest at {DIGEST_H:02d}:00 ({'paused' if kv_get('paused') == '1' else 'active'}); new-source failures are reported here. /pause or /resume to change."); return
    if cmd in QUEUED_CMDS:
        tid = enqueue(cmd, args)
        with tdb() as c:
            ahead = c.execute("SELECT COUNT(*) FROM tasks WHERE status IN('QUEUED','RUNNING') AND id<?", (tid,)).fetchone()[0]
        say(f"\U0001F9E0 NEXUS received <code>/{cmd}</code>.\nTask ID: <code>{code(tid)}</code>"
            f"{'' if not ahead else f' ({ahead} ahead in the queue)'}\nI'll send the result here when it's ready.")
        return
    say(f"Unknown command <code>/{N.esc(cmd)}</code>. Send /help for the list.")


THREADS = []


def main():
    if not (CHAT and os.environ.get("TELEGRAM_BOT_TOKEN")):
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
    init()
    try:
        N.tg("setMyCommands", commands=json.dumps([{"command": c, "description": d} for c, d in [
            ("idea", "Project ideas"), ("cyber", "Cybersecurity ideas"), ("briefing", "Short briefing"), ("status", "System health"),
            ("projects", "Explored ideas"), ("help", "All commands")]]))
    except Exception as e:  # noqa
        log("setMyCommands:", e)
    for _ in range(WORKERS):
        t = threading.Thread(target=worker, daemon=True); t.start(); THREADS.append(t)
    threading.Thread(target=scheduler, daemon=True).start()
    log("NEXUS cloud service started")
    run_min = float(os.environ.get("NEXUS_RUN_MINUTES", "0"))  # >0 = time-boxed run (GitHub Actions)
    deadline = time.time() + run_min * 60 if run_min else None
    offset = None
    while not (deadline and time.time() > deadline):
        HEART.write_text(str(time.time()))
        try:
            r = N.tg("getUpdates", http_timeout=70, timeout=50, **({"offset": offset} if offset else {}))
        except Exception as e:  # noqa
            log("poll error:", str(e)[:100]); time.sleep(8); continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            try:
                handle_update(u)
            except Exception as e:  # noqa
                log("update error:", traceback.format_exc()[-300:])
                try:
                    say(f"❌ I received your message but hit an error: {N.esc(str(e)[:150])}")
                except Exception:
                    pass
    # time-boxed run ending: confirm last updates, let workers finish queued tasks, then exit so state can be saved
    try:
        N.tg("getUpdates", timeout=0, **({"offset": offset} if offset else {}))
    except Exception:
        pass
    STOP.set()
    drain = time.time() + float(os.environ.get("NEXUS_DRAIN_MINUTES", "8")) * 60
    for t in THREADS:
        t.join(max(0, drain - time.time()))
    log("run finished; unfinished tasks (if any) stay queued for the next run")


if __name__ == "__main__":
    main()
