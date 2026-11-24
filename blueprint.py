"""Offline blueprint builder: turns a plan record into a structured implementation blueprint.

It only rearranges what the plan already says plus standard engineering checklists. It does NOT invent
approaches, prices or results. Deep, plan-specific blueprints come from `nexus.py explore <id>` with an API key.
"""

PREREQ = {
    "security": "Linux + networking basics, Python, packet/log analysis (Wireshark or Zeek), a lab VM you control",
    "ai": "Python, NumPy/pandas, PyTorch or scikit-learn, train/validation/test discipline, experiment tracking",
    "edge": "Model quantisation basics, TFLite/ONNX Runtime, profiling latency and memory",
    "embedded": "C/C++ or MicroPython, electronics basics (voltage, I2C/SPI/UART), a multimeter, serial debugging",
    "vision": "OpenCV, image datasets and augmentation, camera calibration basics",
    "robotics": "ROS 2 basics, coordinate frames, motor control, safe testing rules",
    "crypto": "Hashes, signatures, key management; use vetted libraries only, never invent crypto",
    "web": "HTTP, a backend framework (FastAPI), a minimal frontend, browser dev tools",
    "data": "SQL/SQLite, data cleaning, evaluation against labelled data",
    "health": "Signal processing basics, medical-data ethics; no clinical claims without validation",
    "energy": "Basic electrical safety, sensor calibration, time-series analysis",
    "agri": "Field data collection protocol, domain advice from an extension officer",
}

MERMAID = {
    "device": "flowchart LR\n  S[Sensors] --> F[Firmware: sampling + filtering]\n  F --> M[On-device model or rules]\n  M --> A[Alert / actuator]\n  M --> G[Gateway: MQTT/LoRa/BLE]\n  G --> D[(Storage)]\n  D --> U[Dashboard + evaluation scripts]",
    "security": "flowchart LR\n  I[Inputs: logs / packets / repos / binaries] --> P[Parsers + normaliser]\n  P --> F[Feature extraction]\n  F --> D[Detector: rules first, model if justified]\n  D --> R[Report + evidence links]\n  R --> E[(Labelled test set)]\n  E --> V[Precision/recall + adversarial tests]",
    "ml": "flowchart LR\n  D[(Dataset)] --> B[Baseline]\n  D --> M[Proposed method]\n  B --> E[Evaluation harness]\n  M --> E\n  E --> R[Tables, plots, error analysis]",
    "app": "flowchart LR\n  U[User] --> UI[Frontend]\n  UI --> API[Backend API]\n  API --> C[Core engine]\n  C --> DB[(Storage)]\n  C --> X[External data / APIs]",
}


def _diagram(p):
    t = set(p["tags"])
    if t & {"embedded", "robotics"}:
        return MERMAID["device"]
    if "security" in t:
        return MERMAID["security"]
    if t & {"ai", "science", "data"}:
        return MERMAID["ml"]
    return MERMAID["app"]


def _bul(xs):
    return "\n".join(f"- {x}" for x in xs)


def blueprint_md(p):
    tags = set(p["tags"])
    stages = [s.strip() for s in p["stages"].split("->")]
    comps = [c.strip() for c in p["stack"].split(",") if c.strip()]
    risks = [r.strip() + "." if not r.strip().endswith(".") else r.strip() for r in p["risks"].split(";")]
    prereq = [f"**{t}**: {PREREQ[t]}" for t in p["tags"] if t in PREREQ]
    L = []
    a = L.append
    a(f"# PROJECT IMPLEMENTATION BLUEPRINT (core version): {p['name']}\n")
    a("> Built offline from the plan record. Approach comparison, code-level design, budget options and a plan-specific "
      "troubleshooting guide need the deep mode: `python nexus.py explore " + p["id"] + "` (needs ANTHROPIC_API_KEY). "
      "Nothing below is a verified result.\n")
    a("## A. Project definition")
    a(f"- **Problem:** {p['problem']}\n- **Establish this evidence first:** {p['verify']}\n- **Existing approaches:** {p['existing']}")
    a(f"- **Proposed solution:** {p['idea']}\n- **Novelty (hypothesis, unverified):** {p['novelty']}")
    a(f"- **Level / time / cost:** L{p['level']} of 5, {p['fit']}, {p['cost']} (rough; verify current prices)\n")
    a("## B. Approaches")
    a(f"- **Practical:** build only the first two stages - *{stages[0]}* then *{stages[1] if len(stages) > 1 else stages[0]}* - "
      "and measure the core claim against a simple baseline.")
    a(f"- **Advanced:** the full stage list below, with the evaluation harness automated and re-runnable.")
    a(f"- **Research:** test the novelty hypothesis against the closest prior work found with the searches below; "
      f"report negative results honestly. Metrics: {p['metrics']}.")
    a("- Plan-specific alternatives and trade-offs: deep mode.\n")
    a("## C. Architecture (generic for this domain; refine after the core experiment)")
    a("```mermaid\n" + _diagram(p) + "\n```")
    a("**MVP components:** " + ", ".join(comps[:4]) + ". **Later:** dashboards, automation, extra data sources.\n")
    a("## D. Stack and hardware")
    a(f"- Software/stack: {p['stack']}\n- Hardware: {p['hw']}\n- Rule: take the smallest stack that proves the hypothesis; add a component only when a measurement demands it.\n")
    a("## E. Implementation blueprint")
    a("**Phase 1 - Research:** run these prior-art searches and record what exists and what differs (docs/NOVELTY.md):")
    a(_bul(p["prior_art"]))
    a("**Prerequisites:**")
    a(_bul(prereq) if prereq else "- General Python and Git")
    for i, s in enumerate(stages, 1):
        a(f"\n**Stage {i}: {s}**\n- Done when: a committed artefact proves it (data file, plot, passing test or recorded measurement).\n"
          f"- Test: run it twice from a clean checkout and get the same result.")
    a("\n**Final stage - demo and documentation:** README with measured results, limitations, reproduction steps, short demo video.\n")
    a("## F. Project layout")
    a("```\n" + p["id"] + "/\n  README.md\n  docs/ (NOVELTY.md, RESEARCH.md, ARCHITECTURE.md)\n  src/\n  tests/\n  experiments/ (configs, scripts, results.csv)\n"
      "  data/ (README on how to obtain; never commit secrets)\n  .github/workflows/ci.yml\n```\n")
    a("## G. Experiment design")
    a(f"- **Hypothesis:** {p['novelty']}\n- **Baseline:** the simplest existing method from the prior-art list.\n"
      f"- **Metrics:** {p['metrics']}\n- **Failure conditions:** results no better than baseline, or only better on your own data.\n"
      "- **Reproducibility:** fixed seeds, pinned dependencies, scripted data download, one command to regenerate every table.\n")
    a("## H. Challenges")
    a(_bul(risks))
    a("- Generic checks: confirm sensor/data quality before modelling; log raw inputs; change one variable at a time.\n")
    if "security" in tags:
        a("## Security add-on")
        a("- **Threat model:** list assets, adversary capabilities, attack surface and what you will NOT defend.\n"
          "- **Evaluation:** false-positive and false-negative rates, plus an adversarial test where you try to evade your own detector.\n"
          "- **Scope:** only systems you own or have written permission to test; isolated lab VM for any malicious samples; no live malware.")
        a("")
    if tags & {"embedded", "robotics"}:
        a("## Hardware add-on")
        a("- Power budget (sleep vs active current, battery life), calibration procedure, safety (isolated supply for anything touching a person or mains), "
          "real-time limits (sampling rate vs processing time), and a bench test before any field test.\n")
    if "ai" in tags:
        a("## ML add-on")
        a("- Start with a classical baseline; justify any LLM/deep model by beating it. Track data provenance, train/val/test split, calibration, latency and memory.\n")
    a("## I. Budget and time")
    a(f"- Hardware/API estimate: {p['cost']} (my rough estimate - verify current prices). Time class: {p['fit']}.\n")
    a("## J. Roadmap")
    a(f"- **MVP:** stages 1-{min(2, len(stages))} with one measured result.\n- **v1:** all stages, automated tests, CI, README results.\n"
      "- **v2:** robustness, second dataset/site, optimisation.\n- **v3 / research:** write up as a reproducible report comparing against baselines.\n")
    a("## Hackathon mode (24-48h)")
    a(f"- **Must build:** the core mechanism from stage 1-2 working live.\n- **Should:** one measured number vs baseline.\n"
      "- **Avoid:** extra features, polished UI before the mechanism works.\n- **Backup:** pre-recorded demo and saved results.\n")
    a("## GitHub deliverables")
    a("README (problem, method, results, limitations), architecture diagram, tests + CI, reproducible setup, results with raw data, license, citations.")
    return "\n".join(L)


# ---------------------------------------------------------------- PDF export
_MAP = {"→": "->", "←": "<-", "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"',
        "”": '"', "•": "-", "≥": ">=", "≤": "<=", "×": "x", "✓": "ok", "▶": ">", "…": "..."}


def _clean(t):
    for k, v in _MAP.items():
        t = t.replace(k, v)
    return t.encode("latin-1", "replace").decode("latin-1")


def md_to_pdf(md, out_path, title="Blueprint"):
    """Render the blueprint Markdown to a readable PDF with reportlab (headings, bullets, code blocks)."""
    import re, textwrap
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13)
    h = {1: ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, leading=21, textColor=colors.HexColor("#0f6b5c")),
         2: ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, leading=16, spaceBefore=10, textColor=colors.HexColor("#0f6b5c")),
         3: ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11, leading=14, spaceBefore=6)}
    bullet = ParagraphStyle("bl", parent=body, leftIndent=14, bulletIndent=4)
    quote = ParagraphStyle("q", parent=body, textColor=colors.HexColor("#555555"), leftIndent=8, fontName="Helvetica-Oblique")
    code = ParagraphStyle("c", fontName="Courier", fontSize=7.8, leading=9.6, backColor=colors.HexColor("#f2f2ee"),
                          borderPadding=5, leftIndent=4, spaceBefore=4, spaceAfter=6)

    def inline(s):
        s = escape(_clean(s))
        s = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", r"<i>\1</i>", s)
        return s

    flow, buf, in_code, lang = [], [], False, ""
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                txt = "\n".join(buf)
                if lang == "mermaid":
                    flow.append(Paragraph("<i>Diagram source (Mermaid) - paste into mermaid.live to render:</i>", body))
                flow.append(Preformatted(_clean(txt), code))
                buf, in_code = [], False
            else:
                in_code, lang = True, line[3:].strip().lower()
            continue
        if in_code:
            buf += textwrap.wrap(line, 100, replace_whitespace=False, drop_whitespace=False) or [""]
            continue
        if not line.strip():
            flow.append(Spacer(1, 3)); continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flow.append(Paragraph(inline(m.group(2)), h[len(m.group(1))])); continue
        if line.startswith("> "):
            flow.append(Paragraph(inline(line[2:]), quote)); continue
        if line.startswith("|"):  # table rows shown as monospace lines
            flow.append(Preformatted(_clean("\n".join(textwrap.wrap(line, 110))), code)); continue
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)", line)
        if m:
            ind = (len(line) - len(line.lstrip())) // 2 * 10
            st = ParagraphStyle("bl2", parent=bullet, leftIndent=14 + ind, bulletIndent=4 + ind)
            flow.append(Paragraph(inline(m.group(2)), st, bulletText="-" if m.group(1) in "-*" else m.group(1)))
            continue
        flow.append(Paragraph(inline(line), body))

    def footer(c, d):
        c.saveState(); c.setFont("Helvetica", 7.5); c.setFillColor(colors.grey)
        c.drawString(18 * mm, 10 * mm, "NEXUS blueprint - plan-derived, not a verified result")
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}"); c.restoreState()

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=_clean(title), author="NEXUS")
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return out_path
