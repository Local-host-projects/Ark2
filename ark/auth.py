"""Authentication for ARK: register, login, token sessions."""
import hashlib
import hmac
import os
import secrets

from . import db


def hash_pw(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_pw(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_pw(password, salt), stored)


def create_user(username: str, password: str) -> dict:
    handle = username.replace(" ", "_").lower()
    with db.get_conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO users (username, handle, pw_hash) VALUES (?,?,?)",
                (username, handle, hash_pw(password)),
            )
            uid = cur.lastrowid
        except Exception:
            raise ValueError("That name is already taken.")
    return {"id": uid, "username": username, "handle": handle, "avatar": ""}


def authenticate(username: str, password: str) -> dict | None:
    with db.cursor() as cur:
        row = cur.execute(
            "SELECT * FROM users WHERE username=? OR handle=?", (username, username)
        ).fetchone()
    if not row:
        return None
    if not verify_pw(password, row["pw_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "handle": row["handle"], "avatar": row["avatar"] or ""}


def issue_token(user_id: int) -> str:
    token = secrets.token_hex(24)
    with db.get_conn() as c:
        c.execute("INSERT INTO sessions (token, user_id) VALUES (?,?)", (token, user_id))
    return token


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    with db.cursor() as cur:
        row = cur.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.created_at > datetime('now', '-30 days')",
            (token,),
        ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "handle": row["handle"], "avatar": row["avatar"] or ""}


def revoke_token(token: str):
    with db.get_conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization.strip()
