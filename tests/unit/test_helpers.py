from datetime import datetime, timezone

import app as app_module


def test_parse_expiry_valid_value():
    result = app_module.parse_expiry("2030-12-01T14:30")

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 2030


def test_parse_expiry_invalid_value():
    assert app_module.parse_expiry("not-a-date") is None


def test_parse_donation_price_rules():
    assert app_module.parse_donation_price("10.129") == 10.13
    assert app_module.parse_donation_price("0") is None
    assert app_module.parse_donation_price("-5") is None
    assert app_module.parse_donation_price("abc") is None


def test_parse_coordinates_requires_both_values():
    lat, lng, err = app_module.parse_coordinates("6.9", "")

    assert lat is None
    assert lng is None
    assert "both latitude and longitude" in err


def test_parse_coordinates_success_and_rounding():
    lat, lng, err = app_module.parse_coordinates("6.92714555", "79.86124444")

    assert err is None
    assert lat == 6.927146
    assert lng == 79.861244


def test_parse_contact_number_accepts_exactly_10_digits():
    assert app_module.parse_contact_number("0712345678") == "0712345678"


def test_parse_contact_number_rejects_invalid_values():
    assert app_module.parse_contact_number("712345678") is None
    assert app_module.parse_contact_number("07123-45678") is None
    assert app_module.parse_contact_number("07123456789") is None


def test_quick_chatbot_reply_for_guest_login_status():
    reply = app_module.quick_chatbot_reply(
        "am i logged in",
        user_context={"is_authenticated": False, "role": "guest", "username": "Guest"},
    )

    assert "not logged in" in reply.lower()


def test_quick_chatbot_reply_for_guest_password_reset():
    reply = app_module.quick_chatbot_reply(
        "I forgot password",
        user_context={"is_authenticated": False, "role": "guest", "username": "Guest"},
    )

    assert "contact" in reply.lower()
    assert "admin" in reply.lower()


def test_quick_chatbot_reply_for_logged_in_password_reset():
    reply = app_module.quick_chatbot_reply(
        "reset password",
        user_context={"is_authenticated": True, "role": "donor", "username": "alex"},
    )

    assert "settings" in reply.lower()
    assert "change password" in reply.lower()


def test_format_chatbot_answer_limits_lines():
    result = app_module.format_chatbot_answer("1. One\n2. Two\n3. Three\n4. Four\n5. Five")

    assert result.count("\n") == 3
    assert "Five" not in result
