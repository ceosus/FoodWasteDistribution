from datetime import datetime, timedelta


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


def donor_listing_payload(donation_price="50"):
    expiry_value = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return {
        "food_name": "Bread",
        "quantity": "10",
        "donation_price": donation_price,
        "pickup_address": "Street 1",
        "latitude": "6.9271",
        "longitude": "79.8612",
        "expiry": expiry_value,
        "location": "Colombo",
        "description": "Fresh and packed",
        "category": "packaged",
    }


def test_zero_donation_price_rejected_by_default(client, app_state):
    app_state.app.config["DONATION_PRICE_ALLOW_ZERO"] = False
    register_user(client, "donor_zero_off", "secret123", "donor")
    login_user(client, "donor_zero_off", "secret123")

    response = client.post("/donor/food/add", data=donor_listing_payload(donation_price="0"), follow_redirects=True)

    assert response.status_code == 200
    assert b"Donation price must be greater than 0" in response.data


def test_zero_donation_price_allowed_when_config_enabled(client, app_state):
    app_state.app.config["DONATION_PRICE_ALLOW_ZERO"] = True
    register_user(client, "donor_zero_on", "secret123", "donor")
    login_user(client, "donor_zero_on", "secret123")

    response = client.post("/donor/food/add", data=donor_listing_payload(donation_price="0"), follow_redirects=True)

    assert response.status_code == 200
    assert b"added successfully" in response.data.lower()

    created_listing = app_state.food_col.find_one({"food_name": "Bread"})
    assert created_listing is not None
    assert created_listing["donation_price"] == 0.0
