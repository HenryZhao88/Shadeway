from shadeway_pipeline.sources.fetch import cached_download


def test_download_is_cached_and_idempotent(tmp_path, monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {"content-length": "4"}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"data"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr("shadeway_pipeline.sources.fetch.requests.get", fake_get)

    first = cached_download("http://example.test/a.json", "a.json", cache_dir=tmp_path)
    second = cached_download("http://example.test/a.json", "a.json", cache_dir=tmp_path)

    assert first == second
    assert first.read_bytes() == b"data"
    assert len(calls) == 1, "second call must hit the cache, not the network"


def test_partial_download_is_not_left_in_the_cache(tmp_path, monkeypatch):
    def boom(url, **kwargs):
        raise ConnectionError("network died mid-stream")

    monkeypatch.setattr("shadeway_pipeline.sources.fetch.requests.get", boom)

    try:
        cached_download("http://example.test/b.json", "b.json", cache_dir=tmp_path)
    except ConnectionError:
        pass
    assert not (tmp_path / "b.json").exists(), "a failed download must not poison the cache"


def test_datasets_json_pins_every_key():
    from shadeway_pipeline.sources.resolve import DATASET_QUERIES, load_datasets

    pinned = load_datasets()
    for key in DATASET_QUERIES:
        assert key in pinned, key
        assert "-" in pinned[key], f"{key} does not look like a socrata id"
