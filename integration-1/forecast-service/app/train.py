"""Train the model, evaluate it honestly, and persist the artifact.

Evaluation protocol
-------------------
1. Hold-out: 80 % of the rows are used for fitting, 20 % are never seen
   during training and are used only to compute R2 / MAE.
2. 5-fold cross-validation on the full dataset, to show how stable the
   hold-out estimate is.
3. The in-sample metrics (train on everything, score on the same rows)
   are still printed, but only to be compared with the honest numbers.

The artifact that is persisted for the API is refit on ALL rows, because
the evaluation above has already told us how well this recipe generalizes.
"""

from pathlib import Path

import joblib
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_validate, train_test_split

from .model import (
    CAT,
    NUM,
    TARGET,
    build_pipeline,
    load_training_data,
    train_model,
)


ARTIFACTS = (
    Path(__file__).resolve().parent.parent
    / "artifacts"
)

TEST_SIZE = 0.2
RANDOM_STATE = 42
CV_FOLDS = 5


def _score(model, df) -> tuple[float, float]:
    """Return (R2, MAE) of ``model`` on ``df``."""
    predictions = model.predict(df[NUM + CAT])

    return (
        r2_score(df[TARGET], predictions),
        mean_absolute_error(df[TARGET], predictions),
    )


def main() -> None:
    """Evaluate the model, then fit and persist the final artifact."""

    df = load_training_data()

    # ---- 1. Hold-out evaluation -------------------------------------
    train_df, test_df = train_test_split(
        df,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )

    holdout_model = train_model(train_df)

    train_r2, train_mae = _score(holdout_model, train_df)
    test_r2, test_mae = _score(holdout_model, test_df)

    print(
        f"[train] rows: total={len(df)}, "
        f"train={len(train_df)}, test={len(test_df)}"
    )
    print(
        f"[train] train   (seen):   "
        f"R2={train_r2:.4f}, MAE={train_mae:.0f} USD"
    )
    print(
        f"[train] test    (unseen): "
        f"R2={test_r2:.4f}, MAE={test_mae:.0f} USD"
    )

    # ---- 2. Cross-validation ----------------------------------------
    cv = cross_validate(
        build_pipeline(),
        df[NUM + CAT],
        df[TARGET],
        cv=CV_FOLDS,
        scoring=("r2", "neg_mean_absolute_error"),
    )

    cv_r2 = cv["test_r2"]
    cv_mae = -cv["test_neg_mean_absolute_error"]

    print(
        f"[train] {CV_FOLDS}-fold CV:       "
        f"R2={cv_r2.mean():.4f} +/- {cv_r2.std():.4f}, "
        f"MAE={cv_mae.mean():.0f} +/- {cv_mae.std():.0f} USD"
    )

    # ---- 3. Overfitting check ---------------------------------------
    gap = train_r2 - test_r2

    print(
        f"[train] R2 gap (train - test) = {gap:+.4f}; "
        f"MAE ratio (test / train) = {test_mae / train_mae:.2f}"
    )

    # ---- 4. Final model on all data ---------------------------------
    model = train_model(df)

    in_r2, in_mae = _score(model, df)

    print(
        f"[train] Ames in-sample (final model, for comparison only): "
        f"R2={in_r2:.4f}, MAE={in_mae:.0f} USD"
    )

    ARTIFACTS.mkdir(
        parents=True,
        exist_ok=True,
    )

    artifact_path = ARTIFACTS / "model.pkl"

    joblib.dump(
        model,
        artifact_path,
    )

    print(
        f"[train] artifact persisted: {artifact_path}"
    )


if __name__ == "__main__":
    main()
