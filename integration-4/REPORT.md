# Practice 4 Report

## 1. Baseline vs Final model (identical hold-out conditions)

| Metric          | Ridge baseline | XGBoost final |
|-----------------|----------------|---------------|
| holdout_r2      | (fill after training) | |
| holdout_mae     |                | |
| holdout_rmse    |                | |
| holdout_mape    |                | |

## 2. Trainer log excerpt

```
(paste relevant lines from `docker compose --profile train run --rm trainer`)
```

## 3. Rollback experiment timeline (R3.5)

| Step | Action | Observed model_version | Prediction sample |
|------|--------|------------------------|-------------------|
| 1    | Initial @prod = vN | | |
| 2    | Register second version, set @prod, restart forecast | | |
| 3    | Re-assign @prod back to previous, restart | | |

## 4. Acceptance tests T1–T19

| ID | Result | Notes |
|----|--------|-------|
| T1 | PASS/FAIL | |
| T2 | | |
| …  | | |
| T19 | (bonus) | |

## 5. Notes

- MLflow database provisioning: …
- Fail-fast behaviour when alias is missing: …
