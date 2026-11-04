from tests.conftest import signup_and_login
from tests.sample import sample_profile


def test_profile_starts_empty_and_round_trips(client, auth):
    assert client.get("/profile", headers=auth).json()["experience"] == []
    body = sample_profile().model_dump()
    assert client.put("/profile", json=body, headers=auth).status_code == 200
    assert client.get("/profile", headers=auth).json() == body


def test_profiles_are_isolated_per_user(client, auth):
    client.put("/profile", json=sample_profile().model_dump(), headers=auth)
    other = signup_and_login(client, "friend@example.com")
    assert client.get("/profile", headers=other).json()["contact"]["name"] == ""
