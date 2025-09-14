# main.py
import os, io, shutil, zipfile, sqlite3, urllib.parse, secrets
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, aiofiles
from passlib.hash import bcrypt

APP_SECRET = secrets.token_urlsafe(32)
BASE = Path("./storage").resolve()
BASE.mkdir(parents=True, exist_ok=True)
DB_PATH = "users.db"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- DB helpers (sqlite, raw SQL) ---
def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)")
init_db()

def db_execute(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur

# --- Auth helpers: simple cookie session (not secure for production) ---
SESSION_COOKIE = "fm_sess"
SESSIONS = {}  # in-memory: token->username

def create_user(username, password):
    pw = bcrypt.hash(password)
    try:
        db_execute("INSERT INTO users(username,password) VALUES(?,?)",(username,pw))
    except sqlite3.IntegrityError:
        raise HTTPException(400,"Username exists")
    (BASE/username).mkdir(parents=True,exist_ok=True)
    return True

def verify_user(username,password):
    cur = db_execute("SELECT password FROM users WHERE username=?",(username,))
    row = cur.fetchone()
    if not row: return False
    return bcrypt.verify(password,row[0])

def get_username_by_session(token:Optional[str]):
    if not token: return None
    return SESSIONS.get(token)

def require_user(request:Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = get_username_by_session(token)
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    return user

# --- Path helpers ---
def safe_user_path(username, rel_path: str):
    rel = urllib.parse.unquote(rel_path or "").strip("/")
    target = (BASE/username / rel).resolve()
    try:
        target.relative_to(BASE/username)
    except Exception:
        raise HTTPException(400,"Invalid path")
    return target

# --- File APIs ---
@app.post("/api/mkdir")
def api_mkdir(request:Request, path: str = ""):
    user = require_user(request)
    p = safe_user_path(user,path)
    p.mkdir(parents=True,exist_ok=True)
    return {"ok":True,"path":str(p.relative_to(BASE/user))}

@app.post("/api/upload")
async def api_upload(request:Request, path: str = "", files: List[UploadFile] = File(...)):
    user = require_user(request)
    dest_dir = safe_user_path(user,path)
    dest_dir.mkdir(parents=True,exist_ok=True)
    saved=[]
    for up in files:
        fn = Path(up.filename).name
        dest = dest_dir/fn
        async with aiofiles.open(dest,'wb') as f:
            while True:
                chunk = await up.read(1024*1024)
                if not chunk: break
                await f.write(chunk)
        saved.append(str(dest.relative_to(BASE/user)))
    return {"ok":True,"saved":saved}

@app.get("/api/list")
def api_list(request:Request, path: str = ""):
    user = require_user(request)
    p = safe_user_path(user,path)
    if not p.exists(): raise HTTPException(404,"Not found")
    if p.is_file():
        return {"type":"file","name":p.name,"path":str(p.relative_to(BASE/user)),"size":p.stat().st_size}
    def build(dirp):
        children=[]
        for c in sorted(dirp.iterdir(), key=lambda x:(not x.is_dir(), x.name.lower())):
            if c.is_dir():
                children.append({"type":"dir","name":c.name,"path":str(c.relative_to(BASE/user))})
            else:
                children.append({"type":"file","name":c.name,"path":str(c.relative_to(BASE/user)),"size":c.stat().st_size})
        return {"type":"dir","path":str(dirp.relative_to(BASE/user)),"children":children}
    return build(p)

@app.get("/api/download")
def api_download(request:Request, path: str):
    user = require_user(request)
    p = safe_user_path(user,path)
    if not p.exists(): raise HTTPException(404,"Not found")
    if p.is_file(): return FileResponse(str(p), filename=p.name, media_type="application/octet-stream")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for root,dirs,files in os.walk(p):
            for f in files:
                full = Path(root)/f
                arc = str(full.relative_to(p.parent))
                z.write(full,arc)
    buf.seek(0)
    return StreamingResponse(buf,media_type="application/zip", headers={"Content-Disposition":f'attachment; filename="{p.name}.zip"'})

@app.post("/api/move")
def api_move(request:Request, src: str = Form(...), dst: str = Form(...)):
    user = require_user(request)
    s = safe_user_path(user,src); d = safe_user_path(user,dst)
    if not s.exists(): raise HTTPException(404,"Source not found")
    if d.exists() and d.is_dir(): final = d/s.name
    else:
        pd = d.parent
        pd.mkdir(parents=True,exist_ok=True)
        final = d
    shutil.move(str(s),str(final))
    return {"ok":True,"from":str(s.relative_to(BASE/user)),"to":str(final.relative_to(BASE/user))}

@app.delete("/api/delete")
def api_delete(request:Request, path: str):
    user = require_user(request)
    p = safe_user_path(user,path)
    if not p.exists(): raise HTTPException(404,"Not found")
    if p.is_dir(): shutil.rmtree(p)
    else: p.unlink()
    return {"ok":True}

# --- Auth endpoints (register/login/logout) ---
@app.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not username or not password: raise HTTPException(400,"Invalid")
    create_user(username,password)
    return RedirectResponse("/", status_code=303)

@app.post("/login")
def login(response:RedirectResponse, username: str = Form(...), password: str = Form(...)):
    if verify_user(username,password):
        token = secrets.token_urlsafe(32)
        SESSIONS[token]=username
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(SESSION_COOKIE, token, httponly=True)
        return r
    raise HTTPException(400,"Invalid credentials")

@app.get("/logout")
def logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie(SESSION_COOKIE)
    return r

# --- Frontend single page (Bootstrap styling, red/gold/green theme, simple Google-like login box) ---
INDEX = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>File Manager</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
:root{--red:#b22222;--gold:#c39b00;--green:#2e8b57;--bg:#f7f6f5}
body{background:linear-gradient(180deg,#fff,#f7f6f5);font-family:Roboto,Arial;color:#222}
.navbar{background:linear-gradient(90deg,var(--red),var(--gold));color:#fff}
.logo{font-weight:700;letter-spacing:1px}
.card-auth{max-width:380px;margin:40px auto;padding:24px;border-radius:12px;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#fff}
.side{width:320px;background:#fff;border-right:1px solid #eee;padding:16px;overflow:auto}
.main{flex:1;padding:18px}
.dir{font-weight:600;color:var(--red);cursor:pointer}
.file{color:#333}
.children{margin-left:12px}
.item{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px dashed #f0f0f0}
.drop{border:2px dashed #eee;padding:20px;text-align:center;border-radius:8px;background:#fff}
.btn-gold{background:var(--gold);border:none;color:#fff}
.btn-danger{background:var(--red);border:none;color:#fff}
.btn-green{background:var(--green);border:none;color:#fff}
small.muted{color:#666}
footer {text-align:center;color:#888;padding:8px}
</style>
</head><body>
<nav class="navbar navbar-expand p-3"><div class="container-fluid"><div class="logo text-white">FileManager</div><div class="ms-auto">
<form method="post" action="/logout"><button class="btn btn-sm btn-outline-light">Logout</button></form></div></div></nav>
<div class="d-flex" style="height:calc(100vh - 64px)">
<div class="side"><h5 class="mb-2">Your Files</h5><div id="tree"></div><hr><small class="muted">Drag items to move</small></div>
<div class="main">
<div class="d-flex justify-content-between align-items-center mb-2"><div><strong id="curpath">/</strong></div>
<div><button id="refresh" class="btn btn-sm btn-outline-secondary">Refresh</button></div></div>
<div class="row g-3">
<div class="col-md-4">
<div class="card p-3">
<h6>Create Folder</h6>
<div class="input-group"><input id="newdir" class="form-control" placeholder="folder name"><button id="mk" class="btn btn-gold">Create</button></div>
</div>
</div>
<div class="col-md-8">
<div class="card p-3"><h6>Upload</h6><div class="d-flex gap-2"><input type="file" id="files" multiple class="form-control"><button id="up" class="btn btn-green">Upload</button></div>
<div class="drop mt-3" id="drop">Drop files here to upload</div></div>
</div>
</div>
<div class="card mt-3 p-3"><h6>Contents</h6><div id="list"></div></div>
<footer class="mt-2">Theme: <span style="color:var(--red)">Red</span> / <span style="color:var(--gold)">Gold</span> / <span style="color:var(--green)">Green</span></footer>
</div>
</div>

<!-- If not logged in, show auth card -->
<div id="authwrap"></div>

<script>
const api=(p)=>'/api'+p;
let cur='';
async function init(){
 const r=await fetch('/whoami'); const j=await r.json();
 if(!j.user){ showAuth(); return; } else { document.querySelector('nav .logo').textContent='FileManager — '+j.user; loadTree(); openPath(''); }
 document.getElementById('refresh').onclick=()=>{loadTree(); openPath(cur);}
 document.getElementById('mk').onclick=async ()=>{ const name=document.getElementById('newdir').value.trim(); if(!name) return alert('Enter name'); await fetch('/api/mkdir?path='+encodeURIComponent(cur?cur+'/'+name:name),{method:'POST'}); document.getElementById('newdir').value=''; loadTree(); openPath(cur); }
 document.getElementById('up').onclick=async ()=>{ const f=document.getElementById('files').files; if(!f.length) return alert('Select'); const fd=new FormData(); for(const x of f) fd.append('files',x); await fetch('/api/upload?path='+encodeURIComponent(cur),{method:'POST',body:fd}); loadTree(); openPath(cur); }
 const dz=document.getElementById('drop'); dz.ondragover=e=>{e.preventDefault(); dz.style.borderColor='#c9a400'}; dz.ondragleave=e=>{dz.style.borderColor='#eee'}; dz.ondrop=async e=>{ e.preventDefault(); dz.style.borderColor='#eee'; const items=e.dataTransfer.files; const fd=new FormData(); for(const x of items) fd.append('files',x); await fetch('/api/upload?path='+encodeURIComponent(cur),{method:'POST',body:fd}); loadTree(); openPath(cur);}
}
function showAuth(){
 document.body.style.background='linear-gradient(180deg,#fff,#f0f0f0)';
 document.getElementById('authwrap').innerHTML=`<div class="card-auth"><h4 style="text-align:center;color:var(--red)">Sign in</h4>
 <form method="post" action="/login" style="display:flex;flex-direction:column;gap:8px">
 <input name="username" class="form-control" placeholder="Username" required>
 <input name="password" type="password" class="form-control" placeholder="Password" required>
 <div><button class="btn btn-gold w-100">Sign in</button></div>
 </form>
 <hr>
 <form method="post" action="/register" style="display:flex;flex-direction:column;gap:8px">
 <input name="username" class="form-control" placeholder="New username" required>
 <input name="password" type="password" class="form-control" placeholder="Password" required>
 <div><button class="btn btn-green w-100">Create account</button></div>
 </form></div>`; document.querySelector('.side').style.display='none'; document.querySelector('.main').style.display='none'; document.querySelector('nav .ms-auto').style.display='none';
}
async function loadTree(){
 const res=await fetch('/api/list?path='); if(res.status===401){ showAuth(); return; } const tree=await res.json(); const t=document.getElementById('tree'); t.innerHTML=''; function render(node,el){ const d=document.createElement('div'); d.className='dir'; d.textContent=node.name||'/'; d.dataset.path=node.path||''; d.draggable=true; d.onclick=()=>openPath(d.dataset.path); d.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain',d.dataset.path)); el.appendChild(d); if(node.children){ const c=document.createElement('div'); c.className='children'; el.appendChild(c); for(const ch of node.children){ if(ch.type==='dir') render(ch,c); else{ const f=document.createElement('div'); f.className='file'; f.textContent=ch.name; f.dataset.path=ch.path; f.draggable=true; f.onclick=()=>openPath(ch.path); f.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain',ch.path)); c.appendChild(f); } } } }
 render(tree,t);
 // allow drop on dirs
 t.querySelectorAll('.dir').forEach(d=>{ d.ondragover=e=>e.preventDefault(); d.ondrop=async e=>{ e.preventDefault(); const src=e.dataTransfer.getData('text/plain'); const dst=d.dataset.path; if(!src) return; await fetch('/api/move',{method:'POST',body:new URLSearchParams({src,dst})}); loadTree(); openPath(cur); }});
}
async function openPath(path){
 cur=path||''; document.getElementById('curpath').textContent='/'+cur; const res=await fetch('/api/list?path='+encodeURIComponent(cur)); if(res.status===401){ showAuth(); return;} const data=await res.json(); const list=document.getElementById('list'); list.innerHTML=''; if(data.children.length===0) list.innerHTML='<div class="p-2 text-muted">Empty</div>'; for(const it of data.children){ const row=document.createElement('div'); row.className='item'; const left=document.createElement('div'); left.textContent=(it.type==='dir'? '📁 ':'📄 ')+it.name; left.style.cursor='pointer'; left.onclick=()=>{ if(it.type==='dir') openPath(it.path); else window.location='/api/download?path='+encodeURIComponent(it.path); }; const right=document.createElement('div'); right.innerHTML=`<button class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation();window.location='/api/download?path=${encodeURIComponent(it.path)}'">Download</button>
 <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();if(confirm('Delete?'))fetch('/api/delete?path=${encodeURIComponent(it.path)}',{method:'DELETE'}).then(()=>{loadTree();openPath(cur)})">Delete</button>`; row.appendChild(left); row.appendChild(right); // drag-drop into dir or current
 row.draggable=true; row.ondragstart=e=>e.dataTransfer.setData('text/plain',it.path);
 row.ondragover=e=>e.preventDefault();
 row.ondrop=async e=>{ e.preventDefault(); const src=e.dataTransfer.getData('text/plain'); const dst=it.type==='dir'? it.path : cur; await fetch('/api/move',{method:'POST',body:new URLSearchParams({src,dst})}); loadTree(); openPath(cur); }
 list.appendChild(row);
 }
}
window.onload=init;
</script>
</body></html>
"""

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = get_username_by_session(token)
    return HTMLResponse(INDEX)

@app.get("/whoami")
def whoami(request:Request):
    user = get_username_by_session(request.cookies.get(SESSION_COOKIE))
    return {"user": user}

if __name__=="__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
