import io
import os
import zipfile

import openpyxl
from flask import Blueprint, Response, render_template, request

splitter_bp = Blueprint("splitter", __name__, template_folder="templates")

MAX_ROWS = 15_000


@splitter_bp.route("/")
def index():
    return render_template("file_splitter/index.html")


@splitter_bp.route("/split", methods=["POST"])
def split():
    file = request.files.get("file")
    if not file or file.filename == "":
        return Response('{"error":"No file uploaded"}', status=400, mimetype="application/json")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        return Response('{"error":"Only .xlsx / .xls files are supported"}', status=400, mimetype="application/json")

    try:
        wb_src = openpyxl.load_workbook(io.BytesIO(file.read()), read_only=True, data_only=True)
        ws_src = wb_src.active
        all_rows = list(ws_src.iter_rows(values_only=True))
        wb_src.close()
    except Exception as exc:
        return Response(f'{{"error":"Could not read file: {exc}"}}', status=400, mimetype="application/json")

    if not all_rows:
        return Response('{"error":"File is empty"}', status=400, mimetype="application/json")

    header   = all_rows[0]
    data     = all_rows[1:]
    chunks   = [data[i : i + MAX_ROWS] for i in range(0, max(len(data), 1), MAX_ROWS)]
    base     = os.path.splitext(file.filename)[0]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, chunk in enumerate(chunks, 1):
            wb_out = openpyxl.Workbook(write_only=True)
            ws_out = wb_out.create_sheet()
            ws_out.append(list(header))
            for row in chunk:
                ws_out.append(list(row))
            part_buf = io.BytesIO()
            wb_out.save(part_buf)
            zf.writestr(f"{base}_part{i:02d}.xlsx", part_buf.getvalue())

    zip_bytes = buf.getvalue()
    return Response(
        zip_bytes,
        status=200,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base}_split.zip"',
            "X-Parts-Count": str(len(chunks)),
            "Content-Length": str(len(zip_bytes)),
        },
    )
