"""ML domain classifier used by NEXUS at run time.

The model is trained offline by `ml/train_final.py` and saved as `ml/models/domain_model.npz` (a linear
softmax classifier over sentence embeddings). Inference needs only numpy and `fastembed` (ONNX, no PyTorch).
If either is missing, NEXUS keeps working with its keyword rules - every function here fails soft.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "ml" / "models" / "domain_model.npz"
SECOND_MIN = 0.25        # a second domain is kept only if its probability reaches this
# one representative item tag per domain, so ML predictions plug into the existing tag-based filters
DOMAIN_TAG = {"cyber": "security", "ai": "ai", "healthcare": "health", "fintech": "fintech", "stockmarket": "stockmarket",
              "economy": "economy", "supplychain": "supply", "manufacturing": "manufacturing", "disaster": "disaster",
              "climate": "climate", "energy": "energy", "agriculture": "agri", "robotics": "robotics",
              "hardware": "embedded", "space": "space", "education": "education", "society": "hci",
              "software": "web", "science": "science"}
_state = {}


def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS item_domain(id TEXT PRIMARY KEY, d1 TEXT, p1 REAL, d2 TEXT, p2 REAL, "
              "model TEXT, at TEXT)")


def _load():
    if "w" in _state or _state.get("error"):
        return _state.get("w") is not None
    try:
        z = np.load(MODEL, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        from fastembed import TextEmbedding
        _state.update(w=z["coef"], b=z["intercept"], classes=z["classes"], meta=meta,
                      emb=TextEmbedding(meta["embedder"], cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"),
                                        providers=["CPUExecutionProvider"]))
        return True
    except Exception as e:  # noqa - missing file/library must never break the bot
        _state["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return False


def available():
    return _load()


def status():
    if _load():
        m = _state["meta"]
        return (f"ML domain model {m['version']} ({m['embedder'].split('/')[-1]} + logistic regression, "
                f"{m['n_train']} training items; held-out-feed accuracy {m['acc_unseen']:.0%}, top-2 {m['top2_unseen']:.0%})")
    return f"ML domain model unavailable, keyword rules in use ({_state.get('error', 'not loaded')})"


def text_of(title, summary):
    return f"{title or ''}. {(summary or '')[:300]}"


def predict(texts):
    """Return [(d1, p1, d2, p2), ...] for a list of texts; empty list if the model is unavailable."""
    if not texts or not _load():
        return []
    X = np.array(list(_state["emb"].embed(texts, batch_size=64)), dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    z = X @ _state["w"].T + _state["b"]
    z -= z.max(1, keepdims=True)
    P = np.exp(z); P /= P.sum(1, keepdims=True)
    top = np.argsort(-P, 1)[:, :2]
    cl = _state["classes"]
    return [(str(cl[a]), float(P[i, a]), str(cl[b]), float(P[i, b])) for i, (a, b) in enumerate(top)]


def classify_pending(c, limit=5000):
    """Classify stored items that have no prediction yet. Returns how many were classified."""
    init(c)
    rows = c.execute("SELECT i.id, i.title, i.summary FROM items i LEFT JOIN item_domain d ON d.id = i.id "
                     "WHERE d.id IS NULL AND i.dup_of IS NULL LIMIT ?", (limit,)).fetchall()
    if not rows or not _load():
        return 0
    preds = predict([text_of(t, s) for _, t, s in rows])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ver = _state["meta"]["version"]
    c.executemany("INSERT OR REPLACE INTO item_domain VALUES(?,?,?,?,?,?,?)",
                  [(r[0], d1, p1, d2, p2, ver, now) for r, (d1, p1, d2, p2) in zip(rows, preds)])
    c.commit()
    return len(rows)


def domains(d1, p1, d2, p2):
    """Domains to attach to an item from its stored prediction ('other' means not a technology domain)."""
    out = [d1] if d1 and d1 != "other" else []
    if d2 and d2 != "other" and p2 is not None and p2 >= SECOND_MIN:
        out.append(d2)
    return out
