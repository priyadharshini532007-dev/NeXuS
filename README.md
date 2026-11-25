# NEXUS agent

Fetches ~50 sources, stores/dedups them in SQLite, matches them to a library of project plans, and renders a menu you choose from.

```
python nexus.py run                      # fetch + build -> out/menu.html, out/menu.md
python nexus.py health                   # which sources work
python nexus.py scaffold --from chosen.json   # after clicking "Export chosen" in the menu
python nexus.py scaffold <plan-id> ...   # or by id
# need ANTHROPIC_API_KEY (untested here):
python nexus.py ideate                   # Claude proposes NEW plans from today's signals -> plans_generated.json
python nexus.py deep <plan-id>           # scaffold + Claude-written critique/architecture dossier
```

Schedule `python nexus.py run` daily (Task Scheduler / cron). Optional `GITHUB_TOKEN` raises GitHub rate limits.

## Research agent (`agent.py`)
Runs every 3 hours in the cloud (and on `/agent <domain>` or the 🔄 Refresh button). For each chosen domain it:
1. **gathers** - searches Google News when the domain is thin in the database (news is kept 120 days);
2. **finds topics** - groups the domain's recent news by sentence-embedding similarity; topics in several sources rank higher;
3. **generates** - a free LLM (Groq, Gemini or OpenRouter free tier) writes ideas grounded in those topics, told which ideas
   already exist and which ones you shortlisted or marked 👎;
4. **critiques** - a second LLM pass drops weak ideas, names existing products and re-scores;
5. **dedupes** - ideas too similar (cosine >= 0.86) to anything proposed before or to the catalogue are rejected;
6. **stores** - kept ideas join the catalogue and appear first in `/idea` and under 🤖 in `/menu`; used news is not reused.

It needs one free key (`GROQ_API_KEY`, `GEMINI_API_KEY` or `OPENROUTER_API_KEY`, see GITHUB_SETUP.md). Without one it
still gathers and groups news but writes no ideas. LLM-written novelty and scores are unverified hypotheses.
Test: `python tests/test_agent.py` (stand-in LLM, no key needed).

## Design notes
- Every item carries an evidence type: primary / research / report / lead. Inshorts, HN, DEV and GitHub are leads, never facts.
- GitHub repos get a 0-100 build-quality score (stars, fork ratio, licence, recent push, hygiene, star-farming penalty); below 40 are dropped.
- A plan only matches news on keyword evidence (tag overlap alone was too noisy); the page shows which keywords matched.
- Plans' "novelty" fields are hypotheses; each plan lists prior-art searches to run before building.
- Known dead sources: CISA (403), Nature feed (invalid XML), Reddit (blocks anonymous access), Medgadget (timeouts). Inshorts uses an unofficial endpoint and may break.
