import io
import os
import zipfile

from flask import Blueprint, Response, render_template, request

splitter_bp = Blueprint("splitter", __name__, template_folder="templates")


@splitter_bp.route("/")
def index():
    return render_template("file_splitter/index.html")


@splitter_bp.route("/split", methods=["POST"])
def split():
    file = request.files.get("file")
    if not file or file.filename == "":
        return Response('{"error":"No file uploaded"}', status=400, mimetype="application/json")

    try:
        max_lines = int(request.form.get("max_lines", 15000))
        keep_header = request.form.get("keep_header") == "on"
        content = file.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return Response(f'{{"error":"{exc}"}}', status=400, mimetype="application/json")

    lines = content.splitlines()
    if not lines:
        return Response('{"error":"File is empty"}', status=400, mimetype="application/json")

    header_line = None
    data_lines = lines
    if keep_header and len(lines) > 1:
        header_line = lines[0]
        data_lines = lines[1:]

    chunk_size = max(1, max_lines - (1 if header_line else 0))
    chunks = [data_lines[i : i + chunk_size] for i in range(0, len(data_lines), chunk_size)]

    if len(chunks) <= 1 and len(lines) <= max_lines:
        return Response(
            f'{{"error":"File only has {len(lines)} lines — no splitting needed (limit is {max_lines})."}}',
            status=400,
            mimetype="application/json",
        )

    base_name = os.path.splitext(file.filename)[0]
    ext = os.path.splitext(file.filename)[1] or ".txt"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, chunk in enumerate(chunks, 1):
            part_lines = ([header_line] + chunk) if header_line else chunk
            zf.writestr(f"{base_name}_part{i:02d}{ext}", "\n".join(part_lines))

    zip_bytes = buf.getvalue()
    return Response(
        zip_bytes,
        status=200,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base_name}_split.zip"',
            "X-Parts-Count": str(len(chunks)),
            "Content-Length": str(len(zip_bytes)),
        },
    )
