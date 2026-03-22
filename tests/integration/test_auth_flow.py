from werkzeug.security import check_password_hash


def register_user(client, username, password, role, organization="Org", location="City", contact="123456"):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": password,
            "role": role,
            "organization_name": organization,
            "location": location,
            "contact": contact,
        },
        follow_redirects=True,
    )


def login_user(client, username, password, follow_redirects=True):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=follow_redirects,
    )


def test_register_login_logout_flow(client, app_state):
    register_response = register_user(client, "donor_a", "secret123", "donor")

    assert register_response.status_code == 200
    assert b"Registration successful" in register_response.data

    created_user = app_state.users_col.find_one({"username": "donor_a"})
    assert created_user is not None
    assert created_user["password"] != "secret123"
    assert check_password_hash(created_user["password"], "secret123")

    login_response = login_user(client, "donor_a", "secret123", follow_redirects=False)

    assert login_response.status_code == 302
    assert "/donor/dashboard" in login_response.headers["Location"]

    with client.session_transaction() as session_data:
        assert session_data.get("username") == "donor_a"
        assert session_data.get("role") == "donor"

    logout_response = client.post("/logout", follow_redirects=True)
    assert logout_response.status_code == 200
    assert b"logged out" in logout_response.data.lower()

    with client.session_transaction() as session_data:
        assert "user_id" not in session_data
