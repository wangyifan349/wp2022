import os
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template, abort
from werkzeug.utils import secure_filename
import mimetypes

# 配置
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, 'uploads')
MAX_CONTENT_LENGTH = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.txt', '.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip'}

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['UPLOAD_ROOT'] = UPLOAD_ROOT
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

def ensure_upload_root() -> None:
    os.makedirs(app.config['UPLOAD_ROOT'], exist_ok=True)

def is_allowed_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return (not ALLOWED_EXTENSIONS) or (ext in ALLOWED_EXTENSIONS)

def safe_join(root: str, *paths: str) -> str:
    candidate = os.path.normpath(os.path.join(root, *paths))
    root_norm = os.path.normpath(root)
    if candidate == root_norm:
        return candidate
    if not candidate.startswith(root_norm + os.sep):
        raise ValueError("Attempted directory traversal")
    return candidate

@app.route('/')
def index_view():
    return render_template('index.html')

@app.route('/api/list', methods=['GET'])
def api_list_directory():
    ensure_upload_root()
    rel_path = (request.args.get('path') or '').strip('/')
    try:
        target_dir = safe_join(app.config['UPLOAD_ROOT'], rel_path)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400

    if not os.path.exists(target_dir):
        return jsonify({'path': rel_path, 'exists': False, 'directories': [], 'files': []})

    directories = []
    files = []
    with os.scandir(target_dir) as it:
        for entry in it:
            if entry.is_dir():
                directories.append(entry.name)
            elif entry.is_file():
                files.append({'name': entry.name, 'size': entry.stat().st_size})

    directories.sort()
    files.sort(key=lambda x: x['name'])
    return jsonify({'path': rel_path, 'exists': True, 'directories': directories, 'files': files})

@app.route('/api/upload', methods=['POST'])
def api_upload_files():
    ensure_upload_root()
    rel_path = (request.form.get('path') or '').strip('/')
    try:
        target_dir = safe_join(app.config['UPLOAD_ROOT'], rel_path)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400

    os.makedirs(target_dir, exist_ok=True)
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    uploaded_files = request.files.getlist('file')
    saved_items = []
    for uploaded in uploaded_files:
        if uploaded.filename == '':
            continue
        safe_name = secure_filename(uploaded.filename)
        if not is_allowed_extension(safe_name):
            return jsonify({'error': f'Blocked extension: {safe_name}'}), 400
        dest_path = os.path.join(target_dir, safe_name)
        uploaded.save(dest_path)
        saved_items.append({'name': safe_name, 'relative_path': os.path.relpath(dest_path, app.config['UPLOAD_ROOT'])})

    return jsonify({'saved': saved_items})

@app.route('/api/mkdir', methods=['POST'])
def api_make_directory():
    ensure_upload_root()
    payload = request.get_json() or {}
    rel_path = (payload.get('path') or '').strip('/')
    if rel_path == '':
        return jsonify({'error': 'Empty path'}), 400
    try:
        dir_path = safe_join(app.config['UPLOAD_ROOT'], rel_path)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400
    os.makedirs(dir_path, exist_ok=True)
    return jsonify({'created': rel_path})

@app.route('/api/download', methods=['GET'])
def api_download_file():
    ensure_upload_root()
    rel_path = (request.args.get('path') or '').strip('/')
    if rel_path == '':
        return jsonify({'error': 'path required'}), 400
    try:
        file_path = safe_join(app.config['UPLOAD_ROOT'], rel_path)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400
    if not os.path.isfile(file_path):
        return jsonify({'error': 'Not found'}), 404
    mime_type, _ = mimetypes.guess_type(file_path)
    return send_file(file_path, mimetype=mime_type or 'application/octet-stream', as_attachment=True, download_name=os.path.basename(file_path))

@app.route('/api/delete', methods=['POST'])
def api_delete_path():
    ensure_upload_root()
    payload = request.get_json() or {}
    rel_path = (payload.get('path') or '').strip('/')
    if rel_path == '':
        return jsonify({'error': 'Empty path'}), 400
    try:
        target_path = safe_join(app.config['UPLOAD_ROOT'], rel_path)
    except ValueError:
        return jsonify({'error': 'Invalid path'}), 400

    if os.path.isdir(target_path):
        try:
            os.rmdir(target_path)
            return jsonify({'deleted': rel_path})
        except OSError:
            return jsonify({'error': 'Directory not empty or cannot remove'}), 400
    elif os.path.isfile(target_path):
        os.remove(target_path)
        return jsonify({'deleted': rel_path})
    else:
        return jsonify({'error': 'Not found'}), 404

if __name__ == '__main__':
    ensure_upload_root()
    app.run(debug=True)




<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>文件管理 单页</title>
  <style>
    body{font-family:Arial,Helvetica,sans-serif;margin:20px;color:#222}
    .container{max-width:980px;margin:0 auto}
    .panel{border:1px solid #ddd;padding:12px;margin-bottom:16px;border-radius:6px}
    .row{display:flex;gap:8px;align-items:center;margin:8px 0}
    input[type="text"]{flex:1;padding:6px 8px}
    button{padding:6px 10px;cursor:pointer}
    pre{white-space:pre-wrap;font-family:monospace;background:#f9f9f9;padding:8px;border-radius:4px}
    .file-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px dashed #eee}
    .file-actions button{margin-left:6px}
    .breadcrumb{font-size:14px;color:#444;margin-bottom:8px}
    a.link-button{color:#007bff;text-decoration:none;cursor:pointer}
  </style>
</head>
<body>
  <main class="container">
    <h1>文件管理（单页）</h1>

    <section class="panel" id="panel-browser">
      <div class="row">
        <input id="input-path" type="text" placeholder="相对路径，例如 a/b（留空为根目录）">
        <button id="btn-list">列出</button>
        <button id="btn-refresh">刷新</button>
      </div>
      <div class="breadcrumb" id="breadcrumb">/</div>
      <div id="list-area"><pre id="list-pre">尚未加载</pre></div>
    </section>

    <section class="panel" id="panel-upload">
      <h2>上传</h2>
      <div class="row">
        <input id="input-upload-path" type="text" placeholder="上传目标相对路径，例如 a/b（留空为根目录）">
      </div>
      <div class="row">
        <input id="input-upload-files" type="file" multiple>
        <button id="btn-upload">上传</button>
      </div>
      <div id="upload-area"><pre id="upload-pre"></pre></div>
    </section>

    <section class="panel" id="panel-mkdir">
      <h2>创建目录</h2>
      <div class="row">
        <input id="input-mkdir-path" type="text" placeholder="要创建的相对路径，例如 a/b">
        <button id="btn-mkdir">创建</button>
      </div>
      <div id="mkdir-area"><pre id="mkdir-pre"></pre></div>
    </section>
  </main>

  <script>
    const apiBaseUrl = '/api';

    function formatBytes(bytes){
      if(bytes===0) return '0 B';
      const units=['B','KB','MB','GB','TB'];
      const i=Math.floor(Math.log(bytes)/Math.log(1024));
      return (bytes/Math.pow(1024,i)).toFixed(2)+' '+units[i];
    }

    async function listDirectory(relativePath){
      const params = new URLSearchParams();
      if(relativePath) params.set('path', relativePath);
      const resp = await fetch(`${apiBaseUrl}/list?${params.toString()}`);
      return resp.json();
    }

    async function downloadFile(relativePath){
      const params = new URLSearchParams();
      params.set('path', relativePath);
      // 直接导航到下载链接以触发浏览器下载
      window.location = `${apiBaseUrl}/download?${params.toString()}`;
    }

    async function deletePath(relativePath){
      const resp = await fetch(`${apiBaseUrl}/delete`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path: relativePath})
      });
      return resp.json();
    }

    async function uploadFiles(relativePath, fileList){
      const form = new FormData();
      if(relativePath) form.append('path', relativePath);
      for(const f of fileList) form.append('file', f, f.name);
      const resp = await fetch(`${apiBaseUrl}/upload`, {method:'POST', body: form});
      return resp.json();
    }

    async function makeDirectory(relativePath){
      const resp = await fetch(`${apiBaseUrl}/mkdir`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path: relativePath})
      });
      return resp.json();
    }

    function renderList(domPre, data){
      if(data.error){
        domPre.textContent = `错误: ${data.error}`;
        return;
      }
      if(data.exists===false){
        domPre.textContent = `路径不存在: ${data.path || '/'}`;
        return;
      }
      const lines = [];
      lines.push(`Path: /${data.path || ''}`);
      lines.push('');
      lines.push('Directories:');
      if(data.directories.length===0){
        lines.push('  (none)');
      } else {
        data.directories.forEach(d => lines.push(`  [DIR] ${d}`));
      }
      lines.push('');
      lines.push('Files:');
      if(data.files.length===0){
        lines.push('  (none)');
      } else {
        data.files.forEach(f => lines.push(`  ${f.name}    ${formatBytes(f.size)}`));
      }
      domPre.textContent = lines.join('\n');

      // 为每个文件与目录渲染可点击操作（在 pre 下面替代为 DOM 列表）
      const listArea = document.getElementById('list-area');
      // 清除并构建更友好的列表视图
      listArea.innerHTML = '';
      const pathHeader = document.createElement('div');
      pathHeader.className = 'breadcrumb';
      pathHeader.textContent = `/${data.path || ''}`;
      listArea.appendChild(pathHeader);

      const dirContainer = document.createElement('div');
      dirContainer.innerHTML = '<h3>Directories</h3>';
      if(data.directories.length===0){
        dirContainer.appendChild(document.createTextNode('(none)'));
      } else {
        data.directories.forEach(dirName => {
          const row = document.createElement('div');
          row.className = 'file-row';
          const left = document.createElement('div');
          left.textContent = dirName;
          const actions = document.createElement('div');
          actions.className = 'file-actions';
          const openBtn = document.createElement('button');
          openBtn.textContent = '打开';
          openBtn.addEventListener('click', () => {
            document.getElementById('input-path').value = (data.path ? data.path + '/' : '') + dirName;
            document.getElementById('btn-list').click();
          });
          const deleteBtn = document.createElement('button');
          deleteBtn.textContent = '删除';
          deleteBtn.addEventListener('click', async () => {
            if(!confirm(`删除目录 ${dirName}? 仅能删除空目录`)) return;
            const rel = (data.path ? data.path + '/' : '') + dirName;
            const res = await deletePath(rel);
            alert(res.deleted ? `已删除 ${res.deleted}` : `错误: ${res.error}`);
            document.getElementById('btn-list').click();
          });
          actions.appendChild(openBtn);
          actions.appendChild(deleteBtn);
          row.appendChild(left);
          row.appendChild(actions);
          dirContainer.appendChild(row);
        });
      }
      listArea.appendChild(dirContainer);

      const fileContainer = document.createElement('div');
      fileContainer.innerHTML = '<h3>Files</h3>';
      if(data.files.length===0){
        fileContainer.appendChild(document.createTextNode('(none)'));
      } else {
        data.files.forEach(file => {
          const row = document.createElement('div');
          row.className = 'file-row';
          const left = document.createElement('div');
          left.textContent = `${file.name}    ${formatBytes(file.size)}`;
          const actions = document.createElement('div');
          actions.className = 'file-actions';
          const downloadBtn = document.createElement('button');
          downloadBtn.textContent = '下载';
          downloadBtn.addEventListener('click', () => {
            const rel = (data.path ? data.path + '/' : '') + file.name;
            downloadFile(rel);
          });
          const deleteBtn = document.createElement('button');
          deleteBtn.textContent = '删除';
          deleteBtn.addEventListener('click', async () => {
            if(!confirm(`删除文件 ${file.name}?`)) return;
            const rel = (data.path ? data.path + '/' : '') + file.name;
            const res = await deletePath(rel);
            alert(res.deleted ? `已删除 ${res.deleted}` : `错误: ${res.error}`);
            document.getElementById('btn-list').click();
          });
          actions.appendChild(downloadBtn);
          actions.appendChild(deleteBtn);
          row.appendChild(left);
          row.appendChild(actions);
          fileContainer.appendChild(row);
        });
      }
      listArea.appendChild(fileContainer);
    }

    document.getElementById('btn-list').addEventListener('click', async () => {
      const path = document.getElementById('input-path').value.trim();
      const pre = document.getElementById('list-pre');
      pre.textContent = '加载中...';
      try {
        const data = await listDirectory(path);
        renderList(pre, data);
        document.getElementById('breadcrumb').textContent = '/' + (data.path || '');
      } catch(err){
        pre.textContent = '错误: ' + err.message;
      }
    });

    document.getElementById('btn-refresh').addEventListener('click', () => {
      document.getElementById('btn-list').click();
    });

    document.getElementById('btn-upload').addEventListener('click', async () => {
      const path = document.getElementById('input-upload-path').value.trim();
      const files = document.getElementById('input-upload-files').files;
      const pre = document.getElementById('upload-pre');
      if(!files || files.length===0){
        pre.textContent = '请选择文件';
        return;
      }
      pre.textContent = '上传中...';
      try {
        const res = await uploadFiles(path, files);
        if(res.error){
          pre.textContent = '错误: ' + res.error;
        } else {
          pre.textContent = '已保存:\n' + res.saved.map(s=>s.relative_path).join('\n');
          document.getElementById('input-upload-files').value = '';
          document.getElementById('btn-list').click();
        }
      } catch(err){
        pre.textContent = '错误: ' + err.message;
      }
    });

    document.getElementById('btn-mkdir').addEventListener('click', async () => {
      const path = document.getElementById('input-mkdir-path').value.trim();
      const pre = document.getElementById('mkdir-pre');
      if(!path){
        pre.textContent = '请输入路径';
        return;
      }
      pre.textContent = '创建中...';
      try {
        const res = await makeDirectory(path);
        if(res.error){
          pre.textContent = '错误: ' + res.error;
        } else {
          pre.textContent = '已创建: ' + res.created;
          document.getElementById('btn-list').click();
        }
      } catch(err){
        pre.textContent = '错误: ' + err.message;
      }
    });

    // 初始加载根目录
    document.addEventListener('DOMContentLoaded', () => {
      document.getElementById('btn-list').click();
    });
  </script>
</body>
</html>
