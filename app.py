import os
import re
import json
from datetime import datetime, timezone
from functools import wraps

from bson.errors import InvalidId
from bson.objectid import ObjectId
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect
from dotenv import dotenv_values
from jinja2 import Undefined
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
import requests
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config


app = Flask(__name__)
csrf = CSRFProtect(app)
app.config.from_object(Config)

mongo_client = MongoClient(app.config["MONGO_URI"])
db = mongo_client[app.config["MONGO_DB_NAME"]]
users_col = db.users
food_col = db.food_listings
messages_col = db.messages

CHATBOT_MODEL = "llama-3.1-8b-instant"
CHATBOT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
CHATBOT_OFFTOPIC_REPLY = "I can only answer questions about the FWD project."
CHATBOT_DATASET_PATH = os.path.join(os.path.dirname(__file__), "data", "fwd_chatbot_dataset.json")
CHATBOT_ACK_WORDS = {
    "ok",
    "okay",
    "k",
    "cool",
    "great",
    "nice",
    "fine",
    "good",
    "thanks",
    "thank",
    "thx",
    "got",
    "it",
    "understood",
    "sure",
    "yes",
    "yep",
    "yup",
}
CHATBOT_GREETING_WORDS = {"hi", "hello", "hey", "hola", "namaste"}
PROJECT_SYSTEM_PROMPT = (
    "You are fwdChat, the assistant for FWD (Food Waste Distribution), used by donors and NGOs. "
    "Be conversational and friendly, and answer user questions about how FWD works from a user perspective. "
    "FWD is web-based only for now. Do not mention mobile apps, app store, play store, or app downloads. "
    "Do not claim email-login or app-only onboarding. Account creation happens on the web register page. "
    "You can answer greetings like hi, hello, and hey. "
    "You can answer questions about food listings, claiming food, donor and NGO actions, dashboards, messaging, and app workflows. "
    "If a question is completely unrelated to FWD (for example sports, movies, or unrelated coding help), "
    "reply exactly: 'I can only answer questions about the FWD project.' "
    "Use the provided FWD knowledge context as the source of truth. If a detail is not in that context, say it is not available yet in the current web app. "
    "Keep answers clear, concise, and focused on the user's question. "
    "Use 2-4 short lines, plain text only, and avoid markdown tables or code blocks."
)


def get_chatbot_user_context():
    role = (session.get("role") or "").strip().lower()
    username = (session.get("username") or "").strip()
    is_authenticated = bool(session.get("user_id")) and role in {"donor", "ngo"}

    if not is_authenticated:
        return {"is_authenticated": False, "role": "guest", "username": "Guest"}

    return {
        "is_authenticated": True,
        "role": role,
        "username": username or "User",
    }


def build_chatbot_user_context_prompt(user_context: dict) -> str:
    role = user_context.get("role", "guest")
    username = user_context.get("username", "Guest")
    is_authenticated = bool(user_context.get("is_authenticated"))

    if not is_authenticated:
        return (
            "Current User Context:\n"
            "- Authenticated: no\n"
            "- Role: guest\n"
            "- Guidance: Give general FWD guidance and suggest login/register when role-specific actions are requested.\n"
            "- Constraint: Never claim the user is logged in, never claim a dashboard is active, and never claim a username is known."
        )

    return (
        "Current User Context:\n"
        f"- Authenticated: yes\n"
        f"- Username: {username}\n"
        f"- Role: {role}\n"
        "- Guidance: Personalize naturally using username and prioritize role-specific actions for this user.\n"
        "- Constraint: Do not deny login status when Authenticated is yes."
    )


def load_chatbot_dataset():
    try:
        with open(CHATBOT_DATASET_PATH, "r", encoding="utf-8") as dataset_file:
            payload = json.load(dataset_file)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    cleaned = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer", "")).strip()
        if not answer:
            continue
        cleaned.append(
            {
                "intent": str(item.get("intent", "General")).strip() or "General",
                "question": str(item.get("question", "")).strip(),
                "answer": answer,
                "keywords": [
                    str(keyword).strip().lower()
                    for keyword in (item.get("keywords") or [])
                    if str(keyword).strip()
                ],
            }
        )
    return cleaned


CHATBOT_DATASET = load_chatbot_dataset()


def _tokenize_text(text: str):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def build_chatbot_context(question: str) -> str:
    if not CHATBOT_DATASET:
        return (
            "FWD Knowledge Context:\n"
            "- FWD is a web platform for donors and NGOs to coordinate surplus food distribution.\n"
            "- If details are missing, answer conservatively and avoid inventing features."
        )

    question_tokens = _tokenize_text(question)
    ranked_entries = []

    for item in CHATBOT_DATASET:
        searchable_text = " ".join(
            [
                item.get("intent", ""),
                item.get("question", ""),
                item.get("answer", ""),
                " ".join(item.get("keywords", [])),
            ]
        )
        entry_tokens = _tokenize_text(searchable_text)
        overlap = len(question_tokens & entry_tokens)
        if overlap > 0:
            ranked_entries.append((overlap, item))

    ranked_entries.sort(key=lambda row: row[0], reverse=True)
    selected = [row[1] for row in ranked_entries[:5]]

    if not selected:
        selected = CHATBOT_DATASET[:5]

    context_lines = ["FWD Knowledge Context (use these facts only):"]
    for idx, item in enumerate(selected, start=1):
        context_lines.append(
            f"{idx}. Intent: {item.get('intent', 'General')} | "
            f"Question: {item.get('question', '')} | "
            f"Answer: {item.get('answer', '')}"
        )
    return "\n".join(context_lines)


def quick_chatbot_reply(question: str, user_context: dict | None = None):
    user_context = user_context or {"is_authenticated": False, "role": "guest", "username": "Guest"}
    role = user_context.get("role", "guest")
    username = user_context.get("username", "Guest")

    normalized = re.sub(r"[^a-z0-9\s]", " ", (question or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return None

    words = [word for word in normalized.split(" ") if word]
    if not words:
        return None

    # Handle direct session-status checks deterministically from Flask session context.
    login_status_phrases = {
        "am i logged in",
        "i am logged in",
        "im logged in",
        "logged in",
        "login status",
        "am i login",
        "who am i",
        "what is my role",
        "my role",
        "my username",
    }
    if normalized in login_status_phrases:
        if role == "donor":
            return (
                f"Yes, {username}. You are logged in as a donor.\n"
                "You can manage listings, messages, settings, and pickup status from the donor dashboard."
            )
        if role == "ngo":
            return (
                f"Yes, {username}. You are logged in as an NGO.\n"
                "You can claim food, message donors, open settings, and update received status."
            )
        return (
            "You are not logged in right now.\n"
            "Please use Login, then I can give donor/NGO-specific guidance with your account context."
        )

    # Handle short acknowledgement turns so the bot does not reset into generic replies.
    if len(words) <= 4 and all(word in CHATBOT_ACK_WORDS for word in words):
        if role == "donor":
            return (
                f"Great, {username}. I can help with donor tasks.\n"
                "Ask about adding listings, improving claim speed, pricing, messaging, or collected status updates."
            )
        if role == "ngo":
            return (
                f"Great, {username}. I can help with NGO tasks.\n"
                "Ask about filters, claim decisions, donor coordination, map distance, or marking received."
            )
        return (
            "Great. I am here for FWD web support.\n"
            "Ask about account setup, posting food, NGO claims, pricing, messaging, or map distance."
        )

    if len(words) <= 4 and all(word in CHATBOT_GREETING_WORDS for word in words):
        if role == "donor":
            return (
                f"Hello {username}. You are logged in as a donor.\n"
                "I can help with listings, claim coordination, pricing, messages, and dashboard actions."
            )
        if role == "ngo":
            return (
                f"Hello {username}. You are logged in as an NGO.\n"
                "I can help with claiming food, distance checks, donor messaging, received status, and settings."
            )
        return (
            "Hello from fwdChat.\n"
            "I can help with FWD web workflows: register, login, donor listings, NGO claims, messages, and maps."
        )

    return None


def create_indexes() -> None:
    users_col.create_index([("username", ASCENDING)], unique=True)
    food_col.create_index([("donor_id", ASCENDING), ("created_at", DESCENDING)])
    food_col.create_index([("status", ASCENDING), ("location", ASCENDING), ("category", ASCENDING)])
    messages_col.create_index([("recipient_id", ASCENDING), ("created_at", DESCENDING)])
    messages_col.create_index([("sender_id", ASCENDING), ("created_at", DESCENDING)])


create_indexes()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_object_id(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    obj_id = parse_object_id(user_id)
    if not obj_id:
        return None

    return users_col.find_one({"_id": obj_id})


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def role_required(role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if session.get("role") != role:
                flash("You are not authorized to access this page.", "error")
                return redirect(url_for("home"))
            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator


def parse_expiry(expiry_input: str):
    if not expiry_input:
        return None
    try:
        naive = datetime.strptime(expiry_input, "%Y-%m-%dT%H:%M")
        return naive.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_donation_price(price_input: str):
    if not price_input:
        return None
    try:
        price = float(price_input)
    except ValueError:
        return None
    if price <= 0:
        return None
    return round(price, 2)


def parse_coordinates(latitude_raw: str, longitude_raw: str):
    lat_raw = (latitude_raw or "").strip()
    lng_raw = (longitude_raw or "").strip()

    if not lat_raw and not lng_raw:
        return None, None, None
    if not lat_raw or not lng_raw:
        return None, None, "Please select both latitude and longitude on the map."

    try:
        lat = float(lat_raw)
        lng = float(lng_raw)
    except ValueError:
        return None, None, "Invalid map coordinates. Please pick a valid location."

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None, None, "Map coordinates are out of range."

    return round(lat, 6), round(lng, 6), None


def _clean_env_value(value: str) -> str:
    return value.strip().strip('"').strip("'")


def get_chatbot_api_keys():
    key_candidates = []

    for env_name in [
        "FWD_API_KEY_1",
        "FWD_API_KEY_2",
        "FWD_API_KEY_3",
        "GROQ_API_KEY_1",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
        "fwd_1_api",
        "fwd_2_api",
        "fwd_3_api",
    ]:
        env_value = os.getenv(env_name)
        if env_value:
            key_candidates.append(_clean_env_value(env_value))

    dotenv_map = dotenv_values(".env")
    for env_name in ["fwd_1_api", "fwd_2_api", "fwd_3_api"]:
        env_value = dotenv_map.get(env_name)
        if env_value:
            key_candidates.append(_clean_env_value(str(env_value)))

    deduped = []
    seen = set()
    for key in key_candidates:
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)

    return deduped


CHATBOT_API_KEYS = get_chatbot_api_keys()


def format_chatbot_answer(answer: str) -> str:
    if not answer:
        return "I can only answer questions about the FWD project."

    text = answer.replace("\r\n", "\n").replace("```", "").strip()
    cleaned_lines = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*•]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()

        if line:
            cleaned_lines.append(line)

    if not cleaned_lines:
        return "I can only answer questions about the FWD project."

    return "\n".join(cleaned_lines[:4])


def ask_project_chatbot(question: str, user_context: dict | None = None):
    user_context = user_context or get_chatbot_user_context()

    quick_reply = quick_chatbot_reply(question, user_context=user_context)
    if quick_reply:
        return quick_reply, True

    api_keys = CHATBOT_API_KEYS
    if not api_keys:
        return "Chatbot is not configured. Add API keys in .env.", False

    payload = {
        "model": CHATBOT_MODEL,
        "temperature": 0.0,
        "max_tokens": 350,
        "messages": [
            {"role": "system", "content": PROJECT_SYSTEM_PROMPT},
            {"role": "system", "content": build_chatbot_user_context_prompt(user_context)},
            {"role": "system", "content": build_chatbot_context(question)},
            {"role": "user", "content": question},
        ],
    }

    for api_key in api_keys:
        try:
            response = requests.post(
                CHATBOT_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            if response.status_code >= 400:
                continue

            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                continue

            content = (choices[0].get("message") or {}).get("content", "").strip()
            if not content:
                continue

            return format_chatbot_answer(content), True
        except requests.RequestException:
            continue

    return "Chatbot is temporarily unavailable. Please try again shortly.", False


@app.context_processor
def inject_user_context():
    unread_messages = 0
    user_id = parse_object_id(session.get("user_id"))
    if user_id:
        unread_messages = messages_col.count_documents({"recipient_id": user_id, "is_read": False})

    return {
        "current_role": session.get("role"),
        "current_username": session.get("username"),
        "is_authenticated": "user_id" in session,
        "unread_messages": unread_messages,
    }


@app.template_filter("datetime_fmt")
def datetime_fmt(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


@app.template_filter("money_fmt")
def money_fmt(value):
    if value is None or isinstance(value, Undefined):
        return "Rs. 0.00"
    try:
        return f"Rs. {float(value):,.2f}"
    except (TypeError, ValueError):
        return "Rs. 0.00"


@app.get("/")
def home():
    value_pipeline = [
        {
            "$project": {
                "line_total": {
                    "$multiply": [
                        {"$ifNull": ["$quantity", 0]},
                        {"$ifNull": ["$donation_price", 0]},
                    ]
                }
            }
        },
        {"$group": {"_id": None, "total_value": {"$sum": "$line_total"}}},
    ]
    value_result = list(food_col.aggregate(value_pipeline))
    total_donation_value = value_result[0].get("total_value", 0) if value_result else 0

    stats = {
        "total_donors": users_col.count_documents({"role": "donor"}),
        "total_ngos": users_col.count_documents({"role": "ngo"}),
        "total_listings": food_col.count_documents({}),
        "available_listings": food_col.count_documents({"status": "available"}),
        "claimed_orders": food_col.count_documents({"status": "claimed"}),
        "collected_orders": food_col.count_documents({"status": "collected"}),
        "total_donation_value": round(total_donation_value, 2),
    }

    user_role = session.get("role")
    role_route = None
    if user_role == "donor":
        role_route = url_for("donor_dashboard")
    elif user_role == "ngo":
        role_route = url_for("ngo_dashboard")

    return render_template("home.html", stats=stats, role_route=role_route)


@app.get("/privacy-policy")
def privacy_policy():
    return render_template("legal/privacy.html")


@app.get("/terms-of-use")
def terms_of_use():
    return render_template("legal/terms.html")


@app.get("/contact")
def contact_page():
    return render_template("legal/contact.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip().lower()
        organization_name = request.form.get("organization_name", "").strip()
        location = request.form.get("location", "").strip()
        contact = request.form.get("contact", "").strip()

        if not all([username, password, role, organization_name, location, contact]):
            flash("All fields are required.", "error")
            return render_template("auth/register.html")

        if role not in {"donor", "ngo"}:
            flash("Invalid role selected.", "error")
            return render_template("auth/register.html")

        user_doc = {
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
            "organization_name": organization_name,
            "location": location,
            "contact": contact,
            "created_at": utcnow(),
        }

        try:
            users_col.insert_one(user_doc)
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
        except DuplicateKeyError:
            flash("Username already exists. Please choose another.", "error")

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/login.html")

        user = users_col.find_one({"username": username})
        if not user or not check_password_hash(user.get("password", ""), password):
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = str(user["_id"])
        session["role"] = user["role"]
        session["username"] = user["username"]
        session.permanent = True

        flash("Login successful.", "success")
        if user["role"] == "donor":
            return redirect(url_for("donor_dashboard"))
        return redirect(url_for("ngo_dashboard"))

    return render_template("auth/login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.get("/donor/dashboard")
@login_required
@role_required("donor")
def donor_dashboard():
    donor_id = parse_object_id(session.get("user_id"))
    listings = list(food_col.find({"donor_id": donor_id}).sort("created_at", DESCENDING))

    total_listings = len(listings)
    available_count = sum(1 for listing in listings if listing.get("status") == "available")
    claimed_count = sum(1 for listing in listings if listing.get("status") == "claimed")
    collected_count = sum(1 for listing in listings if listing.get("status") == "collected")
    total_quantity = sum(int(listing.get("quantity", 0)) for listing in listings)
    total_order_value = sum(float(listing.get("donation_price", 0)) * int(listing.get("quantity", 0)) for listing in listings)

    unread_for_donor = messages_col.count_documents({"recipient_id": donor_id, "is_read": False})

    claimed_user_ids = [item.get("claimed_by") for item in listings if item.get("claimed_by")]
    claimed_users = {
        user["_id"]: user
        for user in users_col.find(
            {"_id": {"$in": claimed_user_ids}},
            {"organization_name": 1, "username": 1},
        )
    }

    for item in listings:
        claimed_by = item.get("claimed_by")
        claimant = claimed_users.get(claimed_by) if claimed_by else None
        item["claimed_org_name"] = claimant.get("organization_name") if claimant else None

    mapped_listings = [
        {
            "id": str(item.get("_id")),
            "food_name": item.get("food_name", "Listing"),
            "location": item.get("location", "Unknown"),
            "pickup_address": item.get("pickup_address") or item.get("location", "Unknown"),
            "status": item.get("status", "available"),
            "quantity": item.get("quantity", 0),
            "donation_price": item.get("donation_price", 0),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in listings
        if item.get("latitude") is not None and item.get("longitude") is not None
    ]

    return render_template(
        "donor/dashboard.html",
        listings=listings,
        total_listings=total_listings,
        available_count=available_count,
        claimed_count=claimed_count,
        collected_count=collected_count,
        total_quantity=total_quantity,
        total_order_value=round(total_order_value, 2),
        mapped_listings=mapped_listings,
        unread_for_donor=unread_for_donor,
        suggested_prompts=[
            "How can I improve pickup success for my listings?",
            "What should I do after an NGO claims my food?",
            "How do I keep my food listings clear and complete?",
        ],
    )


@app.route("/donor/food/add", methods=["GET", "POST"])
@login_required
@role_required("donor")
def donor_add_food():
    if request.method == "POST":
        donor_id = parse_object_id(session.get("user_id"))
        food_name = request.form.get("food_name", "").strip()
        quantity_raw = request.form.get("quantity", "").strip()
        donation_price_raw = request.form.get("donation_price", "").strip()
        pickup_address = request.form.get("pickup_address", "").strip()
        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()
        expiry_input = request.form.get("expiry", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip().lower()

        expiry = parse_expiry(expiry_input)
        donation_price = parse_donation_price(donation_price_raw)
        if not all([food_name, quantity_raw, expiry, location, description, category, donation_price, pickup_address]):
            flash("All fields are required, and expiry must be valid.", "error")
            return render_template("donor/add_food.html")

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a positive integer.", "error")
            return render_template("donor/add_food.html")

        if category not in {"cooked", "raw", "packaged"}:
            flash("Invalid food category.", "error")
            return render_template("donor/add_food.html")

        if donation_price is None:
            flash("Donation price must be greater than 0.", "error")
            return render_template("donor/add_food.html")

        latitude, longitude, coord_error = parse_coordinates(latitude_raw, longitude_raw)
        if coord_error:
            flash(coord_error, "error")
            return render_template("donor/add_food.html")

        if latitude is None or longitude is None:
            flash("Please pin the pickup point on the map.", "error")
            return render_template("donor/add_food.html")

        food_doc = {
            "donor_id": donor_id,
            "food_name": food_name,
            "quantity": quantity,
            "donation_price": donation_price,
            "latitude": latitude,
            "longitude": longitude,
            "pickup_address": pickup_address,
            "expiry": expiry,
            "location": location,
            "description": description,
            "category": category,
            "status": "available",
            "claimed_by": None,
            "created_at": utcnow(),
        }

        food_col.insert_one(food_doc)
        flash("Food listing added successfully.", "success")
        return redirect(url_for("donor_dashboard"))

    return render_template("donor/add_food.html")


@app.route("/donor/food/<listing_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("donor")
def donor_edit_food(listing_id):
    donor_id = parse_object_id(session.get("user_id"))
    obj_id = parse_object_id(listing_id)
    if not obj_id:
        flash("Invalid listing id.", "error")
        return redirect(url_for("donor_dashboard"))

    listing = food_col.find_one({"_id": obj_id, "donor_id": donor_id})
    if not listing:
        flash("Listing not found.", "error")
        return redirect(url_for("donor_dashboard"))

    if listing.get("status") == "collected":
        flash("Collected listings cannot be edited.", "error")
        return redirect(url_for("donor_dashboard"))

    if request.method == "POST":
        food_name = request.form.get("food_name", "").strip()
        quantity_raw = request.form.get("quantity", "").strip()
        donation_price_raw = request.form.get("donation_price", "").strip()
        pickup_address = request.form.get("pickup_address", "").strip()
        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()
        expiry_input = request.form.get("expiry", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip().lower()

        expiry = parse_expiry(expiry_input)
        donation_price = parse_donation_price(donation_price_raw)
        if not all([food_name, quantity_raw, expiry, location, description, category, donation_price, pickup_address]):
            flash("All fields are required, and expiry must be valid.", "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a positive integer.", "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        if category not in {"cooked", "raw", "packaged"}:
            flash("Invalid food category.", "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        if donation_price is None:
            flash("Donation price must be greater than 0.", "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        latitude, longitude, coord_error = parse_coordinates(latitude_raw, longitude_raw)
        if coord_error:
            flash(coord_error, "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        if latitude is None or longitude is None:
            flash("Please pin the pickup point on the map.", "error")
            return render_template("donor/add_food.html", listing=listing, is_edit=True)

        food_col.update_one(
            {"_id": obj_id, "donor_id": donor_id},
            {
                "$set": {
                    "food_name": food_name,
                    "quantity": quantity,
                    "donation_price": donation_price,
                    "latitude": latitude,
                    "longitude": longitude,
                    "pickup_address": pickup_address,
                    "expiry": expiry,
                    "location": location,
                    "description": description,
                    "category": category,
                }
            },
        )
        flash("Listing updated successfully.", "success")
        return redirect(url_for("donor_dashboard"))

    return render_template("donor/add_food.html", listing=listing, is_edit=True)


@app.post("/donor/food/<listing_id>/delete")
@login_required
@role_required("donor")
def donor_delete_food(listing_id):
    donor_id = parse_object_id(session.get("user_id"))
    obj_id = parse_object_id(listing_id)
    if not obj_id:
        flash("Invalid listing id.", "error")
        return redirect(url_for("donor_dashboard"))

    listing = food_col.find_one({"_id": obj_id, "donor_id": donor_id})
    if not listing:
        flash("Listing not found.", "error")
        return redirect(url_for("donor_dashboard"))

    if listing.get("status") == "claimed":
        flash("Claimed listings cannot be deleted.", "error")
        return redirect(url_for("donor_dashboard"))

    food_col.delete_one({"_id": obj_id, "donor_id": donor_id})
    flash("Listing deleted successfully.", "success")
    return redirect(url_for("donor_dashboard"))


@app.post("/donor/food/<listing_id>/collected")
@login_required
@role_required("donor")
def donor_mark_collected(listing_id):
    donor_id = parse_object_id(session.get("user_id"))
    obj_id = parse_object_id(listing_id)
    if not obj_id:
        flash("Invalid listing id.", "error")
        return redirect(url_for("donor_dashboard"))

    result = food_col.update_one(
        {"_id": obj_id, "donor_id": donor_id, "status": {"$in": ["available", "claimed"]}},
        {"$set": {"status": "collected", "collected_at": utcnow()}},
    )

    if result.modified_count:
        flash("Listing marked as collected.", "success")
    else:
        flash("Unable to update listing status.", "error")

    return redirect(url_for("donor_dashboard"))


@app.route("/donor/settings", methods=["GET", "POST"])
@login_required
@role_required("donor")
def donor_settings():
    current_user = get_current_user()
    if not current_user:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "update":
            username = request.form.get("username", "").strip().lower()
            organization_name = request.form.get("organization_name", "").strip()
            location = request.form.get("location", "").strip()
            contact = request.form.get("contact", "").strip()

            if not all([username, organization_name, location, contact]):
                flash("All fields are required.", "error")
                return render_template("donor/settings.html", current_user=current_user)

            # Check if new username is already taken (if changed)
            if username != current_user.get("username"):
                existing = users_col.find_one({"username": username})
                if existing:
                    flash("Username already taken. Please choose another.", "error")
                    return render_template("donor/settings.html", current_user=current_user)

            users_col.update_one(
                {"_id": current_user["_id"]},
                {
                    "$set": {
                        "username": username,
                        "organization_name": organization_name,
                        "location": location,
                        "contact": contact,
                    }
                },
            )
            session["username"] = username
            flash("Profile updated successfully.", "success")
            current_user = get_current_user()
            return render_template("donor/settings.html", current_user=current_user)

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password or not new_password or not confirm_password:
                flash("All password fields are required.", "error")
                return render_template("donor/settings.html", current_user=current_user)

            if not check_password_hash(current_user.get("password", ""), current_password):
                flash("Current password is incorrect.", "error")
                return render_template("donor/settings.html", current_user=current_user)

            if new_password != confirm_password:
                flash("New passwords do not match.", "error")
                return render_template("donor/settings.html", current_user=current_user)

            if len(new_password) < 6:
                flash("New password must be at least 6 characters.", "error")
                return render_template("donor/settings.html", current_user=current_user)

            users_col.update_one(
                {"_id": current_user["_id"]},
                {"$set": {"password": generate_password_hash(new_password)}},
            )
            flash("Password changed successfully.", "success")
            current_user = get_current_user()
            return render_template("donor/settings.html", current_user=current_user)

        elif action == "delete":
            # Delete user's account and all related data
            users_col.delete_one({"_id": current_user["_id"]})
            food_col.delete_many({"donor_id": current_user["_id"]})
            messages_col.delete_many({"sender_id": current_user["_id"]})
            messages_col.delete_many({"recipient_id": current_user["_id"]})
            session.clear()
            flash("Your account has been deleted.", "success")
            return redirect(url_for("home"))

    return render_template("donor/settings.html", current_user=current_user)


@app.get("/ngo/dashboard")
@login_required
@role_required("ngo")
def ngo_dashboard():
    ngo_id = parse_object_id(session.get("user_id"))
    available_count = food_col.count_documents({"status": "available"})
    claimed_count = food_col.count_documents({"claimed_by": ngo_id, "status": "claimed"})
    collected_count = food_col.count_documents({"claimed_by": ngo_id, "status": "collected"})
    recent_claims = list(food_col.find({"claimed_by": ngo_id}).sort("created_at", DESCENDING).limit(8))
    unread_for_ngo = messages_col.count_documents({"recipient_id": ngo_id, "is_read": False})

    qty_pipeline = [
        {"$match": {"claimed_by": ngo_id}},
        {"$group": {"_id": None, "total_quantity": {"$sum": "$quantity"}}},
    ]
    qty_result = list(food_col.aggregate(qty_pipeline))
    total_claimed_quantity = qty_result[0].get("total_quantity", 0) if qty_result else 0

    value_pipeline = [
        {"$match": {"claimed_by": ngo_id}},
        {
            "$project": {
                "line_total": {
                    "$multiply": [
                        {"$ifNull": ["$quantity", 0]},
                        {"$ifNull": ["$donation_price", 0]},
                    ]
                }
            }
        },
        {"$group": {"_id": None, "total_value": {"$sum": "$line_total"}}},
    ]
    value_result = list(food_col.aggregate(value_pipeline))
    total_claimed_value = value_result[0].get("total_value", 0) if value_result else 0

    return render_template(
        "ngo/dashboard.html",
        available_count=available_count,
        claimed_count=claimed_count,
        collected_count=collected_count,
        recent_claims=recent_claims,
        total_claimed_quantity=total_claimed_quantity,
        total_claimed_value=round(total_claimed_value, 2),
        unread_for_ngo=unread_for_ngo,
        suggested_prompts=[
            "How do I prioritize which listing to claim first?",
            "What checks should I do before marking as received?",
            "How can I coordinate faster with donors in FWD?",
        ],
    )


@app.get("/ngo/food/claim")
@login_required
@role_required("ngo")
def ngo_claim_food():
    location = request.args.get("location", "").strip()
    category = request.args.get("category", "").strip().lower()
    min_quantity_raw = request.args.get("min_quantity", "").strip()

    query = {"status": "available"}
    if location:
        query["location"] = {"$regex": location, "$options": "i"}
    if category in {"cooked", "raw", "packaged"}:
        query["category"] = category
    if min_quantity_raw:
        try:
            min_quantity = int(min_quantity_raw)
            if min_quantity > 0:
                query["quantity"] = {"$gte": min_quantity}
        except ValueError:
            flash("Minimum quantity filter must be a number.", "error")

    listings = list(food_col.find(query).sort("expiry", ASCENDING))
    ngo_id = parse_object_id(session.get("user_id"))
    claimed_history = list(food_col.find({"claimed_by": ngo_id}).sort("created_at", DESCENDING).limit(20))

    donor_ids = list({item.get("donor_id") for item in listings + claimed_history if item.get("donor_id")})
    donors = {
        user["_id"]: user
        for user in users_col.find(
            {"_id": {"$in": donor_ids}},
            {"organization_name": 1, "username": 1},
        )
    }

    for item in listings:
        donor = donors.get(item.get("donor_id"))
        item["donor_org_name"] = donor.get("organization_name") if donor else None

    for item in claimed_history:
        donor = donors.get(item.get("donor_id"))
        item["donor_org_name"] = donor.get("organization_name") if donor else None

    mapped_listings = [
        {
            "id": str(item.get("_id")),
            "food_name": item.get("food_name", "Listing"),
            "location": item.get("location", "Unknown"),
            "pickup_address": item.get("pickup_address") or item.get("location", "Unknown"),
            "quantity": item.get("quantity", 0),
            "donation_price": item.get("donation_price", 0),
            "status": item.get("status", "available"),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in listings
        if item.get("latitude") is not None and item.get("longitude") is not None
    ]

    return render_template(
        "ngo/claim_food.html",
        listings=listings,
        mapped_listings=mapped_listings,
        claimed_history=claimed_history,
        filters={"location": location, "category": category, "min_quantity": min_quantity_raw},
    )


@app.post("/ngo/food/<listing_id>/claim")
@login_required
@role_required("ngo")
def ngo_claim_listing(listing_id):
    ngo_id = parse_object_id(session.get("user_id"))
    obj_id = parse_object_id(listing_id)
    if not obj_id:
        flash("Invalid listing id.", "error")
        return redirect(url_for("ngo_claim_food"))

    result = food_col.update_one(
        {"_id": obj_id, "status": "available"},
        {"$set": {"status": "claimed", "claimed_by": ngo_id, "claimed_at": utcnow()}},
    )

    if result.modified_count:
        flash("Food listing claimed successfully.", "success")
    else:
        flash("This listing is no longer available.", "error")

    return redirect(url_for("ngo_claim_food"))


@app.post("/ngo/food/<listing_id>/received")
@login_required
@role_required("ngo")
def ngo_mark_received(listing_id):
    ngo_id = parse_object_id(session.get("user_id"))
    obj_id = parse_object_id(listing_id)
    if not obj_id:
        flash("Invalid listing id.", "error")
        return redirect(url_for("ngo_claim_food"))

    result = food_col.update_one(
        {"_id": obj_id, "claimed_by": ngo_id, "status": "claimed"},
        {"$set": {"status": "collected", "collected_at": utcnow()}},
    )

    if result.modified_count:
        flash("Listing marked as collected/received.", "success")
    else:
        flash("Unable to mark listing as received.", "error")

    return redirect(url_for("ngo_claim_food"))


@app.route("/ngo/settings", methods=["GET", "POST"])
@login_required
@role_required("ngo")
def ngo_settings():
    current_user = get_current_user()
    if not current_user:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "update":
            username = request.form.get("username", "").strip().lower()
            organization_name = request.form.get("organization_name", "").strip()
            location = request.form.get("location", "").strip()
            contact = request.form.get("contact", "").strip()

            if not all([username, organization_name, location, contact]):
                flash("All fields are required.", "error")
                return render_template("ngo/settings.html", current_user=current_user)

            # Check if new username is already taken (if changed)
            if username != current_user.get("username"):
                existing = users_col.find_one({"username": username})
                if existing:
                    flash("Username already taken. Please choose another.", "error")
                    return render_template("ngo/settings.html", current_user=current_user)

            users_col.update_one(
                {"_id": current_user["_id"]},
                {
                    "$set": {
                        "username": username,
                        "organization_name": organization_name,
                        "location": location,
                        "contact": contact,
                    }
                },
            )
            session["username"] = username
            flash("Profile updated successfully.", "success")
            current_user = get_current_user()
            return render_template("ngo/settings.html", current_user=current_user)

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password or not new_password or not confirm_password:
                flash("All password fields are required.", "error")
                return render_template("ngo/settings.html", current_user=current_user)

            if not check_password_hash(current_user.get("password", ""), current_password):
                flash("Current password is incorrect.", "error")
                return render_template("ngo/settings.html", current_user=current_user)

            if new_password != confirm_password:
                flash("New passwords do not match.", "error")
                return render_template("ngo/settings.html", current_user=current_user)

            if len(new_password) < 6:
                flash("New password must be at least 6 characters.", "error")
                return render_template("ngo/settings.html", current_user=current_user)

            users_col.update_one(
                {"_id": current_user["_id"]},
                {"$set": {"password": generate_password_hash(new_password)}},
            )
            flash("Password changed successfully.", "success")
            current_user = get_current_user()
            return render_template("ngo/settings.html", current_user=current_user)

        elif action == "delete":
            ngo_id = current_user["_id"]
            # Unclaim active NGO claims before deleting account.
            food_col.update_many(
                {"claimed_by": ngo_id, "status": "claimed"},
                {
                    "$set": {
                        "status": "available",
                        "claimed_by": None,
                        "claimed_at": None,
                    }
                },
            )
            users_col.delete_one({"_id": current_user["_id"]})
            messages_col.delete_many({"sender_id": current_user["_id"]})
            messages_col.delete_many({"recipient_id": current_user["_id"]})
            session.clear()
            flash("Your account has been deleted.", "success")
            return redirect(url_for("home"))

    return render_template("ngo/settings.html", current_user=current_user)


@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages_page():
    current_user = get_current_user()
    if not current_user:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("login"))

    current_user_id = current_user["_id"]
    current_role = current_user.get("role")
    opposite_role = "ngo" if current_role == "donor" else "donor"

    recipient_options = list(
        users_col.find(
            {"role": opposite_role},
            {"organization_name": 1, "username": 1, "location": 1},
        ).sort("organization_name", ASCENDING)
    )

    default_to = request.args.get("chat_with", "").strip() or request.args.get("to", "").strip()
    if not default_to and recipient_options:
        default_to = str(recipient_options[0]["_id"])

    if request.method == "POST":
        recipient_id = parse_object_id(request.form.get("recipient_id", "").strip())
        listing_id = parse_object_id(request.form.get("listing_id", "").strip())
        message_text = request.form.get("message", "").strip()

        if not recipient_id or not message_text:
            flash("Recipient and message are required.", "error")
            return redirect(url_for("messages_page", chat_with=default_to))

        if len(message_text) > 1000:
            flash("Message is too long. Keep it under 1000 characters.", "error")
            return redirect(url_for("messages_page", chat_with=default_to))

        recipient = users_col.find_one({"_id": recipient_id})
        if not recipient:
            flash("Recipient not found.", "error")
            return redirect(url_for("messages_page", chat_with=default_to))

        if recipient.get("role") != opposite_role:
            flash("You can only message users from the other role.", "error")
            return redirect(url_for("messages_page", chat_with=default_to))

        message_doc = {
            "sender_id": current_user_id,
            "recipient_id": recipient_id,
            "sender_role": current_role,
            "recipient_role": recipient.get("role"),
            "listing_id": listing_id,
            "message": message_text,
            "is_read": False,
            "created_at": utcnow(),
        }
        messages_col.insert_one(message_doc)
        return redirect(url_for("messages_page", chat_with=str(recipient_id)))

    to_prefill = default_to
    listing_prefill = request.args.get("listing_id", "").strip()

    selected_recipient_id = parse_object_id(to_prefill)
    selected_recipient = None
    if selected_recipient_id:
        selected_recipient = users_col.find_one(
            {"_id": selected_recipient_id, "role": opposite_role},
            {"organization_name": 1, "username": 1, "location": 1, "contact": 1, "role": 1},
        )
    if not selected_recipient:
        selected_recipient_id = None

    listing_options_query = {}
    if current_role == "donor":
        listing_options_query = {"donor_id": current_user_id}
    elif current_role == "ngo":
        listing_options_query = {"claimed_by": current_user_id}

    listing_options = list(
        food_col.find(listing_options_query, {"food_name": 1, "status": 1, "location": 1, "created_at": 1}).sort(
            "created_at", DESCENDING
        )
    )

    conversation_query = {"_id": {"$in": []}}
    if selected_recipient_id:
        conversation_query = {
            "$or": [
                {"sender_id": current_user_id, "recipient_id": selected_recipient_id},
                {"sender_id": selected_recipient_id, "recipient_id": current_user_id},
            ]
        }

    conversation_messages = list(messages_col.find(conversation_query).sort("created_at", ASCENDING).limit(200))

    if selected_recipient_id:
        messages_col.update_many(
            {"sender_id": selected_recipient_id, "recipient_id": current_user_id, "is_read": False},
            {"$set": {"is_read": True}},
        )

    user_ids = {current_user_id, selected_recipient_id} if selected_recipient_id else {current_user_id}
    listing_ids = set()
    for msg in conversation_messages:
        sender_id = msg.get("sender_id")
        recipient_id = msg.get("recipient_id")
        listing_id = msg.get("listing_id")
        if sender_id:
            user_ids.add(sender_id)
        if recipient_id:
            user_ids.add(recipient_id)
        if listing_id:
            listing_ids.add(listing_id)

    users_map = {
        user["_id"]: user
        for user in users_col.find(
            {"_id": {"$in": list(user_ids)}},
            {"organization_name": 1, "username": 1, "role": 1},
        )
    }
    listings_map = {
        listing["_id"]: listing
        for listing in food_col.find({"_id": {"$in": list(listing_ids)}}, {"food_name": 1, "location": 1})
    }

    def enrich_messages(messages):
        for msg in messages:
            sender = users_map.get(msg.get("sender_id"), {})
            recipient = users_map.get(msg.get("recipient_id"), {})
            listing = listings_map.get(msg.get("listing_id"), {})
            msg["sender_name"] = sender.get("organization_name") or sender.get("username", "Unknown")
            msg["recipient_name"] = recipient.get("organization_name") or recipient.get("username", "Unknown")
            msg["sender_role"] = sender.get("role", msg.get("sender_role", ""))
            msg["recipient_role"] = recipient.get("role", msg.get("recipient_role", ""))
            msg["listing_name"] = listing.get("food_name")
            msg["listing_location"] = listing.get("location")
            msg["is_mine"] = msg.get("sender_id") == current_user_id

    enrich_messages(conversation_messages)

    recipient_unread = {
        msg.get("sender_id"): msg.get("count")
        for msg in messages_col.aggregate(
            [
                {"$match": {"recipient_id": current_user_id, "is_read": False}},
                {"$group": {"_id": "$sender_id", "count": {"$sum": 1}}},
            ]
        )
    }

    for recipient in recipient_options:
        recipient["unread_count"] = recipient_unread.get(recipient.get("_id"), 0)

    return render_template(
        "messages/messages.html",
        recipient_options=recipient_options,
        selected_recipient=selected_recipient,
        selected_recipient_id=str(selected_recipient_id) if selected_recipient_id else "",
        conversation_messages=conversation_messages,
        listing_options=listing_options,
        to_prefill=to_prefill,
        listing_prefill=listing_prefill,
        opposite_role=opposite_role,
    )


@app.route("/chatbot", methods=["GET", "POST"])
@login_required
def chatbot_page():
    history = []

    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if not question:
            flash("Please enter a question.", "error")
            return redirect(url_for("chatbot_page"))

        if len(question) > 1000:
            flash("Question is too long. Keep it under 1000 characters.", "error")
            return redirect(url_for("chatbot_page"))

        user_context = get_chatbot_user_context()
        answer, success = ask_project_chatbot(question, user_context=user_context)
        if not success:
            flash("Chatbot API issue detected. Auto-rotation attempted all keys.", "error")

        history = [{"question": question, "answer": answer, "asked_at": utcnow()}]
        return render_template("chatbot/chatbot.html", history=history)

    session.pop("chatbot_history", None)
    return render_template("chatbot/chatbot.html", history=history)


@app.post("/api/chatbot")
def chatbot_api():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()

    if not question:
        return jsonify({"ok": False, "answer": "Please ask a question."}), 400

    if len(question) > 1000:
        return jsonify({"ok": False, "answer": "Question is too long. Keep it under 1000 characters."}), 400

    user_context = get_chatbot_user_context()
    answer, success = ask_project_chatbot(question, user_context=user_context)
    return jsonify({"ok": success, "answer": answer})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
