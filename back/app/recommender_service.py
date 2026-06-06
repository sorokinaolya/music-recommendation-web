from pathlib import Path
import pickle
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.sparse import load_npz
from implicit.cpu.als import AlternatingLeastSquares


class RecommenderService:
    def __init__(self, artifacts_dir: str = "artifacts"):
        self.artifacts_dir = Path(artifacts_dir)
        self.loaded = False
        self.load_artifacts()

    def _filter_by_genres_if_possible(self, candidate_codes, genres):
        if not genres:
            return candidate_codes

        genre_scores = self._calculate_genre_scores(candidate_codes, genres)
        strict_candidate_codes = candidate_codes[genre_scores >= 1.0]

        if len(strict_candidate_codes) > 0:
            return strict_candidate_codes

        return candidate_codes
    
    def _deduplicate_and_limit_tracks(self, tracks, limit=10, max_per_artist=2):
        limit = max(1, min(int(limit), 10))

        result = []
        seen_track_ids = set()
        seen_title_artist = set()
        artist_counts = {}

        for track in tracks:
            track_id = str(track.get("track_id") or track.get("id") or "").strip().lower()
            title = str(track.get("title") or track.get("name") or "").strip().lower()
            artist = str(track.get("artist") or "").strip().lower()

            title_artist_key = f"{title}::{artist}"

            if track_id and track_id in seen_track_ids:
                continue

            if title_artist_key in seen_title_artist:
                continue

            if artist_counts.get(artist, 0) >= max_per_artist:
                continue

            result.append(track)

            if track_id:
                seen_track_ids.add(track_id)

            seen_title_artist.add(title_artist_key)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1

            if len(result) >= limit:
                break

        return result

    def _select_with_artist_limit(self, candidate_codes, scores, limit=10, max_per_artist=2):
        order = np.argsort(-scores)

        selected = []
        artist_counts = {}

        for idx in order:
            code = int(candidate_codes[idx])

            artist = ""
            if self.track_artist_array is not None and code < len(self.track_artist_array):
                artist = str(self.track_artist_array[code]).strip().lower()

            if not artist:
                artist = "unknown"

            if artist_counts.get(artist, 0) >= max_per_artist:
                continue

            selected.append(idx)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1

            if len(selected) >= limit:
                break

        return np.asarray(selected, dtype=np.int64)
    
    def _has_mood(self, mood):
        return mood is not None and str(mood).strip() not in ["", "any", "none", "null"]

    def _find_file(self, filename: str) -> Path:
        matches = list(self.artifacts_dir.rglob(filename))
        if not matches:
            raise FileNotFoundError(f"Не найден файл: {filename} в {self.artifacts_dir}")
        return matches[0]

    def load_artifacts(self):
        self.model = AlternatingLeastSquares.load(str(self._find_file("best_tpe_als_model.npz")))

        self.user_mapping = pd.read_parquet(self._find_file("user_mapping.parquet"))
        self.track_mapping = pd.read_parquet(self._find_file("track_mapping.parquet"))
        self.track_features = pd.read_parquet(self._find_file("track_features_filtered.parquet"))

        self.train_user_items = load_npz(self._find_file("train_user_items.npz"))
        self.track_tag_matrix = load_npz(self._find_file("track_tag_matrix_binary.npz"))

        item_play_sum = np.asarray(self.train_user_items.sum(axis=0)).ravel()
        item_user_count = np.asarray((self.train_user_items > 0).sum(axis=0)).ravel()

        play_sum_norm = self._normalize(np.log1p(item_play_sum))
        user_count_norm = self._normalize(np.log1p(item_user_count))

        self.item_popularity = (
            0.4 * play_sum_norm
            + 0.6 * user_count_norm
        )

        self.item_popularity_norm = self._normalize(self.item_popularity)


        self.track_id_to_track_code = dict(
            zip(self.track_mapping["track_id"], self.track_mapping["track_code"])
        )

        self.track_artist_array = np.load(self._find_file("track_artist_array.npy"), allow_pickle=True)
        self.track_genre_array = np.load(self._find_file("track_genre_array.npy"), allow_pickle=True)

        self.valence_array = np.load(self._find_file("valence_array.npy"), allow_pickle=True)
        self.energy_array = np.load(self._find_file("energy_array.npy"), allow_pickle=True)
        self.danceability_array = np.load(self._find_file("danceability_array.npy"), allow_pickle=True)
        self.acousticness_array = np.load(self._find_file("acousticness_array.npy"), allow_pickle=True)

        with open(self._find_file("objects.pkl"), "rb") as f:
            self.objects = pickle.load(f)

        self.tag_to_id = self.objects.get("tag_to_id", {})
        self.id_to_tag = self.objects.get("id_to_tag", {})
        self.mood_targets = self.objects.get("mood_targets", {})

        self.track_code_to_track_id = dict(
            zip(self.track_mapping["track_code"], self.track_mapping["track_id"])
        )

        self.track_features_by_id = self.track_features.set_index("track_id", drop=False)

        self.loaded = True

        

    def debug_info(self):
        return {
            "loaded": self.loaded,
            "artifacts_dir": str(self.artifacts_dir),
            "info": {
                "user_mapping_shape": self.user_mapping.shape,
                "track_mapping_shape": self.track_mapping.shape,
                "track_features_shape": self.track_features.shape,
                "train_user_items_shape": self.train_user_items.shape,
                "track_tag_matrix_shape": self.track_tag_matrix.shape,
                "model_user_factors_shape": self.model.user_factors.shape,
                "model_item_factors_shape": self.model.item_factors.shape,
                "objects_keys": list(self.objects.keys()),
                "track_features_columns": list(self.track_features.columns),
            },
        }

    @staticmethod
    def _normalize(values):
        values = np.asarray(values, dtype=np.float64)
        if len(values) == 0:
            return values

        min_v = np.nanmin(values)
        max_v = np.nanmax(values)

        if np.isclose(max_v, min_v):
            return np.ones_like(values) * 0.5

        return (values - min_v) / (max_v - min_v)

    def _get_mood_target(self, mood: str):
        defaults = {
            "happy": {
                "valence": 0.85,
                "energy": 0.75,
                "danceability": 0.65,
                "acousticness": 0.25,
            },
            "sad": {
                "valence": 0.25,
                "energy": 0.35,
                "danceability": 0.35,
                "acousticness": 0.55,
            },
            "energetic": {
                "valence": 0.65,
                "energy": 0.9,
                "danceability": 0.75,
                "acousticness": 0.2,
            },
            "calm": {
                "valence": 0.55,
                "energy": 0.25,
                "danceability": 0.35,
                "acousticness": 0.75,
            },
            "romantic": {
                "valence": 0.7,
                "energy": 0.45,
                "danceability": 0.5,
                "acousticness": 0.55,
            },
            "focused": {
                "valence": 0.5,
                "energy": 0.45,
                "danceability": 0.35,
                "acousticness": 0.5,
            },
            "angry": {
                "valence": 0.35,
                "energy": 0.9,
                "danceability": 0.55,
                "acousticness": 0.15,
            },
            "nostalgic": {
                "valence": 0.55,
                "energy": 0.45,
                "danceability": 0.45,
                "acousticness": 0.6,
            },
        }

        target = self.mood_targets.get(mood, None)

        if isinstance(target, dict):
            parsed = {}
            for feature in ["valence", "energy", "danceability", "acousticness"]:
                if feature in target:
                    parsed[feature] = float(target[feature])
                elif f"{feature}_target" in target:
                    parsed[feature] = float(target[f"{feature}_target"])
                elif f"{feature}_min" in target and f"{feature}_max" in target:
                    parsed[feature] = (
                        float(target[f"{feature}_min"]) + float(target[f"{feature}_max"])
                    ) / 2
                elif f"{feature}_min" in target:
                    parsed[feature] = float(target[f"{feature}_min"])

            if parsed:
                return parsed

        return defaults.get(mood, defaults["happy"])

    def _calculate_mood_scores(self, candidate_codes, mood: str):
        if not self._has_mood(mood):
            return np.ones(len(candidate_codes), dtype=np.float64) * 0.5
            
        target = self._get_mood_target(mood)

        scores = []

        for code in candidate_codes:
            feature_scores = []

            values = {
                "valence": float(self.valence_array[code]),
                "energy": float(self.energy_array[code]),
                "danceability": float(self.danceability_array[code]),
                "acousticness": float(self.acousticness_array[code]),
            }

            for feature, target_value in target.items():
                value = values.get(feature)
                if value is None or np.isnan(value):
                    continue

                diff = abs(value - target_value)
                feature_score = max(0.0, 1.0 - diff)
                feature_scores.append(feature_score)

            if feature_scores:
                scores.append(float(np.mean(feature_scores)))
            else:
                scores.append(0.5)

        return np.asarray(scores, dtype=np.float64)

    def _get_user_tag_profile(self, user_code: int):
        user_row = self.train_user_items[user_code].tocoo()

        if len(user_row.col) == 0:
            return np.zeros(self.track_tag_matrix.shape[1], dtype=np.float64)

        item_codes = user_row.col
        weights = user_row.data.astype(np.float64)

        user_tags = self.track_tag_matrix[item_codes].multiply(weights[:, None]).sum(axis=0)
        user_tags = np.asarray(user_tags).ravel()

        total = user_tags.sum()
        if total > 0:
            user_tags = user_tags / total

        return user_tags

    def _calculate_tag_scores(self, candidate_codes, user_code: int):
        user_tag_profile = self._get_user_tag_profile(user_code)

        if user_tag_profile.sum() == 0:
            return np.zeros(len(candidate_codes), dtype=np.float64), []

        scores = self.track_tag_matrix[candidate_codes].dot(user_tag_profile)
        scores = np.asarray(scores).ravel()

        top_tag_ids = np.argsort(user_tag_profile)[::-1][:5]
        top_tags = []

        for tag_id in top_tag_ids:
            if user_tag_profile[tag_id] <= 0:
                continue

            tag = self.id_to_tag.get(int(tag_id), self.id_to_tag.get(str(tag_id), None))
            if tag is not None:
                top_tags.append(str(tag))

        return scores, top_tags

    def _apply_genre_bonus(self, candidate_codes, genres):
        if not genres:
            return np.ones(len(candidate_codes), dtype=np.float64)

        selected = {g.strip().lower() for g in genres if g.strip()}
        bonuses = []

        for code in candidate_codes:
            genre = ""

            if self.track_genre_array is not None and code < len(self.track_genre_array):
                genre = str(self.track_genre_array[code]).lower()

            match = any(g in genre or genre in g for g in selected)
            bonuses.append(1.10 if match else 1.0)

        return np.asarray(bonuses, dtype=np.float64)

    def _diversify_by_artist(self, candidate_codes, final_scores, limit: int):
        order = np.argsort(final_scores)[::-1]

        result = []
        artist_count = defaultdict(int)

        for idx in order:
            code = int(candidate_codes[idx])
            artist = str(self.track_artist_array[code])

            if artist_count[artist] >= 2:
                continue

            result.append(idx)
            artist_count[artist] += 1

            if len(result) >= limit:
                break

        if len(result) < limit:
            for idx in order:
                if idx not in result:
                    result.append(idx)
                if len(result) >= limit:
                    break

        return result

    @staticmethod
    def _format_duration(duration_ms):
        try:
            if pd.isna(duration_ms):
                return "—"
            total_sec = int(float(duration_ms) / 1000)
            minutes = total_sec // 60
            seconds = total_sec % 60
            return f"{minutes}:{seconds:02d}"
        except Exception:
            return "—"

    def _format_track(self, track_code, score, match, mood, top_tags):
        track_code = int(track_code)
        track_id = self.track_code_to_track_id.get(track_code)

        if track_id in self.track_features_by_id.index:
            row = self.track_features_by_id.loc[track_id]
        else:
            row = self.track_features.iloc[track_code]

        name = row.get("name", "Unknown track")
        artist = row.get("artist", "Unknown artist")
        genre = row.get("genre_filled", row.get("genre_clean", "Unknown"))

        spotify_id = row.get("spotify_id", None)
        preview_url = row.get("spotify_preview_url", None)
        duration = self._format_duration(row.get("duration_ms", None))

        valence = float(row.get("valence", self.valence_array[track_code]))
        energy = float(row.get("energy", self.energy_array[track_code]))
        danceability = float(row.get("danceability", self.danceability_array[track_code]))

        tag_part = ", ".join(top_tags[:3]) if top_tags else "ваши музыкальные предпочтения"

        return {
            "track_id": str(track_id),
            "id": str(track_id),
            "name": str(name),
            "title": str(name),
            "artist": str(artist),
            "genre": str(genre),
            "spotify_id": None if pd.isna(spotify_id) else str(spotify_id),
            "spotify_preview_url": None if pd.isna(preview_url) else str(preview_url),
            "preview_url": None if pd.isna(preview_url) else str(preview_url),
            "valence": round(valence, 3),
            "energy": round(energy, 3),
            "danceability": round(danceability, 3),
            "score": round(float(score), 4),
            "match": int(match),
            "duration": duration,
            "reason": f"Подходит под настроение {mood} и похож на ваши теги: {tag_part}",
        }

    def recommend(self, user_code: int = 0, mood: str = "happy", genres=None, limit: int = 10):
        if genres is None:
            genres = []

        if user_code < 0 or user_code >= self.train_user_items.shape[0]:
            user_code = 0

        candidate_count = max(500, limit * 50)

        candidate_codes, als_scores = self.model.recommend(
            userid=user_code,
            user_items=self.train_user_items[user_code],
            N=candidate_count,
            filter_already_liked_items=True,
        )

        candidate_codes = np.asarray(candidate_codes, dtype=np.int64)
        als_scores = np.asarray(als_scores, dtype=np.float64)

        als_score_norm = self._normalize(als_scores)
        mood_scores = self._calculate_mood_scores(candidate_codes, mood)
        tag_scores, top_tags = self._calculate_tag_scores(candidate_codes, user_code)
        tag_score_norm = self._normalize(tag_scores)
        genre_bonus = self._apply_genre_bonus(candidate_codes, genres)

        final_scores = (
            0.65 * als_score_norm
            + 0.20 * mood_scores
            + 0.15 * tag_score_norm
        ) * genre_bonus

        selected_indices = self._diversify_by_artist(
            candidate_codes=candidate_codes,
            final_scores=final_scores,
            limit=limit,
        )

        tracks = []

        for idx in selected_indices:
            code = candidate_codes[idx]
            score = final_scores[idx]
            match = round(score * 100)

            tracks.append(
                self._format_track(
                    track_code=code,
                    score=score,
                    match=match,
                    mood=mood,
                    top_tags=top_tags,
                )
            )

        return tracks

    def _calculate_genre_scores(self, candidate_codes, genres):
        if not genres:
            return np.ones(len(candidate_codes), dtype=np.float64) * 0.5

        selected = {g.strip().lower() for g in genres if g.strip()}
        scores = []

        for code in candidate_codes:
            genre = ""

            if self.track_genre_array is not None and code < len(self.track_genre_array):
                genre = str(self.track_genre_array[code]).lower()

            match = any(g in genre or genre in g for g in selected)
            scores.append(1.0 if match else 0.15)

        return np.asarray(scores, dtype=np.float64)

    def _calculate_preview_bonus(self, candidate_codes):
        bonuses = []

        for code in candidate_codes:
            track_id = self.track_code_to_track_id.get(int(code))

            if track_id in self.track_features_by_id.index:
                row = self.track_features_by_id.loc[track_id]
                preview_url = row.get("spotify_preview_url", None)
                bonuses.append(
                    1.0
                    if not pd.isna(preview_url) and str(preview_url).strip()
                    else 0.0
                )
            else:
                bonuses.append(0.0)

        return np.asarray(bonuses, dtype=np.float64)

    def _filter_excluded_codes(self, candidate_codes, excluded_codes):
        if len(excluded_codes) == 0:
            return candidate_codes

        excluded_set = set(map(int, excluded_codes))
        return np.asarray(
            [c for c in candidate_codes if int(c) not in excluded_set],
            dtype=np.int64,
        )

    def _format_track_with_reason(self, track_code, score, match, reason):
        track = self._format_track(
            track_code=track_code,
            score=score,
            match=match,
            mood="",
            top_tags=[],
        )

        track["reason"] = reason
        return track

    def _codes_from_track_ids(self, track_ids):
        codes = []

        if not track_ids:
            return np.asarray(codes, dtype=np.int64)

        for track_id in track_ids:
            track_id = str(track_id)
            if track_id in self.track_id_to_track_code:
                codes.append(int(self.track_id_to_track_code[track_id]))

        return np.asarray(codes, dtype=np.int64)

    def recommend_cold_start(
        self,
        mood: str = "happy",
        genres=None,
        limit: int = 10,
        exclude_track_ids=None,
    ):
        if genres is None:
            genres = []

        if exclude_track_ids is None:
            exclude_track_ids = []

        all_codes = np.arange(self.train_user_items.shape[1], dtype=np.int64)

        excluded_codes = self._codes_from_track_ids(exclude_track_ids)
        candidate_codes = self._filter_excluded_codes(all_codes, excluded_codes)
        candidate_codes = self._filter_by_genres_if_possible(candidate_codes, genres)

        if genres:
            genre_scores_for_filter = self._calculate_genre_scores(candidate_codes, genres)
            strict_candidate_codes = candidate_codes[genre_scores_for_filter >= 1.0]

            if len(strict_candidate_codes) >= limit:
                candidate_codes = strict_candidate_codes

        mood_scores = self._calculate_mood_scores(candidate_codes, mood)
        genre_scores = self._calculate_genre_scores(candidate_codes, genres)
        preview_bonus = self._calculate_preview_bonus(candidate_codes)
        popularity_scores = self.item_popularity_norm[candidate_codes]

        has_mood = self._has_mood(mood)
        has_genres = bool(genres)

        if has_mood and has_genres:
            final_scores = (
                0.40 * mood_scores
                + 0.30 * genre_scores
                + 0.20 * popularity_scores
                + 0.10 * preview_bonus
            )
        elif has_mood:
            final_scores = (
                0.55 * mood_scores
                + 0.30 * popularity_scores
                + 0.15 * preview_bonus
            )
        elif has_genres:
            final_scores = (
                0.45 * genre_scores
                + 0.40 * popularity_scores
                + 0.15 * preview_bonus
            )
        else:
            final_scores = (
                0.85 * popularity_scores
                + 0.15 * preview_bonus
            )

        selected_indices = self._select_with_artist_limit(
            candidate_codes=candidate_codes,
            scores=final_scores,
            limit=limit,
            max_per_artist=2,
        )

        tracks = []
        genre_text = ", ".join(genres) if genres else "любой жанр"

        for idx in selected_indices:
            code = int(candidate_codes[idx])
            score = float(final_scores[idx])
            match = int(round(score * 100))

            if has_mood and has_genres:
                reason = (
                    f"Рекомендация для нового пользователя: популярный трек выбранного жанра "
                    f"{genre_text}, подходящий под настроение {mood}"
                )
            elif has_mood:
                reason = (
                    f"Рекомендация для нового пользователя: популярный трек, "
                    f"подходящий под настроение {mood}"
                )
            elif has_genres:
                reason = (
                    f"Рекомендация для нового пользователя: популярный трек выбранного жанра "
                    f"{genre_text}"
                )
            else:
                reason = (
                    "Рекомендация для нового пользователя: популярный трек из обучающего датасета"
                )

            tracks.append(
                self._format_track_with_reason(
                    track_code=code,
                    score=score,
                    match=match,
                    reason=reason,
                )
            )

        return self._deduplicate_and_limit_tracks(
            tracks,
            limit=limit,
            max_per_artist=2,
        )

    def _build_session_profile(self, favorite_codes, listened_codes):
        profile = {}

        for code in listened_codes:
            code = int(code)
            profile[code] = profile.get(code, 0.0) + 1.0

        for code in favorite_codes:
            code = int(code)
            profile[code] = profile.get(code, 0.0) + 5.0

        if not profile:
            return None

        profile_codes = np.asarray(list(profile.keys()), dtype=np.int64)
        weights = np.asarray(list(profile.values()), dtype=np.float64)

        return profile_codes, weights

    def _calculate_item_similarity_scores(self, candidate_codes, profile_codes, weights):
        item_factors = self.model.item_factors

        profile_vectors = item_factors[profile_codes]
        weighted_profile = np.average(profile_vectors, axis=0, weights=weights)

        profile_norm = np.linalg.norm(weighted_profile)
        if profile_norm == 0:
            return np.zeros(len(candidate_codes), dtype=np.float64)

        candidate_vectors = item_factors[candidate_codes]
        candidate_norms = np.linalg.norm(candidate_vectors, axis=1)
        candidate_norms[candidate_norms == 0] = 1e-9

        similarities = candidate_vectors @ weighted_profile / (candidate_norms * profile_norm)

        return self._normalize(similarities)

    def _calculate_profile_tag_scores(self, candidate_codes, profile_codes, weights):
        if len(profile_codes) == 0:
            return np.zeros(len(candidate_codes), dtype=np.float64), []

        profile_tags = self.track_tag_matrix[profile_codes].multiply(weights[:, None]).sum(axis=0)
        profile_tags = np.asarray(profile_tags).ravel()

        total = profile_tags.sum()
        if total <= 0:
            return np.zeros(len(candidate_codes), dtype=np.float64), []

        profile_tags = profile_tags / total

        tag_scores = self.track_tag_matrix[candidate_codes].dot(profile_tags)
        tag_scores = np.asarray(tag_scores).ravel()
        tag_scores = self._normalize(tag_scores)

        top_tag_ids = np.argsort(profile_tags)[::-1][:5]
        top_tags = []

        for tag_id in top_tag_ids:
            if profile_tags[tag_id] <= 0:
                continue

            tag = self.id_to_tag.get(int(tag_id), self.id_to_tag.get(str(tag_id), None))
            if tag is not None:
                top_tags.append(str(tag))

        return tag_scores, top_tags

    def recommend_session_personalized(
        self,
        mood: str = "",
        genres=None,
        favorite_track_ids=None,
        listened_track_ids=None,
        disliked_track_ids=None,
        limit: int = 10,
    ):
        if genres is None:
            genres = []

        favorite_track_ids = favorite_track_ids or []
        listened_track_ids = listened_track_ids or []
        disliked_track_ids = disliked_track_ids or []

        favorite_codes = self._codes_from_track_ids(favorite_track_ids)
        listened_codes = self._codes_from_track_ids(listened_track_ids)
        disliked_codes = self._codes_from_track_ids(disliked_track_ids)

        profile = self._build_session_profile(
            favorite_codes=favorite_codes,
            listened_codes=listened_codes,
        )

        exclude_track_ids = list(set(
            favorite_track_ids
            + listened_track_ids
            + disliked_track_ids
        ))

        if profile is None:
            return self.recommend_cold_start(
                mood=mood,
                genres=genres,
                limit=limit,
                exclude_track_ids=exclude_track_ids,
            )

        profile_codes, weights = profile

        all_codes = np.arange(self.train_user_items.shape[1], dtype=np.int64)

        excluded_codes = self._codes_from_track_ids(exclude_track_ids)
        candidate_codes = self._filter_excluded_codes(all_codes, excluded_codes)
        candidate_codes = self._filter_by_genres_if_possible(candidate_codes, genres)

        item_similarity_scores = self._calculate_item_similarity_scores(
            candidate_codes=candidate_codes,
            profile_codes=profile_codes,
            weights=weights,
        )

        tag_scores, top_tags = self._calculate_profile_tag_scores(
            candidate_codes=candidate_codes,
            profile_codes=profile_codes,
            weights=weights,
        )

        if len(disliked_codes) > 0:
            dislike_weights = np.ones(len(disliked_codes), dtype=np.float64)

            dislike_similarity_scores = self._calculate_item_similarity_scores(
                candidate_codes=candidate_codes,
                profile_codes=disliked_codes,
                weights=dislike_weights,
            )
        else:
            dislike_similarity_scores = np.zeros(len(candidate_codes), dtype=np.float64)

        mood_scores = self._calculate_mood_scores(candidate_codes, mood)
        genre_scores = self._calculate_genre_scores(candidate_codes, genres)
        popularity_scores = self.item_popularity_norm[candidate_codes]
        preview_bonus = self._calculate_preview_bonus(candidate_codes)

        positive_weight_sum = float(np.sum(weights))
        feedback_strength = min(1.0, positive_weight_sum / 25.0)

        has_mood = self._has_mood(mood)
        has_genres = bool(genres)

        if has_mood:
            als_weight = 0.25 + 0.15 * feedback_strength
            tag_weight = 0.15 + 0.05 * feedback_strength
            mood_weight = 0.35
            genre_weight = 0.15 if has_genres else 0.0
            popularity_weight = 0.10 * (1.0 - feedback_strength)
            preview_weight = 0.05
        else:
            als_weight = 0.45 + 0.15 * feedback_strength
            tag_weight = 0.25
            mood_weight = 0.0
            genre_weight = 0.15 if has_genres else 0.0
            popularity_weight = 0.10 * (1.0 - feedback_strength)
            preview_weight = 0.05

        weight_sum = (
            als_weight
            + tag_weight
            + mood_weight
            + genre_weight
            + popularity_weight
            + preview_weight
        )

        als_weight /= weight_sum
        tag_weight /= weight_sum
        mood_weight /= weight_sum
        genre_weight /= weight_sum
        popularity_weight /= weight_sum
        preview_weight /= weight_sum

        final_scores = (
            als_weight * item_similarity_scores
            + tag_weight * tag_scores
            + mood_weight * mood_scores
            + genre_weight * genre_scores
            + popularity_weight * popularity_scores
            + preview_weight * preview_bonus
        )

        if len(disliked_codes) > 0:
            final_scores = final_scores - 0.12 * dislike_similarity_scores

        final_scores = np.maximum(final_scores, 0.0)

        selected_indices = self._select_with_artist_limit(
            candidate_codes=candidate_codes,
            scores=final_scores,
            limit=limit,
            max_per_artist=2,
        )

        tracks = []

        tag_text = ", ".join(top_tags[:3]) if top_tags else "ваши прослушивания и лайки"
        genre_text = ", ".join(genres) if genres else "любой жанр"

        for idx in selected_indices:
            code = int(candidate_codes[idx])
            score = float(final_scores[idx])
            match = int(round(score * 100))

            mood_text = f"настроение: {mood}; " if has_mood else ""
            genre_text = f"жанр: {', '.join(genres)}; " if has_genres else ""

            if has_genres:
                reason = (
                    f"Рекомендовано с учётом вашей истории и избранного. "
                    f"{mood_text}{genre_text}"
                    f"Система подбирает треки внутри выбранного жанра, учитывая ваши прошлые предпочтения"
                )
            else:
                tag_text = ", ".join(top_tags[:3]) if top_tags else "ваши прослушивания и избранное"

                reason = (
                    f"Рекомендовано на основе вашей истории и избранного. "
                    f"{mood_text}"
                    f"Похоже на ваши теги: {tag_text}"
                )

            tracks.append(
                self._format_track_with_reason(
                    track_code=code,
                    score=score,
                    match=match,
                    reason=reason,
                )
            )

        return self._deduplicate_and_limit_tracks(
            tracks,
            limit=limit,
            max_per_artist=2,
        )