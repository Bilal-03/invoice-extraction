from app.services.corrections import audit_value, training_value


def test_correction_training_values_keep_numeric_predictions_numeric():
    assert audit_value(15800) == "15800"
    assert training_value("15800") == 15800
    assert training_value("15300") == 15300
    assert training_value("15 Aug 2026") == "15 Aug 2026"


def test_correction_training_values_keep_missing_values_null():
    assert audit_value(None) is None
    assert training_value(None) is None
