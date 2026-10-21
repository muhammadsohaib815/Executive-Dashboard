import scripts.server as server


def test_password_hash_round_trip_and_wrong_password_rejected():
    encoded = server.hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha256$")
    assert server.verify_password("correct horse battery staple", encoded)
    assert not server.verify_password("wrong password", encoded)


def test_signed_session_round_trip_and_expiry():
    token = server.create_session({"id": 42, "username": "admin", "role": "admin"})
    payload = server.decode_session(token)
    assert payload["uid"] == 42
    assert payload["role"] == "admin"

    original = server.AUTH_SESSION_TTL_SECONDS
    try:
        server.AUTH_SESSION_TTL_SECONDS = -1
        expired = server.create_session({"id": 42, "username": "admin", "role": "admin"})
        assert server.decode_session(expired) is None
    finally:
        server.AUTH_SESSION_TTL_SECONDS = original
