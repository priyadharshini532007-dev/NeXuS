"""Project catalogue: domains, metadata, tiers, filters, sorting, cross-domain search, persistent shortlist/archive.

All scores are NEXUS screening estimates (1-5) stored in catalogue_meta.json - not validated findings.
"""
import csv, html, json, re
from datetime import datetime, timezone
from pathlib import Path

# key: (label, subdomains, aliases)
DOMAINS = {
 "cyber": ("Cybersecurity", ["network security", "application security", "cloud security", "endpoint security", "mobile security", "iot security",
           "ot/ics security", "hardware & firmware security", "digital forensics", "malware analysis", "threat intelligence", "reverse engineering",
           "cryptography", "post-quantum cryptography", "ai & llm security", "identity & access", "privacy engineering", "supply-chain security",
           "critical infrastructure", "automotive & aerospace security", "fraud detection"], ["cyber", "cybersecurity", "security", "infosec"]),
 "ai": ("AI, data & computing", ["machine learning", "deep learning", "generative ai", "agentic ai", "multi-agent systems", "computer vision", "nlp",
        "speech & audio", "edge ai", "federated learning", "explainable ai", "reinforcement learning", "data engineering", "knowledge graphs",
        "distributed computing", "quantum computing", "neuromorphic computing", "human-computer interaction"], ["ai", "ml", "machinelearning", "data"]),
 "healthcare": ("Healthcare & biotech", ["medical diagnostics", "preventive healthcare", "medical imaging", "digital health", "wearable health", "remote monitoring",
                "assistive technology", "rehabilitation", "biomedical engineering", "bioinformatics", "genomics", "drug discovery", "medical robotics",
                "hospital operations", "public health", "healthcare data security", "mental health tech", "disease surveillance", "patient monitoring",
                "brain-computer interfaces"], ["healthcare", "health", "medical", "medicine", "biotech", "bio"]),
 "fintech": ("FinTech & payments", ["digital payments", "banking technology", "fraud detection", "financial cybersecurity", "credit risk", "financial inclusion",
             "regtech", "insurtech", "blockchain finance", "defi security", "personal finance intelligence"], ["fintech", "payments", "banking", "finance"]),
 "stockmarket": ("Stock market & trading research", ["market surveillance", "algorithmic trading research", "financial forecasting", "stock analytics",
                 "portfolio risk", "alternative data", "market microstructure"], ["stockmarket", "stocks", "stock", "market", "trading", "markets"]),
 "economy": ("Economic intelligence", ["economic forecasting", "macroeconomic intelligence", "inflation and price monitoring", "supply and demand",
             "public finance"], ["economy", "economics", "economic", "macro", "inflation"]),
 "supplychain": ("Supply chain & logistics", ["supply-chain intelligence", "product authenticity", "logistics optimisation", "warehouse automation", "fleet management",
                 "cold-chain monitoring", "traceability & provenance", "procurement", "transportation optimisation", "inventory"], ["supplychain", "logistics", "supply", "procurement"]),
 "manufacturing": ("Manufacturing & industry", ["predictive maintenance", "industrial iot", "manufacturing intelligence", "digital twins", "quality control",
                   "smart factories", "industrial robotics"], ["manufacturing", "industry", "industrial", "factory"]),
 "disaster": ("Disaster management", ["disaster prediction", "flood intelligence", "earthquake monitoring", "landslide detection", "cyclone & storm", "wildfire detection",
              "emergency communication", "emergency response", "search & rescue", "community resilience"], ["disaster", "disasters", "emergency", "flood", "resilience"]),
 "climate": ("Climate & environment", ["climate intelligence", "environmental monitoring", "air-quality monitoring", "water-resource management", "waste management",
             "carbon monitoring", "climate adaptation"], ["climate", "environment", "water", "pollution"]),
 "energy": ("Energy", ["renewable energy", "smart grids", "energy storage", "waste-to-energy", "energy efficiency"], ["energy", "power", "solar", "battery"]),
 "agriculture": ("Agriculture & food", ["precision agriculture", "smart irrigation", "crop-disease detection", "soil intelligence", "agricultural robotics",
                "livestock monitoring", "food safety", "post-harvest", "market intelligence", "rural innovation"], ["agriculture", "agri", "farming", "food", "farm"]),
 "robotics": ("Robotics & autonomy", ["autonomous robotics", "drones", "sensor fusion", "human-robot interaction", "autonomous vehicles", "underwater robotics",
              "assistive robotics", "industrial automation"], ["robotics", "robot", "robots", "drone", "drones", "autonomous"]),
 "hardware": ("Hardware & embedded", ["embedded systems", "smart sensors", "microcontrollers", "edge hardware", "semiconductors", "materials", "3d printing"],
              ["hardware", "embedded", "electronics", "iot", "sensors"]),
 "space": ("Space & geospatial", ["satellite technology", "satellite data analytics", "remote sensing", "geospatial intelligence", "space situational awareness",
           "navigation", "aerospace engineering"], ["space", "aerospace", "satellite", "satellites", "geospatial"]),
 "education": ("Education", ["adaptive learning", "educational technology", "learning analytics", "offline learning"], ["education", "learning", "edtech", "teaching"]),
 "society": ("Society & public infrastructure", ["smart cities", "urban infrastructure", "traffic intelligence", "accessibility", "digital public infrastructure",
            "civic technology", "digital identity", "public safety"], ["society", "infrastructure", "infra", "accessibility", "smartcity", "civic"]),
 "software": ("Software & developer tools", ["developer tools", "software-engineering automation", "cloud-native systems", "decentralised infrastructure", "ar/vr",
              "spatial computing"], ["software", "devtools", "developer", "web"]),
 "science": ("Scientific computing & research", ["scientific computing", "scientific ml", "simulation", "physics", "materials science"], ["science", "scientific", "research", "physics"]),
}
ALIAS = {a: k for k, (_, _, al) in DOMAINS.items() for a in al}
ALIAS.update({k: k for k in DOMAINS})
HW = {"hardware", "hwsw", "embedded", "iot", "robotics"}
TAG_PRIORITY = [("fintech", "fintech"), ("stockmarket", "stockmarket"), ("economy", "economy"), ("disaster", "disaster"), ("health", "healthcare"),
                ("agri", "agriculture"), ("supply", "supplychain"), ("manufacturing", "manufacturing"), ("energy", "energy"), ("climate", "climate"),
                ("water", "climate"), ("geospatial", "space"), ("space", "space"), ("robotics", "robotics"), ("security", "cyber"), ("crypto", "cyber"),
                ("pqc", "cyber"), ("forensics", "cyber"), ("education", "education"), ("ai", "ai"), ("vision", "ai"), ("edge", "ai"),
                ("embedded", "hardware"), ("web", "software"), ("science", "science"), ("hci", "society"), ("infra", "society"), ("data", "ai")]
DOMAIN_TAGS = {}
for t, d in TAG_PRIORITY:
    DOMAIN_TAGS.setdefault(d, set()).add(t)
LEVEL_DIFF = {1: "beginner", 2: "intermediate", 3: "advanced", 4: "advanced", 5: "research"}
W = [0.2, 0.1, 0.2, 0.1, 0.1, 0.1, 0.2]  # feasibility, novelty, impact, scalability, research, hackathon, portfolio
SORTS = {"score": "composite", "novelty": 1, "feasibility": 0, "impact": 2, "scalability": 3, "research": 4, "hackathon": 5, "portfolio": 6,
         "cost": "cost", "difficulty": "level", "latest": "latest"}


def e(t):
    return html.escape(str(t), quote=False)


def cost_num(s):
    s = s.lower()
    if s.startswith("free") and "usd" not in s and "inr" not in s:
        return 0
    nums = [float(x) * (1000 if k else 1) for x, k in re.findall(r"(\d+(?:\.\d+)?)\s*(k)?", s)]
    if not nums:
        return 0
    v = max(nums)
    return v * (85 if "usd" in s else 1)  # rough INR conversion, only used for ordering and classes


def cost_class(v):
    return "minimal" if v == 0 else "low" if v <= 5000 else "moderate" if v <= 20000 else "high"


def derive_domain(p):
    for t, d in TAG_PRIORITY:
        if t in p.get("tags", []):
            return d
    return "ai"


def enrich(plans, meta):
    out = []
    for i, p in enumerate(plans):
        m = meta.get(p["id"])
        if m:
            d, sub, x, innov, comp, tier, sc = m
        else:
            d, sub, x = derive_domain(p), "emerging signal" if p.get("spark") else "generated concept", []
            innov, comp, tier, sc = "research" if p.get("source_item", {}).get("source", "").startswith("arXiv") else "incremental", "software", \
                (4 if p.get("spark") else 3), [3, 2, 2, 2, 3, 3, 2]
        cn = cost_num(p.get("cost", "Free"))
        out.append(dict(p=p, id=p["id"], name=p["name"], d=d, sub=sub, x=x, innov=innov, comp=comp, tier=tier, sc=sc,
                        composite=round(sum(w * s for w, s in zip(W, sc)) / 5 * 100), level=p["level"], fit=p["fit"],
                        diff=LEVEL_DIFF.get(p["level"], "advanced"), cost_num=cn, cost_class=cost_class(cn), order=i,
                        at=(p.get("source_item") or {}).get("published") or ""))
    return out


def in_domain(r, dom):
    if dom == "hardware":
        return r["d"] == "hardware" or "hardware" in r["x"] or r["comp"] in HW
    if dom == "ai":
        return r["d"] == "ai" or "ai" in r["x"] or r["comp"] == "ai"
    return r["d"] == dom or dom in r["x"]


class Query:
    def __init__(self):
        self.doms, self.n, self.sort, self.group, self.words = [], None, None, False, []
        self.diff = self.cost = self.typ = self.time = self.tier = self.innov = None
        self.archived = False


def parse(text):
    q = Query()
    t = " " + text.lower().replace("—", "--") + " "
    for key, attr in (("sort", "sort"), ("difficulty", "diff"), ("cost", "cost"), ("type", "typ"), ("time", "time"), ("tier", "tier"),
                      ("innovation", "innov"), ("domain", "dom1")):
        m = re.search(rf"--{key}[ =]+([\w\-+]+)", t)
        if m:
            setattr(q, attr, m.group(1)); t = t.replace(m.group(0), " ")
    m = re.search(r"\bsort(?:ed)?\s+by\s+(\w+)|\branked by\s+(\w+)|\bby\s+(novelty|impact|score|feasibility|scalability|research|hackathon|cost|difficulty|latest|portfolio)\b", t)
    if m and not q.sort:
        q.sort = next(g for g in m.groups() if g); t = t.replace(m.group(0), " ")
    if "--group" in t:
        q.group = True; t = re.sub(r"--group\s*\w*", " ", t)
    if "--archived" in t:
        q.archived = True; t = t.replace("--archived", " ")
    if getattr(q, "dom1", None):
        t += " " + q.dom1
    for tok in re.findall(r"[\w+\-]+", t):
        if tok.isdigit():
            q.n = q.n or int(tok); continue
        parts = tok.split("+")
        if all(p in ALIAS for p in parts):
            q.doms.append([ALIAS[p] for p in parts]); continue
        if tok in ("hw", "hardware-software"):
            q.typ = q.typ or "hwsw"; continue
        if tok in ("beginner", "intermediate", "advanced", "research-grade"):
            q.diff = q.diff or tok.replace("-grade", ""); continue
        if tok in ("minimal", "low", "moderate", "high") and "cost" in t:
            q.cost = q.cost or tok; continue
        if len(tok) > 3 and tok not in {"ideas", "idea", "find", "give", "show", "explore", "projects", "project", "list", "about", "with", "that",
                                         "some", "more", "sorted", "sort", "please", "need", "want", "get", "all", "for", "the", "and", "from"}:
            q.words.append(tok)
    return q


def run(cat, q, states=None):
    states = states or {}
    rows = [r for r in cat if (states.get(r["id"]) == "archived") == q.archived]
    if q.doms:  # each group is a cross-domain AND (cyber+ai); several groups are OR
        rows = [r for r in rows if any(all(in_domain(r, d) for d in g) for g in q.doms)]
    if q.diff:
        rows = [r for r in rows if r["diff"].startswith(q.diff[:4])]
    if q.cost:
        rows = [r for r in rows if r["cost_class"] == q.cost]
    if q.typ:
        t = q.typ.replace("hardware-software", "hwsw")
        rows = [r for r in rows if r["comp"] == t or (t == "hardware" and r["comp"] in HW) or (t == "software" and r["comp"] in ("software", "ai"))]
    if q.time:
        rows = [r for r in rows if (r["fit"] in ("24h", "48h") if q.time in ("24h", "48h", "24-48h") else r["fit"] == q.time)]
    if q.tier:
        rows = [r for r in rows if str(r["tier"]) == str(q.tier).replace("tier", "")]
    if q.innov:
        rows = [r for r in rows if r["innov"].startswith(q.innov[:5])]
    if q.words and not q.doms:  # free-text topic
        rows = [r for r in rows if all(any(w in (r["p"]["name"] + " " + r["p"]["problem"] + " " + r["sub"] + " " + " ".join(r["p"].get("kw", []))).lower()
                                           for w in [x]) for x in q.words)] or \
               [r for r in rows if any(w in (r["p"]["name"] + " " + r["p"]["problem"] + " " + r["sub"]).lower() for w in q.words)]
    key = SORTS.get(q.sort or "score", "composite")
    if key == "composite":
        rows.sort(key=lambda r: (-r["composite"], r["tier"]))
    elif isinstance(key, int):
        rows.sort(key=lambda r: (-r["sc"][key], -r["composite"]))
    elif key == "cost":
        rows.sort(key=lambda r: (r["cost_num"], -r["composite"]))
    elif key == "level":
        rows.sort(key=lambda r: (r["level"], -r["composite"]))
    else:  # latest: sparks by date, then library newest-last-added first
        rows.sort(key=lambda r: (r["at"] or "", r["order"]), reverse=True)
    return rows


def fmt_list(rows, q, per=10, cap=60):
    n = min(q.n or 25, cap)
    rows = rows[:n]
    if not rows:
        return ["Nothing matched. Try <code>/domains</code> to see what exists, or <code>/idea &lt;topic&gt;</code> for a fresh research mission on a new topic."]
    desc = []
    if q.doms:
        desc.append(" or ".join("+".join(g) for g in q.doms))
    for lab, v in (("difficulty", q.diff), ("cost", q.cost), ("type", q.typ), ("time", q.time), ("tier", q.tier)):
        if v:
            desc.append(f"{lab}={v}")
    head = f"<b>Catalogue</b> - {len(rows)} shown | sorted by {q.sort or 'score'}" + (f" | {', '.join(desc)}" if desc else "") + \
           "\n<i>Scores are NEXUS screening estimates, not validated.</i> Tiers: 1 exceptional, 2 high-potential, 3 research, 4 watchlist."
    msgs, cur = [], []
    for i, r in enumerate(rows, 1):
        cur.append(f"{i}. [T{r['tier']}] <b>{e(r['name'].split(':')[0][:60])}</b> - {e(r['name'].split(':', 1)[-1].strip()[:70]) if ':' in r['name'] else ''}\n"
                   f"   <code>{r['id']}</code> | {r['d']} | L{r['level']} {r['fit']} | est. {r['composite']}/100")
        if len(cur) == per:
            msgs.append("\n".join(cur)); cur = []
    if cur:
        msgs.append("\n".join(cur))
    msgs[0] = head + "\n\n" + msgs[0]
    msgs.append("Open one: <code>/project id</code> | blueprint: <code>/explore id</code> | keep it: <code>/shortlist id</code>. "
                "Filters: <code>--sort novelty --difficulty advanced --cost low --type hardware --time weeks</code>; cross-domain: <code>cyber+ai</code>.")
    return msgs


def fmt_domains(cat, key=None):
    if key and key in ("finance",):
        keys = ["fintech", "stockmarket", "economy"]
    elif key and key in ALIAS:
        keys = [ALIAS[key]]
    elif key:
        return [f"No domain called <code>{e(key)}</code> yet. Send <code>/idea {e(key)}</code> to start a fresh research mission on it."]
    else:
        keys = None
    msgs = []
    if keys:
        for k in keys:
            lab, subs, _ = DOMAINS[k]
            rs = [r for r in cat if r["d"] == k]
            used = sorted({r["sub"] for r in rs})
            msgs.append(f"<b>{lab}</b> (<code>{k}</code>)\nIn catalogue: {len(rs)} projects\n<b>Subdomains:</b> " + e(", ".join(subs)) +
                        (f"\n<b>With projects:</b> {e(', '.join(used))}" if used else "\n<i>No projects yet - try /idea " + k + "</i>") +
                        f"\nBrowse: <code>/ideas {k}</code>")
        return msgs
    lines = []
    for k, (lab, _, _) in DOMAINS.items():
        rs = [r for r in cat if r["d"] == k]
        if not rs:
            lines.append(f"<b>{lab.upper()}</b> (<code>{k}</code>) - no projects yet; try /idea {k}")
            continue
        cnt = {t: sum(1 for r in rs if r["tier"] == t) for t in (1, 2, 3, 4)}
        best = max(rs, key=lambda r: r["composite"])
        scored = [r["composite"] for r in rs if not r["p"].get("spark")]
        lines.append(f"<b>{lab.upper()}</b> (<code>{k}</code>)\n- total {len(rs)} | T1 {cnt[1]} | T2 {cnt[2]} | research T3 {cnt[3]} | watchlist T4 {cnt[4]}\n"
                     f"- strongest: {e(best['name'].split(':')[0])} ({best['composite']})" + (f"\n- avg est. score {round(sum(scored) / len(scored))}" if scored else ""))
    pages, cur = [], ""
    for ln in lines:
        if len(cur) + len(ln) > 3300:
            pages.append(cur); cur = ""
        cur += ln + "\n\n"
    pages.append(cur)
    pages[0] = f"<b>Domains</b> - {len(cat)} projects in the catalogue\n\n" + pages[0]
    pages[-1] += "Expand: <code>/domains cyber</code> (subdomains) or <code>/ideas cyber</code> (projects)."
    return pages


def fmt_project(r, state=None):
    p = r["p"]
    s = r["sc"]
    return (f"<b>{e(r['name'])}</b>\n<code>{r['id']}</code> | tier {r['tier']} | status: {state or 'catalogued'}\n"
            f"Domain: {r['d']} / {e(r['sub'])}" + (f" (+{', '.join(r['x'])})" if r["x"] else "") + f"\nInnovation: {r['innov']} | build: {r['comp']}\n"
            f"Level {r['level']} ({r['diff']}) | {r['fit']} | cost {e(p.get('cost', '?'))} [{r['cost_class']}, estimate]\n\n"
            f"<b>Problem:</b> {e(p['problem'])}\n<b>Idea:</b> {e(p['idea'])}\n<b>Novelty (hypothesis, unverified):</b> {e(p['novelty'])}\n\n"
            f"<b>NEXUS screening estimates (1-5):</b> feasibility {s[0]}, novelty {s[1]}, impact {s[2]}, scalability {s[3]}, research {s[4]}, "
            f"hackathon {s[5]}, portfolio {s[6]} -> est. {r['composite']}/100\n<i>Unvalidated: prior art, evidence and judging not yet performed.</i>\n"
            f"Next: /explore {r['id']} | /validate {r['id']} | /shortlist {r['id']}")


def fmt_top(cat, states, k=8):
    rows = [r for r in cat if r["tier"] <= 2 and states.get(r["id"]) != "archived" and not r["p"].get("spark")]
    rows.sort(key=lambda r: (-r["composite"], r["tier"]))
    rows = rows[:k]
    body = "\n".join(f"{i}. <b>{e(r['name'].split(':')[0])}</b> <code>{r['id']}</code> T{r['tier']} est. {r['composite']}\n   {e(r['name'].split(':', 1)[-1].strip()[:90])}"
                     for i, r in enumerate(rows, 1))
    return [f"<b>Strongest candidates now</b> (tier 1-2, by screening estimate)\n{body}\n\n<i>This is a shortlist for deeper work, not a validated ranking. "
            "Each still needs a real prior-art search, evidence for the problem and the full judging pass; run /validate and /explore.</i>"]


def set_state(c, pid, state):
    c.execute("CREATE TABLE IF NOT EXISTS cstate(id TEXT PRIMARY KEY, state TEXT, at TEXT)")
    c.execute("INSERT INTO cstate VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, at=excluded.at",
              (pid, state, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    c.commit()


def get_states(c):
    c.execute("CREATE TABLE IF NOT EXISTS cstate(id TEXT PRIMARY KEY, state TEXT, at TEXT)")
    return {r[0]: r[1] for r in c.execute("SELECT id, state FROM cstate")}


def export_csv(cat, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "domain", "subdomain", "secondary", "tier", "innovation", "build", "level", "time", "cost", "feasibility", "novelty_hyp",
                    "impact", "scalability", "research", "hackathon", "portfolio", "est_score"])
        for r in cat:
            w.writerow([r["id"], r["name"], r["d"], r["sub"], "+".join(r["x"]), r["tier"], r["innov"], r["comp"], r["level"], r["fit"], r["p"].get("cost", ""),
                        *r["sc"], r["composite"]])
    return Path(path)
