# app.py
import os
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Root storage directory (absolute path)
STORAGE_ROOT = Path(__file__).resolve().parent / "data"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

# Max upload size (bytes)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB


def resolve_path(relative_path: str) -> Path:
    """
    Resolve a user-provided relative path into a safe absolute Path
    under STORAGE_ROOT to prevent directory traversal.
    relative_path may be empty or a subpath using '/' separators.
    Returns an absolute Path (may not exist).
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
