#!/usr/bin/env python3
"""NEXUS ML experiment 2: domain classifier evaluated on a hand-labelled gold set.

Gold set   ml/data/gold.jsonl - 400 items sampled across all feeds, labelled by reading each item
           (primary NEXUS domain or 'other'). Labelled by an AI assistant (Claude), single annotator:
           spot-check before trusting small differences.
Features   TF-IDF (word 1-2 grams) | all-MiniLM-L6-v2 embeddings | bge-small-en-v1.5 embeddings
Training   G   = gold training folds only
           G+W = gold training folds + weakly labelled news (feed category) + catalogue ideas (their domain)
           Weak items that are in the gold set are excluded, so no test item is ever used for training.
Models     keyword rules (current NEXUS), zero-shot prototypes, nearest centroid, kNN, logistic regression,
           linear SVM, Random Forest, XGBoost
Protocol   A. Repeated stratified 5-fold CV on gold (3 repeats -> 15 test folds)
           B. Grouped 5-fold CV: whole feeds held out of the gold training folds AND of the weak data
Metric     macro-F1 over classes with >= 5 gold examples (main), accuracy; mean +/- std over folds
Usage      python ml/experiment2.py            (writes ml/reports/experiment2.md and ml/cache/*.npy)
"""
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, RepeatedStratifiedKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder, normalize
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ML = ROOT / "ml"
CACHE = ML / "cache"
SEED = 42
MIN_EVAL = 5
CAT2DOM = {"ai": "ai", "security": "cyber", "science": "science", "hardware": "hardware", "embedded": "hardware",
           "robotics": "robotics", "climate": "climate", "space": "space", "agri": "agriculture",
           "health": "healthcare", "supply": "supplychain"}
OTHER_DESC = ("business and corporate news, executives, funding rounds, lawsuits, politics, elections, careers, "
              "lifestyle, books, consumer product promotions, cars, games, opinion without technology content")
EMB_MODELS = {"MiniLM": "sentence-transformers/all-MiniLM-L6-v2", "BGE-small": "BAAI/bge-small-en-v1.5"}


def text(title, summary):
    return f"{title or ''}. {(summary or '')[:300]}"


def load_all():
    import nexus as N
    gold = [json.loads(l) for l in open(ML / "data" / "gold.jsonl", encoding="utf-8")]
    gold_ids = {g["id"] for g in gold}
    c = sqlite3.connect(f"file:{ROOT / 'nexus.db'}?mode=ro", uri=True)
    weak = [(i, text(t, s), CAT2DOM[cat], src) for i, t, s, src, cat in
            c.execute("SELECT id,title,summary,source,cat FROM items WHERE dup_of IS NULL")
            if cat in CAT2DOM and i not in gold_ids]
    meta = json.load(open(ROOT / "catalogue_meta.json", encoding="utf-8"))
    ideas = [(p["id"], f"{p['name']}. {p['problem']} {p['idea']}", meta[p["id"]][0], "catalogue")
             for p in json.load(open(ROOT / "plans.json", encoding="utf-8")) if p["id"] in meta]
    desc = {d: f"{name}: {', '.join(subs)}" for d, (name, subs, _) in N.CT.DOMAINS.items()}
    desc["other"] = OTHER_DESC
    G = dict(X=[text(g["title"], g["summary"]) for g in gold], y=np.array([g["label"] for g in gold]),
             src=np.array([g["source"] for g in gold]))
    W = dict(X=[w[1] for w in weak] + [i[1] for i in ideas], y=np.array([w[2] for w in weak] + [i[2] for i in ideas]),
             src=np.array([w[3] for w in weak] + [i[3] for i in ideas]))
    return G, W, desc, N


def embed(name, texts, tag):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{tag}_{name}.npy"
    if f.exists():
        e = np.load(f)
        if len(e) == len(texts):
            return e
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(EMB_MODELS[name], device="cpu")
    e = m.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    np.save(f, e)
    return e


# ---------------------------------------------------------------- classifiers on a fixed feature matrix
class Keyword:
    def __init__(self, N, texts_all):
        self.N, self.texts = N, texts_all

    def fit(self, idx, y):
        return self

    def predict(self, idx):
        out = []
        for i in idx:
            tags = set(self.N.tag_text(self.texts[i]))
            out.append(next((d for t, d in self.N.CT.TAG_PRIORITY if t in tags), "other"))
        return np.array(out)


class Prototype:
    """Zero-shot: cosine similarity to an embedded description of each domain. No training data used."""

    def __init__(self, F, P, labels):
        self.F, self.P, self.labels = F, P, labels

    def fit(self, idx, y):
        return self

    def predict(self, idx):
        return np.array(self.labels)[(self.F[idx] @ self.P.T).argmax(1)]


class Sk:
    """Wraps a scikit-learn style estimator over row indices of a precomputed feature matrix."""

    def __init__(self, F, make, encode=False):
        self.F, self.make, self.encode = F, make, encode

    def fit(self, idx, y):
        if self.encode:
            self.le = LabelEncoder().fit(y)
            y = self.le.transform(y)
        self.m = self.make(len(set(y))).fit(self.F[idx], y)
        return self

    def predict(self, idx):
        p = self.m.predict(self.F[idx])
        return self.le.inverse_transform(p.astype(int)) if self.encode else p


def centroid(k):
    from sklearn.neighbors import NearestCentroid
    return NearestCentroid()


def make_models(F, N, texts_all, P, plabels, dense):
    from xgboost import XGBClassifier
    m = {
        "Logistic regression": lambda: Sk(F, lambda k: LogisticRegression(max_iter=3000, C=10 if dense else 20, class_weight="balanced")),
        "Linear SVM": lambda: Sk(F, lambda k: LinearSVC(C=1 if dense else 0.5, class_weight="balanced")),
        "kNN (k=7, cosine)": lambda: Sk(F, lambda k: KNeighborsClassifier(n_neighbors=7, weights="distance", metric="cosine")),
        "Random Forest": lambda: Sk(F, lambda k: RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample",
                                                                        n_jobs=-1, random_state=SEED)),
        "XGBoost": lambda: Sk(F, lambda k: XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.1, subsample=0.9,
                                                         colsample_bytree=0.6, tree_method="hist", random_state=SEED,
                                                         n_jobs=-1, verbosity=0), encode=True),
    }
    if dense:
        m["Nearest centroid"] = lambda: Sk(F, centroid)
        m["Zero-shot prototypes"] = lambda: Prototype(F, P, plabels)
    return m


def run(Gn, F, y, groups, splits, use_weak, models, eval_classes, n_weak):
    """F holds gold rows [0, Gn) followed by weak rows; splits index the gold rows."""
    widx = np.arange(Gn, Gn + n_weak)
    res = {}
    for name, make in models.items():
        accs, f1s, t0 = [], [], time.time()
        allp, ally = [], []
        for tr, te in splits:
            tr_idx = tr
            if use_weak and name not in ("Keyword rules (current NEXUS)", "Zero-shot prototypes"):
                held = set(groups[te])          # never train on weak items from a held-out feed
                keep = widx[[g not in held for g in groups[Gn:]]]
                tr_idx = np.concatenate([tr, keep])
            m = make().fit(tr_idx, y[tr_idx])
            p = m.predict(te)
            accs.append(accuracy_score(y[te], p))
            f1s.append(f1_score(y[te], p, labels=eval_classes, average="macro", zero_division=0))
            allp += list(p); ally += list(y[te])
        res[name] = dict(acc=np.mean(accs), acc_sd=np.std(accs), f1=np.mean(f1s), f1_sd=np.std(f1s),
                         secs=time.time() - t0, pred=np.array(allp), true=np.array(ally))
        print(f"    {name:30s} macro-F1 {np.mean(f1s):.3f} +/- {np.std(f1s):.3f}   acc {np.mean(accs):.3f} +/- {np.std(accs):.3f}"
              f"   {time.time() - t0:6.1f}s", flush=True)
    return res


def main():
    G, W, desc, N = load_all()
    yG = G["y"]
    counts = Counter(yG)
    eval_classes = sorted(d for d, n in counts.items() if n >= MIN_EVAL)
    print(f"gold {len(yG)} items, weak {len(W['y'])} items; eval classes ({len(eval_classes)}): {eval_classes}")
    Gn = len(yG)
    texts_all = G["X"] + W["X"]
    y_all = np.concatenate([yG, W["y"]])
    groups = np.concatenate([G["src"], W["src"]])

    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=SEED)
    # stratification needs >= 5 members per class; rare classes are folded into a placeholder only for splitting
    strat = np.array([c if counts[c] >= 5 else "_rare" for c in yG])
    split_A = list(rskf.split(np.zeros(Gn), strat))
    split_B = list(GroupKFold(n_splits=5).split(np.zeros(Gn), yG, G["src"]))

    plabels = sorted(desc)
    feats = {}
    tf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True, strip_accents="unicode")
    feats["TF-IDF"] = (tf.fit_transform(texts_all), None, False)  # unsupervised fit on all text (no labels)
    for name in EMB_MODELS:
        E = embed(name, texts_all, "items")
        P = embed(name, [desc[d] for d in plabels], "prototypes")
        feats[name] = (E, P, True)

    results = {}
    for fname, (F, P, dense) in feats.items():
        models = make_models(F, N, texts_all, P, plabels, dense)
        models = {"Keyword rules (current NEXUS)": lambda: Keyword(N, texts_all), **models} if fname == "TF-IDF" else models
        for proto, splits in (("A", split_A), ("B", split_B)):
            for use_weak in (False, True):
                key = (fname, proto, "G+W" if use_weak else "G")
                print(f"\n== features {fname} | protocol {proto} | training {key[2]}")
                results[key] = run(Gn, F, y_all, groups, splits, use_weak, models, eval_classes, len(W["y"]))

    write_report(results, eval_classes, counts, Gn, len(W["y"]))


def write_report(results, eval_classes, counts, Gn, Wn):
    rows = []
    for (fname, proto, tr), res in results.items():
        for model, r in res.items():
            rows.append((proto, fname, tr, model, r))
    best = {p: max((r for r in rows if r[0] == p), key=lambda r: r[4]["f1"]) for p in ("A", "B")}

    def table(p):
        sel = sorted((r for r in rows if r[0] == p), key=lambda r: -r[4]["f1"])
        out = ["| # | Features | Training | Model | Macro-F1 | Accuracy |", "|---|---|---|---|---|---|"]
        for i, (_, f, tr, m, r) in enumerate(sel, 1):
            out.append(f"| {i} | {f} | {tr} | {m} | {r['f1']:.3f} ± {r['f1_sd']:.3f} | {r['acc']:.3f} ± {r['acc_sd']:.3f} |")
        return "\n".join(out)

    def per_class(r):
        from sklearn.metrics import classification_report
        return classification_report(r["true"], r["pred"], labels=sorted(counts), zero_division=0, digits=3)

    bA, bB = best["A"], best["B"]
    rep = f"""# Experiment 2 - domain classifier on a hand-labelled gold set

Generated by `ml/experiment2.py` on {time.strftime('%Y-%m-%d %H:%M')} (seed {SEED}).

**Gold set:** {Gn} news items sampled across all feeds and labelled by reading each one (primary NEXUS domain, or
`other` for non-technology news). Labelled by an AI assistant, single annotator - spot-check before trusting small
differences. Class counts: {json.dumps(dict(counts.most_common()))}.

**Main metric:** macro-F1 over the {len(eval_classes)} classes with at least {MIN_EVAL} gold examples
({', '.join(eval_classes)}). Classes with fewer examples are still predicted but cannot be measured reliably.

**Training data:** `G` = gold training folds only. `G+W` = gold training folds + {Wn} weakly labelled items
(news labelled by feed category, and catalogue ideas labelled by their domain). Test items are never in training.

## Protocol A - repeated stratified 5-fold CV (3 repeats, 15 test folds)
{table('A')}

## Protocol B - whole feeds held out (5-fold GroupKFold by feed)
Test items come from feeds absent from both the gold training folds and the weak training data.

{table('B')}

## Best model per protocol
- A: **{bA[3]}** on {bA[1]} features, training {bA[2]} - macro-F1 {bA[4]['f1']:.3f} ± {bA[4]['f1_sd']:.3f}, accuracy {bA[4]['acc']:.3f}
- B: **{bB[3]}** on {bB[1]} features, training {bB[2]} - macro-F1 {bB[4]['f1']:.3f} ± {bB[4]['f1_sd']:.3f}, accuracy {bB[4]['acc']:.3f}

### Per-class results of the best protocol-B model (pooled over folds)
```
{per_class(bB[4])}
```
"""
    out = ML / "reports" / "experiment2.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rep, encoding="utf-8")
    json.dump({f"{p}|{f}|{t}|{m}": dict(f1=r["f1"], f1_sd=r["f1_sd"], acc=r["acc"], acc_sd=r["acc_sd"])
               for p, f, t, m, r in rows}, open(ML / "reports" / "experiment2.json", "w"), indent=1)
    print(f"\nreport: {out}\nbest A: {bA[1]} {bA[2]} {bA[3]} F1 {bA[4]['f1']:.3f}\nbest B: {bB[1]} {bB[2]} {bB[3]} F1 {bB[4]['f1']:.3f}")


if __name__ == "__main__":
    main()
