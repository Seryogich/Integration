from app.model import make_dataset, predict_price, train_model


def test_dataset_is_reproducible():
    X1, y1 = make_dataset(n_samples=100, seed=1)
    X2, y2 = make_dataset(n_samples=100, seed=1)
    assert (X1 == X2).all() and (y1 == y2).all()


def test_out_of_sample_quality():
    model = train_model(n_samples=1500)
    assert model.metrics["n_test"] == 300
    assert model.metrics["test_r2"] > 0.9
    assert model.metrics["cv5_r2_mean"] > 0.9


def test_prediction_is_monotonic_in_area():
    model = train_model(n_samples=1500)
    small = predict_price(model, 40, 2, 1, 2000)
    large = predict_price(model, 300, 2, 1, 2000)
    assert large > small
