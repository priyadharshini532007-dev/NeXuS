"""Freshness engine: never repeat an idea, turn today's sources into NEW project directions, learn rising topics,
and import your Feedly sources (OPML export).

Sparks are *directions derived from real items* (a paper, a repo, a security event, a claim). They are not vetted
plans: each one tells you to verify the problem and novelty first. No LLM is needed; they are template-built from
the item so they never claim more than the item supports.
"""
import hashlib, json, re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone

STOP = set("""about above after again against all also and any are because been before being between both but can could did does
doing down during each few for from further had has have having her here hers him his how into its itself just more most not
now off once only other our out over own same she should some such than that the their them then there these they this those
through too under until very was were what when where which while who whom why will with would you your new says say using use
used via how why what vs get gets its one two more first week year years report reports show shows study researchers""".split())


def init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS shown(id TEXT, at TEXT);
    CREATE INDEX IF NOT EXISTS shown_id ON shown(id);
    CREATE TABLE IF NOT EXISTS sparks(id TEXT PRIMARY KEY, json TEXT, at TEXT);
    """)


def _now():
    return datetime.now(timezone.utc)


def seen(c, days=45):
    cut = (_now() - timedelta(days=days)).isoformat()
    return {r[0] for r in c.execute("SELECT id FROM shown WHERE at > ?", (cut,))}


def mark(c, ids):
    t = _now().isoformat(timespec="seconds")
    c.executemany("INSERT INTO shown VALUES(?,?)", [(i, t) for i in ids])
    c.commit()


def _words(t, n=4):
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{4,}", t):
        w = w.lower()
        if w not in STOP and w not in out:
            out.append(w)
    return out[:n]


def _kind(it):
    s = it["source"]
    if s.startswith("arXiv"):
        return "paper"
    if s.startswith("GitHub"):
        return "repo"
    if it["cat"] == "security" or "security" in it["tags"]:
        return "sec"
    return "claim"


def _plan(it):
    k = _kind(it)
    full = it["title"].split(" - ")[0].strip()
    t = re.sub(r"\s+", " ", it["title"]).strip()[:90]
    base = dict(id="sp-" + it["id"], spark=True, kw=_words(it["title"]), tags=it["tags"] or ["data"],
                source_item=dict(title=it["title"], url=it["url"], source=it["source"], type=it["type"], published=it["published"]))
    common = dict(hw="Laptop", cost="Free", level=2, fit="weeks")
    if k == "paper":
        return {**base, **common, "level": 3, "name": f"Reproduce and stress-test: {t}",
                "problem": f"The paper '{t}' reports results that stay unverified until someone reproduces them; whether they hold under other data, seeds or settings is unknown.",
                "verify": "Read the paper and any code release; list the headline claims and the exact metrics.",
                "existing": "The authors' own experiments; look for follow-ups, critiques or independent reproductions.",
                "idea": "Reproduce the main result from scratch, then test robustness (ablations, distribution shift, other datasets, seeds) and write a reproducibility report.",
                "novelty": "Hypothesis: a careful independent reproduction with new stress tests is itself a contribution. It is not a new method.",
                "stack": "Python, PyTorch or JAX (whatever the paper uses), CSV/W&B logging, Docker",
                "stages": "Read paper and code -> run or reimplement baseline -> match reported numbers -> add stress tests -> compare -> write report",
                "hw": "Laptop or GPU (check the paper's requirements)", "cost": "Free to USD 30 of compute",
                "risks": "Missing code or data; compute limits; results may not reproduce (report that honestly).",
                "metrics": "Reproduced vs reported metric gap, robustness drop under shift, run-to-run variance",
                "prior_art": [t, f"{t} github implementation", f"{t} reproducibility"]}
    if k == "repo":
        return {**base, **common, "fit": "48h", "name": f"Audit and extend: {full}",
                "problem": f"The new open-source project '{full}' is gaining attention, but its reliability, security and real performance versus alternatives have not been checked by you.",
                "verify": "Read its README, issues and licence; run it; check tests and recent commits.",
                "existing": "The repository itself and its closest alternatives (search by topic).",
                "idea": "Benchmark it against one or two alternatives, review it for security and robustness, fix or extend something real, and contribute upstream.",
                "novelty": "Hypothesis: a rigorous comparison plus an accepted upstream contribution is valuable even though the tool is not yours.",
                "stack": "The repo's language, Docker, pytest or equivalent, benchmark scripts",
                "stages": "Run it -> read the code -> write tests and benchmarks -> compare with alternatives -> security review -> contribute a fix or feature",
                "risks": "Project may be immature or abandoned; maintainers may not accept changes.",
                "metrics": "Benchmark numbers vs alternatives, tests added, issues or PRs accepted",
                "prior_art": [f"{full} alternatives", f"{full} vulnerabilities", f"{full} benchmark"]}
    if k == "sec":
        return {**base, **common, "level": 3, "tags": sorted(set(base["tags"]) | {"security"}), "name": f"Lab replication and detector: {t}",
                "problem": f"A reported security event ('{t}') points to an attack class defenders may not detect; the real mechanism is only described in news.",
                "verify": "Find the primary advisory or vendor write-up (CISA, vendor blog, CVE entry) and read the technical details.",
                "existing": "Vendor detections and advisories; public Sigma, YARA and Suricata rules.",
                "idea": "Reproduce the weakness class in an isolated lab you own (never against real systems), then write and evaluate a detection or hardening control with measured false positives.",
                "novelty": "Hypothesis: a documented, tested detector for this class may add to public rules. Check existing rules first.",
                "stack": "Isolated VM lab, Wireshark/Zeek or Sysmon, Sigma/YARA, Python for evaluation",
                "stages": "Read primary source -> build isolated lab -> reproduce safely -> capture telemetry -> write detection -> measure detection and false positives -> write up",
                "hw": "Laptop with VM support",
                "risks": "Scope and legality: only your own lab; public details may be incomplete; detection may be evaded.",
                "metrics": "Detection rate on lab replays, false positives on benign data, time to detect",
                "prior_art": [f"{t} sigma rule", f"{t} technical analysis", "MITRE ATT&CK technique for this behaviour"]}
    return {**base, **common, "name": f"Test the claim: {t}",
            "problem": f"A headline claims something ('{t}'); whether it holds up in practice is not established.",
            "verify": "Find the primary source (paper, release notes, repository) behind the headline.",
            "existing": "The original announcement and any independent coverage.",
            "idea": "Build the smallest experiment that tests the central claim and measure it against a simple baseline.",
            "novelty": "Hypothesis: an independent small test adds evidence even if the idea itself is not new.",
            "stack": "Python plus whatever the claim needs", "stages": "Find primary source -> define the claim as a measurable statement -> build minimal test -> compare with baseline -> report",
            "risks": "The claim may be marketing with nothing testable; data may be unavailable.",
            "metrics": "Measured effect vs baseline, with variance",
            "prior_art": [t, f"{t} independent evaluation"]}


def make_sparks(c, items, k, security=False, tags=None, words=None):
    """Create up to k NEW sparks from today's best items (one per item, ever). Returns the new plan dicts."""
    if k <= 0:
        return []
    have = {r[0] for r in c.execute("SELECT id FROM sparks")}
    groups = {"paper": [], "repo": [], "sec": [], "claim": []}
    for it in sorted(items, key=lambda i: -i["score"]):
        if "sp-" + it["id"] in have or len(it["title"]) < 25:
            continue
        kd = _kind(it)
        if security and kd != "sec" and "security" not in it["tags"]:
            continue
        if tags and not (set(it["tags"]) & tags):
            continue
        if words and not any(w in (it["title"] + " " + it["summary"]).lower() for w in words):
            continue
        groups[kd].append(it)
    order = ["sec", "paper", "repo", "claim"] if security else ["paper", "sec", "repo", "claim"]
    picked, used_src = [], Counter()
    while len(picked) < k and any(groups[g] for g in order):
        for g in order:
            while groups[g] and used_src[groups[g][0]["source"]] >= 2:
                groups[g].pop(0)
            if groups[g] and len(picked) < k:
                it = groups[g].pop(0); used_src[it["source"]] += 1; picked.append(it)
    out = []
    for it in picked:
        p = _plan(it)
        c.execute("INSERT OR IGNORE INTO sparks VALUES(?,?,?)", (p["id"], json.dumps(p), _now().isoformat(timespec="seconds")))
        out.append(p)
    c.commit()
    return out


def load_sparks(c, days=14):
    cut = (_now() - timedelta(days=days)).isoformat()
    return [json.loads(r[0]) for r in c.execute("SELECT json FROM sparks WHERE at > ?", (cut,))]


def rising_terms(c, recent_days=3, older_days=21, top=12):
    """Terms whose share of titles jumped recently, seen in 2+ different sources. Learns vocabulary from the feeds."""
    now = _now()
    rows = c.execute("SELECT title, source, COALESCE(published, fetched) FROM items WHERE dup_of IS NULL").fetchall()
    rec, old, srcs = Counter(), Counter(), {}
    nr = no = 0
    for title, source, when in rows:
        try:
            d = datetime.fromisoformat(when.replace("Z", "+00:00"))
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        age = (now - d).days
        if age > older_days:
            continue
        ws = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", title.lower())
        toks = {w for w in ws if w not in STOP} | {f"{a} {b}" for a, b in zip(ws, ws[1:]) if a not in STOP and b not in STOP}
        if age <= recent_days:
            nr += 1
            for t in toks:
                rec[t] += 1; srcs.setdefault(t, set()).add(source)
        else:
            no += 1
            for t in toks:
                old[t] += 1
    out = []
    for t, n in rec.items():
        if n >= 3 and len(srcs[t]) >= 2:
            ratio = (n / max(nr, 1)) / ((old[t] + 1) / max(no, 1))
            if ratio > 2:
                out.append((ratio, t, n, len(srcs[t]), old[t]))
    out.sort(reverse=True)
    covered = {w for _, t, n, *_ in out if " " in t for w in t.split()}
    out = [o for o in out if " " in o[1] or o[1] not in covered]
    return [dict(term=t, recent=n, sources=s, older=o, ratio=round(r, 1)) for r, t, n, s, o in out[:top]]


def import_opml(path, sources_path):
    """Add RSS feeds from a Feedly (or any) OPML export to sources.json. Returns number added."""
    root = ET.parse(path).getroot()
    data = json.load(open(sources_path, encoding="utf-8"))
    have = {s["url"].rstrip("/") for s in data["sources"]}
    added = 0
    for o in root.iter("outline"):
        url = o.get("xmlUrl")
        if url and url.rstrip("/") not in have:
            data["sources"].append({"name": (o.get("title") or o.get("text") or url)[:60], "kind": "rss", "url": url,
                                    "cat": "feedly", "rel": 0.5, "type": "report"})
            have.add(url.rstrip("/")); added += 1
    json.dump(data, open(sources_path, "w", encoding="utf-8"), indent=1)
    return added
