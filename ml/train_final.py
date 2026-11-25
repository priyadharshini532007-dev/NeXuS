#!/usr/bin/env python3
"""Train the production NEXUS domain classifier and save it for `domain_model.py`.

Uses the configuration that won the experiments (see ml/reports/), embeds with `fastembed` - the same library
used at run time, so training and inference features are identical - and stores a numpy-only linear model.
Before saving it re-measures accuracy with the two protocols used in the experiments and checks that the
numpy inference path reproduces scikit-learn's predictions exactly.

Usage: python ml/train_final.py [--embedder BAAI/bge-small-en-v1.5] [--weak] [--search] [--self-train]
--search: add search-labelled news kept only where the base model agrees (top 2); --self-train: add confident
pseudo-labels for all other stored news (experiment 5). Accuracy is then measured with experiment 5's protocol.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, RepeatedStratifiedKFold, StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment2 as E  # noqa: E402

SEED = 42
CS = [0.3, 1, 3, 10, 30, 100]


def embed(texts, name):
    from fastembed import TextEmbedding
    X = np.array(list(TextEmbedding(name).embed(texts, batch_size=64)), dtype=np.float32)
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)


def cv(X, y, grp, Gn, splits, weak, ev):
    acc, top2, f1 = [], [], []
    for tr, te in splits:
        idx = tr
        if weak:
            held = set(grp[te])
            idx = np.concatenate([tr, np.arange(Gn, len(y))[[g not in held for g in grp[Gn:]]]])
        m = LogisticRegressionCV(Cs=CS, cv=StratifiedKFold(3, shuffle=True, random_state=SEED), max_iter=4000,
                                 class_weight="balanced", scoring="accuracy", n_jobs=-1).fit(X[idx], y[idx])
        P = m.predict_proba(X[te]); o = np.argsort(-P, 1)
        pred = m.classes_[o[:, 0]]
        acc.append(accuracy_score(y[te], pred))
        top2.append(np.mean([y[te][i] in m.classes_[o[i, :2]] for i in range(len(te))]))
        f1.append(f1_score(y[te], pred, labels=ev, average="macro", zero_division=0))
    return dict(acc=float(np.mean(acc)), acc_sd=float(np.std(acc)), top2=float(np.mean(top2)), f1=float(np.mean(f1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--weak", action="store_true", help="also train on feed-labelled news and catalogue ideas")
    ap.add_argument("--search", action="store_true", help="also train on agreement-filtered search-labelled news")
    ap.add_argument("--self-train", action="store_true", help="also train on confident pseudo-labels of stored news")
    a = ap.parse_args()

    G, W, desc, N = E.load_all()
    yG = G["y"]; Gn = len(yG); c = Counter(yG)
    ev = sorted(d for d, n in c.items() if n >= E.MIN_EVAL)
    texts = G["X"] + (W["X"] if a.weak else [])
    y = np.concatenate([yG, W["y"]]) if a.weak else yG
    grp = np.concatenate([G["src"], W["src"]]) if a.weak else G["src"]
    t0 = time.time()
    if a.embedder == "BAAI/bge-base-en-v1.5" and a.weak:  # cached by experiment 5 (same texts, same library)
        import experiment5 as X5
        X = np.vstack([X5.embed(G["X"], "gold"), X5.embed(W["X"], "weak")])
    else:
        X = embed(texts, a.embedder)
    print(f"embedded {len(texts)} texts with {a.embedder} in {time.time() - t0:.0f}s", flush=True)

    strat = np.array([x if c[x] >= 5 else "_rare" for x in yG])
    A = list(RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=SEED).split(np.zeros(Gn), strat))
    B = list(GroupKFold(n_splits=5).split(np.zeros(Gn), yG, G["src"]))
    extra = a.search or a.self_train
    if extra:  # measure the full recipe exactly as experiment 5 did (filtering/pseudo-labelling inside each fold)
        import experiment5 as X5
        _, _, S, P = X5.load()
        same = a.embedder == X5.EMBEDDER  # reuse experiment 5's cached fastembed embeddings when the embedder matches
        XS = X5.embed(S["X"], "search") if same else embed(S["X"], a.embedder)
        XP = X5.embed(P["X"], "pool") if same else embed(P["X"], a.embedder)
        cfg = "+" + "+".join(k for k, on in (("S*", a.search), ("P", a.self_train)) if on)
        args = (X[:Gn], yG, G["src"], X[Gn:], W["y"], W["src"], XS, S["y"], S["src"], XP, P["src"])
        rA = X5.run(cfg, *args[:11], A, False, ev); print("protocol A (mixed news):", rA, flush=True)
        rB = X5.run(cfg, *args[:11], B, True, ev); print("protocol B (unseen feeds):", rB, flush=True)
    else:
        rA = cv(X, y, grp, Gn, A, a.weak, ev); print("protocol A (mixed news):", rA, flush=True)
        rB = cv(X, y, grp, Gn, B, a.weak, ev); print("protocol B (unseen feeds):", rB, flush=True)

    sel = LogisticRegressionCV(Cs=CS, cv=StratifiedKFold(5, shuffle=True, random_state=SEED), max_iter=4000,
                               class_weight="balanced", scoring="accuracy", n_jobs=-1).fit(X[:Gn], yG)
    C = float(sel.C_[0])
    m = LogisticRegression(C=C, max_iter=4000, class_weight="balanced").fit(X, y)
    n_search = n_self = 0
    if extra:  # same recipe on all data: base model filters search labels and pseudo-labels the pool, then retrain
        Xa, ya = [X], [y]
        if a.search:
            o = np.argsort(-m.predict_proba(XS), 1)[:, :2]
            ok = np.array([S["y"][i] in m.classes_[o[i]] for i in range(len(o))])
            Xa.append(XS[ok]); ya.append(S["y"][ok]); n_search = int(ok.sum())
        if a.self_train:
            Pr = m.predict_proba(XP); conf = Pr.max(1) >= X5.TAU
            Xa.append(XP[conf]); ya.append(m.classes_[Pr.argmax(1)][conf]); n_self = int(conf.sum())
        X, y = np.vstack(Xa), np.concatenate(ya)
        m = LogisticRegression(C=C, max_iter=4000, class_weight="balanced").fit(X, y)
        print(f"final training set: {len(y)} items (+{n_search} search-labelled, +{n_self} self-trained)", flush=True)

    # numpy inference must reproduce scikit-learn exactly
    z = X @ m.coef_.T + m.intercept_; z -= z.max(1, keepdims=True); P = np.exp(z); P /= P.sum(1, keepdims=True)
    assert np.allclose(P, m.predict_proba(X), atol=1e-6), "numpy softmax differs from predict_proba"
    assert (m.classes_[P.argmax(1)] == m.predict(X)).all()

    version = time.strftime("v%Y%m%d-%H%M")
    meta = dict(version=version, embedder=a.embedder, C=C, n_train=int(len(y)), n_gold=int(Gn), weak=bool(a.weak),
                n_search=n_search, n_self_trained=n_self,
                classes=[str(x) for x in m.classes_], acc_mixed=rA["acc"], top2_mixed=rA["top2"], f1_mixed=rA["f1"],
                acc_unseen=rB["acc"], top2_unseen=rB["top2"], f1_unseen=rB["f1"], trained=time.strftime("%Y-%m-%d %H:%M"))
    out = E.ML / "models"; out.mkdir(exist_ok=True)
    np.savez_compressed(out / "domain_model.npz", coef=m.coef_.astype(np.float32), intercept=m.intercept_.astype(np.float32),
                        classes=np.array([str(x) for x in m.classes_]), meta=np.array(json.dumps(meta)))
    (out / "domain_model.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"saved {out / 'domain_model.npz'} ({version}, C={C})")


if __name__ == "__main__":
    main()
