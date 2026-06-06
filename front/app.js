let currentMood = null;
let selectedGenres = [];
let currentTrack = null;
let currentIndex = -1;
let isPlaying = false;
let currentPlaylist = [];

let favorites = JSON.parse(localStorage.getItem('favorites') || '[]');
let history = JSON.parse(localStorage.getItem('history') || '[]');
let disliked = JSON.parse(localStorage.getItem('disliked') || '[]');

let audioPlayer = new Audio();

let currentUser = JSON.parse(localStorage.getItem('currentUser') || 'null');
let authToken = localStorage.getItem('authToken') || null;
let profilePrefs = JSON.parse(localStorage.getItem('profilePrefs') || '{}');

const API = 'http://localhost:8000/api';

function getAuthHeaders() {
  return authToken
    ? { 'Authorization': `Bearer ${authToken}` }
    : {};
}

function getUserDisplayName(user) {
  return user?.username || user?.name || user?.email || 'Пользователь';
}

function mergeTracksById(serverTracks, localTracks) {
  const map = new Map();

  [...serverTracks, ...localTracks].forEach(track => {
    const id = track.id || track.track_id;
    if (id) map.set(id, track);
  });

  return Array.from(map.values());
}

async function loadUserStateFromServer() {
  if (!authToken) return;

  try {
    const res = await fetch(`${API}/user/state`, {
      headers: {
        ...getAuthHeaders()
      }
    });

    if (!res.ok) return;

    const state = await res.json();

    const localHistory = JSON.parse(localStorage.getItem('history') || '[]');
    const localFavorites = JSON.parse(localStorage.getItem('favorites') || '[]');
    const localDisliked = JSON.parse(localStorage.getItem('disliked') || '[]');

    history = mergeTracksById(state.history || [], localHistory);
    favorites = mergeTracksById(state.favorites || [], localFavorites);
    disliked = mergeTracksById(state.disliked || [], localDisliked);

    const localProfilePrefs = JSON.parse(localStorage.getItem('profilePrefs') || '{}');

    profilePrefs = {
      ...localProfilePrefs,
      ...(state.profilePrefs || {})
    };

    localStorage.setItem('history', JSON.stringify(history));
    localStorage.setItem('favorites', JSON.stringify(favorites));
    localStorage.setItem('disliked', JSON.stringify(disliked));
    localStorage.setItem('profilePrefs', JSON.stringify(profilePrefs));

    renderProfileGenres();

    await saveUserStateToServer();
  } catch (e) {
    console.error('Ошибка загрузки состояния пользователя:', e);
  }
}

async function saveUserStateToServer() {
  if (!authToken) return;

  try {
    await fetch(`${API}/user/state`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders()
      },
      body: JSON.stringify({
      history,
      favorites,
      disliked,
      profilePrefs
    })
    });
  } catch (e) {
    console.error('Ошибка сохранения состояния пользователя:', e);
  }
}

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  document.querySelectorAll('.nav-btn').forEach((b, i) => {
    b.classList.toggle('active', b.getAttribute('onclick').includes(name));
  });

  if (name === 'history') renderHistory();
  if (name === 'favorites') renderFavorites();
  if (name === 'profile') renderProfile();
}


function selectMood(el) {
  document.querySelectorAll('.mood-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  currentMood = el.dataset.mood;
  document.getElementById('genreBlock').style.display = 'block';
  document.getElementById('genreBlock').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  document.getElementById('vinylDisc').classList.add('playing');
}


function toggleGenre(el) {
  el.classList.toggle('selected');
  const g = el.dataset.genre;
  if (selectedGenres.includes(g)) {
    selectedGenres = selectedGenres.filter(x => x !== g);
  } else {
    selectedGenres.push(g);
  }
}


async function getRecommendations() {
  const btn = document.querySelector('.btn-get-recs');
  btn.textContent = '⏳ Подбираем...';
  btn.disabled = true;

  try {
    const favoriteTrackIds = favorites
      .map(t => t.id || t.track_id)
      .filter(Boolean);

    const listenedTrackIds = history
      .map(t => t.id || t.track_id)
      .filter(Boolean);

    const dislikedTrackIds = disliked
      .map(t => t.id || t.track_id)
      .filter(Boolean);

    const genresForRequest = selectedGenres.length > 0
      ? selectedGenres
      : (profilePrefs.genres || []);

    const payload = {
      mood: currentMood || "",
      genres: genresForRequest,
      favorite_track_ids: favoriteTrackIds,
      listened_track_ids: listenedTrackIds,
      disliked_track_ids: dislikedTrackIds,
      limit: 10
    };

    const res = await fetch(`${API}/recommendations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка получения рекомендаций');
    }

    currentPlaylist = (data.tracks || []).slice(0, 10);
    renderTracks(currentPlaylist);

    document.getElementById('recsSection').style.display = 'block';
    document.getElementById('recsSection').scrollIntoView({ behavior: 'smooth' });

    const modeText = data.mode === 'session_personalized'
      ? 'персональные рекомендации'
      : 'рекомендации для нового пользователя';

    showToast(`🎵 Найдено ${currentPlaylist.length} треков — ${modeText}`);
  } catch (e) {
    console.error(e);
    showToast('❌ Ошибка соединения с сервером');
  } finally {
    btn.textContent = '🎵 Подобрать музыку';
    btn.disabled = false;
  }
}

function renderProfileGenres() {
  document.querySelectorAll('#profileGenres .genre-chip').forEach(btn => {
    const genre = btn.dataset.genre;
    btn.classList.toggle('selected', (profilePrefs.genres || []).includes(genre));
  });
}

function renderTracks(tracks) {
  const list = document.getElementById('recsList');

  if (!tracks.length) {
    list.innerHTML = '<p style="color:var(--muted);text-align:center;padding:30px">Треки не найдены</p>';
    return;
  }

  list.innerHTML = tracks.map((t, i) => {
    const trackId = t.id || t.track_id;
    const isFavorite = favorites.some(f => (f.id || f.track_id) === trackId);
    const isDisliked = disliked.some(d => (d.id || d.track_id) === trackId);

    return `
      <div class="track-card${currentIndex === i ? ' playing' : ''}" id="track-${i}" onclick="playTrack(${i})">
        <span class="track-num">${currentIndex === i ? '▶' : i + 1}</span>

        <div class="track-cover">${t.emoji || '🎵'}</div>

        <div class="track-info">
          <div class="track-name">${t.title || t.name}</div>
          <div class="track-artist">${t.artist} · ${t.genre || 'Unknown'}</div>
          <div class="track-reason">${t.reason || ''}</div>
        </div>

        <div class="track-meta">
          <span class="track-duration">${t.duration || '—'}</span>

          <div class="track-actions">
            <button
              class="icon-btn favorite-btn ${isFavorite ? 'liked' : ''}"
              onclick="event.stopPropagation(); toggleFavorite(${i})"
              title="В избранное"
            >♡</button>

            <button
              class="icon-btn dislike-btn ${isDisliked ? 'disliked' : ''}"
              onclick="event.stopPropagation(); dislikeTrack(${i})"
              title="Не нравится">
              <span class="broken-heart">♡</span>
            </button>

            <button
              class="icon-btn"
              onclick="event.stopPropagation(); addToQueue(${i})"
              title="Добавить в очередь"
            >+</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}


function playTrack(index) {
  const track = currentPlaylist[index];
  if (!track) return;

  currentIndex = index;
  currentTrack = track;

  document.getElementById('playerBar').style.display = 'flex';
  document.getElementById('playerTrack').textContent = track.title || track.name;
  document.getElementById('playerArtist').textContent = track.artist;
  document.getElementById('playerCover').textContent = track.emoji || '🎵';

  const previewUrl = track.spotify_preview_url || track.preview_url;

  if (previewUrl) {
    audioPlayer.pause();
    audioPlayer.src = previewUrl;
    audioPlayer.volume = document.getElementById('volumeSlider')?.value / 100 || 0.7;

    audioPlayer.play()
      .then(() => {
        isPlaying = true;
        document.getElementById('playBtn').textContent = '⏸';
        document.getElementById('vinylDisc').classList.add('playing');
        showToast('▶️ Воспроизводим preview');
      })
      .catch(() => {
        isPlaying = false;
        document.getElementById('playBtn').textContent = '▶';
        showToast('⚠️ Preview недоступен, показываем metadata');
      });
  } else {
    isPlaying = false;
    document.getElementById('playBtn').textContent = '▶';
    showToast('⚠️ У этого трека нет preview');
  }

  renderTracks(currentPlaylist);
  addToHistory(track);
}

function togglePlay() {
  if (!currentTrack) return;

  const previewUrl = currentTrack.spotify_preview_url || currentTrack.preview_url;

  if (!previewUrl) {
    showToast('⚠️ У этого трека нет preview');
    return;
  }

  if (isPlaying) {
    audioPlayer.pause();
    isPlaying = false;
    document.getElementById('playBtn').textContent = '▶';
    document.getElementById('vinylDisc').classList.remove('playing');
  } else {
    audioPlayer.play()
      .then(() => {
        isPlaying = true;
        document.getElementById('playBtn').textContent = '⏸';
        document.getElementById('vinylDisc').classList.add('playing');
      })
      .catch(() => {
        showToast('⚠️ Preview не удалось запустить');
      });
  }
}

function nextTrack() {
  if (currentPlaylist.length === 0) return;
  const next = (currentIndex + 1) % currentPlaylist.length;
  playTrack(next);
}

function prevTrack() {
  if (currentPlaylist.length === 0) return;
  const prev = (currentIndex - 1 + currentPlaylist.length) % currentPlaylist.length;
  playTrack(prev);
}

function toggleLike() {
  if (!currentTrack) return;
  toggleFavorite(currentIndex);
}


function toggleFavorite(index) {
  const track = currentPlaylist[index];
  if (!track) return;

  const trackId = track.id || track.track_id;

  const favIdx = favorites.findIndex(f => (f.id || f.track_id) === trackId);

  if (favIdx >= 0) {
    favorites.splice(favIdx, 1);
    showToast('💔 Удалено из избранного');
  } else {
    favorites.unshift({ ...track, savedAt: new Date().toISOString() });

    disliked = disliked.filter(d => (d.id || d.track_id) !== trackId);
    localStorage.setItem('disliked', JSON.stringify(disliked));

    showToast('❤️ Добавлено в избранное');
  }

  localStorage.setItem('favorites', JSON.stringify(favorites));
  saveUserStateToServer();
  renderTracks(currentPlaylist);
}

function dislikeTrack(index) {
  const track = currentPlaylist[index];
  if (!track) return;

  const trackId = track.id || track.track_id;
  const dislikedIdx = disliked.findIndex(d => (d.id || d.track_id) === trackId);

  if (dislikedIdx >= 0) {
    disliked.splice(dislikedIdx, 1);
    showToast('💔 Отметка "не нравится" убрана');
  } else {
    disliked.unshift({ ...track, dislikedAt: new Date().toISOString() });

    favorites = favorites.filter(f => (f.id || f.track_id) !== trackId);
    localStorage.setItem('favorites', JSON.stringify(favorites));

    showToast('💔 Учтено: этот трек не нравится');
  }

  disliked = disliked.slice(0, 100);
  localStorage.setItem('disliked', JSON.stringify(disliked));
  saveUserStateToServer();

  renderTracks(currentPlaylist);
}

function renderFavorites() {
  const el = document.getElementById('favoritesList');
  if (!favorites.length) {
    el.innerHTML = '<div class="track-list-empty"><div class="empty-icon">❤️</div><p>Нет избранных треков</p></div>';
    return;
  }

  el.innerHTML = favorites.map((t, i) => `
    <div class="track-card">
      <div class="track-cover">${t.emoji || '🎵'}</div>
      <div class="track-info">
        <div class="track-name">${t.title}</div>
        <div class="track-artist">${t.artist} · ${t.genre || 'Unknown'}</div>
        <div class="track-reason">${t.reason || ''}</div>
      </div>
      <div class="track-meta">
        <span class="track-duration">${t.duration}</span>
        <div class="track-actions">
          <button class="icon-btn liked" onclick="removeFav(${i})">♡</button>
        </div>
      </div>
    </div>
  `).join('');
}

function removeFav(i) {
  favorites.splice(i, 1);
  localStorage.setItem('favorites', JSON.stringify(favorites));
  renderFavorites();
  showToast('💔 Удалено из избранного');
}


function addToHistory(track) {
  const entry = { ...track, listenedAt: new Date().toISOString() };
  history = history.filter(h => h.id !== track.id);
  history.unshift(entry);
  if (history.length > 50) history = history.slice(0, 50);
  localStorage.setItem('history', JSON.stringify(history));

  saveUserStateToServer();
  }


function renderHistory() {
  const el = document.getElementById('historyList');
  if (!history.length) {
    el.innerHTML = '<div class="track-list-empty"><div class="empty-icon">🎧</div><p>История пуста</p></div>';
    return;
  }

  el.innerHTML = history.map((t, i) => `
    <div class="track-card">
      <span class="track-num">${i + 1}</span>
      <div class="track-cover">${t.emoji || '🎵'}</div>
      <div class="track-info">
        <div class="track-name">${t.title}</div>
        <div class="track-artist">${t.artist} · ${t.genre || 'Unknown'}</div>
      </div>
    </div>
  `).join('');

  el.className = '';
}

function clearHistory() {
  if (!confirm('Очистить историю?')) return;
  history = [];
  localStorage.removeItem('history');
  renderHistory();
  showToast('🗑 История очищена');
}


function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) {
    console.error(`Modal ${id} not found`);
    return;
  }

  modal.classList.add('open');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;

  modal.classList.remove('open');
}

async function login() {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');

  if (!email || !password) {
    showError(errEl, 'Заполните все поля');
    return;
  }

  try {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка входа');
    }

    authToken = data.token;
    currentUser = data.user;

    localStorage.setItem('authToken', authToken);
    localStorage.setItem('currentUser', JSON.stringify(currentUser));

    await loadUserStateFromServer();

    setUser(currentUser);
    closeModal('loginModal');
    showToast(`👋 Привет, ${getUserDisplayName(currentUser)}!`);
  } catch (e) {
    showError(errEl, e.message);
  }
}

async function register() {
  const username = document.getElementById('regName').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const password = document.getElementById('regPassword').value;
  const errEl = document.getElementById('regError');

  if (!username || !email || !password) {
    showError(errEl, 'Заполните все поля');
    return;
  }

  if (password.length < 6) {
    showError(errEl, 'Пароль минимум 6 символов');
    return;
  }

  try {
    const res = await fetch(`${API}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка регистрации');
    }

    authToken = data.token;
    currentUser = data.user;

    localStorage.setItem('authToken', authToken);
    localStorage.setItem('currentUser', JSON.stringify(currentUser));

    await loadUserStateFromServer();

    setUser(currentUser);
    closeModal('loginModal');
    showToast(`🎉 Добро пожаловать, ${getUserDisplayName(currentUser)}!`);
  } catch (e) {
    showError(errEl, e.message);
  }
}


function setUser(user) {
  currentUser = user;
  localStorage.setItem('currentUser', JSON.stringify(user));

  document.getElementById('userBlock').style.display = 'flex';
  document.getElementById('userName').textContent = getUserDisplayName(user);
  document.getElementById('loginBtn').style.display = 'none';

  renderProfile();
}

function logout() {
  currentUser = null;
  authToken = null;

  favorites = [];
  history = [];
  disliked = [];
  profilePrefs = {};
  currentPlaylist = [];
  currentTrack = null;
  currentIndex = -1;
  isPlaying = false;

  audioPlayer.pause();
  audioPlayer.src = '';

  localStorage.removeItem('currentUser');
  localStorage.removeItem('authToken');
  localStorage.removeItem('favorites');
  localStorage.removeItem('history');
  localStorage.removeItem('disliked');
  localStorage.removeItem('profilePrefs');

  document.getElementById('userBlock').style.display = 'none';
  document.getElementById('loginBtn').style.display = 'block';
  document.getElementById('recsSection').style.display = 'none';
  document.getElementById('playerBar').style.display = 'none';

  renderProfile();
  renderHistory();
  renderFavorites();

  showToast('👋 До свидания!');
}

function showError(el, msg) {
  el.textContent = msg;
  el.style.display = 'block';
}


function renderProfile() {
  const content = document.getElementById('profileContent');
  const form = document.getElementById('profileForm');

  if (currentUser) {
    content.style.display = 'none';
    form.style.display = 'block';
    renderProfileGenres();
  } else {
    content.style.display = 'block';
    form.style.display = 'none';
  }
}

function toggleProfileGenre(el) {
  el.classList.toggle('selected');

  const g = el.dataset.genre;

  if (!profilePrefs.genres) {
    profilePrefs.genres = [];
  }

  if (profilePrefs.genres.includes(g)) {
    profilePrefs.genres = profilePrefs.genres.filter(x => x !== g);
  } else {
    profilePrefs.genres.push(g);
  }

  localStorage.setItem('profilePrefs', JSON.stringify(profilePrefs));
}

async function saveProfile() {
  localStorage.setItem('profilePrefs', JSON.stringify(profilePrefs));

  await saveUserStateToServer();

  showToast('✅ Предпочтения сохранены');
}

function closeModalOutside(e, id) {
  if (e.target === document.getElementById(id)) closeModal(id);
}
function switchTab(tab) {
  document.getElementById('loginForm').style.display = tab === 'login' ? 'block' : 'none';
  document.getElementById('registerForm').style.display = tab === 'register' ? 'block' : 'none';
  document.getElementById('tab-login').classList.toggle('active', tab === 'login');
  document.getElementById('tab-register').classList.toggle('active', tab === 'register');
}


let toastTimer;
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}


function addToQueue(index) {
  showToast('➕ Добавлено в очередь');
}

document.getElementById('volumeSlider')?.addEventListener('input', (e) => {
  audioPlayer.volume = e.target.value / 100;
});

if (currentUser) {
  document.getElementById('userBlock').style.display = 'flex';
  document.getElementById('userName').textContent = getUserDisplayName(currentUser);
  document.getElementById('loginBtn').style.display = 'none';
  renderProfile();

  if (authToken) {
    loadUserStateFromServer();
  }
}

document.getElementById('loginBtn')?.addEventListener('click', () => {
  openModal('loginModal');
});