from tests.conftest import signup_and_login


def test_first_user_signs_up_and_becomes_admin(client):
    headers = signup_and_login(client)
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "me@example.com" and me["is_admin"] is True


def test_signup_is_invite_only_after_first_user(client):
    signup_and_login(client)
    r = client.post("/auth/signup", json={"email": "stranger@example.com", "password": "password123"})
    assert r.status_code == 403
    headers = signup_and_login(client, "friend@example.com")  # in SIGNUP_ALLOWLIST
    assert client.get("/auth/me", headers=headers).json()["is_admin"] is False


def test_wrong_password_and_bad_token(client):
    signup_and_login(client)
    assert (
        client.post("/auth/login", data={"username": "me@example.com", "password": "nope-nope"}).status_code
        == 401
    )
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/profile").status_code == 401
