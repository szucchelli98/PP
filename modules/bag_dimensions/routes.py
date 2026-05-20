from io import BytesIO

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request

bag_bp = Blueprint("bag", __name__, template_folder="templates")


@bag_bp.route("/")
def index():
    return render_template("bag_dimensions/index.html")


@bag_bp.route("/preview-columns", methods=["POST"])
def preview_columns():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        df = pd.read_excel(BytesIO(file.read()), nrows=5)
        cols = [c for c in df.columns.tolist() if not str(c).startswith("Unnamed")]
        preview = df[cols].fillna("").astype(str).to_dict(orient="records")
        return jsonify({"columns": cols, "preview": preview})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bag_bp.route("/export", methods=["POST"])
def export():
    """Extract selected columns and return a clean Excel."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    selected_cols = request.form.getlist("columns")
    if not selected_cols:
        return jsonify({"error": "Select at least one column"}), 400

    try:
        df = pd.read_excel(BytesIO(file.read()))
        missing = [c for c in selected_cols if c not in df.columns]
        if missing:
            return jsonify({"error": f"Columns not found: {missing}"}), 400

        out_df = df[selected_cols].copy()

        buf = BytesIO()
        out_df.to_excel(buf, index=False)
        xlsx_bytes = buf.getvalue()

        base = file.filename.rsplit(".", 1)[0]
        return Response(
            xlsx_bytes,
            status=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{base}_dimensions.xlsx"',
                "Content-Length": str(len(xlsx_bytes)),
                "X-Row-Count": str(len(out_df)),
            },
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
