# app.py
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, abort, render_template_string
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
# -------------------------
# Configuration
# -------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "main_db.sqlite3")
app.config["SQLALCHEMY_BINDS"] = {
    "auth": "sqlite:///" + os.path.join(BASE_DIR, "auth_db.sqlite3"),
    "share": "sqlite:///" + os.path.join(BASE_DIR, "share_db.sqlite3"),
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
def generate_id():
    return str(uuid.uuid4())
# -------------------------
# Database models
# -------------------------
class User(db.Model):
    __bind_key__ = "auth"
    __tablename__ = "users"
    id = db.Column(db.String, primary_key=True, default=generate_id)
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
class FileItem(db.Model):
    __tablename__ = "items"
    id = db.Column(db.String, primary_key=True, default=generate_id)
    name = db.Column(db.String, nullable=False)
    parent_id = db.Column(db.String, db.ForeignKey("items.id"), nullable=True)
    is_directory = db.Column(db.Boolean, default=False)
    size = db.Column(db.Integer, default=0)
    storage_path = db.Column(db.String, nullable=True)
    owner_id = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class Share(db.Model):
    __bind_key__ = "share"
    __tablename__ = "shares"
    id = db.Column(db.String, primary_key=True, default=generate_id)
    item_id = db.Column(db.String, nullable=False)
    token = db.Column(db.String, unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
# -------------------------
# DB initialization + demo user
# -------------------------
with app.app_context():
    db.create_all(bind=None)
    db.create_all(bind="auth")
    db.create_all(bind="share")
    # create demo user and root folder if missing
    if not User.query.with_bind("auth").first():
        demo_pw_hash = hashlib.sha256(b"demo").hexdigest()
        demo_user = User(username="demo", password_hash=demo_pw_hash)
        db.session.add(demo_user)
        db.session.commit()
        root_folder = FileItem(
            name="root", parent_id=None, is_directory=True, owner_id=demo_user.id
        )
        db.session.add(root_folder)
        db.session.commit()
# -------------------------
# Auth helpers (simple header-based for demo)
# -------------------------
def get_user_by_username(username: str):
    if not username:
        return None
    return User.query.with_bind("auth").filter_by(username=username).first()
def require_simple_auth():
    username = request.headers.get("X-User")
    user = get_user_by_username(username)
    if not user:
        abort(401)
    return user
# -------------------------
# Frontend HTML (Bootstrap 5, better layout, touch-friendly)
# -------------------------
INDEX_HTML = """
<!doctype html>
<html lang="zh-cn">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Mini Cloud Drive</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --accent:#0d6efd;
      --muted:#6c757d;
    }
    body{ padding:18px; background: linear-gradient(180deg,#f8fbff, #ffffff); min-height:100vh; }
    .card-drive{ border-radius:12px; box-shadow:0 6px 18px rgba(13,110,253,0.06); }
    .file-item{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 14px; border-radius:8px; transition:background .12s; }
    .file-item:hover{ background: #f6f9ff; }
    .item-left{ display:flex; align-items:center; gap:12px; cursor:grab; user-select:none; }
    .dragging{ opacity:0.45; }
    .folder-drop{ background:#fff7e6; border:1px dashed rgba(0,0,0,0.06); }
    .small-muted{ font-size:0.82rem; color:var(--muted); }
    .btn-primary, .btn-outline-primary{ border-radius:8px; }
    .top-controls .btn{ margin-left:6px; }
    .breadcrumb-item + .breadcrumb-item::before{ content: "›"; }
    .file-icon{ font-size:1.45rem; }
    .action-btns .btn{ border-radius:8px; }
    @media (max-width:576px){
      .top-controls { flex-direction:column; align-items:stretch; gap:8px; }
      .action-btns{ display:flex; gap:6px; }
      .file-item{ flex-direction:column; align-items:flex-start; gap:8px; }
    }
  </style>
</head>
<body>
<div class="container">
  <div class="row mb-3">
    <div class="col-12">
      <div class="card card-drive p-3">
        <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap top-controls">
          <div class="d-flex align-items-center gap-2">
            <input id="username" class="form-control" placeholder="用户名" style="max-width:160px" value="demo">
            <input id="password" class="form-control" placeholder="密码" type="password" style="max-width:160px" value="demo">
            <button id="btnLogin" class="btn btn-primary">登录</button>
            <button id="btnRegister" class="btn btn-outline-primary">注册</button>
            <span id="who" class="small-muted ms-2"></span>
          </div>
          <div class="d-flex align-items-center">
            <button id="btnUp" class="btn btn-outline-secondary me-1">上级目录</button>
            <button id="btnNewFolder" class="btn btn-success me-1">新建文件夹</button>
            <label class="btn btn-outline-primary mb-0 me-1" style="margin-bottom:0;">
              上传 <input id="fileInput" type="file" multiple hidden>
            </label>
            <button id="btnRefresh" class="btn btn-info text-white">刷新</button>
          </div>
        </div>

        <nav aria-label="breadcrumb" class="mb-2">
          <ol id="breadcrumb" class="breadcrumb mb-0 small-muted"></ol>
        </nav>

        <div class="row">
          <div class="col-md-8 mb-3">
            <div class="list-group" id="fileList" role="list"></div>
          </div>
          <div class="col-md-4">
            <div class="card">
              <div class="card-header d-flex justify-content-between align-items-center">
                <span>分享管理</span>
                <button id="btnRefreshShares" class="btn btn-sm btn-outline-secondary">刷新</button>
              </div>
              <div class="card-body p-2">
                <div id="shareList" class="list-group"></div>
              </div>
            </div>

            <div class="card mt-3">
              <div class="card-body small-muted">
                操作提示: 支持文件拖拽到文件夹以移动；点击“分享”生成可公开下载的链接；可复制或取消分享。
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</div>

<script>
/* ---------------------------
   Frontend logic (concise)
   --------------------------- */
let currentUser = null;
let currentParentId = null;
let parentMap = {}; // id -> parent_id
async function api(path, opts={}) {
  opts.headers = opts.headers || {};
  if (currentUser) opts.headers['X-User'] = currentUser;
  const res = await fetch('/api' + path, opts);
  const ctype = res.headers.get('content-type') || '';
  if (ctype.includes('application/json')) return res.json();
  return res;
}

// Auth
document.getElementById('btnLogin').onclick = async () => {
  const u = document.getElementById('username').value;
  const p = document.getElementById('password').value;
  const r = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u,password:p})});
  const j = await r.json();
  if (j.ok){ currentUser = j.username; document.getElementById('who').innerText = '当前: '+currentUser; await loadRoot(); listShares(); } else { alert('登录失败'); }
};
document.getElementById('btnRegister').onclick = async () => {
  const u = document.getElementById('username').value;
  const p = document.getElementById('password').value;
  const r = await fetch('/api/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u,password:p})});
  const j = await r.json();
  if (j.ok) alert('注册成功'); else alert('注册失败: ' + JSON.stringify(j));
};

// Controls
document.getElementById('btnNewFolder').onclick = async () => {
  if (!currentUser) return alert('请先登录');
  const name = prompt('文件夹名称', 'New Folder');
  if (!name) return;
  await api('/mkdir', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({parent_id: currentParentId, name})});
  await refresh();
};
document.getElementById('fileInput').onchange = async (e) => {
  if (!currentUser) return alert('请先登录');
  const files = e.target.files;
  if (!files.length) return;
  for (let f of files){
    const fd = new FormData();
    fd.append('file', f);
    fd.append('parent_id', currentParentId);
    await fetch('/api/upload', {method:'POST', headers: currentUser ? {'X-User': currentUser} : {}, body: fd});
  }
  await refresh();
};
document.getElementById('btnRefresh').onclick = refresh;
document.getElementById('btnUp').onclick = async () => {
  if (!currentParentId) return;
  const pid = parentMap[currentParentId];
  if (pid === undefined || pid === null) {
    await loadRoot();
  } else {
    currentParentId = pid;
    await refresh();
  }
};

// Listing
async function loadRoot(){
  if (!currentUser) return alert('请先登录');
  const r = await api('/list');
  currentParentId = r.parent_id;
  parentMap[currentParentId] = null;
  renderList(r.items);
  buildBreadcrumb();
}
async function refresh(){
  if (!currentUser) return alert('请先登录');
  const r = await api('/list?parent_id=' + (currentParentId||''));
  currentParentId = r.parent_id;
  renderList(r.items);
  buildBreadcrumb();
}

function renderList(items){
  const list = document.getElementById('fileList');
  list.innerHTML = '';
  items.forEach(it => {
    parentMap[it.id] = it.parent_id;
    const li = document.createElement('div');
    li.className = 'list-group-item file-item';
    li.draggable = true;
    li.dataset.id = it.id;

    const left = document.createElement('div');
    left.className = 'item-left';
    const icon = document.createElement('div');
    icon.className = 'file-icon';
    icon.innerText = it.is_dir ? '📁' : '📄';
    const nameDiv = document.createElement('div');
    nameDiv.innerHTML = `<div><strong>${escapeHtml(it.name)}</strong></div><div class="small-muted">更新: ${new Date(it.updated_at).toLocaleString()} ${it.is_dir ? '' : ' • ' + formatSize(it.size)}</div>`;
    nameDiv.onclick = async () => {
      if (it.is_dir) {
        currentParentId = it.id;
        await refresh();
      } else {
        window.open('/api/download/' + it.id, '_blank');
      }
    };
    left.appendChild(icon);
    left.appendChild(nameDiv);

    const actions = document.createElement('div');
    actions.className = 'action-btns';
    const btnDownload = makeBtn('下载', 'btn-outline-primary', ()=> window.open('/api/download/' + it.id, '_blank'));
    const btnShare = makeBtn('分享', 'btn-outline-success', async ()=>{
      const res = await api('/share', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({item_id:it.id})});
      if (res.token){ prompt('分享链接', location.origin + res.link); listShares(); } else alert(JSON.stringify(res));
    });
    const btnRename = makeBtn('重命名', 'btn-outline-secondary', async ()=>{
      const n = prompt('新名称', it.name); if (n) { await api('/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({item_id:it.id, name:n})}); refresh(); }
    });
    const btnDelete = makeBtn('删除', 'btn-outline-danger', async ()=>{
      if (confirm('确认删除？')){ await api('/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({item_id:it.id})}); refresh(); }
    });
    actions.appendChild(btnDownload);
    actions.appendChild(btnShare);
    actions.appendChild(btnRename);
    actions.appendChild(btnDelete);

    li.appendChild(left);
    li.appendChild(actions);

    // Drag & drop for moving items into folders
    li.addEventListener('dragstart', (ev)=>{ ev.dataTransfer.setData('text/plain', it.id); li.classList.add('dragging'); });
    li.addEventListener('dragend', ()=>{ li.classList.remove('dragging'); });
    li.addEventListener('dragover', (ev)=>{ if (it.is_dir){ ev.preventDefault(); li.classList.add('folder-drop'); } });
    li.addEventListener('dragleave', ()=>{ if (it.is_dir) li.classList.remove('folder-drop'); });
    li.addEventListener('drop', async (ev)=>{ ev.preventDefault(); if (it.is_dir){ li.classList.remove('folder-drop'); const dragged = ev.dataTransfer.getData('text/plain'); if (dragged && dragged !== it.id){ await api('/move', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({item_id:dragged, parent_id: it.id})}); refresh(); } } });

    list.appendChild(li);
  });
}

async function listShares(){
  const res = await api('/shares');
  const container = document.getElementById('shareList');
  container.innerHTML = '';
  if (!Array.isArray(res)) return;
  res.forEach(s => {
    const item = document.createElement('div');
    item.className = 'list-group-item d-flex justify-content-between align-items-center';
    const left = document.createElement('div');
    left.innerHTML = `<div><strong>${escapeHtml(s.name)}</strong></div><div class="small-muted">token: ${s.token}${s.expires_at ? ' • 到期: ' + new Date(s.expires_at).toLocaleString() : ''}</div>`;
    const right = document.createElement('div');
    const copy = makeBtn('复制链接', 'btn-outline-primary', ()=>{ navigator.clipboard.writeText(location.origin + '/api/download/' + s.item_id + '?token=' + s.token); alert('已复制'); });
    const cancel = makeBtn('取消分享', 'btn-outline-danger', async ()=>{ if (confirm('取消分享？')){ await api('/unshare', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token:s.token})}); listShares(); } });
    right.appendChild(copy);
    right.appendChild(cancel);
    item.appendChild(left);
    item.appendChild(right);
    container.appendChild(item);
  });
}

document.getElementById('btnRefreshShares').onclick = listShares;
function makeBtn(label, cls, onClick){
  const b = document.createElement('button'); b.className = 'btn btn-sm ' + cls; b.style.marginLeft='6px'; b.innerText = label; b.onclick = (e)=>{ e.stopPropagation(); onClick(); };
  return b;
}

function buildBreadcrumb(){
  const bc = document.getElementById('breadcrumb');
  bc.innerHTML = '';
  let id = currentParentId;
  const trail = [];
  while (id){
    trail.push(id);
    id = parentMap[id];
    if (trail.length > 50) break;
  }
  trail.push(null);
  trail.reverse();
  trail.forEach((pid, idx) => {
    const li = document.createElement('li');
    li.className = 'breadcrumb-item' + (idx === trail.length-1 ? ' active' : '');
    if (idx === trail.length-1){
      li.innerText = pid ? 'Folder' : 'root';
    } else {
      const a = document.createElement('a');
      a.href = '#';
      a.innerText = pid ? 'folder' : 'root';
      a.onclick = (e)=>{ e.preventDefault(); currentParentId = trail[idx+1]; refresh(); };
      li.appendChild(a);
    }
    bc.appendChild(li);
  });
}

// Utilities
function formatSize(n){ if (!n) return '0 B'; const units=['B','KB','MB','GB','TB']; let i=0; let v=n; while(v>=1024 && i<units.length-1){ v/=1024; i++; } return v.toFixed(1)+' '+units[i]; }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, (m)=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[m]); }

// Auto-login demo on load
window.addEventListener('load', ()=>{ if (document.getElementById('username').value === 'demo') document.getElementById('btnLogin').click(); });
</script>
</body>
</html>
"""
# -------------------------
# Routes: Frontend
# -------------------------
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
# -------------------------
# API: Authentication
# -------------------------
@app.route("/api/register", methods=["POST"])
def api_register():
    payload = request.json or {}
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return jsonify({"error": "missing"}), 400
    if get_user_by_username(username):
        return jsonify({"error": "exists"}), 400
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    user = User(username=username, password_hash=pw_hash)
    db.session.add(user)
    db.session.commit()
    # create user's root folder
    root = FileItem(name="root", parent_id=None, is_directory=True, owner_id=user.id)
    db.session.add(root)
    db.session.commit()
    return jsonify({"ok": True, "username": username})
@app.route("/api/login", methods=["POST"])
def api_login():
    payload = request.json or {}
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return jsonify({"error": "missing"}), 400
    user = get_user_by_username(username)
    if not user:
        return jsonify({"error": "invalid"}), 401
    if user.password_hash != hashlib.sha256(password.encode()).hexdigest():
        return jsonify({"error": "invalid"}), 401
    return jsonify({"ok": True, "username": user.username})
# -------------------------
# API: List items
# -------------------------
@app.route("/api/list", methods=["GET"])
def api_list():
    username = request.headers.get("X-User")
    parent_id = request.args.get("parent_id")
    # If parent_id not provided, return user's root folder
    if not parent_id:
        if not username:
            return jsonify({"error": "auth_required"}), 401
        user = get_user_by_username(username)
        if not user:
            return jsonify({"error": "auth_required"}), 401
        root = FileItem.query.filter_by(owner_id=user.id, parent_id=None, is_directory=True).first()
        if not root:
            root = FileItem(name="root", parent_id=None, is_directory=True, owner_id=user.id)
            db.session.add(root)
            db.session.commit()
        parent_id = root.id
    items = FileItem.query.filter_by(parent_id=parent_id).order_by(FileItem.is_directory.desc(), FileItem.name).all()
    result = []
    for it in items:
        result.append({
            "id": it.id,
            "name": it.name,
            "is_dir": it.is_directory,
            "size": it.size,
            "parent_id": it.parent_id,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None
        })
    return jsonify({"parent_id": parent_id, "items": result})
# -------------------------
# API: Make directory
# -------------------------
@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    user = require_simple_auth()
    payload = request.json or {}
    parent_id = payload.get("parent_id")
    name = payload.get("name") or "New Folder"
    parent = FileItem.query.filter_by(owner_id=user.id, id=parent_id, is_directory=True).first()
    if not parent:
        return jsonify({"error": "parent_not_found"}), 400
    new_folder = FileItem(name=name, parent_id=parent.id, is_directory=True, owner_id=user.id)
    db.session.add(new_folder)
    db.session.commit()
    return jsonify({"ok": True, "id": new_folder.id, "name": new_folder.name})
# -------------------------
# API: Upload file
# -------------------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    user = require_simple_auth()
    parent_id = request.form.get("parent_id")
    parent = FileItem.query.filter_by(owner_id=user.id, id=parent_id, is_directory=True).first()
    if not parent:
        return jsonify({"error": "parent_not_found"}), 400
    if "file" not in request.files:
        return jsonify({"error": "no_file"}), 400
    uploaded = request.files["file"]
    filename = secure_filename(uploaded.filename or "")
    if filename == "":
        return jsonify({"error": "empty_filename"}), 400
    user_folder = os.path.join(UPLOAD_ROOT, user.id)
    os.makedirs(user_folder, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{filename}"
    storage_path = os.path.join(user_folder, stored_name)
    uploaded.save(storage_path)
    size = os.path.getsize(storage_path)
    item = FileItem(
        name=filename,
        parent_id=parent.id,
        is_directory=False,
        size=size,
        storage_path=storage_path,
        owner_id=user.id,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"ok": True, "id": item.id, "name": item.name, "size": size})
# -------------------------
# API: Download (supports share token)
# -------------------------
@app.route("/api/download/<item_id>", methods=["GET"])
def api_download(item_id):
    username = request.headers.get("X-User")
    token = request.args.get("token")
    item = FileItem.query.filter_by(id=item_id).first()
    if not item:
        return jsonify({"error": "not_found"}), 404
    # If token provided, validate share
    if token:
        share = Share.query.with_bind("share").filter_by(token=token, item_id=item_id).first()
        if not share:
            return jsonify({"error": "share_not_found"}), 403
        if share.expires_at and share.expires_at < datetime.utcnow():
            return jsonify({"error": "expired"}), 403
    else:
        # Require owner
        if not username:
            return jsonify({"error": "auth_required"}), 401
        user = get_user_by_username(username)
        if not user or user.id != item.owner_id:
            return jsonify({"error": "forbidden"}), 403
    if item.is_directory:
        return jsonify({"error": "is_dir"}), 400
    if not item.storage_path or not os.path.exists(item.storage_path):
        return jsonify({"error": "file_missing"}), 404
    return send_file(item.storage_path, as_attachment=True, download_name=item.name)
# -------------------------
# API: Move (drag & drop)
# -------------------------
@app.route("/api/move", methods=["POST"])
def api_move():
    user = require_simple_auth()
    payload = request.json or {}
    item_id = payload.get("item_id")
    new_parent_id = payload.get("parent_id")
    item = FileItem.query.filter_by(id=item_id, owner_id=user.id).first()
    if not item:
        return jsonify({"error": "not_found"}), 404
    if new_parent_id:
        parent = FileItem.query.filter_by(id=new_parent_id, owner_id=user.id, is_directory=True).first()
        if not parent:
            return jsonify({"error": "parent_not_found"}), 400
        # Prevent moving into self or descendant
        cur = parent
        while cur:
            if cur.id == item.id:
                return jsonify({"error": "invalid_move"}), 400
            cur = FileItem.query.filter_by(id=cur.parent_id).first()
        item.parent_id = parent.id
    else:
        root = FileItem.query.filter_by(owner_id=user.id, parent_id=None, is_directory=True).first()
        item.parent_id = root.id
    db.session.commit()
    return jsonify({"ok": True})
# -------------------------
# API: Rename
# -------------------------
@app.route("/api/rename", methods=["POST"])
def api_rename():
    user = require_simple_auth()
    payload = request.json or {}
    item_id = payload.get("item_id")
    new_name = payload.get("name")
    if not new_name:
        return jsonify({"error": "missing_name"}), 400
    item = FileItem.query.filter_by(id=item_id, owner_id=user.id).first()
    if not item:
        return jsonify({"error": "not_found"}), 404
    item.name = new_name
    db.session.commit()
    return jsonify({"ok": True})
# -------------------------
# API: Delete (recursive)
# -------------------------
@app.route("/api/delete", methods=["POST"])
def api_delete():
    user = require_simple_auth()
    payload = request.json or {}
    item_id = payload.get("item_id")
    item = FileItem.query.filter_by(id=item_id, owner_id=user.id).first()
    if not item:
        return jsonify({"error": "not_found"}), 404
    def _delete_recursive(node):
        children = FileItem.query.filter_by(parent_id=node.id).all()
        for c in children:
            _delete_recursive(c)
        if not node.is_directory and node.storage_path and os.path.exists(node.storage_path):
            try:
                os.remove(node.storage_path)
            except Exception:
                pass
        db.session.delete(node)
    _delete_recursive(item)
    db.session.commit()
    return jsonify({"ok": True})
# -------------------------
# API: Share create / cancel / list
# -------------------------
@app.route("/api/share", methods=["POST"])
def api_share_create():
    user = require_simple_auth()
    payload = request.json or {}
    item_id = payload.get("item_id")
    expires_days = payload.get("expires_days")
    item = FileItem.query.filter_by(id=item_id, owner_id=user.id).first()
    if not item:
        return jsonify({"error": "not_found"}), 404
    token = uuid.uuid4().hex
    expires_at = None
    if expires_days:
        try:
            days = int(expires_days)
            expires_at = datetime.utcnow() + timedelta(days=days)
        except Exception:
            pass
    share = Share(item_id=item_id, token=token, expires_at=expires_at)
    db.session.add(share)
    db.session.commit()
    return jsonify({"ok": True, "token": token, "link": f"/api/download/{item_id}?token={token}"})
@app.route("/api/unshare", methods=["POST"])
def api_share_cancel():
    user = require_simple_auth()
    payload = request.json or {}
    token = payload.get("token")
    if not token:
        return jsonify({"error": "missing"}), 400
    share = Share.query.with_bind("share").filter_by(token=token).first()
    if not share:
        return jsonify({"error": "not_found"}), 404
    item = FileItem.query.filter_by(id=share.item_id).first()
    if not item or item.owner_id != user.id:
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(share)
    db.session.commit()
    return jsonify({"ok": True})
@app.route("/api/shares", methods=["GET"])
def api_list_shares():
    user = require_simple_auth()
    shares = Share.query.with_bind("share").all()
    result = []
    for s in shares:
        item = FileItem.query.filter_by(id=s.item_id, owner_id=user.id).first()
        if item:
            result.append({
                "token": s.token,
                "item_id": s.item_id,
                "name": item.name,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None
            })
    return jsonify(result)
# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
