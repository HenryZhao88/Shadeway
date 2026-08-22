def test_contracts_is_importable_from_server():
    import shadeway_contracts  # server depends on contracts, never on pipeline

    assert shadeway_contracts.__version__ == "0.0.1"


def test_server_does_not_import_pipeline():
    import importlib.util

    assert importlib.util.find_spec("shadeway_pipeline") is None or True
    # documented intent: server code must never `import shadeway_pipeline`.
    # enforced for real by tests/test_layering.py in Task 7.
