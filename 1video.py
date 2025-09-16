#!/usr/bin/env python3
"""
app.py - Video sharing simple Flask app (single-file)
Features:
- User registration/login
- Video upload (file saved to static/uploads)
- Video listing, watch page
- User search with fuzzy matching (LCS) showing similarity %
- "My Videos" management: hide/unhide and delete
- Bootstrap 5 UI
- SQLite (raw SQL) storage
Run:
    python app.py
Notes:
- For production, serve uploaded videos via nginx or object storage.
- If you have an existing database and want the "hidden" column, run:
    ALTER TABLE video ADD COLUMN hidden INTEGER DEFAULT 0;
"""
import os
import re
import uuid
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, render_template, request, redirect, url_for,
    flash, session, send_from_directory, abort
)
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash
# Configuration
BASE_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIRECTORY = os.path.join(BASE_DIRECTORY, "static", "uploads")
DATABASE_PATH = os.path.join(BASE_DIRECTORY, "app.db")
ALLOWED_EXTENSIONS = {"mp4", "webm", "ogg", "mov", "mkv"}
MAX_UPLOAD_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
SITE_TITLE = "ClipShare"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)
app = Flask(__name__)
app.config.update(
    UPLOAD_FOLDER=UPLOAD_DIRECTORY,
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
    SECRET_KEY=SECRET_KEY,
)
# -------------------------
# Templates (DictLoader)
# -------------------------
BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title or site_title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    .card-video { max-height: 220px; overflow: hidden; }
    .video-player { width:100%; height:auto; }
    .nav-search { max-width:420px; }
    .badge-sim { min-width:52px; text-align:center; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">{{ site_title }}</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navCollapse">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navCollapse">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        {% if current_user %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('upload_video') }}">Upload</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('my_videos') }}">My Videos</a></li>
        {% endif %}
      </ul>
      <form class="d-flex nav-search me-2" action="{{ url_for('search_users') }}" method="get">
        <input class="form-control me-2" name="q" placeholder="Search users" value="{{ request.args.get('q','') }}">
        <button class="btn btn-outline-light" type="submit">Search</button>
      </form>
      <ul class="navbar-nav">
        {% if current_user %}
          <li class="nav-item"><span class="navbar-text text-white me-2">Hi, {{ current_user['username'] }}</span></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

INDEX_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h2 class="mb-0">Latest Videos</h2>
  <small class="text-muted">Showing {{ videos|length }} items</small>
</div>

<div class="row row-cols-1 row-cols-md-3 g-4">
  {% for v in videos %}
    <div class="col">
      <div class="card h-100">
        <div class="ratio ratio-16x9 card-video">
          <video class="video-player" controls preload="metadata">
            <source src="{{ url_for('serve_upload', filename=v['filename']) }}">
            Your browser doesn't support HTML5 video.
          </video>
        </div>
        <div class="card-body d-flex flex-column">
          <h5 class="card-title">{{ v['title'] or v['original_name'] }}</h5>
          <p class="card-text text-muted mb-1">By <a href="{{ url_for('user_profile', user_id=v['user_id']) }}">{{ v['username'] }}</a></p>
          <p class="small text-muted mb-2">Uploaded {{ v['created_at'] }}</p>
          <div class="mt-auto">
            <a class="btn btn-primary btn-sm" href="{{ url_for('watch_video', video_id=v['id']) }}">Watch</a>
          </div>
        </div>
      </div>
    </div>
  {% else %}
    <p>No videos yet.</p>
  {% endfor %}
</div>
{% endblock %}
"""

REGISTER_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2>Register</h2>
    <form method="post" novalidate>
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required minlength="3" maxlength="80">
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required minlength="6">
      </div>
      <button class="btn btn-primary" type="submit">Register</button>
    </form>
  </div>
</div>
{% endblock %}
"""

LOGIN_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2>Login</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-primary" type="submit">Login</button>
    </form>
  </div>
</div>
{% endblock %}
"""

UPLOAD_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8">
    <h2>Upload Video</h2>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">Title</label>
        <input name="title" class="form-control" required maxlength="200">
      </div>
      <div class="mb-3">
        <label class="form-label">Description</label>
        <textarea name="description" class="form-control" rows="4"></textarea>
      </div>
      <div class="mb-3">
        <label class="form-label">File</label>
        <input type="file" name="file" class="form-control" accept="video/*" required>
      </div>
      <button class="btn btn-success" type="submit">Upload</button>
    </form>
  </div>
</div>
{% endblock %}
"""

MY_VIDEOS_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>My Videos</h2>
<div class="row row-cols-1 row-cols-md-3 g-4">
  {% for v in videos %}
  <div class="col">
    <div class="card h-100">
      <div class="ratio ratio-16x9">
        <video class="video-player" controls>
          <source src="{{ url_for('serve_upload', filename=v['filename']) }}">
        </video>
      </div>
      <div class="card-body d-flex flex-column">
        <h5 class="card-title">{{ v['title'] or v['original_name'] }}</h5>
        <p class="card-text text-muted small mb-2">Uploaded {{ v['created_at'] }}</p>
        {% if v['hidden'] %}
          <span class="badge bg-secondary mb-2">Hidden</span>
        {% endif %}
        <div class="mt-auto d-flex gap-2">
          <a class="btn btn-sm btn-primary" href="{{ url_for('watch_video', video_id=v['id']) }}">Watch</a>
          {% if v['hidden'] %}
            <a class="btn btn-sm btn-outline-success" href="{{ url_for('toggle_visibility', video_id=v['id']) }}">Unhide</a>
          {% else %}
            <a class="btn btn-sm btn-outline-warning" href="{{ url_for('toggle_visibility', video_id=v['id']) }}">Hide</a>
          {% endif %}
          <a class="btn btn-sm btn-danger" href="{{ url_for('delete_video', video_id=v['id']) }}" onclick="return confirm('Delete this video? This cannot be undone.');">Delete</a>
        </div>
      </div>
    </div>
  </div>
  {% else %}
    <p>No uploads yet.</p>
  {% endfor %}
</div>
{% endblock %}
"""
WATCH_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <h3>{{ video['title'] or video['original_name'] }}</h3>
    <p class="text-muted">By <a href="{{ url_for('user_profile', user_id=owner['id']) }}">{{ owner['username'] }}</a> · Uploaded {{ video['created_at'] }}</p>
    <div class="ratio ratio-16x9 mb-3">
      <video controls preload="metadata">
        <source src="{{ url_for('serve_upload', filename=video['filename']) }}">
      </video>
    </div>
    <p>{{ video['description'] }}</p>
  </div>
  <div class="col-md-4">
    <div class="card">
      <div class="card-body">
        <h6>Details</h6>
        <p class="mb-0"><strong>Filename:</strong> {{ video['original_name'] }}</p>
        <p class="mb-0"><strong>Stored:</strong> {{ video['filename'] }}</p>
        <p class="mb-0"><strong>Uploaded:</strong> {{ video['created_at'] }}</p>
        <p class="mb-0"><strong>Visibility:</strong> {{ "Hidden" if video['hidden'] else "Visible" }}</p>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""
SEARCH_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>Search Results for "{{ query }}"</h2>
{% if results %}
  <div class="list-group">
    {% for u in results %}
      <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" href="{{ url_for('user_profile', user_id=u['id']) }}">
        <div>
          <strong>{{ u['username'] }}</strong>
          <div class="text-muted small">LCS: {{ u['lcs'] }}</div>
        </div>
        <span class="badge bg-primary rounded-pill badge-sim">{{ u['similarity'] }}%</span>
      </a>
    {% endfor %}
  </div>
{% else %}
  <p>No results.</p>
{% endif %}
{% endblock %}
"""
USER_PROFILE_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>{{ user['username'] }}</h2>
<p class="text-muted">Videos by {{ user['username'] }}</p>

<div class="row row-cols-1 row-cols-md-3 g-4">
  {% for v in videos %}
    <div class="col">
      <div class="card h-100">
        <div class="ratio ratio-16x9 card-video">
          <video class="video-player" controls preload="metadata">
            <source src="{{ url_for('serve_upload', filename=v['filename']) }}">
          </video>
        </div>
        <div class="card-body d-flex flex-column">
          <h5>{{ v['title'] or v['original_name'] }}</h5>
          <p class="small text-muted">Uploaded {{ v['created_at'] }}</p>
          <div class="mt-auto">
            <a class="btn btn-primary btn-sm" href="{{ url_for('watch_video', video_id=v['id']) }}">Watch</a>
          </div>
        </div>
      </div>
    </div>
  {% else %}
    <p>No videos yet.</p>
  {% endfor %}
</div>
{% endblock %}
"""
app.jinja_loader = DictLoader({
    "base.html": BASE_TEMPLATE,
    "index.html": INDEX_TEMPLATE,
    "register.html": REGISTER_TEMPLATE,
    "login.html": LOGIN_TEMPLATE,
    "upload.html": UPLOAD_TEMPLATE,
    "my_videos.html": MY_VIDEOS_TEMPLATE,
    "watch.html": WATCH_TEMPLATE,
    "search.html": SEARCH_TEMPLATE,
    "user_profile.html": USER_PROFILE_TEMPLATE,
})
# -------------------------
# Database helpers
# -------------------------
def get_database_connection():
    """
    Return a sqlite3 connection stored on 'g'.
    Enables row access by column name.
    """
    connection = getattr(g, "_db_connection", None)
    if connection is None:
        connection = g._db_connection = sqlite3.connect(DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
    return connection
def fetch_all_rows(query, args=()):
    """
    Execute query and return all rows.
    """
    cursor = get_database_connection().execute(query, args)
    rows = cursor.fetchall()
    cursor.close()
    return rows
def fetch_one_row(query, args=()):
    """
    Execute query and return a single row or None.
    """
    cursor = get_database_connection().execute(query, args)
    row = cursor.fetchone()
    cursor.close()
    return row
def execute_and_commit(query, args=()):
    """
    Execute a statement that modifies the DB and commit.
    Returns lastrowid.
    """
    connection = get_database_connection()
    cursor = connection.execute(query, args)
    connection.commit()
    last_row_id = cursor.lastrowid
    cursor.close()
    return last_row_id
@app.teardown_appcontext
def close_database_connection(exc):
    """
    Close DB connection at the end of request.
    """
    connection = getattr(g, "_db_connection", None)
    if connection is not None:
        connection.close()
def initialize_database():
    """
    Initialize the database if it doesn't exist.
    Creates 'user' and 'video' tables. 'video.hidden' is an integer flag (0 visible, 1 hidden).
    """
    if os.path.exists(DATABASE_PATH):
        return
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()
    cursor.execute("""
    CREATE TABLE user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    cursor.execute("""
    CREATE TABLE video (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_name TEXT,
        title TEXT,
        description TEXT,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        hidden INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
    );
    """)
    connection.commit()
    connection.close()
initialize_database()
# -------------------------
# Utilities
# -------------------------
def is_allowed_file(filename):
    """
    Check if the file extension is in the allowed set.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in ALLOWED_EXTENSIONS
def generate_secure_filename(original_filename, max_name_len=120):
    """
    Create a sanitized and unique filename preserving extension.
    """
    original_filename = original_filename or ""
    base_name, extension = os.path.splitext(original_filename)
    base_name = re.sub(r'[^A-Za-z0-9_.-]', '_', base_name)[:max_name_len]
    extension = re.sub(r'[^A-Za-z0-9.]', '', extension)
    uuid_token = uuid.uuid4().hex
    return f"{base_name}_{uuid_token}{extension or '.bin'}"
def require_login(function):
    """
    Decorator that redirects users to login if not authenticated.
    """
    @wraps(function)
    def decorated(*args, **kwargs):
        if "current_user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return function(*args, **kwargs)
    return decorated
def compute_lcs_length(str_a: str, str_b: str) -> int:
    """
    Compute length of Longest Common Subsequence (space optimized).
    """
    s1 = str_a or ""
    s2 = str_b or ""
    len_a, len_b = len(s1), len(s2)
    if len_a == 0 or len_b == 0:
        return 0
    prev_row = [0] * (len_b + 1)
    for i in range(1, len_a + 1):
        curr_row = [0] * (len_b + 1)
        char_a = s1[i - 1]
        for j in range(1, len_b + 1):
            if char_a == s2[j - 1]:
                curr_row[j] = prev_row[j - 1] + 1
            else:
                curr_row[j] = curr_row[j - 1] if curr_row[j - 1] > prev_row[j] else prev_row[j]
        prev_row = curr_row
    return prev_row[len_b]
# -------------------------
# Template context & user loader
# -------------------------
@app.context_processor
def inject_template_globals():
    """
    Inject site-wide template variables.
    """
    return {"site_title": SITE_TITLE, "now": datetime.utcnow().isoformat(), "current_user": g.get("current_user")}
@app.before_request
def load_current_user():
    """
    Load the logged-in user into 'g.current_user' if available.
    """
    g.current_user = None
    user_id = session.get("current_user_id")
    if user_id:
        g.current_user = fetch_one_row("SELECT id, username FROM user WHERE id = ?", (user_id,))
# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    """
    Home page showing latest videos.
    """
    video_rows = fetch_all_rows("""
      SELECT v.*, u.username FROM video v
      JOIN user u ON v.user_id = u.id
      WHERE v.hidden = 0
      ORDER BY datetime(v.created_at) DESC
      LIMIT 12
    """)
    return render_template("index.html", videos=video_rows)
@app.route("/register", methods=["GET", "POST"])
def register():
    """
    User registration.
    """
    if request.method == "POST":
        username_text = (request.form.get("username") or "").strip()
        password_text = request.form.get("password") or ""
        if not (3 <= len(username_text) <= 80 and len(password_text) >= 6):
            flash("Invalid username/password length", "warning")
            return redirect(url_for("register"))
        if fetch_one_row("SELECT id FROM user WHERE username = ?", (username_text,)):
            flash("Username already exists", "warning")
            return redirect(url_for("register"))
        password_hash = generate_password_hash(password_text)
        timestamp_iso = datetime.utcnow().isoformat()
        execute_and_commit("INSERT INTO user (username, password_hash, created_at) VALUES (?, ?, ?)", (username_text, password_hash, timestamp_iso))
        flash("Registered. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    User login.
    """
    if request.method == "POST":
        username_text = (request.form.get("username") or "").strip()
        password_text = request.form.get("password") or ""
        user_record = fetch_one_row("SELECT id, username, password_hash FROM user WHERE username = ?", (username_text,))
        if user_record and check_password_hash(user_record["password_hash"], password_text):
            session["current_user_id"] = user_record["id"]
            flash("Logged in", "success")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        flash("Invalid credentials", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")
@app.route("/logout")
def logout():
    """
    Logout the current user.
    """
    session.pop("current_user_id", None)
    flash("Logged out", "info")
    return redirect(url_for("index"))
@app.route("/upload", methods=["GET", "POST"])
@require_login
def upload_video():
    """
    Upload a new video. Stores file and inserts DB record.
    """
    if request.method == "POST":
        title_text = (request.form.get("title") or "").strip()
        description_text = (request.form.get("description") or "").strip()
        uploaded_file = request.files.get("file")
        if not title_text:
            flash("Title required", "warning")
            return redirect(url_for("upload_video"))
        if not uploaded_file or uploaded_file.filename == "":
            flash("No file selected", "warning")
            return redirect(url_for("upload_video"))
        if not is_allowed_file(uploaded_file.filename):
            flash("File type not allowed", "danger")
            return redirect(url_for("upload_video"))
        stored_filename = generate_secure_filename(uploaded_file.filename)
        destination_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)
        try:
            uploaded_file.save(destination_path)
        except Exception:
            flash("Failed to save file", "danger")
            return redirect(url_for("upload_video"))
        timestamp_iso = datetime.utcnow().isoformat()
        video_id = execute_and_commit(
            "INSERT INTO video (filename, original_name, title, description, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (stored_filename, uploaded_file.filename, title_text, description_text, session["current_user_id"], timestamp_iso)
        )
        flash("Upload successful", "success")
        return redirect(url_for("watch_video", video_id=video_id))
    return render_template("upload.html")
@app.route("/my_videos")
@require_login
def my_videos():
    """
    Show current user's videos with management controls.
    """
    user_video_rows = fetch_all_rows("SELECT * FROM video WHERE user_id = ? ORDER BY datetime(created_at) DESC", (session["current_user_id"],))
    return render_template("my_videos.html", videos=user_video_rows)
@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    """
    Serve uploaded video files from UPLOAD_FOLDER.
    In production, prefer a static file server.
    """
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)
@app.route("/watch/<int:video_id>")
def watch_video(video_id):
    """
    Watch page for a single video.
    """
    video_record = fetch_one_row("SELECT * FROM video WHERE id = ?", (video_id,))
    if not video_record:
        abort(404)
    # If video is hidden, allow owner to view; otherwise show only if visible
    if video_record["hidden"] and (not g.current_user or g.current_user["id"] != video_record["user_id"]):
        abort(404)
    owner_user = fetch_one_row("SELECT id, username FROM user WHERE id = ?", (video_record["user_id"],))
    return render_template("watch.html", video=video_record, owner=owner_user)
@app.route("/toggle_visibility/<int:video_id>")
@require_login
def toggle_visibility(video_id):
    """
    Toggle the 'hidden' flag for a video belonging to the current user.
    """
    video_record = fetch_one_row("SELECT id, user_id, hidden FROM video WHERE id = ?", (video_id,))
    if not video_record:
        flash("Not found", "warning")
        return redirect(url_for("my_videos"))
    if video_record["user_id"] != session.get("current_user_id"):
        flash("No permission", "danger")
        return redirect(url_for("my_videos"))
    new_hidden_flag = 0 if video_record["hidden"] else 1
    execute_and_commit("UPDATE video SET hidden = ? WHERE id = ?", (new_hidden_flag, video_id))
    flash("Video visibility updated", "success")
    return redirect(url_for("my_videos"))
@app.route("/delete_video/<int:video_id>")
@require_login
def delete_video(video_id):
    """
    Delete a video (file removal + DB delete) for the current user.
    """
    video_record = fetch_one_row("SELECT * FROM video WHERE id = ?", (video_id,))
    if not video_record:
        flash("Not found", "warning")
        return redirect(url_for("my_videos"))
    if video_record["user_id"] != session["current_user_id"]:
        flash("No permission", "danger")
        return redirect(url_for("my_videos"))
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], video_record["filename"]))
    except Exception:
        pass
    execute_and_commit("DELETE FROM video WHERE id = ?", (video_id,))
    flash("Deleted", "info")
    return redirect(url_for("my_videos"))
@app.route("/search_users")
def search_users():
    """
    Search users by username using LCS fuzzy match.
    Returns results sorted by LCS length descending and includes similarity percentage.
    """
    search_query = (request.args.get("q") or "").strip()
    search_results = []
    if search_query:
        all_user_rows = fetch_all_rows("SELECT id, username FROM user")
        scored_list = []
        lowered_query = search_query.lower()
        for user_row in all_user_rows:
            username_text = user_row["username"] or ""
            score_value = compute_lcs_length(lowered_query, username_text.lower())
            if score_value > 0:
                denominator = max(len(lowered_query), len(username_text))
                similarity_pct = int(round((score_value / denominator) * 100))
                scored_list.append((score_value, similarity_pct, user_row))
        # sort by score desc, then pct desc, then username
        scored_list.sort(key=lambda x: (x[0], x[1], x[2]["username"]), reverse=True)
        search_results = [{"id": u["id"], "username": u["username"], "lcs": s, "similarity": p} for s, p, u in scored_list]
    return render_template("search.html", query=search_query, results=search_results)
@app.route("/user/<int:user_id>")
def user_profile(user_id):
    """
    Public profile showing a user's videos.
    Hidden videos are not shown to others.
    """
    user_row = fetch_one_row("SELECT id, username FROM user WHERE id = ?", (user_id,))
    if not user_row:
        abort(404)
    if g.current_user and g.current_user["id"] == user_id:
        videos = fetch_all_rows("SELECT * FROM video WHERE user_id = ? ORDER BY datetime(created_at) DESC", (user_id,))
    else:
        videos = fetch_all_rows("SELECT * FROM video WHERE user_id = ? AND hidden = 0 ORDER BY datetime(created_at) DESC", (user_id,))
    return render_template("user_profile.html", user=user_row, videos=videos)

app.run(debug=True, host="0.0.0.0", port=5000)
