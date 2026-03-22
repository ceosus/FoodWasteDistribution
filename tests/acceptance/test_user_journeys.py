
def register_user(client, username, password, role, organization="Org", location="City", contact="0712345678"):
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


def test_guest_is_redirected_from_protected_dashboard(client):
    response = client.get("/donor/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_donor_user_story_register_login_and_reach_dashboard(client):
    register_user(client, "donor_story", "secret123", "donor", organization="Story Donor")

    login_response = login_user(client, "donor_story", "secret123", follow_redirects=False)

    assert login_response.status_code == 302
    assert "/donor/dashboard" in login_response.headers["Location"]

    page_response = client.get("/donor/dashboard", follow_redirects=True)
    assert page_response.status_code == 200


def test_ngo_cannot_access_donor_dashboard(client):
    register_user(client, "ngo_story", "secret123", "ngo", organization="Story NGO")
    login_user(client, "ngo_story", "secret123")

    response = client.get("/donor/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
