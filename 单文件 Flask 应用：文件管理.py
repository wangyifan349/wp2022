#!/usr/bin/env python3
"""
单文件 Flask 应用：文件管理 + 分享（SQLite3）
保存为 app.py 后运行：python app.py
依赖：Flask（pip install flask）
"""

from flask import (
    Flask, request, jsonify, send_file, render_template_string,
    abort, url_for
)
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import shutil
import uuid
import sqlite3
import json
import datetime

# -----------------------
# 配置
# -----------------------
BASE_DIR = Path(__file__).parent.resolve()
STORAGE_ROOT = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "shares.db"
APP_HOST = "0.0.0.0"
APP_PORT = 5000
DEBUG = True

# 创建存储目录
os.makedirs(STORAGE_ROOT, exist_ok=True)

app = Flask(__name__)

# -----------------------
# 数据库（SQLite） 辅助
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        path TEXT NOT NULL,
        link TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        note TEXT
    )
    """)
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetch=False, fetchone=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    rv = None
    if fetch:
        rv = c.fetchall()
    elif fetchone:
        rv = c.fetchone()
    conn.commit()
    conn.close()
    return rv

init_db()

# -----------------------
# 工具函数
# -----------------------
def is_safe_path(base: Path, target: Path) -> bool:
    """确保 target 在 base 下，防止路径穿越"""
    try:
        base_res = base.resolve()
        target_res = target.resolve()
        return str(target_res).startswith(str(base_res))
    except Exception:
        return False

def make_rel_path(p: Path) -> str:
    return str(p.relative_to(STORAGE_ROOT)).replace("\\", "/")

def ensure_dir_for(path: Path):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

def iso_to_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None

# -----------------------
# 路由：前端页面（内嵌模板）
# -----------------------
INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>文件管理（单文件示例）</title>
  <style>
    body { font-family: Arial, Helvetica, sans-serif; margin:20px; }
    .file, .dir { padding:6px; border:1px solid #ddd; margin:4px; display:inline-block; cursor:grab; }
    .folder { padding:8px; border:1px dashed #aaa; min-height:60px; margin:6px; }
    .controls { margin-bottom:10px; }
    .small { font-size:0.9em; color:#555; }
    .btn { padding:6px 10px; margin-right:6px; }
    .item-row { display:flex; align-items:center; gap:8px; margin:4px 0; }
  </style>
</head>
<body>
<h2>文件管理（单文件示例）</h2>

<div class="controls">
  <input type="file" id="fileInput" multiple>
  <button class="btn" id="uploadBtn">上传到当前目录</button>
  <button class="btn" id="refreshBtn">刷新</button>
  <span class="small">当前路径：<span id="curPath">/</span></span>
</div>

<hr>

<div id="breadcrumbs"></div>
<div id="tree"></div>

<div id="msg"></div>

<script>
const api = path => '/api/' + path;
let currentPath = ''; // 相对 storage 根，空表示根

async function refresh(path='') {
  currentPath = path || '';
  document.getElementById('curPath').textContent = '/' + currentPath;
  renderBreadcrumbs(currentPath);
  const res = await fetch('/api/list?path=' + encodeURIComponent(currentPath));
  if (!res.ok) {
    const j = await res.json();
    alert('错误: ' + (j.error || res.status));
    return;
  }
  const json = await res.json();
  renderNode(json);
}

function renderBreadcrumbs(path) {
  const container = document.getElementById('breadcrumbs');
  container.innerHTML = '';
  const parts = path ? path.split('/') : [];
  let acc = '';
  const rootBtn = document.createElement('button');
  rootBtn.textContent = '根目录';
  rootBtn.onclick = () => refresh('');
  container.appendChild(rootBtn);
  for (let i=0;i<parts.length;i++){
    acc = acc ? acc + '/' + parts[i] : parts[i];
    const btn = document.createElement('button');
    btn.textContent = parts[i];
    btn.onclick = () => refresh(acc);
    container.appendChild(btn);
  }
}

function renderNode(node) {
  const container = document.getElementById('tree');
  container.innerHTML = '';

  if (node.type === 'dir') {
    // 操作条：新建文件夹、上传到此目录
    const ops = document.createElement('div');
    ops.innerHTML = `
      <div style="margin-bottom:8px;">
        <input id="newFolderName" placeholder="新建文件夹名称">
        <button id="mkdirBtn">新建文件夹</button>
        <button id="shareThisBtn">分享此目录</button>
      </div>
    `;
    container.appendChild(ops);
    document.getElementById('mkdirBtn').onclick = async () => {
      const name = document.getElementById('newFolderName').value.trim();
      if (!name) return alert('请输入名称');
      const r = await fetch(api('mkdir'), {
        method:'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path: node.path, name})
      });
      const j = await r.json();
      if (r.ok) refresh(node.path);
      else alert('错误: ' + (j.error || r.status));
    };
    document.getElementById('shareThisBtn').onclick = async () => {
      const expires = prompt('可选：输入过期时间（UTC ISO，例如 2025-09-30T12:00:00），留空表示不过期');
      const r = await fetch(api('share'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({path: node.path, expires: expires || null})
      });
      const j = await r.json();
      if (r.ok) {
        alert('分享链接: ' + j.link);
        refresh(node.path);
      } else alert('错误: ' + (j.error || JSON.stringify(j)));
    };

    // 列出子项（可拖拽移动到文件夹）
    const box = document.createElement('div');
    box.className = 'folder';
    box.dataset.path = node.path || '';
    box.ondrop = async (e) => {
      e.preventDefault();
      const src = e.dataTransfer.getData('text/plain');
      await fetch(api('move'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({src:src, dest: (node.path ? node.path + '/' : '')})});
      refresh(node.path);
    };
    box.ondragover = e => e.preventDefault();

    // show children (dirs first)
    (node.children || []).forEach(c => {
      const child = renderItem(c);
      box.appendChild(child);
    });
    container.appendChild(box);

    // 分享列表查看与取消
    const shareListBtn = document.createElement('button');
    shareListBtn.textContent = '查看本目录分享';
    shareListBtn.onclick = async () => {
      const r = await fetch(api('shares_for_path') + '?path=' + encodeURIComponent(node.path));
      const j = await r.json();
      if (!r.ok) { alert('错误: ' + (j.error || r.status)); return; }
      if (!j.shares.length) { alert('无分享条目'); return; }
      let txt = '分享列表:\\n';
      j.shares.forEach(s => {
        txt += `${s.id} | ${s.link} | expires=${s.expires_at}\\n`;
      });
      const id = prompt(txt + '\\n输入要取消分享的 id（留空取消）');
      if (id) {
        const rr = await fetch(api('unshare'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(id)})});
        const jj = await rr.json();
        if (rr.ok) alert('已取消: ' + JSON.stringify(jj));
        else alert('错误: ' + (jj.error || rr.status));
        refresh(node.path);
      }
    };
    container.appendChild(shareListBtn);
  }
}

function renderItem(n) {
  const el = document.createElement('div');
  el.className = 'item-row';
  if (n.type === 'dir') {
    const nameBtn = document.createElement('button');
    nameBtn.textContent = '📁 ' + n.name;
    nameBtn.onclick = () => refresh(n.path);
    el.appendChild(nameBtn);

    const shareBtn = document.createElement('button');
    shareBtn.textContent = '分享';
    shareBtn.onclick = async () => {
      const expires = prompt('可选：输入过期时间（UTC ISO，例如 2025-09-30T12:00:00），留空表示不过期');
      const r = await fetch(api('share'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({path: n.path, expires: expires || null})
      });
      const j = await r.json();
      if (r.ok) alert('分享链接: ' + j.link);
      else alert('错误: ' + (j.error || JSON.stringify(j)));
    };
    el.appendChild(shareBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = '删除';
    delBtn.onclick = async () => {
      if (!confirm('删除此文件夹及其所有内容？')) return;
      const r = await fetch(api('delete'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: n.path})});
      const j = await r.json();
      if (r.ok) refresh(currentPath); else alert('错误: ' + (j.error || JSON.stringify(j)));
    };
    el.appendChild(delBtn);

    // make droppable target
    const box = document.createElement('div');
    box.className = 'dir';
    box.textContent = '';
    box.ondrop = async (e) => {
      e.preventDefault();
      const src = e.dataTransfer.getData('text/plain');
      await fetch(api('move'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({src: src, dest: n.path + '/'})});
      refresh(currentPath);
    };
    box.ondragover = e => e.preventDefault();

    el.appendChild(box);
  } else {
    const nameSpan = document.createElement('span');
    nameSpan.textContent = n.name;
    el.appendChild(nameSpan);

    const dl = document.createElement('button');
    dl.textContent = '下载';
    dl.onclick = () => { location.href = '/api/download?path=' + encodeURIComponent(n.path); };
    el.appendChild(dl);

    const shareBtn = document.createElement('button');
    shareBtn.textContent = '分享';
    shareBtn.onclick = async () => {
      const expires = prompt('可选：输入过期时间（UTC ISO，例如 2025-09-30T12:00:00），留空表示不过期');
      const r = await fetch(api('share'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({path: n.path, expires: expires || null})
      });
      const j = await r.json();
      if (r.ok) alert('分享链接: ' + j.link);
      else alert('错误: ' + (j.error || JSON.stringify(j)));
    };
    el.appendChild(shareBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = '删除';
    delBtn.onclick = async () => {
      if (!confirm('删除此文件？')) return;
      const r = await fetch(api('delete'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: n.path})});
      const j = await r.json();
      if (r.ok) refresh(currentPath); else alert('错误: ' + (j.error || JSON.stringify(j)));
    };
    el.appendChild(delBtn);

    el.draggable = true;
    el.ondragstart = e => {
      e.dataTransfer.setData('text/plain', n.path);
    };
  }
  return el;
}

document.getElementById('uploadBtn').addEventListener('click', async () => {
  const files = document.getElementById('fileInput').files;
  if (!files.length) return alert('请选择文件');
  const fd = new FormData();
  for (const f of files) fd.append('file', f);
  fd.append('path', currentPath);
  const r = await fetch('/api/upload', { method:'POST', body: fd });
  const j = await r.json();
  if (r.ok) {
    alert('上传完成: ' + JSON.stringify(j.created));
    refresh(currentPath);
  } else alert('错误: ' + (j.error || JSON.stringify(j)));
});

document.getElementById('refreshBtn').addEventListener('click', () => refresh(currentPath));

refresh('');
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

# -----------------------
# API：列出（树形）
# -----------------------
@app.route("/api/list", methods=["GET"])
def api_list():
    rel = request.args.get("path", "").strip("/")
    target = (STORAGE_ROOT / rel) if rel else STORAGE_ROOT
    if not is_safe_path(STORAGE_ROOT, target):
        return jsonify({"error": "invalid path"}), 400
    if not target.exists():
        return jsonify({"error": "not found"}), 404

    def node(p: Path):
        entry = {"name": p.name, "path": make_rel_path(p) if p != STORAGE_ROOT else "", "type": "dir" if p.is_dir() else "file"}
        if p.is_dir():
            children = []
            try:
                for c in p.iterdir():
                    children.append(node(c))
            except PermissionError:
                pass
            # dirs first, then files, alphabetically
            entry["children"] = sorted(children, key=lambda x: (x["type"] != "dir", x["name"].lower()))
        else:
            entry["size"] = p.stat().st_size
        return entry

    # for root we want name maybe storage root; set name to '/'
    root_node = node(target)
    if target == STORAGE_ROOT:
        root_node["name"] = ""
        root_node["path"] = ""
    return jsonify(root_node)

# -----------------------
# API：上传
# -----------------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    path = request.form.get("path", "").strip("/")
    target_dir = STORAGE_ROOT / path if path else STORAGE_ROOT
    if not is_safe_path(STORAGE_ROOT, target_dir):
        return jsonify({"error": "invalid path"}), 400
    ensure_dir_for(target_dir / "dummy")
    files = request.files.getlist("file")
    created = []
    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            continue
        dest = target_dir / filename
        # 若存在同名，加随机后缀
        if dest.exists():
            base, ext = os.path.splitext(filename)
            dest = target_dir / f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        f.save(dest)
        created.append(make_rel_path(dest))
    return jsonify({"created": created})

# -----------------------
# API：mkdir
# -----------------------
@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    data = request.get_json() or {}
    path = (data.get("path") or "").strip("/")
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "no name"}), 400
    target = STORAGE_ROOT / path / secure_filename(name)
    if not is_safe_path(STORAGE_ROOT, target):
        return jsonify({"error": "invalid path"}), 400
    target.mkdir(parents=True, exist_ok=True)
    return jsonify({"created": make_rel_path(target)})

# -----------------------
# API：下载
# -----------------------
@app.route("/api/download", methods=["GET"])
def api_download():
    rel = request.args.get("path", "")
    rel = rel.strip("/")
    target = STORAGE_ROOT / rel
    if not is_safe_path(STORAGE_ROOT, target) or not target.exists() or target.is_dir():
        return jsonify({"error": "not found"}), 404
    # send_file with download_name requires flask>=2.0
    return send_file(str(target), as_attachment=True, download_name=target.name)

# -----------------------
# API：删除
# -----------------------
@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip("/")
    target = STORAGE_ROOT / rel
    if not is_safe_path(STORAGE_ROOT, target) or not target.exists():
        return jsonify({"error": "not found"}), 404
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return jsonify({"deleted": rel})

# -----------------------
# API：移动/重命名（拖拽）
# -----------------------
@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json() or {}
    src = (data.get("src") or "").strip("/")
    dest = (data.get("dest") or "").strip("/")
    src_p = STORAGE_ROOT / src
    dest_p = STORAGE_ROOT / dest
    # 若 dest 以斜杠结尾或是目录，则目标为 dest/src_name
    if dest.endswith("/") or dest == "":
        dest_p = dest_p / src_p.name
    if not (is_safe_path(STORAGE_ROOT, src_p) and is_safe_path(STORAGE_ROOT, dest_p)):
        return jsonify({"error": "invalid path"}), 400
    if not src_p.exists():
        return jsonify({"error": "source not found"}), 404
    ensure_dir_for(dest_p)
    if dest_p.exists():
        dest_p = dest_p.with_name(dest_p.stem + "_" + uuid.uuid4().hex[:6] + dest_p.suffix)
    shutil.move(str(src_p), str(dest_p))
    return jsonify({"moved": make_rel_path(dest_p)})

# -----------------------
# API：分享（保存到 SQLite）
# -----------------------
@app.route("/api/share", methods=["POST"])
def api_share():
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip("/")
    expires = data.get("expires")  # 可 None 或 ISO 字符串
    note = data.get("note")
    target = STORAGE_ROOT / rel if rel else STORAGE_ROOT
    if not is_safe_path(STORAGE_ROOT, target) or not target.exists():
        return jsonify({"error": "not found"}), 404
    token = uuid.uuid4().hex
    link = url_for("share_access", token=token, _external=True)
    created_at = now_iso()
    # 存入数据库
    db_execute(
        "INSERT INTO shares (token, path, link, created_at, expires_at, note) VALUES (?, ?, ?, ?, ?, ?)",
        (token, make_rel_path(target), link, created_at, expires, note)
    )
    # 返回条目信息（包含 token 与 link）
    return jsonify({"token": token, "link": link, "path": make_rel_path(target), "created_at": created_at, "expires": expires})

# -----------------------
# API：取消分享（按 id 或 token）
# -----------------------
@app.route("/api/unshare", methods=["POST"])
def api_unshare():
    data = request.get_json() or {}
    item_id = data.get("id")
    token = data.get("token")
    if item_id:
        # 先确认存在
        row = db_execute("SELECT id FROM shares WHERE id=?",(item_id,), fetchone=True)
        if not row:
            return jsonify({"error":"id not found"}), 404
        db_execute("DELETE FROM shares WHERE id=?", (item_id,))
        return jsonify({"unshared_id": item_id})
    elif token:
        row = db_execute("SELECT id FROM shares WHERE token=?", (token,), fetchone=True)
        if not row:
            return jsonify({"error":"token not found"}), 404
        db_execute("DELETE FROM shares WHERE token=?", (token,))
        return jsonify({"unshared_token": token})
    else:
        return jsonify({"error":"no id or token provided"}), 400

# -----------------------
# API：通过路径查看分享（用于前端显示某路径的分享记录）
# -----------------------
@app.route("/api/shares_for_path", methods=["GET"])
def api_shares_for_path():
    path = (request.args.get("path") or "").strip("/")
    if path == "":
        path = ""  # root stored as ""
    rows = db_execute("SELECT id, token, path, link, created_at, expires_at, note FROM shares WHERE path LIKE ? ORDER BY created_at DESC", (path,), fetch=True)
    shares = []
    for r in rows:
        shares.append({
            "id": r[0], "token": r[1], "path": r[2], "link": r[3], "created_at": r[4], "expires_at": r[5], "note": r[6]
        })
    return jsonify({"shares": shares})

# -----------------------
# 访问分享链接
# -----------------------
@app.route("/s/<token>", methods=["GET"])
def share_access(token):
    row = db_execute("SELECT id, token, path, link, created_at, expires_at FROM shares WHERE token=?", (token,), fetchone=True)
    if not row:
        abort(404)
    _, token, path, link, created_at, expires_at = row
    # 检查过期
    if expires_at:
        exp_dt = iso_to_dt(expires_at)
        if exp_dt and datetime.datetime.utcnow() > exp_dt:
            # 可以选择自动删除过期项，下面示例先返回 410
            # db_execute("DELETE FROM shares WHERE token=?", (token,))
            return "分享已过期", 410
    target = STORAGE_ROOT / path if path else STORAGE_ROOT
    if not target.exists():
        abort(404)
    if target.is_dir():
        # 返回 JSON 列表（目录摘要）；也可以生成 zip 并返回
        items = []
        for p in target.iterdir():
            items.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
        return jsonify({"path": path, "items": items})
    else:
        return send_file(str(target), as_attachment=True, download_name=target.name)

# -----------------------
# API：列出所有分享（管理用途）
# -----------------------
@app.route("/api/shares", methods=["GET"])
def api_shares():
    rows = db_execute("SELECT id, token, path, link, created_at, expires_at, note FROM shares ORDER BY created_at DESC", fetch=True)
    shares = []
    for r in rows:
        shares.append({
            "id": r[0], "token": r[1], "path": r[2], "link": r[3], "created_at": r[4], "expires_at": r[5], "note": r[6]
        })
    return jsonify({"shares": shares})

# -----------------------
# 启动
# -----------------------
if __name__ == "__main__":
    print(f"Storage root: {STORAGE_ROOT}")
    print(f"SQLite DB: {DB_PATH}")
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG)
