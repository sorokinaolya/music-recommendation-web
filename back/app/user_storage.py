import json
import sqlite3
from pathlib import Path
from typing import Optional

from app.auth_service import hash_password, verify_password


DB_PATH = Path("app_data.sqlite3")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        create table if not exists users (
            id integer primary key autoincrement,
            username text not null,
            email text not null unique,
            password_hash text not null,
            created_at text not null default current_timestamp
        )
    """)

    cur.execute("""
        create table if not exists user_state (
            user_id integer primary key,
            history_json text not null default '[]',
            favorites_json text not null default '[]',
            disliked_json text not null default '[]',
            updated_at text not null default current_timestamp,
            foreign key(user_id) references users(id)
        )
    """)

    cur.execute("pragma table_info(user_state)")
    columns = [row["name"] for row in cur.fetchall()]

    if "profile_prefs_json" not in columns:
        cur.execute("""
            alter table user_state
            add column profile_prefs_json text not null default '{}'
        """)

    conn.commit()
    conn.close()


def create_user(username: str, email: str, password: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()

    password_hash = hash_password(password)

    cur.execute(
        """
        insert into users (username, email, password_hash)
        values (?, ?, ?)
        """,
        (username, email, password_hash),
    )

    user_id = cur.lastrowid

    cur.execute(
        """
        insert into user_state (user_id, history_json, favorites_json, disliked_json)
        values (?, '[]', '[]', '[]')
        """,
        (user_id,),
    )

    conn.commit()

    user = {
        "id": user_id,
        "username": username,
        "email": email,
    }

    conn.close()
    return user


def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select id, username, email, password_hash
        from users
        where email = ?
        """,
        (email,),
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select id, username, email
        from users
        where id = ?
        """,
        (user_id,),
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)


def authenticate_user(email: str, password: str) -> Optional[dict]:
    user = get_user_by_email(email)

    if not user:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
    }


def get_user_state(user_id: int) -> dict:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select history_json, favorites_json, disliked_json, profile_prefs_json
        from user_state
        where user_id = ?
        """,
        (user_id,),
    )

    row = cur.fetchone()

    if not row:
        cur.execute(
            """
            insert into user_state (user_id, history_json, favorites_json, disliked_json)
            values (?, '[]', '[]', '[]')
            """,
            (user_id,),
        )
        conn.commit()

        state = {
            "history": [],
            "favorites": [],
            "disliked": [],
            "profilePrefs": {},
        }
    else:
        state = {
            "history": json.loads(row["history_json"]),
            "favorites": json.loads(row["favorites_json"]),
            "disliked": json.loads(row["disliked_json"]),
            "profilePrefs": json.loads(row["profile_prefs_json"] or "{}"),
        }

    conn.close()
    return state


def save_user_state(
    user_id: int,
    history: list,
    favorites: list,
    disliked: list,
    profile_prefs: dict,
) -> dict:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        insert into user_state (
            user_id,
            history_json,
            favorites_json,
            disliked_json,
            profile_prefs_json,
            updated_at
        )
        values (?, ?, ?, ?, ?, current_timestamp)
        on conflict(user_id) do update set
            history_json = excluded.history_json,
            favorites_json = excluded.favorites_json,
            disliked_json = excluded.disliked_json,
            profile_prefs_json = excluded.profile_prefs_json,
            updated_at = current_timestamp
        """,
        (
            user_id,
            json.dumps(history, ensure_ascii=False),
            json.dumps(favorites, ensure_ascii=False),
            json.dumps(disliked, ensure_ascii=False),
            json.dumps(profile_prefs, ensure_ascii=False),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "history": history,
        "favorites": favorites,
        "disliked": disliked,
        "profilePrefs": profile_prefs,
    }