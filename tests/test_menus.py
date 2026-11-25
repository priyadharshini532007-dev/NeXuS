#!/usr/bin/env python3
"""Crawl every reachable button of the Telegram menus offline (Telegram API replaced by a recorder).

Checks: no exceptions, every callback query is answered, every callback_data <= 64 bytes, every screen has text,
typed follow-ups ("/architecture 3") resolve to the listed project, and tasks queued by buttons are not duplicated.
Run: TELEGRAM_CHAT_ID=1 TELEGRAM_BOT_TOKEN=x NEXUS_DATA=<copy of data dir> python tests/test_menus.py
"""
import json
import os
import sys
from collections import Counter, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nexus as N  # noqa: E402

CALLS = []


def fake_tg(method, http_timeout=30, **p):
    CALLS.append((method, p))
    if method in ("sendMessage", "editMessageText"):
        assert p.get("text"), f"{method} without text"
        assert len(p["text"]) <= 4096, f"{method} text too long ({len(p['text'])})"
    return {"ok": True, "result": {"message_id": len(CALLS)}}


N.tg = fake_tg
import cloud_bot as B  # noqa: E402

B.init()
CHAT = B.CHAT
uid = [1000]


def send_text(text):
    uid[0] += 1
    B.handle_update({"update_id": uid[0], "message": {"chat": {"id": int(CHAT)}, "text": text}})


def tap(data):
    uid[0] += 1
    start = len(CALLS)
    B.handle_update({"update_id": uid[0], "callback_query": {"id": f"q{uid[0]}", "data": data,
                                                             "message": {"chat": {"id": int(CHAT)}, "message_id": 5}}})
    new = CALLS[start:]
    answered = any(m == "answerCallbackQuery" for m, _ in new)
    errors = [p.get("text", "") for m, p in new if m == "sendMessage" and "Menu error" in p.get("text", "")]
    kbs = [json.loads(p["reply_markup"])["inline_keyboard"] for m, p in new if "reply_markup" in p]
    return answered, errors, kbs


def buttons(kbs):
    for kb in kbs:
        for row in kb:
            for b in row:
                yield b["callback_data"]


def main():
    fails = []
    send_text("/ideas")
    first = [json.loads(p["reply_markup"])["inline_keyboard"] for m, p in CALLS if "reply_markup" in p]
    assert first, "/ideas did not show a menu"
    seen, queue, kinds = set(), deque(buttons(first)), Counter()
    while queue and len(seen) < 4000:
        d = queue.popleft()
        if d in seen:
            continue
        seen.add(d)
        if len(d.encode()) > 64:
            fails.append(f"callback too long: {d}")
        kinds[d.split("|")[0]] += 1
        if len(seen) % 200 == 0:
            print(f"  ...{len(seen)} buttons tapped, {len(fails)} failures so far", flush=True)
        ans, errs, kbs = tap(d)
        if not ans:
            fails.append(f"not answered: {d}")
        if errs:
            fails.append(f"error on {d}: {errs[0][:120]}")
        for nd in buttons(kbs):
            if nd not in seen and not nd.startswith("x:"):
                queue.append(nd)
    print(f"crawled {len(seen)} distinct buttons: {dict(kinds)}")

    # stale / malformed / out-of-range callbacks must be handled, not crash
    for d in ("zzz", "B|healthcare|999", "L|99|-|sc|0|u", "P|no-such-project", "A|j|no-such-project", "D|nosuch", "MC|x"):
        ans, errs, _ = tap(d)
        if not ans or errs:
            fails.append(f"bad handling of stale callback {d}: answered={ans} errors={errs}")

    # repeated button -> no duplicate task
    before = B.tdb().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    tap("R|healthcare|-"); tap("R|healthcare|-")
    after = B.tdb().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if after - before > 1:
        fails.append(f"repeated Refresh created {after - before} tasks")

    # context: list cyber projects, then "/architecture 2" must target project 2 of that list
    tap("L|" + B.MENU.enc(["cyber"]) + "|-|nv|0|u")
    last = json.loads(B.kv_get("last_ids", "[]"))
    send_text("/architecture 2")
    t = B.tdb().execute("SELECT cmd,args FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
    msgs, files = B.run_command(t["cmd"], t["args"])
    if not any(last[1] in str(f[1]) for f in files):
        fails.append(f"/architecture 2 did not build project 2 ({last[1]}): {msgs}")
    send_text("show me the novelty of project 1")
    t = B.tdb().execute("SELECT cmd,args FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
    msgs, _ = B.run_command(t["cmd"], t["args"])
    p1 = B.plans_by_id().get(last[0])
    if t["cmd"] != "validate" or not p1 or p1["name"][:30] not in str(msgs):
        fails.append(f"natural-language follow-up failed: {t['cmd']} {t['args']}")

    # tasks queued by buttons actually run
    for cmd, args in (("news", "healthcare"), ("idea", "healthcare medical imaging")):
        msgs, _ = B.run_command(cmd, args)
        if not msgs:
            fails.append(f"task {cmd} {args} produced nothing")

    print("FAILURES:" if fails else "ALL CHECKS PASSED")
    for f in fails:
        print("  -", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
