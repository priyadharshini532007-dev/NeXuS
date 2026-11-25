"""Interactive Telegram menus for NEXUS (inline keyboards + callback queries).

Flow: main menu -> domain -> subdomain -> project list (sortable, paged) -> project -> actions.
Every callback carries all it needs (domain, subdomain, sort, page), so old or repeated taps still work after a
restart; per-chat context (current list, current project, multi-selection, compare tray) is stored in the
persistent `kv` table so typed follow-ups such as "/architecture 3" refer to what was last shown.
Telegram limits callback_data to 64 bytes; domains are encoded as short indices to stay well inside that.
"""
import json
import re
import time

import catalog as CT

PER_PAGE = 5
MENU = [("all", "🌐 All Domains"), ("cyber", "🛡️ Cybersecurity"), ("ai", "🧠 AI & ML"),
        ("healthcare", "🏥 Healthcare & Biotech"), ("fintech", "💳 FinTech & Banking"),
        ("stockmarket", "📈 Stock Market & Fin. Intel"), ("economy", "📊 Economics"),
        ("supplychain", "📦 Supply Chain & Logistics"), ("disaster", "🌪️ Disaster Management"),
        ("agriculture", "🌱 Agriculture & Food Tech"), ("robotics", "🤖 Robotics & Autonomy"),
        ("hardware", "🔧 Hardware & Embedded"), ("energy", "⚡ Energy & Power"), ("climate", "🌍 Climate & Environment"),
        ("space", "🛰️ Space & Aerospace"), ("manufacturing", "🏭 Manufacturing & Industry"),
        ("society", "🚦 Transport & Smart Cities"), ("education", "🎓 Education & Accessibility"),
        ("software", "🔬 Emerging Technologies"), ("other", "➕ Other Domains")]
LABEL = dict(MENU)
SORTS = [("sc", "🏆 Overall NEXUS score"), ("in", "💡 Innovation"), ("nv", "✨ Novelty"), ("im", "🌍 Real-world impact"),
         ("sl", "📈 Scalability"), ("fe", "⚙️ Feasibility"), ("rs", "🧪 Research potential"), ("hk", "🏅 Hackathon potential"),
         ("co", "💰 Implementation cost (low first)"), ("df", "🔧 Technical difficulty (hardest first)"),
         ("lt", "🆕 Latest discoveries")]
SORT_NAME = dict(SORTS)
SC_IDX = {"fe": 0, "nv": 1, "im": 2, "sl": 3, "rs": 4, "hk": 5}
INNOV_RANK = {"research": 5, "mechanism": 4, "architectural": 3, "cross-domain": 2, "incremental": 1}
DKEYS = list(CT.DOMAINS)            # stable order -> short numeric codes in callback data


def other_domains():
    return [k for k in DKEYS if k not in LABEL]


def dlabel(k):
    return LABEL.get(k) or CT.DOMAINS[k][0]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def enc(doms):
    return ".".join(str(DKEYS.index(d)) for d in doms)


def dec(code):
    if code in ("A", "S"):
        return code
    try:
        return [DKEYS[int(x)] for x in code.split(".")]
    except (ValueError, IndexError):
        return None


def match_dom(r, d):
    if d == "education":
        return CT.in_domain(r, "education") or r["sub"] == "accessibility"
    return CT.in_domain(r, d)


def btn(text, data):
    assert len(data.encode()) <= 64, data
    return {"text": text, "callback_data": data}


def grid(buttons, cols=2):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


# ---------------------------------------------------------------- data
_CACHE = {"t": 0.0, "rows": None}


def cat_rows(N, ttl=30):
    """Catalogue rows, rebuilt at most every `ttl` seconds - menus call this several times per tap."""
    if _CACHE["rows"] is None or time.time() - _CACHE["t"] > ttl:
        _CACHE.update(rows=N.catalog_rows(), t=time.time())
    return _CACHE["rows"]


def rows_for(N, dcode, sub, mode, states):
    rows = [r for r in cat_rows(N) if states.get(r["id"]) != "archived"]
    if dcode == "S":
        return [r for r in rows if states.get(r["id"]) == "shortlisted"], "⭐ Shortlist"
    if dcode == "A":
        return rows, "🌐 All domains"
    if dcode == "G":
        return [r for r in rows if r["p"].get("gen")], "🤖 Research-agent ideas"
    doms = dec(dcode)
    if not doms:
        return None, None
    pick = all if mode == "x" else any
    rows = [r for r in rows if pick(match_dom(r, d) for d in doms)]
    title = (" × " if mode == "x" else " + ").join(dlabel(d) for d in doms)
    if sub == "g":
        return [r for r in rows if r["p"].get("gen")], title + " › 🤖 agent ideas"
    if sub not in ("-", None) and len(doms) == 1:
        subs = sub_list(N, doms[0])
        i = int(sub)
        if i >= len(subs):
            return None, None
        rows = [r for r in rows if r["sub"] == subs[i][0]]
        title += f" › {subs[i][1]}"
    return rows, title


def sort_rows(rows, key):
    if key in SC_IDX:
        k = SC_IDX[key]; rows.sort(key=lambda r: (-r["sc"][k], -r["composite"]))
    elif key == "in":
        rows.sort(key=lambda r: (-INNOV_RANK.get(r["innov"], 0), -r["sc"][1], -r["composite"]))
    elif key == "co":
        rows.sort(key=lambda r: (r["cost_num"], -r["composite"]))
    elif key == "df":
        rows.sort(key=lambda r: (-r["level"], -r["composite"]))
    elif key == "lt":
        rows.sort(key=lambda r: (r["at"] or "", r["order"]), reverse=True)
    else:
        rows.sort(key=lambda r: (-r["composite"], r["tier"]))
    return rows


def sub_list(N, d):
    """[(slug, display name, n_projects)] - the domain's listed subdomains plus any used by catalogued projects."""
    rows = [r for r in cat_rows(N) if match_dom(r, d) and not r["p"].get("spark")]
    names = [(slug(s), s) for s in CT.DOMAINS.get(d, ("", []))[1]]
    if d == "education":
        names.append(("accessibility", "accessibility"))
    known = {s for s, _ in names}
    names += [(s, s.replace("-", " ")) for s in sorted({r["sub"] for r in rows}) if s not in known]
    cnt = {}
    for r in rows:
        cnt[r["sub"]] = cnt.get(r["sub"], 0) + 1
    return [(s, n, cnt.get(s, 0)) for s, n in names]


# ---------------------------------------------------------------- screens: (text, keyboard)
def main_menu():
    b = [btn(lab, f"D|{k}") for k, lab in MENU]
    kb = grid(b) + [[btn("🧩 Select multiple domains", "MS"), btn("🔀 Cross-domain ideas", "MS|x")],
                    [btn("🤖 New agent ideas", "L|G|-|lt|0|u"), btn("⭐ My shortlist", "L|S|-|sc|0|u")]]
    return ("<b>NEXUS — SELECT YOUR DOMAIN</b>\nWhich field would you like to explore today?\n\n"
            "<i>Tap a domain for its subdomains, projects, sorting and fresh research.</i>"), kb


def other_menu():
    b = [btn(dlabel(k), f"D|{k}") for k in other_domains()]
    return "<b>Other domains</b>", grid(b) + [[btn("🔙 Back", "H"), btn("🏠 Main menu", "H")]]


def domain_menu(N, d):
    subs = sub_list(N, d)
    rows, _ = rows_for(N, enc([d]), "-", "u", N.CT.get_states(N.db()))
    with_p = [(i, s) for i, s in enumerate(subs) if s[2]]
    without = [(i, s) for i, s in enumerate(subs) if not s[2]]
    b = [btn(f"{s[1][:24]} ({s[2]})", f"B|{d}|{i}") for i, s in with_p] + \
        [btn(f"🔎 {s[1][:24]}", f"B|{d}|{i}") for i, s in without]
    n_gen = sum(1 for r in rows if r["p"].get("gen"))
    kb = [[btn(f"📚 All {len(rows)} {CT.DOMAINS[d][0][:20]} projects", f"L|{enc([d])}|-|sc|0|u")]] + \
        [[btn(f"🤖 Agent ideas ({n_gen}), newest first", f"L|{enc([d])}|g|lt|0|u")]] + grid(b) + [
        [btn("↕️ Sort projects", f"O|{enc([d])}|-|u"), btn("📰 Latest news (ML)", f"N|{d}")],
        [btn("🔄 Refresh research", f"R|{d}|-"), btn("🔁 Change domain", "H")],
        [btn("🔙 Back", "H"), btn("🏠 Main menu", "H")]]
    return (f"<b>{dlabel(d)}</b>\n{len(rows)} projects in the catalogue.\n\n"
            f"Subdomains with projects show a count; 🔎 ones have none yet - tapping them starts a fresh research mission.\n"
            f"<i>Scores are NEXUS screening estimates, not validated results.</i>"), kb


def list_screen(N, ctx, chat, dcode, sub, sort, page, mode):
    states = N.CT.get_states(N.db())
    rows, title = rows_for(N, dcode, sub, mode, states)
    if rows is None:
        return "That menu is out of date (the catalogue changed). Pick again:", main_menu()[1]
    rows = sort_rows(rows, sort)
    ids = [r["id"] for r in rows]
    st = state(ctx, chat)
    st.update(last_list=f"L|{dcode}|{sub}|{sort}|{page}|{mode}")
    save(ctx, chat, st)
    ctx.kv_set("last_ids", json.dumps(ids[:60]))      # "/architecture 3" and "explain idea 3" use this order
    if not rows:
        back = f"D|{dec(dcode)[0]}" if isinstance(dec(dcode), list) else "H"
        extra = [[btn("🔄 Research this now", f"R|{dec(dcode)[0]}|{sub}")]] if isinstance(dec(dcode), list) and len(dec(dcode)) == 1 else []
        return f"<b>{title}</b>\nNo catalogued projects match yet.", extra + [[btn("🔙 Back", back), btn("🏠 Main menu", "H")]]
    pages = (len(rows) - 1) // PER_PAGE + 1
    page = max(0, min(page, pages - 1))
    chunk = rows[page * PER_PAGE:(page + 1) * PER_PAGE]
    lines = []
    for n, r in enumerate(chunk, page * PER_PAGE + 1):
        p, s = r["p"], r["sc"]
        first = p["problem"].split(". ")[0].rstrip(".")
        lines.append(f"<b>{n}. {'🤖 ' if p.get('gen') else ''}{N.esc(r['name'].split(':')[0][:60])}</b>  [T{r['tier']}] est. <b>{r['composite']}/100</b>\n"
                     f"<b>Problem:</b> {N.esc(first[:150])}.\n<b>Solution:</b> {N.esc(p['idea'][:170])}\n"
                     f"<i>{r['d']}/{r['sub']} | innovation: {r['innov']} | novelty {s[1]}/5 (hypothesis) | "
                     f"feasibility {s[0]}/5 | scalability {s[3]}/5</i>")
    text = (f"<b>{title}</b> — {len(rows)} projects, sorted by {SORT_NAME.get(sort, ' score').split(' ', 1)[1].lower()}, page {page + 1}/{pages}\n\n"
            + "\n\n".join(lines) + "\n\n<i>Scores are screening estimates. Tap a number to open a project.</i>")
    kb = [[btn(str(n), f"P|{r['id']}") for n, r in enumerate(chunk, page * PER_PAGE + 1)]]
    nav = []
    if page > 0:
        nav.append(btn("◀ Previous", f"L|{dcode}|{sub}|{sort}|{page - 1}|{mode}"))
    if page < pages - 1:
        nav.append(btn("▶ View more", f"L|{dcode}|{sub}|{sort}|{page + 1}|{mode}"))
    if nav:
        kb.append(nav)
    single = dec(dcode)[0] if isinstance(dec(dcode), list) and len(dec(dcode)) == 1 else None
    kb.append([btn("↕️ Sort", f"O|{dcode}|{sub}|{mode}")] +
              ([btn("🔄 Refresh research", f"R|{single}|{sub}")] if single else []))
    kb.append([btn("🔙 Back", f"D|{single}" if single else "H"), btn("🔁 Change domain", "H"), btn("🏠 Menu", "H")])
    return text, kb


def sort_menu(dcode, sub, mode):
    b = [btn(lab, f"L|{dcode}|{sub}|{k}|0|{mode}") for k, lab in SORTS]
    return "<b>SORT PROJECTS BY</b>", grid(b) + [[btn("🔙 Back", f"L|{dcode}|{sub}|sc|0|{mode}"), btn("🏠 Main menu", "H")]]


def multi_menu(ctx, chat, mode=None):
    st = state(ctx, chat)
    if mode:
        st["multi_mode"] = mode; save(ctx, chat, st)
    sel = st.get("multi", [])
    b = [btn(("✅ " if k in sel else "▫️ ") + lab.split(" ", 1)[1][:22], f"MT|{k}") for k, lab in MENU if k not in ("all", "other")]
    b += [btn(("✅ " if k in sel else "▫️ ") + dlabel(k), f"MT|{k}") for k in other_domains()]
    kb = grid(b) + [[btn(f"✔️ Confirm: any of {len(sel)}", "MC|u"), btn(f"🔀 Cross-domain (all {len(sel)})", "MC|x")],
                    [btn("🧹 Clear", "MX"), btn("🏠 Main menu", "H")]]
    return ("<b>Select multiple domains</b>\nTap to toggle (✅ = selected), then confirm.\n"
            "<b>Any</b> lists projects in at least one selected domain; <b>Cross-domain</b> lists projects that combine "
            f"all of them.\nSelected: {', '.join(sel) or 'none'}"), kb


def project_screen(N, ctx, chat, pid):
    cat = {r["id"]: r for r in cat_rows(N)}
    r = cat.get(pid)
    if not r:
        return "That project is no longer in the catalogue.", [[btn("🏠 Main menu", "H")]]
    st = state(ctx, chat); st["cur"] = pid; save(ctx, chat, st)
    text = N.CT.fmt_project(r, N.CT.get_states(N.db()).get(pid))
    text = text.rsplit("\nNext:", 1)[0]
    kb = [[btn("🔍 Explore project", f"A|x|{pid}"), btn("🏗️ Implementation plan", f"A|i|{pid}")],
          [btn("🧪 Novelty investigation", f"A|v|{pid}"), btn("🏆 Judging (estimates)", f"A|j|{pid}")],
          [btn("⚖️ Compare", f"A|c|{pid}"), btn("⭐ Add to shortlist", f"A|s|{pid}")],
          [btn("👎 Not interested (hide, teach the agent)", f"A|n|{pid}")],
          [btn("🔙 Back to list", st.get("last_list") or "H"), btn("🔙 Domain selection", "H")]]
    return text, kb


def explore_text(N, r):
    p = r["p"]
    f = lambda k: N.esc(str(p.get(k, "")))  # noqa: E731
    return (f"<b>🔍 {N.esc(r['name'])}</b>\n<code>{r['id']}</code>\n\n<b>Problem:</b> {f('problem')}\n<b>How to verify the problem:</b> {f('verify')}\n"
            f"<b>What already exists:</b> {f('existing')}\n<b>Proposed solution:</b> {f('idea')}\n<b>Novelty (hypothesis):</b> {f('novelty')}\n"
            f"<b>Stack:</b> {f('stack')}\n<b>Stages:</b> {f('stages')}\n<b>Hardware:</b> {f('hw')} | <b>Cost:</b> {f('cost')}\n"
            f"<b>Risks:</b> {f('risks')}\n<b>Metrics:</b> {f('metrics')}\n\n<i>Tap 🏗️ Implementation plan for the full blueprint (PDF + Markdown).</i>")[:4000]


def judging_text(N, r):
    s = r["sc"]
    labels = ["Feasibility", "Novelty (hypothesis)", "Impact", "Scalability", "Research potential", "Hackathon potential", "Portfolio value"]
    bars = "\n".join(f"{lab:<22} {'■' * v}{'□' * (5 - v)} {v}/5" for lab, v in zip(labels, s))
    flags = [m for c, m in ((s[0] <= 2, "feasibility risk"), (s[1] <= 2, "novelty doubtful - similar work likely exists"),
                            (r["cost_class"] == "high", "high cost"), (r["level"] >= 5, "research-grade difficulty")) if c]
    return (f"<b>🏆 Judging (screening estimates): {N.esc(r['name'].split(':')[0])}</b>\n<pre>{bars}</pre>\n"
            f"<b>Estimated score:</b> {r['composite']}/100 | tier {r['tier']} (1 exceptional, 2 high-potential, 3 research, 4 watchlist)\n"
            + (f"<b>Flags:</b> {', '.join(flags)}\n" if flags else "") +
            "\n<i>These are estimates made when the idea was catalogued. The full 100-point, five-judge evaluation needs "
            "real prior-art and evidence research that has not been done for this project.</i>")


# ---------------------------------------------------------------- state
def state(ctx, chat):
    try:
        return json.loads(ctx.kv_get(f"ui:{chat}", "{}"))
    except ValueError:
        return {}


def save(ctx, chat, st):
    ctx.kv_set(f"ui:{chat}", json.dumps(st))


# ---------------------------------------------------------------- dispatcher
def show(N, chat, mid, text, kb, edit=True):
    markup = json.dumps({"inline_keyboard": kb})
    if edit and mid:
        try:
            N.tg("editMessageText", chat_id=chat, message_id=mid, text=text[:4000], parse_mode="HTML",
                 disable_web_page_preview="true", reply_markup=markup)
            return
        except Exception as e:  # noqa - "message is not modified" is harmless; anything else: send a new message
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")  # urllib HTTPError carries Telegram's reason in the body
            except Exception:  # noqa
                pass
            if "not modified" in body or "not modified" in str(e):
                return
    N.tg("sendMessage", chat_id=chat, text=text[:4000], parse_mode="HTML", disable_web_page_preview="true", reply_markup=markup)


def handle(N, ctx, chat, mid, cq_id, data):
    """Route one callback query. Every path answers the query so the button stops spinning."""
    toast = None
    parts = data.split("|")
    k = parts[0]
    if k == "H":
        show(N, chat, mid, *main_menu())
    elif k == "D":
        d = parts[1]
        if d == "all":
            show(N, chat, mid, *list_screen(N, ctx, chat, "A", "-", "sc", 0, "u"))
        elif d == "other":
            show(N, chat, mid, *other_menu())
        elif d in CT.DOMAINS:
            show(N, chat, mid, *domain_menu(N, d))
        else:
            toast = "Unknown domain - menu refreshed"; show(N, chat, mid, *main_menu())
    elif k == "B":
        d, i = parts[1], int(parts[2])
        subs = sub_list(N, d)
        if i >= len(subs):
            toast = "Menu changed - pick again"; show(N, chat, mid, *domain_menu(N, d))
        elif subs[i][2]:
            show(N, chat, mid, *list_screen(N, ctx, chat, enc([d]), str(i), "sc", 0, "u"))
        else:
            show(N, chat, mid, f"<b>{dlabel(d)} › {subs[i][1]}</b>\nNo catalogued projects here yet.\n"
                               "Start a fresh research mission on it? It searches the catalogue and recent ML-classified news "
                               "and builds new directions from what it finds.",
                 [[btn("🔄 Research it now", f"R|{d}|{i}")], [btn("🔙 Back", f"D|{d}"), btn("🏠 Main menu", "H")]])
    elif k == "L":
        _, dcode, sub, sort, page, mode = parts
        show(N, chat, mid, *list_screen(N, ctx, chat, dcode, sub, sort, int(page), mode))
    elif k == "O":
        show(N, chat, mid, *sort_menu(parts[1], parts[2], parts[3]))
    elif k == "P":
        show(N, chat, mid, *project_screen(N, ctx, chat, parts[1]), edit=False)
    elif k == "A":
        toast = project_action(N, ctx, chat, parts[1], parts[2])
    elif k == "MS":
        show(N, chat, mid, *multi_menu(ctx, chat, parts[1] if len(parts) > 1 else None))
    elif k == "MT":
        st = state(ctx, chat); sel = st.get("multi", [])
        sel.remove(parts[1]) if parts[1] in sel else sel.append(parts[1])
        st["multi"] = sel; save(ctx, chat, st)
        show(N, chat, mid, *multi_menu(ctx, chat))
    elif k == "MX":
        st = state(ctx, chat); st["multi"] = []; save(ctx, chat, st)
        show(N, chat, mid, *multi_menu(ctx, chat))
    elif k == "MC":
        sel = [d for d in state(ctx, chat).get("multi", []) if d in CT.DOMAINS]
        if len(sel) < (2 if parts[1] == "x" else 1):
            toast = "Select at least two domains for cross-domain ideas" if parts[1] == "x" else "Select at least one domain"
        else:
            show(N, chat, mid, *list_screen(N, ctx, chat, enc(sel), "-", "sc", 0, parts[1]))
    elif k == "R":
        d, sub = parts[1], parts[2]
        args = d
        if sub.isdigit():
            subs = sub_list(N, d)
            args += " " + (subs[int(sub)][1] if int(sub) < len(subs) else "")
        tid, dup = ctx.enqueue_once("agent", args)
        toast = f"Already running as {ctx.code(tid)}" if dup else f"Research agent started: {ctx.code(tid)}"
        if not dup:
            ctx.say(f"🤖 Research agent working on <b>{N.esc(args)}</b>: searching news, finding topics, writing and "
                    f"critiquing new ideas.\nTask ID: <code>{ctx.code(tid)}</code> - takes 1-3 minutes.")
    elif k == "N":
        tid, dup = ctx.enqueue_once("news", parts[1])
        toast = f"{'Already running' if dup else 'Fetching'} {ctx.code(tid)}"
    else:
        toast = "This button is from an old menu - here is the current one"
        show(N, chat, mid, *main_menu())
    try:
        N.tg("answerCallbackQuery", callback_query_id=cq_id, **({"text": toast} if toast else {}))
    except Exception:  # noqa - queries older than ~15 minutes cannot be answered; the action above still ran
        pass


def project_action(N, ctx, chat, act, pid):
    cat = {r["id"]: r for r in cat_rows(N)}
    r = cat.get(pid)
    if not r:
        return "That project is no longer in the catalogue"
    st = state(ctx, chat); st["cur"] = pid; save(ctx, chat, st)
    if act == "x":
        ctx.say(explore_text(N, r)); return "Project details sent"
    if act == "i":
        tid, dup = ctx.enqueue_once("implement", pid)
        if not dup:
            ctx.say(f"🏗️ Building the implementation blueprint for <code>{pid}</code> (PDF + Markdown).\nTask ID: <code>{ctx.code(tid)}</code>")
        return f"{'Already building' if dup else 'Blueprint started'} {ctx.code(tid)}"
    if act == "v":
        msgs, _ = ctx.run_command("validate", pid); ctx.say(msgs); return "Novelty checklist sent"
    if act == "j":
        ctx.say(judging_text(N, r)); return "Scorecard sent"
    if act == "s":
        N.CT.set_state(N.db(), pid, "shortlisted"); return "⭐ Added to your shortlist"
    if act == "n":
        N.CT.set_state(N.db(), pid, "archived")
        return "👎 Hidden. The research agent will steer away from ideas like this"
    if act == "c":
        tray = [x for x in st.get("cmp", []) if x in cat and x != pid]
        if not tray:
            st["cmp"] = [pid]; save(ctx, chat, st)
            return "Added to compare - open another project and tap ⚖️ Compare"
        st["cmp"] = []; save(ctx, chat, st)
        msgs, _ = ctx.run_command("compare", f"{tray[0]} {pid}"); ctx.say(msgs)
        return "Comparison sent"
    return "Unknown action"
