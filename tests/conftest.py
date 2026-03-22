from datetime import datetime, timedelta

import mongomock
import pytest

import app as app_module


@pytest.fixture()
def flask_app():
    fake_client = mongomock.MongoClient()
    fake_db = fake_client["fwd_test_db"]

    app_module.mongo_client = fake_client
    app_module.db = fake_db
    app_module.users_col = fake_db.users
    app_module.food_col = fake_db.food_listings
    app_module.messages_col = fake_db.messages
    app_module.create_indexes()

    app_module.CHATBOT_API_KEYS = []
    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret-key",
    )

    yield app_module.app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture()
def app_state():
    return app_module


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
