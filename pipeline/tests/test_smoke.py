def test_contracts_is_importable_from_pipeline():
    import shadeway_contracts

    assert shadeway_contracts.__version__ == "0.0.1"
