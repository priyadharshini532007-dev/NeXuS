#!/usr/bin/env python3
"""End-to-end test of the research agent with a stand-in LLM (no key or network LLM needed).

Checks: Google News gathering stores new items; news is grouped into topics; a cycle keeps good ideas and rejects
(a) ideas the critic drops and (b) near-copies of catalogue ideas; kept ideas appear in the catalogue, the menus and
/idea (first, marked as agent ideas) and are not shown twice; spent news does not produce the same topic again;
'not interested' feedback reaches the next prompt; with no key the agent says so instead of inventing ideas.
Run: TELEGRAM_CHAT_ID=1 TELEGRAM_BOT_TOKEN=x NEXUS_DATA=<copy of data dir> python tests/test_agent.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nexus as N  # noqa: E402

N.tg = lambda method, http_timeout=30, **p: {"ok": True, "result": {"message_id": 1}}
import agent as AG  # noqa: E402
import cloud_bot as B  # noqa: E402

PROMPTS = []
CAT = json.load(open(N.ROOT / "plans.json", encoding="utf-8"))
COPY = next(p for p in CAT if p["id"] == "ecg-edge-shift")
ROUND = [0]


def fake_chat(system, user, max_tokens=4000, temperature=0.8):
    PROMPTS.append((system, user))
    if system == AG.SYS_GEN:
        ROUND[0] += 1
        r = ROUND[0]
        base = dict(sub="digital health", cross=["ai"], signal=1, why_now="news", existing="manual review", stack=["Python", "FastAPI"],
                    steps=["collect data", "build model", "evaluate", "demo"], hardware="none", cost="Free", difficulty=3,
                    time="weeks", risks=["data access"], metrics="F1 on held-out set", keywords=["triage"], searches=["q1", "q2"],
                    innovation="cross-domain", build="ai", scores=dict(feasibility=4, novelty=3, impact=4, scalability=3,
                                                                        research=3, hackathon=4, portfolio=4))
        ideas = [dict(base, name=f"WardWatch {r}: overnight deterioration alerts from nurse notes",
                      problem=f"Round {r}: night-shift nurses miss slow patient deterioration hidden in free-text notes.",
                      solution="An NLP model flags worrying trends in nursing notes and vitals and pages the duty doctor."),
                 dict(base, name=COPY["name"], problem=COPY["problem"], solution=COPY["idea"]),          # near-copy of catalogue
                 dict(base, name=f"PillSnap {r}: photo-based pill identification for pharmacies",
                      problem="Pharmacists in rural shops confuse look-alike generic pills.",
                      solution="A phone app identifies pills from a photo."),                              # critic drops
                 dict(base, name=f"SoilSense {r}: antibiotic-residue test strips read by phone",
                      problem=f"Round {r}: farms overuse antibiotics and residues reach milk and soil undetected.",
                      solution="Cheap colorimetric strips read by a phone camera model estimate residue levels.", cross=["agriculture"])]
        return json.dumps({"ideas": ideas})
    n = len(json.loads(user.split("Ideas (JSON):\n", 1)[1].split("\n\nReturn", 1)[0]))
    return json.dumps({"reviews": [dict(index=i, verdict="drop" if i == 2 else "keep", reason="too generic" if i == 2 else "solid",
                                        closest_existing="none known", scores=dict(feasibility=4, novelty=4, impact=4,
                                                                                    scalability=3, research=3, hackathon=4, portfolio=4),
                                        sharpen="validate with one hospital ward") for i in range(n)]})


def main():
    fails = []
    B.init()
    c = N.db()

    # 0. no key: honest refusal, nothing invented
    rep = AG.cycle(N, c, "healthcare", gather_first=False)
    print("no-key cycle:", rep["note"])
    if rep["kept"] or "no free LLM key" not in rep["note"]:
        fails.append(f"no-key cycle should explain and keep nothing: {rep}")

    # 1. gathering from Google News
    before = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    g = AG.gather(N, c, "healthcare")
    after = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"gathered {g} new healthcare items ({before} -> {after})")
    if g <= 0 or after - before != g:
        fails.append(f"gather stored {g} (count {before}->{after})")

    # 2. topics
    sigs = AG.signals(N, c, "healthcare")
    print(f"{len(sigs)} topics; top: " + " | ".join(f"{len(s['items'])} items/{s['sources']} src: {s['items'][0]['title'][:50]}" for s in sigs))
    if not sigs:
        fails.append("no healthcare topics found")

    # 3. full cycle with the stand-in LLM
    AG.chat = fake_chat
    AG.provider = lambda: ("Stand-in", "", "", "fake-model")
    rep = AG.cycle(N, c, "healthcare", gather_first=False)
    kept = [p["name"] for p in rep["kept"]]
    print("cycle 1 kept:", kept, "rejected:", rep["rejected"], rep["note"])
    if len(kept) != 2 or not any("WardWatch" in k for k in kept) or not any("SoilSense" in k for k in kept):
        fails.append(f"cycle 1 should keep WardWatch + SoilSense, kept {kept}")
    why = dict(rep["rejected"])
    if not any("too similar" in w for w in why.values()):
        fails.append(f"the catalogue near-copy was not rejected as duplicate: {why}")
    if not any("critic" in w for w in why.values()):
        fails.append(f"the critic's drop was ignored: {why}")
    gen_prompt = next(u for s, u in PROMPTS if s == AG.SYS_GEN)
    if COPY["name"][:60] not in gen_prompt:
        fails.append("existing catalogue ideas were not listed in the generation prompt")

    # 4. ideas reach catalogue, menus and /idea; shown once
    rows = {r["id"]: r for r in N.catalog_rows()}
    for p in rep["kept"]:
        r = rows.get(p["id"])
        if not r or r["d"] != "healthcare" or not r["p"].get("gen"):
            fails.append(f"kept idea missing from catalogue: {p['id']}")
    text, kb = B.MENU.list_screen(N, B.CTX, B.CHAT, "G", "-", "lt", 0, "u")
    if "WardWatch" not in text:
        fails.append("agent ideas missing from the 🤖 New agent ideas menu")
    text, kb = B.MENU.domain_menu(N, "healthcare")
    if "Agent ideas (2)" not in json.dumps(kb, ensure_ascii=False):
        fails.append("domain menu does not show the agent-ideas button with count 2")
    m1 = B.domain_mission("healthcare", 4)
    cards1 = [x["id"] for x in m1 if isinstance(x, dict)]
    if not cards1 or not cards1[0].startswith("ag-"):
        fails.append(f"/idea healthcare should show agent ideas first: {cards1}")
    m2 = B.domain_mission("healthcare", 4)
    cards2 = [x["id"] for x in m2 if isinstance(x, dict)]
    rep_ids = set(cards1) & set(cards2) - {x for x in cards2 if x.startswith("sp-")}
    if rep_ids:
        fails.append(f"ideas repeated on the second /idea: {rep_ids}")

    # 5. second cycle: used topics skipped, earlier ideas not regenerated
    n_sig2 = len(AG.signals(N, c, "healthcare"))
    rep2 = AG.cycle(N, c, "healthcare", gather_first=False)
    print(f"cycle 2: {n_sig2} fresh topics left; kept {[p['name'] for p in rep2['kept']]}; rejected {rep2['rejected']}; {rep2['note']}")
    used_titles = {s["items"][0]["title"] for s in sigs}
    if any(s["items"][0]["title"] in used_titles for s in AG.signals(N, c, "healthcare")):
        fails.append("a topic that already produced ideas came back as fresh")

    # 6. feedback reaches the next prompt
    B.MENU.project_action(N, B.CTX, B.CHAT, "n", rep["kept"][0]["id"])
    PROMPTS.clear()
    AG.cycle(N, c, "healthcare", gather_first=False)
    gp = next((u for s, u in PROMPTS if s == AG.SYS_GEN), "")
    if gp and "REJECTED" not in gp:
        fails.append("'not interested' feedback was not passed to the agent")

    # 7. the bot command and status
    msgs = B.agent_run("healthcare", None)
    print("bot /agent healthcare ->", re.sub(r"<[^>]+>", "", msgs[0])[:200].replace("\n", " | "))
    print("status:", AG.status(c))
    print("auto picks:", AG.pick_domains(N, c, 3))

    print("FAILURES:" if fails else "ALL CHECKS PASSED")
    for f in fails:
        print("  -", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
