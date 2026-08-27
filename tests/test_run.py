import run


def test_the_default_mode_runs_the_debug_dev_server(monkeypatch):
    monkeypatch.delenv("KEYPARAMS_ENV", raising=False)
    calls = []
    monkeypatch.setattr(run.app, "run", lambda **kwargs: calls.append(kwargs))

    run.main()

    assert calls == [{"debug": True}]


def test_production_mode_serves_with_waitress_on_every_interface(monkeypatch):
    monkeypatch.setenv("KEYPARAMS_ENV", "production")
    monkeypatch.delenv("KEYPARAMS_HOST", raising=False)
    monkeypatch.delenv("KEYPARAMS_PORT", raising=False)
    calls = []
    monkeypatch.setattr("waitress.serve", lambda app, **kwargs: calls.append(kwargs))

    run.main()

    assert calls == [{"host": "0.0.0.0", "port": 8080, "threads": 8}]


def test_production_mode_reads_the_host_and_port_from_the_environment(monkeypatch):
    monkeypatch.setenv("KEYPARAMS_ENV", "production")
    monkeypatch.setenv("KEYPARAMS_HOST", "127.0.0.1")
    monkeypatch.setenv("KEYPARAMS_PORT", "9001")
    calls = []
    monkeypatch.setattr("waitress.serve", lambda app, **kwargs: calls.append(kwargs))

    run.main()

    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 9001
