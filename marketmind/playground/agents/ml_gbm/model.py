"""Walk-forward gradient-boosting classifier for the ml_gbm agent (docs/PLAYGROUND_AGENTS.md §7).

Model: sklearn HistGradientBoostingClassifier with fixed, conservative hyperparameters
(shallow trees, few leaves, large leaves, L2 penalty, small learning rate, no early
stopping) chosen a priori, not tuned on our data. Fixed seed -> deterministic.

Leakage control (Lopez de Prado 2018, ch. 7 purging / embargo):
  a model used on as-of date T is trained only on rows dated
      <= calendar[T - HORIZON - EMBARGO]            (purge = label horizon, + embargo)
  whose label end date (bar i + HORIZON) is
      <= calendar[T - EMBARGO],
  where `calendar` is the SPY complete-bar calendar. Probability calibration (Platt
  scaling) is fitted on the last CALIB_FRACTION of those training dates, and the trees
  on the earlier rows whose labels end before the calibration block starts.
Retraining happens at most once per ISO week; the fitted model is cached with its
training cut-off and feature list under <data_dir>/playground/ml_gbm/.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import numpy as np

from marketmind.playground.agents.ml_gbm import features as F

logger = logging.getLogger("marketmind.playground.ml_gbm")

MODEL_VERSION = "ml_gbm/v1"
SEED = 20260929
EMBARGO = 5
HORIZON = F.HORIZON
CALIB_FRACTION = 0.2
MIN_TRAIN_ROWS = 2000
PARAMS = dict(learning_rate=0.05, max_iter=150, max_depth=3, max_leaf_nodes=8,
              min_samples_leaf=200, l2_regularization=1.0, max_bins=64,
              early_stopping=False, random_state=SEED)
TOP_FEATURES = 5


def model_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data")) / "playground" / "ml_gbm"


def week_of(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def cutoffs(calendar: np.ndarray, asof: date) -> tuple[np.datetime64, np.datetime64] | None:
    """(last usable row date, last usable label end date) for a model used on `asof`."""
    i = int(np.searchsorted(calendar, np.datetime64(asof, "D"), side="right")) - 1
    if i - HORIZON - EMBARGO < 0:
        return None
    return calendar[i - HORIZON - EMBARGO], calendar[i - EMBARGO]


def training_mask(panel: F.Panel, asof: date) -> np.ndarray:
    cut = cutoffs(panel.calendar, asof)
    if cut is None:
        return np.zeros(len(panel.date), dtype=bool)
    row_cut, label_cut = cut
    known = ~np.isnan(panel.label) & ~np.isnat(panel.label_end)
    return known & (panel.date <= row_cut) & (panel.label_end <= label_cut)


class Platt:
    """p' = sigmoid(a * logit(p) + b), fitted on a held-out block."""

    def __init__(self, a: float = 1.0, b: float = 0.0):
        self.a, self.b = a, b

    @staticmethod
    def _logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    @classmethod
    def fit(cls, p: np.ndarray, y: np.ndarray) -> "Platt":
        from sklearn.linear_model import LogisticRegression
        if len(np.unique(y)) < 2:
            return cls()
        lr = LogisticRegression(C=1.0).fit(cls._logit(p).reshape(-1, 1), y.astype(int))
        return cls(float(lr.coef_[0, 0]), float(lr.intercept_[0]))

    def __call__(self, p: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-(self.a * self._logit(p) + self.b)))


def fit(panel: F.Panel, asof: date, *, importance: bool = True) -> dict | None:
    """Train on the purged window for `asof`; None when there is too little data."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    train = panel.rows(training_mask(panel, asof))
    if len(train.date) < MIN_TRAIN_ROWS or len(np.unique(train.label)) < 2:
        return None
    dates = np.unique(train.date)
    calib_start = dates[int(len(dates) * (1 - CALIB_FRACTION))]
    fit_mask = train.label_end < calib_start                     # purged before calibration
    cal_mask = train.date >= calib_start
    if fit_mask.sum() < MIN_TRAIN_ROWS // 2 or len(np.unique(train.label[fit_mask])) < 2:
        return None
    clf = HistGradientBoostingClassifier(**PARAMS)
    clf.fit(train.X[fit_mask], train.label[fit_mask].astype(int))
    raw_cal = clf.predict_proba(train.X[cal_mask])[:, 1]
    platt = Platt.fit(raw_cal, train.label[cal_mask])
    row_cut, label_cut = cutoffs(panel.calendar, asof)
    bundle = {
        "version": MODEL_VERSION, "features": list(panel.features), "params": dict(PARAMS),
        "model": clf, "platt": (platt.a, platt.b), "asof": asof.isoformat(),
        "week": week_of(asof), "horizon": HORIZON, "embargo": EMBARGO,
        "row_cutoff": str(row_cut), "label_cutoff": str(label_cut),
        "train_first": str(train.date.min()), "train_last": str(train.date.max()),
        "train_label_end_max": str(train.label_end.max()),
        "calib_start": str(calib_start), "n_fit": int(fit_mask.sum()),
        "n_calib": int(cal_mask.sum()), "base_rate": round(float(train.label.mean()), 4),
        "importance": {},
    }
    if importance and cal_mask.sum() >= 200 and len(np.unique(train.label[cal_mask])) == 2:
        from sklearn.inspection import permutation_importance
        imp = permutation_importance(clf, train.X[cal_mask], train.label[cal_mask].astype(int),
                                     scoring="roc_auc", n_repeats=3, random_state=SEED, n_jobs=1)
        bundle["importance"] = {f: round(float(m), 5)
                                for f, m in zip(panel.features, imp.importances_mean)}
    return bundle


def predict(bundle: dict, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(raw probability, Platt-calibrated probability) of a net-positive 10-bar return."""
    raw = bundle["model"].predict_proba(X)[:, 1]
    return raw, Platt(*bundle["platt"])(raw)


def top_features(bundle: dict, k: int = TOP_FEATURES) -> list[tuple[str, float]]:
    imp = bundle.get("importance") or {}
    return sorted(imp.items(), key=lambda kv: -kv[1])[:k]


# ── cache ─────────────────────────────────────────────────────────────────────

def save(bundle: dict, data_dir=None) -> Path:
    import joblib
    d = model_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "model.joblib"
    tmp = path.with_suffix(".tmp")
    joblib.dump(bundle, tmp)
    os.replace(tmp, path)
    meta = {k: v for k, v in bundle.items() if k not in ("model",)}
    (d / "model_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return path


def load(data_dir=None) -> dict | None:
    path = model_dir(data_dir) / "model.joblib"
    if not path.exists():
        return None
    try:
        import joblib
        return joblib.load(path)
    except Exception:                                   # corrupt / incompatible cache
        logger.warning("ml_gbm: cached model unreadable, retraining", exc_info=True)
        return None


def usable(bundle: dict | None, asof: date, features: list[str]) -> bool:
    """A cached model is reused within its ISO week, same version and features, and only
    for an as-of date at or after the one it was trained for."""
    return (bundle is not None and bundle.get("version") == MODEL_VERSION
            and bundle.get("features") == features and bundle.get("week") == week_of(asof)
            and bundle.get("asof", "9999") <= asof.isoformat())


def get_model(panel: F.Panel, asof: date, data_dir=None) -> tuple[dict | None, bool]:
    """(model bundle, retrained?)"""
    cached = load(data_dir)
    if usable(cached, asof, panel.features):
        return cached, False
    bundle = fit(panel, asof)
    if bundle is not None:
        save(bundle, data_dir)
    return bundle, bundle is not None
