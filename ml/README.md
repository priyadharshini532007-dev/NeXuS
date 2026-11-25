# NEXUS ML: news domain classifier

NEXUS reads ~1,000 technology news items a week from 50 feeds. To give domain-specific research
(`/idea healthcare`, `/news fintech`), it must know which domain each item belongs to. This folder holds the
model that does that, the data it was trained and tested on, and every experiment that led to it.

## Result

| | Exact domain | Correct domain in top 2 |
|---|---|---|
| Keyword rules (before) | 45% | - |
| **Final model, mixed news** (repeated 5-fold CV) | **76%** | **90%** |
| **Final model, news from feeds it never saw** (feeds held out) | **67%** | **84%** |

Experiment 5 added search-labelled news: overall accuracy did not change measurably, but the rare domains improved
(macro-F1 over domains 0.72 -> 0.76; e.g. stock market 8/11 -> 11/11, disaster 2/6 -> 5/6, fintech 5/10 -> 7/10).

20 classes: 19 NEXUS domains + `other` (non-technology news). Final model: `BAAI/bge-base-en-v1.5` sentence
embeddings + logistic regression (C=30, class-balanced), trained on 1,813 items: 800 hand-labelled, 368 weakly
labelled by feed category, and 645 news items found by searching Google News for each domain (kept only where the
model trained on the first two groups agrees the searched domain is in its top 2). File: `models/domain_model.npz` (58 KB). Inference needs only numpy + `fastembed` (ONNX, no PyTorch).

## How it was built

1. **Experiment 1** ([report](reports/domain_classifier.md)) - labels = the category of the source feed.
   TF-IDF + linear models scored 84% on a random split but under 50% when whole feeds were held out:
   the models learned each feed's writing style, not the topic. Random Forest and XGBoost were worse than
   linear models and much slower. Lesson: feed labels and random splits overstate accuracy.
2. **Gold set** ([labels](data/gold_labels.csv)) - 800 items labelled by reading each one. 400 sampled across
   all feeds; 400 chosen by active sampling (items the current model thought were rare domains) plus random.
   Labelled by an AI assistant (single annotator), with consistency rules (e.g. share-price news = stockmarket,
   astronomy = science, space missions = space). Not independently verified.
3. **Experiment 2** ([report](reports/experiment2.md)) - TF-IDF vs MiniLM vs BGE-small embeddings; keyword
   rules, zero-shot prototypes, nearest centroid, kNN, logistic regression, linear SVM, Random Forest, XGBoost.
   Embeddings + linear models won clearly; Random Forest and XGBoost were last on every feature set.
4. **Experiment 3** ([report](reports/experiment3.md)) - larger embedders (BGE-base, MPNet), top-2 accuracy,
   learning curve. Accuracy was still rising with more labels (55% at 80 items -> 69% at 320), so the gold set
   was doubled.
5. **Experiment 4** ([report](reports/experiment4.md)) - 800 gold items, C tuned by nested CV inside each
   training fold, feature concatenation and a 3-model ensemble. BGE-base + weak data was best on unseen feeds;
   concatenation and the ensemble were not significantly better, so the simpler model was kept.
6. **Experiment 5** ([report](reports/experiment5.md)) - can all stored news help? (a) 1,086 items found by the
   research agent's per-domain Google News searches, labelled with the domain searched for; (b) the same, cleaned
   by model agreement; (c) self-training (the model labels the ~1,550 other stored items it is >= 70% sure about).
   Raw search labels hurt slightly (noise); cleaned search labels raised macro-F1 and rare-domain recall without
   changing accuracy; self-training changed nothing measurable, so it is not used.
7. **`train_final.py`** - retrains the chosen configuration with `fastembed` (the run-time library, embeddings
   verified identical to sentence-transformers: cosine 1.0000), re-measures both protocols, and checks that the
   numpy inference path reproduces scikit-learn's probabilities exactly.

## Evaluation protocol

- **A - mixed news:** stratified 5-fold CV repeated 3 times (15 test folds).
- **B - unseen feeds:** GroupKFold by feed; test items come from feeds absent from all training data.
- Metrics: accuracy, top-2 accuracy, macro-F1 over classes with >= 5 gold examples. Weak data from a held-out
  feed is removed from training. Test items are never used for training or tuning.

## Known limits

- Economy (1 gold example), education (3) and manufacturing (2) are too rare to learn or measure; the model
  usually calls such news `other` or a neighbouring domain. More labelled examples are the fix.
- Many items span two domains (AI + hardware, healthcare + AI). Top-2 accuracy reflects how NEXUS uses the
  model: it attaches the second domain when its probability is >= 0.25.
- Fold-to-fold spread is +/- 3-7 points, so differences smaller than that are not meaningful.
- Labels come from one annotator; true accuracy against expert labels is unknown.

## Reproduce

```
pip install -r ml/requirements.txt
python ml/experiment4.py          # needs nexus.db and ml/data/gold.jsonl (local, not published)
python ml/experiment5.py          # search-labelled news + self-training comparison
python ml/train_final.py --embedder BAAI/bge-base-en-v1.5 --weak --search
```
`gold.jsonl` holds article excerpts and stays local; `gold_labels.csv` (id, label, source, title) is published.
