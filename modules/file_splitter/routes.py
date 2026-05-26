import io
import os
import zipfile

import pandas as pd
from flask import Blueprint, Response, render_template, request

splitter_bp = Blueprint("splitter", __name__, template_folder="templates")

MAX_ROWS = 15_000


@splitter_bp.route("/")
def index():
    return render_template("file_splitter/index.html")


@splitter_bp.route("/ping")
def ping():
    return Response('{"status":"ok","version":"v5"}', status=200, mimetype="application/json")


@splitter_bp.route("/split", methods=["POST"])
def split():
    try:
        file = request.files.get("file")
        if not file or file.filename == "":
            return _json_error("No file uploaded", 400)

        ext = os.path.splitext(file.filename)[1].lower()
        if ext == ".xls":
            engine = "xlrd"
        elif ext == ".xlsx":
            engine = "openpyxl"
        else:
            return _json_error("Only .xlsx / .xls files are supported", 400)

        file_bytes = file.read()
        df = pd.read_excel(io.BytesIO(file_bytes), engine=engine, header=0)

        if df.empty:
            return _json_error("File is empty or has no data rows", 400)

        chunks = [df.iloc[i: i + MAX_ROWS] for i in range(0, max(len(df), 1), MAX_ROWS)]
        base   = os.path.splitext(file.filename)[0]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, chunk in enumerate(chunks, 1):
                part_buf = io.BytesIO()
                chunk.to_excel(part_buf, index=False, engine="openpyxl")
                zf.writestr(f"{base}_part{i:02d}.xlsx", part_buf.getvalue())

        zip_bytes = buf.getvalue()
        return Response(
            zip_bytes,
            status=200,
            mimetype="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{base}_split.zip"',
                "X-Parts-Count": str(len(chunks)),
            },
        )

    except BaseException as exc:
        return _json_error(f"{type(exc).__name__}: {exc}", 500)


def _json_error(msg: str, status: int) -> Response:
    safe = str(msg).replace("\\", "/").replace('"', "'").replace("\n", " ").replace("\r", "")[:400]
    return Response(f'{{"error":"{safe}"}}', status=status, mimetype="application/json")
