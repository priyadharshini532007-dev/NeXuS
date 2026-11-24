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

## Design notes
- Every item carries an evidence type: primary / research / report / lead. Inshorts, HN, DEV and GitHub are leads, never facts.
- GitHub repos get a 0-100 build-quality score (stars, fork ratio, licence, recent push, hygiene, star-farming penalty); below 40 are dropped.
- A plan only matches news on keyword evidence (tag overlap alone was too noisy); the page shows which keywords matched.
- Plans' "novelty" fields are hypotheses; each plan lists prior-art searches to run before building.
- Known dead sources: CISA (403), Nature feed (invalid XML), Reddit (blocks anonymous access), Medgadget (timeouts). Inshorts uses an unofficial endpoint and may break.
