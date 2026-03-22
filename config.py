import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE",
        "true" if os.getenv("VERCEL") else "false",
    ).lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600

    # Support either a full MONGO_URI or split Atlas/local Mongo variables.
    _mongo_uri = os.getenv("MONGO_URI")
    _mongo_username = os.getenv("MONGO_USERNAME")
    _mongo_password = os.getenv("MONGO_PASSWORD")
    _mongo_cluster = os.getenv("MONGO_CLUSTER")

    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME") or os.getenv("MONGO_DATABASE", "foodwaste_db")

    if _mongo_uri:
        MONGO_URI = _mongo_uri
    elif _mongo_cluster and _mongo_username and _mongo_password:
        encoded_user = quote_plus(_mongo_username)
        encoded_pass = quote_plus(_mongo_password)
        MONGO_URI = (
            f"mongodb+srv://{encoded_user}:{encoded_pass}@{_mongo_cluster}/{MONGO_DB_NAME}"
            "?retryWrites=true&w=majority"
        )
    else:
        MONGO_URI = "mongodb://localhost:27017"

    if os.getenv("VERCEL") and SECRET_KEY == "change-me-in-production":
        raise RuntimeError("SECRET_KEY must be set in production.")
