#!/usr/bin/env python3
# video_app.py
# 单文件 Flask 视频管理与播放平台（注册/登录/上传/搜索/删除）
# 说明：2025-09-26 — 使用 SQLite（原生 SQL）、文件系统存储视频、LCS 相似度搜索、Bootstrap 5 前端
# 注意：部署时请替换 SECRET_KEY，并根据需要调整 MAX_CONTENT_LENGTH 与 ALLOWED_EXTENSIONS
import os
import sqlite3
import time
from typing import List
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    flash, session, send_from_directory, abort
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# -----------------------
# 配置（部署时请修改）
# -----------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, 'static', 'uploads')  # 每个用户的上传目录：static/uploads/<username>/
DB_PATH = os.path.join(BASE_DIR, 'users.db')
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov', 'mkv'}
MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GiB max upload
SECRET_KEY = 'replace-with-secure-random-secret'  # 部署时替换为安全随机值
# -----------------------
# 应用初始化
# -----------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['UPLOAD_ROOT'] = UPLOAD_ROOT
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
# 确保上传根目录存在
os.makedirs(UPLOAD_ROOT, exist_ok=True)
# -----------------------
# 数据库（SQLite） - 原生 SQL
# users 表：id, username, password_hash
# -----------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    conn = get_db_connection()
    # 使用原生 SQL 创建表（如果不存在）
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()
init_db()
# -----------------------
# 工具函数
# -----------------------
def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def ensure_user_folder(username: str) -> str:
    """创建并返回用户上传目录路径（安全的 username 假定由注册流程保证）"""
    path = os.path.join(app.config['UPLOAD_ROOT'], username)
    os.makedirs(path, exist_ok=True)
    return path
def list_user_videos(username: str) -> List[str]:
    """返回用户目录中按名称排序的可播放文件列表"""
    folder = os.path.join(app.config['UPLOAD_ROOT'], username)
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, f)) and allowed_file(f)]
    return sorted(files)
# 最长公共子序列（LCS）长度算法（动态规划，节省内存的滚动数组）
def lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                if prev[j] >= cur[j - 1]:
                    cur[j] = prev[j]
                else:
                    cur[j] = cur[j - 1]
        prev = cur
    return prev[-1]
def lcs_similarity(a: str, b: str) -> float:
    """返回 [0.0, 1.0] 相似度，使用 LCS 长度除以较长字符串长度"""
    if not a or not b:
        return 0.0
    la = len(a)
    lb = len(b)
    l = lcs_length(a, b)
    return l / max(la, lb)
# -----------------------
# 模板（单文件渲染，Bootstrap 5）
# -----------------------
BASE_TEMPLATE = '''
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>视频管理平台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding-bottom: 40px; }
      video { background:#000; width:100%; }
      .card-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .small-muted { font-size: 0.9rem; color: #6c757d; }
      .nav-brand-small { font-weight:700; letter-spacing:0.5px; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
      <div class="container-fluid">
        <a class="navbar-brand nav-brand-small" href="{{ url_for('index') }}">VideoManager</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMain">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navMain">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
            {% if session.get('username') %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传视频</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('my_videos') }}">我的视频</a></li>
            {% endif %}
          </ul>
          <form class="d-flex me-3" action="{{ url_for('search') }}" method="get" role="search">
            <input class="form-control me-2" name="q" placeholder="搜索标题（相似匹配）" value="{{ request.args.get('q','') }}">
            <button class="btn btn-outline-light" type="submit">搜索</button>
          </form>
          <ul class="navbar-nav">
            {% if session.get('username') %}
              <li class="nav-item d-flex align-items-center"><span class="navbar-text text-light me-3">Hi, {{ session['username'] }}</span></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
            {% else %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
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
'''

INDEX_TEMPLATE = '''
{% extends base %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <h3>用户列表</h3>
    <ul class="list-group">
      {% for u in users %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <a href="{{ url_for('user_videos', username=u) }}">{{ u }}</a>
          <span class="small-muted">{{ counts.get(u, 0) }} 个视频</span>
        </li>
      {% else %}
        <li class="list-group-item">暂无用户</li>
      {% endfor %}
    </ul>
  </div>
  <div class="col-md-4">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">快速使用</h5>
        <p class="card-text">注册并登录后可上传视频。搜索功能使用 LCS（最长公共子序列）进行相似度匹配，支持删除自己上传的视频。</p>
        <ul class="mb-0">
          <li>支持格式：{{ allowed }}</li>
          <li>最大上传：{{ max_mb }} MB（可在配置中调整）</li>
        </ul>
      </div>
    </div>
  </div>
</div>
{% endblock %}
'''

REGISTER_TEMPLATE = '''
{% extends base %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>注册</h3>
    <form method="post" novalidate>
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input class="form-control" name="password" type="password" required>
      </div>
      <button class="btn btn-primary" type="submit">注册</button>
    </form>
  </div>
</div>
{% endblock %}
'''

LOGIN_TEMPLATE = '''
{% extends base %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>登录</h3>
    <form method="post" novalidate>
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input class="form-control" name="password" type="password" required>
      </div>
      <button class="btn btn-primary" type="submit">登录</button>
    </form>
  </div>
</div>
{% endblock %}
'''

UPLOAD_TEMPLATE = '''
{% extends base %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8">
    <h3>上传视频</h3>
    <form method="post" enctype="multipart/form-data" novalidate>
      <div class="mb-3">
        <label class="form-label">视频标题（必填）</label>
        <input class="form-control" name="title" required>
      </div>
      <div class="mb-3">
        <label class="form-label">选择视频文件</label>
        <input class="form-control" type="file" name="file" accept="video/*" required>
      </div>
      <button class="btn btn-success" type="submit">上传</button>
    </form>
  </div>
</div>
{% endblock %}
'''

MY_VIDEOS_TEMPLATE = '''
{% extends base %}
{% block content %}
<h3>{{ username }} 的视频</h3>
<div class="row">
  {% for v in videos %}
    <div class="col-md-6 mb-4">
      <div class="card shadow-sm">
        <video class="card-img-top" controls preload="metadata" style="max-height:300px; object-fit:cover;">
          <source src="{{ url_for('serve_video', username=username, filename=v) }}">
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ v }}</h5>
          <div class="d-flex">
            <a class="btn btn-primary me-2" href="{{ url_for('serve_video', username=username, filename=v) }}" target="_blank">打开</a>
            <form method="post" action="{{ url_for('delete_video') }}" style="display:inline;">
              <input type="hidden" name="username" value="{{ username }}">
              <input type="hidden" name="filename" value="{{ v }}">
              <button class="btn btn-danger" type="submit" onclick="return confirm('确认删除该视频？此操作不可恢复。');">删除</button>
            </form>
          </div>
        </div>
      </div>
    </div>
  {% else %}
    <p>暂无视频</p>
  {% endfor %}
</div>
{% endblock %}
'''

USER_VIDEOS_TEMPLATE = '''
{% extends base %}
{% block content %}
<h3>{{ username }} 的视频</h3>
<div class="row">
  {% for v in videos %}
    <div class="col-md-6 mb-4">
      <div class="card shadow-sm">
        <video class="card-img-top" controls preload="metadata" style="max-height:300px; object-fit:cover;">
          <source src="{{ url_for('serve_video', username=username, filename=v) }}">
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ v }}</h5>
          <p class="card-text"><a class="btn btn-primary" href="{{ url_for('serve_video', username=username, filename=v) }}" target="_blank">打开</a></p>
        </div>
      </div>
    </div>
  {% else %}
    <p>暂无视频</p>
  {% endfor %}
</div>
{% endblock %}
'''

SEARCH_TEMPLATE = '''
{% extends base %}
{% block content %}
<h3>搜索结果： "{{ q }}"</h3>
<p>显示相似度 >= {{ '%.2f' % min_score }}（LCS 相似度）</p>
<div class="row">
  {% for item in results %}
    <div class="col-md-6 mb-4">
      <div class="card shadow-sm">
        <video class="card-img-top" controls preload="metadata" style="max-height:300px; object-fit:cover;">
          <source src="{{ url_for('serve_video', username=item.username, filename=item.filename) }}">
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ item.filename }}</h5>
          <p class="card-text">上传者：<a href="{{ url_for('user_videos', username=item.username) }}">{{ item.username }}</a></p>
          <p class="card-text"><small class="text-muted">相似度：{{ '%.2f' % item.score }}</small></p>
          <a class="btn btn-primary" href="{{ url_for('serve_video', username=item.username, filename=item.filename) }}" target="_blank">打开</a>
        </div>
      </div>
    </div>
  {% else %}
    <p>未找到匹配的视频</p>
  {% endfor %}
</div>
{% endblock %}
'''

# -----------------------
# 路由实现
# -----------------------
@app.route('/')
def index():
    conn = get_db_connection()
    rows = conn.execute('SELECT username FROM users ORDER BY username COLLATE NOCASE;').fetchall()
    conn.close()
    users = [r['username'] for r in rows]
    counts = {u: len(list_user_videos(u)) for u in users}
    return render_template_string(INDEX_TEMPLATE, base=BASE_TEMPLATE, users=users, counts=counts,
                                  allowed=', '.join(sorted(ALLOWED_EXTENSIONS)), max_mb=app.config['MAX_CONTENT_LENGTH'] // (1024*1024))
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空', 'danger')
            return redirect(url_for('register'))
        conn = get_db_connection()
        try:
            pw_hash = generate_password_hash(password)
            conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?);', (username, pw_hash))
            conn.commit()
            ensure_user_folder(username)
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在', 'danger')
            return redirect(url_for('register'))
        finally:
            conn.close()
    return render_template_string(REGISTER_TEMPLATE, base=BASE_TEMPLATE)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?;', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['username'] = username
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger')
        return redirect(url_for('login'))
    return render_template_string(LOGIN_TEMPLATE, base=BASE_TEMPLATE)
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('已登出', 'info')
    return redirect(url_for('index'))
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session:
        flash('请先登录', 'warning')
        return redirect(url_for('login'))
    username = session['username']
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        file = request.files.get('file')
        if not title:
            flash('请填写视频标题', 'danger')
            return redirect(url_for('upload'))
        if not file or file.filename == '':
            flash('请选择视频文件', 'danger')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('不支持的文件类型', 'danger')
            return redirect(url_for('upload'))
        orig_name = secure_filename(file.filename)
        safe_title = secure_filename(title) or 'untitled'
        timestamp = int(time.time())
        name, ext = os.path.splitext(orig_name)
        final_name = f"{safe_title}_{timestamp}{ext}"
        save_path = os.path.join(ensure_user_folder(username), final_name)
        try:
            file.save(save_path)
            flash('上传成功', 'success')
        except Exception:
            flash('保存文件失败', 'danger')
        return redirect(url_for('my_videos'))
    return render_template_string(UPLOAD_TEMPLATE, base=BASE_TEMPLATE)
@app.route('/my_videos')
def my_videos():
    if 'username' not in session:
        flash('请先登录', 'warning')
        return redirect(url_for('login'))
    username = session['username']
    videos = list_user_videos(username)
    return render_template_string(MY_VIDEOS_TEMPLATE, base=BASE_TEMPLATE, username=username, videos=videos)
@app.route('/user/<username>')
def user_videos(username):
    videos = list_user_videos(username)
    return render_template_string(USER_VIDEOS_TEMPLATE, base=BASE_TEMPLATE, username=username, videos=videos)
@app.route('/serve/<username>/<path:filename>')
def serve_video(username, filename):
    folder = os.path.join(app.config['UPLOAD_ROOT'], username)
    if not os.path.isdir(folder):
        abort(404)
    # 安全限制：禁止路径穿越
    safe_path = os.path.normpath(os.path.join(folder, filename))
    if not safe_path.startswith(os.path.normpath(folder) + os.sep) and safe_path != os.path.normpath(folder):
        abort(403)
    if not os.path.isfile(safe_path):
        abort(404)
    return send_from_directory(folder, filename, as_attachment=False)
@app.route('/delete_video', methods=['POST'])
def delete_video():
    if 'username' not in session:
        flash('请先登录', 'warning')
        return redirect(url_for('login'))
    req_user = session['username']
    form_user = (request.form.get('username') or '').strip()
    filename = (request.form.get('filename') or '').strip()
    if not form_user or not filename:
        flash('参数不完整', 'danger')
        return redirect(url_for('my_videos'))
    # 仅允许用户删除自己的视频
    if req_user != form_user:
        flash('无权限删除该视频', 'danger')
        return redirect(url_for('index'))
    file_path = os.path.join(app.config['UPLOAD_ROOT'], form_user, filename)
    # 避免路径穿越
    file_path = os.path.normpath(file_path)
    user_folder = os.path.normpath(os.path.join(app.config['UPLOAD_ROOT'], form_user))
    if not file_path.startswith(user_folder + os.sep) and file_path != user_folder:
        flash('无效文件路径', 'danger')
        return redirect(url_for('my_videos'))
    if not os.path.isfile(file_path):
        flash('文件不存在', 'warning')
        return redirect(url_for('my_videos'))
    try:
        os.remove(file_path)
        flash('删除成功', 'success')
    except Exception:
        flash('删除失败', 'danger')
    return redirect(url_for('my_videos'))
@app.route('/search')
def search():
    q = (request.args.get('q') or '').strip()
    q_norm = q.lower()
    results = []
    min_score = 0.25
    if q_norm:
        for username in os.listdir(app.config['UPLOAD_ROOT']):
            user_dir = os.path.join(app.config['UPLOAD_ROOT'], username)
            if not os.path.isdir(user_dir):
                continue
            for fname in os.listdir(user_dir):
                if not allowed_file(fname):
                    continue
                fname_norm = fname.lower()
                base, _ = os.path.splitext(fname_norm)
                # 从上传时的命名规则 safe_title_timestamp.ext 提取标题部分
                if '_' in base:
                    candidate_title = base.rsplit('_', 1)[0]
                else:
                    candidate_title = base
                score = lcs_similarity(q_norm, candidate_title)
                if score >= min_score:
                    results.append({'username': username, 'filename': fname, 'score': score})
        results.sort(key=lambda x: x['score'], reverse=True)
    class Item:
        def __init__(self, d):
            self.username = d['username']; self.filename = d['filename']; self.score = d['score']
    items = [Item(d) for d in results]
    return render_template_string(SEARCH_TEMPLATE, base=BASE_TEMPLATE, q=q, results=items, min_score=min_score)
# 兼容旧 URL
@app.route('/uploads/<username>/<path:filename>')
def uploads_compat(username, filename):
    return serve_video(username, filename)
if __name__ == '__main__':
    app.run(debug=True)
