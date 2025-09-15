# main.py
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os, shutil, posixpath, uvicorn
app = FastAPI()
BASE_DIR = "uploads"
os.makedirs(BASE_DIR, exist_ok=True)
# 允许的源
allowed_origins = [
    "https://example.com",  # 允许的域名
    "https://another-example.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # 限制允许的源
    allow_methods=["GET", "POST"],  # 只允许 GET 和 POST 方法
    allow_headers=["Content-Type", "Authorization"],  # 只允许特定的请求头
    allow_credentials=True,  # 允许凭证
)

def safe_path(rel_path: str) -> str:
    if rel_path is None or rel_path == "":
        rel_path = "."
    normalized = posixpath.normpath(rel_path)
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    final = os.path.join(BASE_DIR, *parts) if parts else BASE_DIR
    final = os.path.abspath(final)
    base_abs = os.path.abspath(BASE_DIR)
    if not final.startswith(base_abs):
        raise HTTPException(status_code=400, detail="Invalid path")
    return final
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>File Manager — Bootstrap</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{padding:20px;}
    #browser {min-height:300px; border:1px dashed #dee2e6; background:#fafafa; padding:12px; border-radius:8px;}
    .item { display:flex; justify-content:space-between; align-items:center; padding:8px; border-radius:6px; }
    .item:hover{ background:#fff; box-shadow:0 1px 4px rgba(0,0,0,0.03);}
    .list-head{ font-weight:600; color:#333; }
    .draggable{ cursor:grab; }
    .drop-target{ border:2px dashed transparent; }
    .drop-target.over{ border-color:#0d6efd33; background:#e9f2ff; }
    .small-muted{ font-size:0.85rem; color:#666; }
    .file-icon{ width:28px; text-align:center; margin-right:8px; }
    #uploadDrop{ border:2px dashed #ced4da; padding:18px; border-radius:8px; text-align:center; }
    #uploadDrop.drag{ background:#e9f7ef; border-color:#28a745; }
  </style>
</head>
<body>
<div class="container">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h3>文件管理器</h3>
    <div><small class="text-muted">根目录: /</small></div>
  </div>

  <div class="mb-3">
    <div class="input-group">
      <button id="btnUp" class="btn btn-outline-secondary">上级</button>
      <input id="curPath" class="form-control" placeholder="当前路径（只读）" readonly>
      <button id="btnRefresh" class="btn btn-outline-secondary">刷新</button>
    </div>
  </div>

  <div class="row mb-3">
    <div class="col-md-6">
      <div id="uploadDrop">
        <div class="mb-2">拖拽文件到此处或点击选择上传（支持多文件）</div>
        <div class="d-flex gap-2 justify-content-center">
          <input id="fileInput" type="file" multiple style="display:none"/>
          <button id="chooseBtn" class="btn btn-primary">选择文件</button>
          <button id="uploadBtn" class="btn btn-success">上传</button>
          <button id="mkdirBtn" class="btn btn-outline-secondary" data-bs-toggle="modal" data-bs-target="#mkdirModal">新建目录</button>
        </div>
        <div id="uploadList" class="mt-2 small-muted"></div>
      </div>
    </div>
    <div class="col-md-6 text-end">
      <div class="btn-group">
        <button id="btnDownloadAll" class="btn btn-outline-primary">下载选中</button>
        <button id="btnDeleteSel" class="btn btn-outline-danger">删除选中</button>
      </div>
    </div>
  </div>

  <div id="browser" class="drop-target">
    <div class="d-flex list-head mb-2">
      <div style="flex:1">名称</div>
      <div style="width:220px; text-align:right">操作</div>
    </div>
    <div id="entries"></div>
  </div>
</div>

<!-- mkdir modal -->
<div class="modal fade" id="mkdirModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form class="modal-content" id="mkdirForm">
      <div class="modal-header"><h5 class="modal-title">新建目录</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <label>目录名</label>
        <input id="mkdirName" class="form-control" required />
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
        <button type="submit" class="btn btn-primary">创建</button>
      </div>
    </form>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const api = (p)=> '/api/' + p;
let curPath = "";
const entriesEl = document.getElementById('entries');
const curPathInput = document.getElementById('curPath');
const fileInput = document.getElementById('fileInput');
const uploadList = document.getElementById('uploadList');

function setPath(p){
  curPath = p || "";
  curPathInput.value = '/' + curPath;
}

async function listPath(path=""){
  const res = await fetch(api('list?path='+encodeURIComponent(path)));
  if(!res.ok){ alert('列表失败'); return; }
  const data = await res.json();
  setPath(data.path);
  renderEntries(data);
}

function renderEntries(data){
  entriesEl.innerHTML = "";
  // parent
  if(curPath !== ""){
    const div = document.createElement('div'); div.className='item';
    div.innerHTML = `<div class="small-muted">.. (上级目录)</div><div></div>`;
    div.onclick = ()=> { let p = curPath.split('/'); p.pop(); listPath(p.join('/')); };
    entriesEl.appendChild(div);
  }
  data.dirs.forEach(d=>{
    const row = document.createElement('div'); row.className='item drop-target';
    row.draggable = true; row.dataset.name = d; row.dataset.type='dir';
    row.innerHTML = `<div style="display:flex;align-items:center">
        <div class="file-icon">📁</div>
        <div><div class="fw-semibold">${d}</div><div class="small-muted">目录</div></div>
      </div>
      <div style="width:220px; text-align:right">
        <button class="btn btn-sm btn-outline-primary" onclick="enterDir('${d}')">打开</button>
        <button class="btn btn-sm btn-outline-secondary" onclick="renameItem('${d}')">重命名</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteItem('${d}')">删除</button>
      </div>`;
    addDragHandlers(row);
    entriesEl.appendChild(row);
  });
  data.files.forEach(f=>{
    const row = document.createElement('div'); row.className='item drop-target';
    row.draggable = true; row.dataset.name = f; row.dataset.type='file';
    row.innerHTML = `<div style="display:flex;align-items:center">
        <div class="file-icon">📄</div>
        <div><div>${f}</div><div class="small-muted">文件</div></div>
      </div>
      <div style="width:220px; text-align:right">
        <a class="btn btn-sm btn-outline-success" href="${api('download?path=' + encodeURIComponent((curPath?curPath + '/':'') + f))}" target="_blank">下载</a>
        <button class="btn btn-sm btn-outline-secondary" onclick="renameItem('${f}')">重命名</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteItem('${f}')">删除</button>
      </div>`;
    addDragHandlers(row);
    entriesEl.appendChild(row);
  });
}

function enterDir(name){
  const p = curPath ? curPath + '/' + name : name;
  listPath(p);
}

async function deleteItem(name){
  if(!confirm('确认删除？')) return;
  const target = (curPath?curPath + '/':'') + name;
  const res = await fetch(api('delete?path=' + encodeURIComponent(target)), {method:'DELETE'});
  if(res.ok) listPath(curPath); else alert('删除失败');
}

async function renameItem(name){
  const newName = prompt('输入新名称：', name);
  if(!newName) return;
  const res = await fetch(api('rename'), {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path: (curPath?curPath + '/':'') + name, new_name: newName})
  });
  if(res.ok) listPath(curPath); else { const t = await res.text(); alert('失败: '+t); }
}

// drag & drop for moving
function addDragHandlers(el){
  el.addEventListener('dragstart', (e)=>{
    e.dataTransfer.setData('text/plain', JSON.stringify({name: el.dataset.name, type: el.dataset.type, curPath}));
    e.dataTransfer.effectAllowed = 'move';
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', ()=> el.classList.remove('dragging'));
}

const browser = document.getElementById('browser');
browser.addEventListener('dragover', (e)=> { e.preventDefault(); browser.classList.add('over'); });
browser.addEventListener('dragleave', ()=> browser.classList.remove('over'));
browser.addEventListener('drop', async (e)=>{
  e.preventDefault(); browser.classList.remove('over');
  // find drop target entry under pointer
  const payload = e.dataTransfer.getData('text/plain');
  if(!payload) return;
  const obj = JSON.parse(payload);
  // compute destination = current path (drop to folder view root) or if dropping on a dir, that dir
  let dest = curPath;
  // if dropped on a specific dir element
  const el = document.elementFromPoint(e.clientX, e.clientY);
  let dropDir = null;
  if(el){
    const dirEl = el.closest('.drop-target');
    if(dirEl && dirEl.dataset && dirEl.dataset.type === 'dir'){
      dropDir = dirEl.dataset.name;
    }
  }
  if(dropDir){
    dest = curPath ? (curPath + '/' + dropDir) : dropDir;
  }
  // source path
  const source = (obj.curPath ? obj.curPath + '/' : '') + obj.name;
  const destination = dest ? (dest + '/' + obj.name) : obj.name;
  const res = await fetch(api('move'), {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({source, destination})});
  if(res.ok) listPath(curPath); else { const t = await res.text(); alert('移动失败: '+t); }
});

// upload handlers
document.getElementById('chooseBtn').onclick = ()=> fileInput.click();
fileInput.onchange = ()=> {
  renderUploadList();
};
function renderUploadList(){
  const files = fileInput.files;
  if(!files || files.length===0){ uploadList.textContent = '未选择文件'; return; }
  uploadList.innerHTML = '';
  for(let i=0;i<files.length;i++){
    const f = files[i];
    const div = document.createElement('div'); div.textContent = `${f.name} (${Math.round(f.size/1024)} KB)`;
    uploadList.appendChild(div);
  }
}
document.getElementById('uploadDrop').addEventListener('dragover', (e)=>{ e.preventDefault(); document.getElementById('uploadDrop').classList.add('drag'); });
document.getElementById('uploadDrop').addEventListener('dragleave', ()=>{ document.getElementById('uploadDrop').classList.remove('drag'); });
document.getElementById('uploadDrop').addEventListener('drop', (e)=>{ e.preventDefault(); document.getElementById('uploadDrop').classList.remove('drag');
  const dt = e.dataTransfer;
  if(dt.files && dt.files.length){ fileInput.files = dt.files; renderUploadList(); }
});

document.getElementById('uploadBtn').onclick = async ()=>{
  const files = fileInput.files;
  if(!files || files.length===0){ alert('请选择文件'); return; }
  for(let i=0;i<files.length;i++){
    const f = files[i];
    const form = new FormData();
    form.append('file', f, f.name);
    const res = await fetch(api('upload?path='+encodeURIComponent(curPath)), {method:'POST', body: form});
    if(!res.ok){ alert('上传失败: ' + f.name); return; }
  }
  fileInput.value = ''; renderUploadList(); listPath(curPath);
};

// mkdir
document.getElementById('mkdirForm').onsubmit = async (e)=>{
  e.preventDefault();
  const name = document.getElementById('mkdirName').value.trim();
  if(!name){ alert('请输入目录名'); return; }
  const res = await fetch(api('mkdir'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: curPath, name})});
  if(res.ok){ listPath(curPath); var modal = bootstrap.Modal.getInstance(document.getElementById('mkdirModal')); modal.hide(); document.getElementById('mkdirName').value=''; }
  else{ alert('创建失败'); }
};

// up & refresh
document.getElementById('btnUp').onclick = ()=> { if(!curPath) return; const p = curPath.split('/'); p.pop(); listPath(p.join('/')); };
document.getElementById('btnRefresh').onclick = ()=> listPath(curPath);

// bulk actions (simple: delete selected via prompts) — for demo, we skip selection UI
document.getElementById('btnDeleteSel').onclick = ()=> alert('请使用每行的删除按钮进行删除（可按需扩展多选）');
document.getElementById('btnDownloadAll').onclick = ()=> alert('请使用每行的下载按钮（批量下载需打包后端实现）');

window.onload = ()=> listPath('');
</script>
</body>
</html>
"""
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)
@app.get("/api/list")
async def api_list(path: str = ""):
    dirp = safe_path(path)
    if not os.path.exists(dirp):
        raise HTTPException(status_code=404, detail="Directory not found")
    entries = sorted(os.listdir(dirp))
    files = [e for e in entries if os.path.isfile(os.path.join(dirp, e))]
    dirs = [e for e in entries if os.path.isdir(os.path.join(dirp, e))]
    return {"path": path, "files": files, "dirs": dirs}
@app.post("/api/upload")
async def api_upload(path: str = "", file: UploadFile = File(...)):
    dest_dir = safe_path(path)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
    filename = os.path.basename(file.filename)
    dest = os.path.join(dest_dir, filename)
    with open(dest, "wb") as f:
        f.write(await file.read())
    return {"detail": "uploaded", "path": os.path.join(path, filename)}
@app.get("/api/download")
async def api_download(path: str):
    file_path = safe_path(path)
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=os.path.basename(file_path))
@app.post("/api/mkdir")
async def api_mkdir(payload: dict):
    path = payload.get("path", "")
    name = payload.get("name")
    if not name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid directory name")
    dir_path = safe_path(path)
    new_dir = os.path.join(dir_path, name)
    if os.path.exists(new_dir):
        raise HTTPException(status_code=400, detail="Already exists")
    os.makedirs(new_dir, exist_ok=True)
    return {"detail": "created", "path": os.path.join(path, name)}
@app.delete("/api/delete")
async def api_delete(path: str):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.abspath(target) == os.path.abspath(BASE_DIR):
        raise HTTPException(status_code=400, detail="Cannot delete root")
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return {"detail": "deleted", "path": path}
@app.post("/api/rename")
async def api_rename(payload: dict):
    path = payload.get("path")
    new_name = payload.get("new_name")
    if not path or not new_name:
        raise HTTPException(status_code=400, detail="Missing params")
    src = safe_path(path)
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="Source not found")
    dst_dir = os.path.dirname(src)
    dst = os.path.join(dst_dir, new_name)
    if os.path.exists(dst):
        raise HTTPException(status_code=400, detail="Destination exists")
    os.rename(src, dst)
    rel_dst = os.path.relpath(dst, os.path.abspath(BASE_DIR))
    rel_dst = "" if rel_dst == "." else rel_dst.replace("\\", "/")
    return {"detail": "renamed", "new_path": rel_dst}
@app.post("/api/move")
async def api_move(payload: dict):
    source = payload.get("source")
    destination = payload.get("destination")
    if not source or not destination:
        raise HTTPException(status_code=400, detail="Missing params")
    src = safe_path(source)
    dst = safe_path(destination)
    dst_parent = dst if os.path.isdir(dst) else os.path.dirname(dst)
    if not os.path.exists(dst_parent):
        os.makedirs(dst_parent, exist_ok=True)
    if os.path.abspath(src) == os.path.abspath(BASE_DIR):
        raise HTTPException(status_code=400, detail="Cannot move root")
    try:
        shutil.move(src, dst)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    rel_dst = os.path.relpath(dst, os.path.abspath(BASE_DIR))
    rel_dst = "" if rel_dst == "." else rel_dst.replace("\\", "/")
    return {"detail": "moved", "new_path": rel_dst}
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
