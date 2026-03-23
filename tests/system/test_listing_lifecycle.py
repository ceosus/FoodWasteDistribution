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


def donor_listing_payload(food_name="Bread", quantity="10"):
    expiry_value = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return {
        "food_name": food_name,
        "quantity": quantity,
        "donation_price": "50",
        "pickup_address": "Street 1",
        "latitude": "6.9271",
        "longitude": "79.8612",
        "expiry": expiry_value,
        "location": "Colombo",
        "description": "Fresh and packed",
        "category": "packaged",
    }


def test_full_listing_lifecycle_from_donor_to_ngo(client, app_state):
    register_user(client, "donor_1", "secret123", "donor", organization="Donor Org")
    register_user(client, "ngo_1", "secret123", "ngo", organization="NGO Org")

    login_user(client, "donor_1", "secret123")
    add_response = client.post("/donor/food/add", data=donor_listing_payload(), follow_redirects=True)

    assert add_response.status_code == 200
    assert b"added successfully" in add_response.data.lower()

    created_listing = app_state.food_col.find_one({"food_name": "Bread"})
    assert created_listing is not None
    assert created_listing["status"] == "available"

    client.post("/logout", follow_redirects=True)

    login_user(client, "ngo_1", "secret123")

    claim_response = client.post(
        f"/ngo/food/{created_listing['_id']}/claim",
        follow_redirects=True,
    )
    assert claim_response.status_code == 200

    claimed_listing = app_state.food_col.find_one({"_id": created_listing["_id"]})
    assert claimed_listing["status"] == "claimed"
    assert claimed_listing["claimed_by"] is not None

    received_response = client.post(
        f"/ngo/food/{created_listing['_id']}/received",
        follow_redirects=True,
    )
    assert received_response.status_code == 200

    collected_listing = app_state.food_col.find_one({"_id": created_listing["_id"]})
    assert collected_listing["status"] == "collected"


def test_ngo_can_generate_invoice_for_claimed_listing(client, app_state):
    app_state.app.config["BILLING_ENABLED"] = True

    register_user(client, "donor_bill", "secret123", "donor", organization="Donor Org")
    register_user(client, "ngo_bill", "secret123", "ngo", organization="NGO Org")

    login_user(client, "donor_bill", "secret123")
    client.post("/donor/food/add", data=donor_listing_payload(food_name="Rice"), follow_redirects=True)
    created_listing = app_state.food_col.find_one({"food_name": "Rice"})
    client.post("/logout", follow_redirects=True)

    login_user(client, "ngo_bill", "secret123")
    client.post(f"/ngo/food/{created_listing['_id']}/claim", follow_redirects=True)

    invoice_response = client.post(
        f"/ngo/food/{created_listing['_id']}/invoice",
        follow_redirects=True,
    )

    assert invoice_response.status_code == 200
    assert b"Invoice generated successfully" in invoice_response.data

    invoice = app_state.invoices_col.find_one({"listing_id": created_listing["_id"]})
    assert invoice is not None
    assert invoice["invoice_number"].startswith("INV-")
    assert invoice["quantity"] == created_listing["quantity"]
    assert invoice["unit_price"] == float(created_listing["donation_price"])

    client.post("/logout", follow_redirects=True)
    login_user(client, "donor_bill", "secret123")
    donor_invoice_response = client.get(f"/invoices/{invoice['_id']}", follow_redirects=True)

    assert donor_invoice_response.status_code == 200
    assert bytes(invoice["invoice_number"], "utf-8") in donor_invoice_response.data
