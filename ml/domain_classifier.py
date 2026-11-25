#!/usr/bin/env python3
"""NEXUS ML experiment 1: domain classification of news items.

Task      Predict an item's domain (ai, cyber, science, hardware, ...) from its title + summary.
Labels    Distant supervision: the topical category of the feed the item came from (e.g. arXiv cs.CR -> cyber).
          Noisy: a general AI blog can post about security. Feeds with non-topical categories
          (community, news, startups, ...) are excluded.
Baseline  NEXUS's current keyword rules (nexus.tag_text + catalog.TAG_PRIORITY), and the majority class.
Models    Logistic regression, linear SVM, Random Forest, XGBoost on TF-IDF features.
Protocol  A. Stratified 5-fold CV (random split) - optimistic: train and test share sources, so a model
             can learn a feed's writing style instead of the topic.
          B. Grouped CV with whole sources held out - realistic for new feeds. Only classes with >= 2
             sources are used here; a class with a single source can never be seen in training once
             that source is held out.
Usage     python ml/domain_classifier.py [--db nexus.db] [--out ml/reports/domain_classifier.md]
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = 42
# feed category -> NEXUS domain; categories not listed are not topical and are dropped
CAT2DOM = {"ai": "ai", "security": "cyber", "science": "science", "hardware": "hardware", "embedded": "hardware",
           "robotics": "robotics", "climate": "climate", "space": "space", "agri": "agriculture",
           "health": "healthcare", "supply": "supplychain"}


def load(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute("SELECT title, summary, source, cat FROM items WHERE dup_of IS NULL").fetchall()
    X, y, g = [], [], []
    for title, summary, source, cat in rows:
        if cat in CAT2DOM:
            X.append(f"{title or ''}. {summary or ''}")
            y.append(CAT2DOM[cat])
            g.append(source)
    return np.array(X, dtype=object), np.array(y), np.array(g)


class KeywordRules:
    """NEXUS's current behaviour: regex tags -> first matching domain in TAG_PRIORITY."""

    def __init__(self, labels):
        import nexus as N
        self.tag_text, self.prio, self.labels = N.tag_text, N.CT.TAG_PRIORITY, set(labels)

    def fit(self, X, y):
        vals, cnt = np.unique(y, return_counts=True)
        self.fallback = vals[cnt.argmax()]  # most common class when no rule fires
        return self

    def predict(self, X):
        out = []
        for t in X:
            tags = set(self.tag_text(t))
            d = next((d for tag, d in self.prio if tag in tags and d in self.labels), self.fallback)
            out.append(d)
        return np.array(out)


class Majority:
    def fit(self, X, y):
        vals, cnt = np.unique(y, return_counts=True)
        self.c = vals[cnt.argmax()]
        return self

    def predict(self, X):
        return np.array([self.c] * len(X))


class Encoded:
    """Wraps an estimator that needs integer labels (XGBoost)."""

    def __init__(self, make):
        self.make = make

    def fit(self, X, y):
        self.le = LabelEncoder().fit(y)
        self.m = self.make(len(self.le.classes_)).fit(X, self.le.transform(y))
        return self

    def predict(self, X):
        return self.le.inverse_transform(self.m.predict(X).astype(int))


def tfidf():
    return TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True, strip_accents="unicode")


def models(labels):
    from xgboost import XGBClassifier
    return {
        "Majority class": lambda: Majority(),
        "Keyword rules (current NEXUS)": lambda: KeywordRules(labels),
        "Logistic regression": lambda: make_pipeline(tfidf(), LogisticRegression(max_iter=2000, C=10, class_weight="balanced")),
        "Linear SVM": lambda: make_pipeline(tfidf(), LinearSVC(C=1, class_weight="balanced")),
        "Random Forest": lambda: make_pipeline(tfidf(), RandomForestClassifier(
            n_estimators=500, class_weight="balanced_subsample", n_jobs=-1, random_state=SEED)),
        "XGBoost": lambda: Encoded(lambda k: make_pipeline(tfidf(), XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.1, subsample=0.9, colsample_bytree=0.5,
            tree_method="hist", objective="multi:softmax", num_class=k, random_state=SEED, n_jobs=-1, verbosity=0))),
    }


def evaluate(X, y, splits, labels):
    res = {}
    for name, make in models(labels).items():
        acc, mf1, secs = [], [], 0.0
        for tr, te in splits:
            t0 = time.time()
            m = make().fit(X[tr], y[tr])
            p = m.predict(X[te])
            secs += time.time() - t0
            acc.append(accuracy_score(y[te], p))
            mf1.append(f1_score(y[te], p, average="macro", labels=np.unique(y[te]), zero_division=0))
        res[name] = dict(acc=np.mean(acc), acc_sd=np.std(acc), f1=np.mean(mf1), f1_sd=np.std(mf1), secs=secs)
        print(f"  {name:30s} acc {np.mean(acc):.3f} +/- {np.std(acc):.3f}   macro-F1 {np.mean(mf1):.3f} +/- {np.std(mf1):.3f}   {secs:5.1f}s", flush=True)
    return res


def table(res):
    lines = ["| Model | Accuracy | Macro-F1 | Train+predict time |", "|---|---|---|---|"]
    best = max(r["f1"] for r in res.values())
    for name, r in res.items():
        b = "**" if r["f1"] == best else ""
        lines.append(f"| {b}{name}{b} | {r['acc']:.3f} ± {r['acc_sd']:.3f} | {b}{r['f1']:.3f} ± {r['f1_sd']:.3f}{b} | {r['secs']:.1f}s |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "nexus.db"))
    ap.add_argument("--out", default=str(ROOT / "ml" / "reports" / "domain_classifier.md"))
    a = ap.parse_args()

    X, y, g = load(a.db)
    labels = sorted(set(y))
    counts = {d: int((y == d).sum()) for d in labels}
    nsrc = {d: len(set(g[y == d])) for d in labels}
    print(f"{len(X)} labelled items, {len(labels)} classes, {len(set(g))} sources")
    print("class sizes:", counts)

    print("\nA. Random stratified 5-fold CV (all classes)")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    res_a = evaluate(X, y, list(skf.split(X, y)), labels)

    multi = [d for d in labels if nsrc[d] >= 2]
    keep = np.isin(y, multi)
    Xb, yb, gb = X[keep], y[keep], g[keep]
    print(f"\nB. Whole sources held out (StratifiedGroupKFold, {len(multi)} classes with >= 2 sources)")
    sgk = StratifiedGroupKFold(n_splits=min(5, min(nsrc[d] for d in multi)), shuffle=True, random_state=SEED)
    res_b = evaluate(Xb, yb, list(sgk.split(Xb, yb, gb)), multi)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"""# Experiment 1 - news domain classifier

Generated by `ml/domain_classifier.py` on {time.strftime('%Y-%m-%d %H:%M')} (seed {SEED}).

**Data:** {len(X)} de-duplicated news items from {len(set(g))} feeds, {len(labels)} domains.
Labels are the topical category of the source feed (distant supervision) - they are noisy, and no item was
labelled by hand. Class sizes: {json.dumps(counts)}. Sources per class: {json.dumps(nsrc)}.

**Features:** TF-IDF of title + summary, word 1-2 grams (fitted inside each training fold, so no test leakage).
Macro-F1 averages F1 over classes, so small classes (supply chain, healthcare) count as much as large ones;
it is the main metric because accuracy is dominated by the big classes.

## A. Random 5-fold split (optimistic)
Train and test items can come from the same feed, so a model can partly learn each feed's style.

{table(res_a)}

## B. Whole feeds held out (realistic for new sources)
Only the {len(multi)} classes with at least two feeds: {', '.join(multi)}. Every test item comes from a feed
the model never saw.

{table(res_b)}

## Honest limits
- Labels come from feeds, not from reading each item; some "errors" are label noise, so true accuracy is unknown.
- {len(X)} items is small; results will shift as more news is collected. Re-run this script to update.
- Four classes (agriculture, healthcare, supply chain, and part of hardware) come from one feed each, so
  protocol B cannot test them; their scores in A mostly measure recognising that feed.
- Next: a hand-labelled test set of ~300 items, sentence-embedding features, and multi-label output.
""", encoding="utf-8")
    print(f"\nreport written to {out}")


if __name__ == "__main__":
    main()
