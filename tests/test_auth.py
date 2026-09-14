from app import auth, create_app


def test_verify_login_accepts_the_right_password(tmp_path):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    assert auth.verify_login(tmp_path, "Erokhov", "correct horse")


def test_verify_login_rejects_the_wrong_password(tmp_path):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    assert not auth.verify_login(tmp_path, "Erokhov", "wrong password")


def test_verify_login_rejects_an_unknown_user(tmp_path):
    assert not auth.verify_login(tmp_path, "nobody", "anything")


def test_verify_login_ignores_username_case(tmp_path):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    assert auth.verify_login(tmp_path, "erokhov", "correct horse")
    assert auth.verify_login(tmp_path, "EROKHOV", "correct horse")


def test_create_user_twice_replaces_the_password(tmp_path):
    auth.create_user(tmp_path, "Erokhov", "old password")
    auth.create_user(tmp_path, "Erokhov", "new password")
    assert not auth.verify_login(tmp_path, "Erokhov", "old password")
    assert auth.verify_login(tmp_path, "Erokhov", "new password")


def test_login_page_loads(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200


# The remaining tests need the login gate itself switched on — off by
# default under pytest so the rest of the suite can hit routes directly
# without logging in first (see app/__init__.py, _require_login).
# create_app() runs *before* the env var is cleared, the same ordering
# test_csrf.py uses for its own analogous "temporarily as strict as
# production" tests — WTF_CSRF_ENABLED is baked into app.config at
# create_app() time from that same env var, and clearing it after the fact
# would turn CSRF on too and break these POSTs, which aren't testing CSRF
# at all. The gate check itself is re-read from os.environ on every
# request, so clearing the var later still switches it on in time for the
# requests below.


def test_unauthenticated_request_is_sent_to_login(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    client = app.test_client()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    resp = client.get("/")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_with_correct_credentials_reaches_the_dashboard(tmp_path, monkeypatch):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    app = create_app(tmp_path)
    client = app.test_client()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    resp = client.post(
        "/login", data={"username": "Erokhov", "password": "correct horse"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    # Followed through: now signed in, the dashboard itself loads.
    resp = client.get("/")
    assert resp.status_code == 200


def test_login_with_wrong_password_stays_on_the_login_page(tmp_path, monkeypatch):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    app = create_app(tmp_path)
    client = app.test_client()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    resp = client.post(
        "/login", data={"username": "Erokhov", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert "Неверный логин или пароль".encode() in resp.data


def test_logout_clears_the_session(tmp_path, monkeypatch):
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    app = create_app(tmp_path)
    client = app.test_client()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    client.post("/login", data={"username": "Erokhov", "password": "correct horse"})
    client.post("/logout")
    resp = client.get("/")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_redirect_ignores_an_external_next_url(tmp_path, monkeypatch):
    """``next`` only ever sends the browser back into this app — otherwise
    a crafted login link could use it as an open redirect to anywhere."""
    auth.create_user(tmp_path, "Erokhov", "correct horse")
    app = create_app(tmp_path)
    client = app.test_client()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    resp = client.post(
        "/login",
        data={
            "username": "Erokhov", "password": "correct horse",
            "next": "//evil.example/",
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
