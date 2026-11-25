# Experiment 5: training on all stored news

Gold test items: 800 (single annotator). Weak: 368. Search-labelled: 1086 ({'cyber': 54, 'ai': 54, 'healthcare': 59, 'fintech': 59, 'stockmarket': 59, 'economy': 52, 'supplychain': 60, 'manufacturing': 58, 'disaster': 59, 'climate': 59, 'energy': 59, 'agriculture': 59, 'robotics': 58, 'hardware': 58, 'space': 52, 'education': 57, 'society': 58, 'software': 55, 'science': 57}). Self-training pool: 1553 non-gold stored items, confidence >= 0.7.

| Training data | A: accuracy | A: top-2 | A: macro-F1 | B (unseen feeds): accuracy | B: top-2 | B: macro-F1 | items added per fold | A vs base | B vs base |
|---|---|---|---|---|---|---|---|---|---|
| base | 74.9% +/- 3.6% | 89.3% | 0.720 | 67.7% +/- 7.2% | 83.1% | 0.550 | 0 | - | - |
| +S | 73.8% +/- 2.6% | 88.3% | 0.733 | 65.6% +/- 6.8% | 84.2% | 0.542 | 1086 | -0.011 (better in 5/15 folds) | -0.022 (better in 1/5 folds) |
| +S* | 75.9% +/- 2.8% | 89.6% | 0.761 | 67.0% +/- 4.4% | 84.5% | 0.548 | 651 | +0.010 (better in 8/15 folds) | -0.008 (better in 2/5 folds) |
| +P | 74.9% +/- 4.1% | 89.2% | 0.723 | 68.5% +/- 6.2% | 84.3% | 0.560 | 467 | -0.000 (better in 5/15 folds) | +0.008 (better in 3/5 folds) |
| +S*+P | 75.7% +/- 3.0% | 89.8% | 0.766 | 66.7% +/- 4.5% | 84.7% | 0.551 | 1119 | +0.008 (better in 7/15 folds) | -0.010 (better in 1/5 folds) |

Rare-domain recall on gold (protocol A, first 5 folds; correct/total):

| Domain | base | +S |
|---|---|---|
| economy | 0/1 | 0/1 |
| education | 1/3 | 2/3 |
| manufacturing | 0/2 | 1/2 |
| fintech | 5/10 | 7/10 |
| stockmarket | 8/11 | 11/11 |
| energy | 38/44 | 40/44 |
| disaster | 2/6 | 5/6 |
| software | 28/53 | 29/53 |

base = production setup (gold + feed-category weak labels + catalogue ideas). S = search-labelled news, S* = search items whose search domain is in the base model's top 2, P = self-training (pseudo-labels).
Paired differences use the same folds for both configurations.
