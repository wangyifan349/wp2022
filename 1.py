# app.py
import logging
import shutil
from pathlib import Path
from flask import Flask, abort, jsonify, request, send_file, render_template_string
from werkzeug.utils import secure_filename
# -------------------------------------------------
# 配置
BASE_DIR = Path("storage").resolve()
BASE_DIR.mkdir(parents=True, exist_ok=True)
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MiB（可自行调整）
# -------------------------------------------------
# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
# -------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
def safe_path(relative_path: str) -> Path:
    """
    将用户提供的相对路径转为绝对路径，并确保仍位于 BASE_DIR 之内。
    使用 pathlib 的 is_relative_to（Python 3.9+）进行安全检查。
    """
    target = (BASE_DIR / relative_path).resolve()
    if not target.is_relative_to(BASE_DIR):
        abort(400, description="Invalid path")
    return target
def json_error(message: str, status_code: int = 400):
    """统一错误返回格式"""
    response = jsonify({"status": "error", "message": message})
    response.status_code = status_code
    return response
# -------------------------------------------------
# 前端占位页面（可自行替换为真实的 HTML）
INDEX_HTML = """
<!doctype html>
<title>文件管理 API</title>
<h1>文件管理后端已启动</h1>
<p>使用 /api/* 路由进行操作。</p>
"""
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
# -------------------------------------------------
# 上传
@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return json_error("No file part")
    file = request.files["file"]
    if file.filename == "":
        return json_error("No selected file")
    rel_dir = request.form.get("path", "")
    try:
        target_dir = safe_path(rel_dir)
    except Exception as e:
        return json_error(str(e))
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(file.filename)
    dest = target_dir / filename
    file.save(str(dest))
    logger.info("Uploaded %s → %s", file.filename, dest)
    return jsonify({
        "status": "ok",
        "message": "uploaded",
        "path": str(dest.relative_to(BASE_DIR))
    })
# -------------------------------------------------
# 下载
@app.route("/api/download", methods=["GET"])
def download():
    rel_path = request.args.get("path")
    if not rel_path:
        return json_error("path required")
    try:
        file_path = safe_path(rel_path)
    except Exception as e:
        return json_error(str(e))
    if not file_path.is_file():
        return json_error("File not found", 404)
    logger.info("Downloading %s", file_path)
    return send_file(str(file_path), as_attachment=True)
# -------------------------------------------------
# 列出目录
@app.route("/api/list", methods=["GET"])
def list_dir():
    rel_path = request.args.get("path", "")
    try:
        dir_path = safe_path(rel_path)
    except Exception as e:
        return json_error(str(e))
    if not dir_path.is_dir():
        return json_error("Directory not found", 404)
    entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
    folders = [e.name for e in entries if e.is_dir()]
    files = [e.name for e in entries if e.is_file()]
    return jsonify({
        "status": "ok",
        "path": str(dir_path.relative_to(BASE_DIR)),
        "folders": folders,
        "files": files
    })
# -------------------------------------------------
# 删除
@app.route("/api/delete", methods=["POST"])
def delete():
    data = request.get_json(silent=True) or {}
    rel_path = data.get("path")
    if not rel_path:
        return json_error("path required")
    try:
        target = safe_path(rel_path)
    except Exception as e:
        return json_error(str(e))
    if not target.exists():
        return json_error("Target not found", 404)
    try:
        if target.is_file():
            target.unlink()
        else:
            shutil.rmtree(str(target))
        logger.info("Deleted %s", target)
        return jsonify({"status": "ok", "message": "deleted", "path": rel_path})
    except Exception as exc:
        logger.exception("Delete failed")
        return json_error(str(exc), 500)
# -------------------------------------------------
# 移动 / 重命名
@app.route("/api/move", methods=["POST"])
def move():
    data = request.get_json(silent=True) or {}
    src_rel = data.get("src")
    dst_rel = data.get("dst")
    if not src_rel or not dst_rel:
        return json_error("src and dst required")
    try:
        src = safe_path(src_rel)
        dst = safe_path(dst_rel)
    except Exception as e:
        return json_error(str(e))
    if not src.exists():
        return json_error("Source not found", 404)
    # 确保目标父目录存在
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
        logger.info("Moved %s → %s", src, dst)
        return jsonify({
            "status": "ok",
            "message": "moved",
            "src": src_rel,
            "dst": dst_rel
        })
    except Exception as exc:
        logger.exception("Move failed")
        return json_error(str(exc), 500)
# -------------------------------------------------
if __name__ == "__main__":
    # 开发时使用 Flask 内置服务器；生产环境请换成 gunicorn/uwsgi 等
    app.run(host="0.0.0.0", port=5000, debug=True)
