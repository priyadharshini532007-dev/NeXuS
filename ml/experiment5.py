#!/usr/bin/env python3
"""NEXUS ML experiment 5: can ALL stored news improve the domain classifier?

Question   The production model trains on 800 gold items + weak labels (feed category, catalogue ideas). The database
           holds more news. Two ways to use it are tested against the same hand-labelled gold test folds:
  S  search-labelled news: the research agent searched Google News per domain ("<subdomain> technology");
     the domain searched for is a (noisy) label. ~57 items per domain, including domains that have no feed.
  P  self-training: a model trained on the fold's training data labels every non-gold stored item; items it is
     confident about (p >= tau) are added with that label. Computed inside each training fold - no leakage.
  S* search labels cleaned by agreement: keep a search item only if the base model puts its search domain in its
     top 2 (removes off-topic search results).
Configurations: base (gold+weak, = production) | +S | +S* | +P | +S*+P.
Protocols  A = repeated stratified 5-fold x3 on gold; B = whole feeds held out (gold, weak, S and P items from a
           held-out source are removed from training). Embedder BGE-base (fastembed), logistic regression,
           C chosen by inner CV on the training fold.
Usage      python ml/experiment5.py   -> ml/reports/experiment5.md
"""
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, RepeatedStratifiedKFold, StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment2 as E  # noqa: E402

SEED = 42
EMBEDDER = "BAAI/bge-base-en-v1.5"
CS = [3, 10, 30, 100]
TAU = 0.7


def load():
    G, W, _, _ = E.load_all()
    gold_ids = {json.loads(l)["id"] for l in open(E.ML / "data" / "gold.jsonl", encoding="utf-8")}
    c = sqlite3.connect(f"file:{E.ROOT / 'nexus.db'}?mode=ro", uri=True)
    S, P = dict(X=[], y=[], src=[]), dict(X=[], src=[])
    for i, t, s, src, extra in c.execute("SELECT id,title,summary,source,extra FROM items WHERE dup_of IS NULL"):
        if i in gold_ids:
            continue
        tx = E.text(t, s)
        q = json.loads(extra or "{}").get("qdomain")
        if q:
            S["X"].append(tx); S["y"].append(q); S["src"].append(src)
        P["X"].append(tx); P["src"].append(src)   # every non-gold item is a self-training candidate
    S["y"], S["src"], P["src"] = np.array(S["y"]), np.array(S["src"]), np.array(P["src"])
    return G, W, S, P


def embed(texts, tag):
    f = E.CACHE / f"exp5_{tag}.npy"
    if f.exists():
        e = np.load(f)
        if len(e) == len(texts):
            return e
    from fastembed import TextEmbedding
    t0 = time.time()
    X = np.array(list(TextEmbedding(EMBEDDER, providers=["CPUExecutionProvider"]).embed(texts, batch_size=64)), dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    E.CACHE.mkdir(parents=True, exist_ok=True); np.save(f, X)
    print(f"  embedded {len(texts)} {tag} texts in {time.time() - t0:.0f}s", flush=True)
    return X


def fit(X, y):
    return LogisticRegressionCV(Cs=CS, cv=StratifiedKFold(3, shuffle=True, random_state=SEED), max_iter=4000,
                                class_weight="balanced", scoring="accuracy", n_jobs=-1).fit(X, y)


def run(cfg, XG, yG, sG, XW, yW, sW, XS, yS, sS, XP, sP, splits, held_out_sources, ev):
    acc, top2, f1, added = [], [], [], []
    for tr, te in splits:
        held = set(sG[te]) if held_out_sources else set()
        keepW = np.array([s not in held for s in sW]); keepS = np.array([s not in held for s in sS])
        keepP = np.array([s not in held for s in sP])
        Xtr, ytr = np.vstack([XG[tr], XW[keepW]]), np.concatenate([yG[tr], yW[keepW]])
        base = None
        if cfg != "base":
            base = fit(Xtr, ytr) if ("P" in cfg or "S*" in cfg) else None
        Xa, ya = [Xtr], [ytr]
        n_add = 0
        if "S*" in cfg:
            Pr = base.predict_proba(XS[keepS]); o = np.argsort(-Pr, 1)[:, :2]
            ok = np.array([yS[keepS][i] in base.classes_[o[i]] for i in range(len(o))])
            Xa.append(XS[keepS][ok]); ya.append(yS[keepS][ok]); n_add += int(ok.sum())
        elif "S" in cfg:
            Xa.append(XS[keepS]); ya.append(yS[keepS]); n_add += int(keepS.sum())
        if "P" in cfg:
            Pr = base.predict_proba(XP[keepP]); conf = Pr.max(1) >= TAU
            Xa.append(XP[keepP][conf]); ya.append(base.classes_[Pr.argmax(1)][conf]); n_add += int(conf.sum())
        m = fit(np.vstack(Xa), np.concatenate(ya))
        Pt = m.predict_proba(XG[te]); o = np.argsort(-Pt, 1); pred = m.classes_[o[:, 0]]
        acc.append(accuracy_score(yG[te], pred))
        top2.append(np.mean([yG[te][i] in m.classes_[o[i, :2]] for i in range(len(te))]))
        f1.append(f1_score(yG[te], pred, labels=ev, average="macro", zero_division=0))
        added.append(n_add)
    return dict(acc=float(np.mean(acc)), sd=float(np.std(acc)), top2=float(np.mean(top2)), f1=float(np.mean(f1)),
                added=int(np.mean(added)), folds=[float(a) for a in acc])


def per_class(XG, yG, XW, yW, XS, yS, splits, rare):
    """Recall on the rare domains, base vs +S, under protocol A (where the search data should help most)."""
    out = {}
    for cfg in ("base", "+S"):
        hit, tot = Counter(), Counter()
        for tr, te in splits:
            Xtr = np.vstack([XG[tr], XW] + ([XS] if cfg == "+S" else []))
            ytr = np.concatenate([yG[tr], yW] + ([yS] if cfg == "+S" else []))
            pred = fit(Xtr, ytr).predict(XG[te])
            for t, p in zip(yG[te], pred):
                if t in rare:
                    tot[t] += 1; hit[t] += t == p
        out[cfg] = {d: f"{hit[d]}/{tot[d]}" for d in rare}
    return out


def main():
    G, W, S, P = load()
    print(f"gold {len(G['y'])}, weak {len(W['y'])}, search-labelled {len(S['y'])}, self-training pool {len(P['X'])}", flush=True)
    XG = embed(G["X"], "gold"); XW = embed(W["X"], "weak"); XS = embed(S["X"], "search"); XP = embed(P["X"], "pool")
    yG, sG = G["y"], G["src"]
    c = Counter(yG); ev = sorted(d for d, n in c.items() if n >= E.MIN_EVAL)
    strat = np.array([x if c[x] >= 5 else "_rare" for x in yG])
    A = list(RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=SEED).split(np.zeros(len(yG)), strat))
    B = list(GroupKFold(n_splits=5).split(np.zeros(len(yG)), yG, sG))
    res = {}
    for cfg in ("base", "+S", "+S*", "+P", "+S*+P"):
        for proto, splits, held in (("A", A, False), ("B", B, True)):
            t0 = time.time()
            r = run(cfg, XG, yG, sG, XW, W["y"], W["src"], XS, S["y"], S["src"], XP, P["src"], splits, held, ev)
            res[(cfg, proto)] = r
            print(f"{cfg:7s} {proto}: acc {r['acc']:.3f} +/- {r['sd']:.3f}  top2 {r['top2']:.3f}  F1 {r['f1']:.3f}  "
                  f"(+{r['added']} items/fold, {time.time() - t0:.0f}s)", flush=True)
    rare = [d for d in ("economy", "education", "manufacturing", "fintech", "stockmarket", "energy", "disaster", "society", "software") if c[d]]
    pc = per_class(XG, yG, XW, W["y"], XS, S["y"], A[:5], rare)
    print("rare-domain recall (protocol A, first repeat):", pc, flush=True)

    def paired(cfg, proto):
        d = np.array(res[(cfg, proto)]["folds"]) - np.array(res[("base", proto)]["folds"])
        return f"{d.mean():+.3f} (better in {int((d > 0).sum())}/{len(d)} folds)"

    L = ["# Experiment 5: training on all stored news\n",
         f"Gold test items: {len(yG)} (single annotator). Weak: {len(W['y'])}. Search-labelled: {len(S['y'])} "
         f"({dict(Counter(map(str, S['y'])))}). Self-training pool: {len(P['X'])} non-gold stored items, confidence >= {TAU}.\n",
         "| Training data | A: accuracy | A: top-2 | A: macro-F1 | B (unseen feeds): accuracy | B: top-2 | B: macro-F1 | "
         "items added per fold | A vs base | B vs base |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cfg in ("base", "+S", "+S*", "+P", "+S*+P"):
        a, b = res[(cfg, "A")], res[(cfg, "B")]
        L.append(f"| {cfg} | {a['acc']:.1%} +/- {a['sd']:.1%} | {a['top2']:.1%} | {a['f1']:.3f} | {b['acc']:.1%} +/- {b['sd']:.1%} | "
                 f"{b['top2']:.1%} | {b['f1']:.3f} | {a['added']} | {'-' if cfg == 'base' else paired(cfg, 'A')} | "
                 f"{'-' if cfg == 'base' else paired(cfg, 'B')} |")
    L += ["", "Rare-domain recall on gold (protocol A, first 5 folds; correct/total):", "",
          "| Domain | base | +S |", "|---|---|---|"] + [f"| {d} | {pc['base'][d]} | {pc['+S'][d]} |" for d in rare]
    L += ["", "base = production setup (gold + feed-category weak labels + catalogue ideas). S = search-labelled news, "
          "S* = search items whose search domain is in the base model's top 2, P = self-training (pseudo-labels).",
          "Paired differences use the same folds for both configurations."]
    (E.ML / "reports" / "experiment5.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    json.dump({f"{k[0]}|{k[1]}": v for k, v in res.items()} | {"rare": pc},
              open(E.ML / "reports" / "experiment5.json", "w", encoding="utf-8"), indent=1)
    print("wrote ml/reports/experiment5.md")


if __name__ == "__main__":
    main()
