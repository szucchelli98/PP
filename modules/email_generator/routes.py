from io import BytesIO

import pandas as pd
from flask import Blueprint, jsonify, render_template, request

email_bp = Blueprint("email", __name__, template_folder="templates")


@email_bp.route("/")
def index():
    return render_template("email_generator/index.html")


@email_bp.route("/preview-columns", methods=["POST"])
def preview_columns():
    """Return column names + first 5 rows so the UI can populate selects."""
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


@email_bp.route("/generate", methods=["POST"])
def generate():
    """Generate the promotions email comparing the Excel to the last email."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No Excel file provided"}), 400

    key_col = request.form.get("key_column", "").strip()
    display_cols = request.form.getlist("display_columns")
    last_email = request.form.get("last_email", "").lower()
    sender_name = request.form.get("sender_name", "").strip()
    intro_text = request.form.get("intro_text", "Please find below the latest promotions update.").strip()

    if not key_col:
        return jsonify({"error": "Please select the promotion name column"}), 400

    try:
        df = pd.read_excel(BytesIO(file.read()))
        df = df.dropna(subset=[key_col])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    new_rows, ongoing_rows = [], []
    for _, row in df.iterrows():
        key_val = str(row[key_col]).strip()
        if key_val.lower() in last_email:
            ongoing_rows.append(row)
        else:
            new_rows.append(row)

    from datetime import date
    today = date.today().strftime("%d %B %Y")

    def fmt_row(row):
        parts = [str(row[key_col])]
        for col in display_cols:
            if col != key_col and col in row.index:
                val = str(row[col])
                if val and val.lower() != "nan":
                    parts.append(f"{col}: {val}")
        return "  •  ".join(parts)

    lines = [
        f"Subject: Promotions Update – {today}",
        "",
        "Dear Team,",
        "",
        intro_text,
        "",
    ]

    if new_rows:
        lines += ["NEW PROMOTIONS", "─" * 40]
        lines += [f"• {fmt_row(r)}" for r in new_rows]
        lines.append("")

    if ongoing_rows:
        lines += ["ONGOING PROMOTIONS", "─" * 40]
        lines += [f"• {fmt_row(r)}" for r in ongoing_rows]
        lines.append("")

    lines += [
        "CANCELLED PROMOTIONS",
        "─" * 40,
        "(Review manually: check items from the last email that no longer appear in the Excel.)",
        "",
    ]

    if sender_name:
        lines += ["Best regards,", sender_name]

    return jsonify({
        "email": "\n".join(lines),
        "stats": {
            "new": len(new_rows),
            "ongoing": len(ongoing_rows),
            "total": len(df),
        },
    })
