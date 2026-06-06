from fastapi.middleware.cors import CORSMiddleware

from app.recommender_service import RecommenderService
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth_service import create_access_token, decode_access_token
from app.user_storage import (
    init_db,
    create_user,
    authenticate_user,
    get_user_by_id,
    get_user_state,
    save_user_state,
)

class RecommendationRequest(BaseModel):
    mood: str = ""
    genres: List[str] = Field(default_factory=list)
    favorite_track_ids: List[str] = Field(default_factory=list)
    listened_track_ids: List[str] = Field(default_factory=list)
    disliked_track_ids: List[str] = Field(default_factory=list)
    limit: int = 10

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserStateRequest(BaseModel):
    history: List[dict] = Field(default_factory=list)
    favorites: List[dict] = Field(default_factory=list)
    disliked: List[dict] = Field(default_factory=list)
    profilePrefs: dict = Field(default_factory=dict)

app = FastAPI(title="Music Recommendation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
recommender = RecommenderService(artifacts_dir="artifacts")

def get_current_user_from_header(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Необходима авторизация")

    parts = authorization.split()

    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Некорректный токен")

    token = parts[1]
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный токен")

    user_id = int(payload["sub"])
    user = get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    return user

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/recommendations")
def recommendations_post(request: RecommendationRequest):
    limit = max(1, min(int(request.limit), 10))
    has_user_history = bool(
        request.favorite_track_ids
        or request.listened_track_ids
    )

    if has_user_history:
        mode = "session_personalized"
        tracks = recommender.recommend_session_personalized(
            mood=request.mood,
            genres=request.genres,
            favorite_track_ids=request.favorite_track_ids,
            listened_track_ids=request.listened_track_ids,
            disliked_track_ids=request.disliked_track_ids,
            limit=limit,
        )
    else:
        mode = "cold_start"
        tracks = recommender.recommend_cold_start(
            mood=request.mood,
            genres=request.genres,
            limit=limit,
            exclude_track_ids=request.disliked_track_ids,
        )

    return {
        "mode": mode,
        "mood": request.mood,
        "genres": request.genres,
        "count": len(tracks),
        "tracks": tracks,
    }

@app.post("/api/auth/register")
def register(request: RegisterRequest):
    try:
        user = create_user(
            username=request.username,
            email=request.email,
            password=request.password,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    token = create_access_token(user_id=user["id"], email=user["email"])

    return {
        "token": token,
        "user": user,
    }


@app.post("/api/auth/login")
def login(request: LoginRequest):
    user = authenticate_user(
        email=request.email,
        password=request.password,
    )

    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    token = create_access_token(user_id=user["id"], email=user["email"])

    return {
        "token": token,
        "user": user,
    }


@app.get("/api/auth/me")
def me(authorization: Optional[str] = Header(default=None)):
    user = get_current_user_from_header(authorization)

    return {
        "user": user,
    }

@app.get("/api/user/state")
def load_state(authorization: Optional[str] = Header(default=None)):
    user = get_current_user_from_header(authorization)
    state = get_user_state(user["id"])

    return state


@app.post("/api/user/state")
def save_state(
    request: UserStateRequest,
    authorization: Optional[str] = Header(default=None),
):
    user = get_current_user_from_header(authorization)

    state = save_user_state(
        user_id=user["id"],
        history=request.history,
        favorites=request.favorites,
        disliked=request.disliked,
        profile_prefs=request.profilePrefs,
    )

    return state
