
import shutil,os
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort, render_template_string
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Root storage directory (absolute path)
STORAGE_ROOT = Path(__file__).resolve().parent / "data"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

# Max upload size (bytes)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

# --------------------------
# Backend helper functions
# --------------------------
def resolve_path(relative_path: str) -> Path:
    """
    Resolve a user-provided relative path into a safe absolute Path
    under STORAGE_ROOT to prevent directory traversal.
    """
    if not relative_path:
        candidate_path = STORAGE_ROOT
    else:
        rp = Path(relative_path)
        # If an absolute path was given, drop the anchor to treat it as relative
        if rp.is_absolute():
            rp = rp.relative_to(rp.anchor)
        candidate_path = (STORAGE_ROOT / rp).resolve()
    try:
        # Ensure the resolved path is inside STORAGE_ROOT
        candidate_path.relative_to(STORAGE_ROOT.resolve())
    except Exception:
        abort(400, description="Invalid path")
    return candidate_path


def list_directory_contents(directory_path: Path, recursive: bool = False):
    """
    List directory contents. Returns a list of dicts with:
      - name: entry name
      - path: path relative to STORAGE_ROOT (using forward slashes)
      - type: "file" or "dir"
      - size: file size in bytes (only for files; None on error)
    If recursive=True, list all nested items (flat list).
    """
    items = []
    root_path = directory_path.resolve()
    iterator = root_path.rglob('*') if recursive else root_path.iterdir()
    for p in iterator:
        rel_path = p.relative_to(STORAGE_ROOT)
        item = {
            "name": p.name,
            "path": str(rel_path).replace(os.sep, "/"),
            "type": "dir" if p.is_dir() else "file"
        }
        if p.is_file():
            try:
                item["size"] = p.stat().st_size
            except Exception:
                item["size"] = None
        items.append(item)
    return items

# --------------------------
# API routes (unchanged)
# --------------------------
@app.route("/list", methods=["GET"])
def api_list():
    """
    List directory contents.
    Query parameters:
      - path: directory path relative to STORAGE_ROOT (optional; default root)
      - recursive: '1' or 'true' for recursive listing
    """
    relative_path = request.args.get("path", "")
    recursive_flag = request.args.get("recursive", "0").lower() in ("1", "true", "yes")
    target_path = resolve_path(relative_path)
    if not target_path.exists():
        return jsonify({"error": "path not found"}), 404
    if not target_path.is_dir():
        return jsonify({"error": "not a directory"}), 400
    items = list_directory_contents(target_path, recursive=recursive_flag)
    return jsonify({"path": str(Path(relative_path)), "items": items})


@app.route("/upload", methods=["POST"])
def api_upload():
    """
    Upload files (multipart/form-data).
    Form fields:
      - file: file(s) to upload (can appear multiple times)
      - path: target directory relative to STORAGE_ROOT (optional; default root)
      - overwrite: '1' or 'true' to overwrite existing files (default false)
    """
    if 'file' not in request.files:
        return jsonify({"error": "no file part"}), 400
    relative_dir = request.form.get("path", "")
    overwrite_flag = request.form.get("overwrite", "0").lower() in ("1", "true", "yes")
    target_directory = resolve_path(relative_dir)
    if not target_directory.exists():
        try:
            target_directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"cannot create directory: {e}"}), 500
    if not target_directory.is_dir():
        return jsonify({"error": "target path is not a directory"}), 400

    uploaded_files = []
    upload_errors = []
    uploaded_file_list = request.files.getlist("file")
    for upload_file in uploaded_file_list:
        safe_filename = secure_filename(upload_file.filename)
        if safe_filename == "":
            upload_errors.append({"filename": None, "error": "empty filename"})
            continue
        destination_path = target_directory / safe_filename
        if destination_path.exists() and not overwrite_flag:
            upload_errors.append({"filename": safe_filename, "error": "file exists"})
            continue
        try:
            upload_file.save(str(destination_path))
            uploaded_files.append({
                "filename": safe_filename,
                "path": str(destination_path.relative_to(STORAGE_ROOT)).replace(os.sep, "/")
            })
        except Exception as e:
            upload_errors.append({"filename": safe_filename, "error": str(e)})
    return jsonify({"uploaded": uploaded_files, "errors": upload_errors})


@app.route("/download", methods=["GET"])
def api_download():
    """
    Download a file.
    Query parameters:
      - path: file path relative to STORAGE_ROOT (required)
      - as_name: optional filename for the downloaded attachment
    """
    relative_path = request.args.get("path")
    if not relative_path:
        return jsonify({"error": "path required"}), 400
    target_file_path = resolve_path(relative_path)
    if not target_file_path.exists() or not target_file_path.is_file():
        return jsonify({"error": "file not found"}), 404
    download_as_name = request.args.get("as_name")
    try:
        # Flask >= 2.0 uses download_name
        return send_file(str(target_file_path), as_attachment=True, download_name=download_as_name)
    except TypeError:
        # Fallback for older Flask versions
        return send_file(str(target_file_path), as_attachment=True, attachment_filename=download_as_name)


@app.route("/delete", methods=["POST"])
def api_delete():
    """
    Delete a file or directory.
    JSON body:
      - path: target path relative to STORAGE_ROOT (required)
      - recursive: true/false; if true, recursively delete non-empty directories (default false)
    """
    request_data = request.get_json(force=True, silent=True) or {}
    relative_path = request_data.get("path")
    if not relative_path:
        return jsonify({"error": "path required"}), 400
    recursive_flag = bool(request_data.get("recursive", False))
    target_path = resolve_path(relative_path)
    if not target_path.exists():
        return jsonify({"error": "not found"}), 404
    try:
        if target_path.is_file():
            target_path.unlink()
        elif target_path.is_dir():
            if any(target_path.iterdir()) and not recursive_flag:
                return jsonify({"error": "directory not empty, set recursive=true to remove"}), 400
            shutil.rmtree(target_path)
        else:
            return jsonify({"error": "unsupported file type"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"deleted": str(Path(relative_path)).replace(os.sep, "/")})


@app.route("/rename", methods=["POST"])
def api_rename():
    """
    Rename or move a file/directory within STORAGE_ROOT.
    JSON body:
      - src: source path relative to STORAGE_ROOT (required)
      - dst: destination path relative to STORAGE_ROOT (required)
            If dst ends with '/' or refers to a directory, the source name is preserved.
      - overwrite: if true and destination exists, it will be removed first (default false)
    """
    request_data = request.get_json(force=True, silent=True) or {}
    src_relative = request_data.get("src")
    dst_relative = request_data.get("dst")
    overwrite_flag = bool(request_data.get("overwrite", False))
    if not src_relative or not dst_relative:
        return jsonify({"error": "src and dst required"}), 400
    src_path = resolve_path(src_relative)
    dst_path = resolve_path(dst_relative)

    if not src_path.exists():
        return jsonify({"error": "src not found"}), 404

    # If dst looks like a directory or exists as a directory, move inside it preserving the source name
    dst_is_dir_by_syntax = dst_relative.endswith("/") or dst_relative.endswith("\\")
    if dst_is_dir_by_syntax or (dst_path.exists() and dst_path.is_dir()):
        dst_path = dst_path / src_path.name

    # Prevent moving a directory into one of its own subdirectories
    try:
        if dst_path.resolve().is_relative_to(src_path.resolve()):
            return jsonify({"error": "cannot move into subpath of source"}), 400
    except Exception:
        pass

    if dst_path.exists():
        if not overwrite_flag:
            return jsonify({"error": "destination exists"}), 400
        try:
            if dst_path.is_file():
                dst_path.unlink()
            else:
                shutil.rmtree(dst_path)
        except Exception as e:
            return jsonify({"error": f"cannot remove existing destination: {e}"}), 500

    # Ensure destination parent directory exists
    dst_parent = dst_path.parent
    dst_parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(src_path), str(dst_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "moved": {
            "src": str(Path(src_relative)).replace(os.sep, "/"),
            "dst": str(dst_path.relative_to(STORAGE_ROOT)).replace(os.sep, "/")
        }
    })


@app.route("/mkdir", methods=["POST"])
def api_mkdir():
    """
    Create a directory.
    JSON body:
      - path: directory path relative to STORAGE_ROOT (required)
      - exist_ok: if true, do not error when directory already exists (default true)
    """
    request_data = request.get_json(force=True, silent=True) or {}
    relative_path = request_data.get("path")
    exist_ok_flag = bool(request_data.get("exist_ok", True))
    if not relative_path:
        return jsonify({"error": "path required"}), 400
    target_directory = resolve_path(relative_path)
    try:
        target_directory.mkdir(parents=True, exist_ok=exist_ok_flag)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"created": str(Path(relative_path)).replace(os.sep, "/")})

# --------------------------
# Single-file frontend route
# --------------------------
INDEX_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>文件管理</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding-top: 56px; }
    .file-row:hover { background: #f8f9fa; }
    .monospace { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, "Roboto Mono", "Courier New", monospace; }
    .small-muted { font-size: 0.85rem; color: #6c757d; }
    #file-list { max-height: 60vh; overflow: auto; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="#">文件管理</a>
    <div class="d-flex align-items-center">
      <div class="text-white me-3 monospace" id="current-path">/</div>
      <button class="btn btn-outline-light btn-sm" id="btn-refresh">刷新</button>
    </div>
  </div>
</nav>

<div class="container mt-3">
  <div class="row g-3">
    <div class="col-md-4">
      <div class="card">
        <div class="card-body">
          <h5 class="card-title">浏览</h5>
          <div class="mb-2">
            <label class="form-label">路径</label>
            <input id="input-path" class="form-control" placeholder="" />
          </div>
          <div class="mb-2 form-check">
            <input class="form-check-input" type="checkbox" id="input-recursive">
            <label class="form-check-label" for="input-recursive">递归列出</label>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary" id="btn-list">列出</button>
            <button class="btn btn-secondary" id="btn-up">上级</button>
            <button class="btn btn-success" id="btn-mkdir" data-bs-toggle="modal" data-bs-target="#mkdirModal">新建文件夹</button>
          </div>
        </div>
      </div>

      <div class="card mt-3">
        <div class="card-body">
          <h5 class="card-title">上传</h5>
          <form id="upload-form">
            <div class="mb-2">
              <input type="file" id="upload-files" name="file" multiple class="form-control" />
            </div>
            <div class="mb-2 form-check">
              <input class="form-check-input" type="checkbox" id="upload-overwrite">
              <label class="form-check-label" for="upload-overwrite">覆盖同名文件</label>
            </div>
            <div class="d-grid">
              <button class="btn btn-primary" type="submit">上传到当前路径</button>
            </div>
          </form>
        </div>
      </div>

      <div class="card mt-3">
        <div class="card-body">
          <h5 class="card-title">操作</h5>
          <div class="mb-2">
            <input id="selected-path" class="form-control" placeholder="选中文件/目录路径" readonly />
          </div>
          <div class="d-grid gap-2">
            <button class="btn btn-outline-danger" id="btn-delete">删除</button>
            <button class="btn btn-outline-secondary" id="btn-download">下载（文件）</button>
            <button class="btn btn-outline-warning" id="btn-rename" data-bs-toggle="modal" data-bs-target="#renameModal">重命名/移动</button>
          </div>
        </div>
      </div>

    </div>

    <div class="col-md-8">
      <div class="card">
        <div class="card-body">
          <h5 class="card-title">文件列表</h5>
          <div id="file-list" class="list-group">
            <!-- items injected here -->
          </div>
        </div>
      </div>
      <div class="mt-2 small-muted">提示：点击列表项以选择；双击目录以进入。</div>
    </div>
  </div>
</div>

<!-- Modals -->
<div class="modal fade" id="mkdirModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form class="modal-content" id="mkdir-form">
      <div class="modal-header">
        <h5 class="modal-title">新建文件夹</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="关闭"></button>
      </div>
      <div class="modal-body">
        <label class="form-label">文件夹名（相对于当前路径）</label>
        <input class="form-control" id="mkdir-name" placeholder="例如: new-folder" required />
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
        <button type="submit" class="btn btn-primary">创建</button>
      </div>
    </form>
  </div>
</div>

<div class="modal fade" id="renameModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form class="modal-content" id="rename-form">
      <div class="modal-header">
        <h5 class="modal-title">重命名 / 移动</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="关闭"></button>
      </div>
      <div class="modal-body">
        <label class="form-label">目标路径（相对于存储根）</label>
        <input class="form-control" id="rename-dst" placeholder="例如: folder/newname.txt 或 folder/" required />
        <div class="form-check mt-2">
          <input class="form-check-input" type="checkbox" id="rename-overwrite">
          <label class="form-check-label" for="rename-overwrite">若存在则覆盖</label>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
        <button type="submit" class="btn btn-primary">确定</button>
      </div>
    </form>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const api = {
  list: (path='', recursive=false) => fetch('/list?path='+encodeURIComponent(path)+'&recursive='+(recursive?1:0)).then(r=>r.json()),
  upload: (formData) => fetch('/upload', { method: 'POST', body: formData }).then(r=>r.json()),
  downloadUrl: (path) => '/download?path='+encodeURIComponent(path),
  delete: (path, recursive=false) => fetch('/delete', { method: 'POST', headers: {'Content-Type':'application/json}, body: JSON.stringify({path, recursive}) }).then(r=>r.json()),
  mkdir: (path) => fetch('/mkdir', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path}) }).then(r=>r.json()),
  rename: (src, dst, overwrite=false) => fetch('/rename', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({src, dst, overwrite}) }).then(r=>r.json())
};

let currentPath = '';
const el = (id) => document.getElementById(id);

function setCurrentPath(p) {
  currentPath = p || '';
  el('current-path').textContent = currentPath === '' ? '/' : '/' + currentPath;
  el('input-path').value = currentPath;
}

function loadList() {
  const recursive = el('input-recursive').checked;
  const path = el('input-path').value.trim().replace(/^\/+|\/+$/g, '');
  api.list(path, recursive).then(data => {
    if (data.error) { alert(data.error); return; }
    setCurrentPath(path);
    renderList(data.items || []);
  }).catch(e => alert('请求失败: '+e));
}

function renderList(items) {
  const container = el('file-list');
  container.innerHTML = '';
  // sort dirs first then files
  items.sort((a,b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  for (const it of items) {
    const div = document.createElement('button');
    div.type = 'button';
    div.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center file-row';
    div.dataset.path = it.path;
    const left = document.createElement('div');
    left.className = 'text-start';
    const title = document.createElement('div');
    title.className = it.type === 'dir' ? 'fw-semibold' : '';
    title.textContent = it.name;
    const sub = document.createElement('div');
    sub.className = 'small-muted';
    sub.textContent = it.type === 'dir' ? '目录 — ' + it.path : '文件 — ' + it.path + (it.size!=null?(' — '+it.size+' 字节'):'');
    left.appendChild(title);
    left.appendChild(sub);
    const right = document.createElement('div');
    if (it.type === 'file') {
      const dl = document.createElement('a');
      dl.className = 'btn btn-sm btn-outline-primary';
      dl.textContent = '下载';
      dl.href = api.downloadUrl(it.path);
      dl.target = '_blank';
      right.appendChild(dl);
    } else {
      const enter = document.createElement('button');
      enter.className = 'btn btn-sm btn-outline-secondary';
      enter.textContent = '进入';
      enter.onclick = (ev) => {
        ev.stopPropagation();
        const newPath = it.path;
        setCurrentPath(newPath);
        el('input-recursive').checked = false;
        loadList();
      };
      right.appendChild(enter);
    }
    div.appendChild(left);
    div.appendChild(right);

    // click to select
    div.addEventListener('click', () => {
      document.querySelectorAll('.file-row').forEach(r=>r.classList.remove('active'));
      div.classList.add('active');
      el('selected-path').value = it.path;
    });

    // double click: if dir, enter; if file, trigger download
    div.addEventListener('dblclick', () => {
      if (it.type === 'dir') {
        setCurrentPath(it.path);
        el('input-recursive').checked = false;
        loadList();
      } else {
        window.open(api.downloadUrl(it.path), '_blank');
      }
    });

    container.appendChild(div);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setCurrentPath('');
  loadList();

  el('btn-refresh').addEventListener('click', loadList);
  el('btn-list').addEventListener('click', () => {
    setCurrentPath(el('input-path').value.trim().replace(/^\/+|\/+$/g, ''));
    loadList();
  });
  el('btn-up').addEventListener('click', () => {
    const p = currentPath;
    if (!p) return;
    const parts = p.split('/').filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join('/'));
    loadList();
  });

  // upload
  el('upload-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const files = el('upload-files').files;
    if (!files.length) { alert('请选择文件'); return; }
    const fd = new FormData();
    for (const f of files) fd.append('file', f);
    fd.append('path', currentPath);
    if (el('upload-overwrite').checked) fd.append('overwrite', '1');
    api.upload(fd).then(res => {
      if (res.errors && res.errors.length) {
        alert('部分文件上传失败：' + JSON.stringify(res.errors));
      } else {
        alert('上传成功');
      }
      loadList();
    }).catch(e => alert('上传失败: '+e));
  });

  // delete
  el('btn-delete').addEventListener('click', () => {
    const p = el('selected-path').value.trim();
    if (!p) { alert('先选择要删除的项'); return; }
    if (!confirm('确认删除：' + p + ' ?')) return;
    const rec = confirm('如果是非空目录，是否递归删除？ 点击“确定”表示递归删除。') ? true : false;
    api.delete(p, rec).then(res => {
      if (res.error) alert('删除失败：' + res.error); else alert('已删除：' + res.deleted);
      el('selected-path').value = '';
      loadList();
    }).catch(e => alert('删除请求失败：' + e));
  });

  // download button (uses selected path)
  el('btn-download').addEventListener('click', () => {
    const p = el('selected-path').value.trim();
    if (!p) { alert('先选择要下载的文件'); return; }
    window.open(api.downloadUrl(p), '_blank');
  });

  // mkdir
  el('mkdir-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const name = el('mkdir-name').value.trim();
    if (!name) return alert('请输入文件夹名');
    const target = (currentPath ? currentPath + '/' : '') + name;
    api.mkdir(target).then(res => {
      if (res.error) alert('创建失败：' + res.error); else alert('已创建：' + res.created);
      el('mkdir-name').value = '';
      var modal = bootstrap.Modal.getInstance(document.getElementById('mkdirModal'));
      modal.hide();
      loadList();
    }).catch(e => alert('请求失败：' + e));
  });

  // rename
  el('rename-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const src = el('selected-path').value.trim();
    if (!src) return alert('先选择要重命名/移动的项');
    const dst = el('rename-dst').value.trim();
    if (!dst) return alert('请输入目标路径');
    const overwrite = el('rename-overwrite').checked;
    api.rename(src, dst, overwrite).then(res => {
      if (res.error) alert('操作失败：' + res.error); else alert('已移动：' + JSON.stringify(res.moved));
      var modal = bootstrap.Modal.getInstance(document.getElementById('renameModal'));
      modal.hide();
      el('selected-path').value = '';
      loadList();
    }).catch(e => alert('请求失败：' + e));
  });

});
</script>
</body>
</html>
