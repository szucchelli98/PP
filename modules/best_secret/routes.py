import json
import os
from io import BytesIO

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request

best_secret_bp = Blueprint("best_secret", __name__, template_folder="templates")

TOOLS = {
    "category":      {"label": "Category Mapping",       "icon": "fas fa-tags"},
    "description":   {"label": "Description Mapping",    "icon": "fas fa-align-left"},
    "shop_category": {"label": "Shop Category Mapping",  "icon": "fas fa-store"},
    "materials":     {"label": "Materials Mapping",      "icon": "fas fa-layer-group"},
    "size":          {"label": "Size Mapping",           "icon": "fas fa-ruler"},
    "closure":       {"label": "Closure Mapping",        "icon": "fas fa-lock"},
}

MAPPINGS_DIR = os.path.join(os.path.dirname(__file__), "mappings")


def _mapping_path(tool_name):
    return os.path.join(MAPPINGS_DIR, f"{tool_name}.json")


def _load(tool_name):
    path = _mapping_path(tool_name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(tool_name, mapping):
    with open(_mapping_path(tool_name), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


# ── Pages ────────────────────────────────────────────────────────────────────

@best_secret_bp.route("/")
def index():
    return render_template("best_secret/index.html", tools=TOOLS)


@best_secret_bp.route("/<tool_name>")
def mapping_tool(tool_name):
    if tool_name not in TOOLS:
        return "Tool not found", 404
    return render_template(
        "best_secret/mapping_tool.html",
        tool_name=tool_name,
        tool_info=TOOLS[tool_name],
        mapping=_load(tool_name),
        all_tools=TOOLS,
    )


# ── Mapping CRUD ─────────────────────────────────────────────────────────────

@best_secret_bp.route("/<tool_name>/save-mapping", methods=["POST"])
def save_mapping(tool_name):
    if tool_name not in TOOLS:
        return jsonify({"error": "Invalid tool"}), 400
    data = request.get_json()
    mapping = {str(k).strip(): str(v).strip() for k, v in data.get("mapping", {}).items() if k}
    _save(tool_name, mapping)
    return jsonify({"success": True, "count": len(mapping)})


@best_secret_bp.route("/<tool_name>/import-mapping", methods=["POST"])
def import_mapping(tool_name):
    if tool_name not in TOOLS:
        return jsonify({"error": "Invalid tool"}), 400
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        if file.filename.endswith(".json"):
            mapping = json.load(file)
        else:
            df = pd.read_csv(BytesIO(file.read()), header=None, dtype=str).fillna("")
            mapping = dict(zip(df.iloc[:, 0].str.strip(), df.iloc[:, 1].str.strip()))
        _save(tool_name, mapping)
        return jsonify({"success": True, "count": len(mapping), "mapping": mapping})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── File processing ──────────────────────────────────────────────────────────

@best_secret_bp.route("/<tool_name>/preview-columns", methods=["POST"])
def preview_columns(tool_name):
    if tool_name not in TOOLS:
        return jsonify({"error": "Invalid tool"}), 400
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        raw = file.read()
        df = pd.read_csv(BytesIO(raw), nrows=5) if file.filename.endswith(".csv") \
             else pd.read_excel(BytesIO(raw), nrows=5)
        cols = [c for c in df.columns.tolist() if not str(c).startswith("Unnamed")]
        preview = df[cols].fillna("").astype(str).to_dict(orient="records")
        return jsonify({"columns": cols, "preview": preview})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@best_secret_bp.route("/<tool_name>/process", methods=["POST"])
def process(tool_name):
    if tool_name not in TOOLS:
        return jsonify({"error": "Invalid tool"}), 400

    file = request.files.get("file")
    source_col = request.form.get("source_column", "").strip()
    output_col = request.form.get("output_column", "").strip() or f"{source_col}_mapped"
    keep_original = request.form.get("unmapped_action", "keep") == "keep"

    if not file or not source_col:
        return jsonify({"error": "File and source column are required"}), 400

    mapping = _load(tool_name)
    try:
        raw = file.read()
        is_csv = file.filename.lower().endswith(".csv")
        df = pd.read_csv(BytesIO(raw)) if is_csv else pd.read_excel(BytesIO(raw))

        if source_col not in df.columns:
            return jsonify({"error": f"Column '{source_col}' not found in file"}), 400

        def apply(val):
            key = str(val).strip()
            return mapping.get(key, val if keep_original else "")

        df[output_col] = df[source_col].apply(apply)

        total    = len(df)
        mapped   = int(df[source_col].apply(lambda v: str(v).strip() in mapping).sum())
        unmapped = total - mapped

        buf = BytesIO()
        base = file.filename.rsplit(".", 1)[0]
        if is_csv:
            df.to_csv(buf, index=False)
            mime = "text/csv"
            dl_name = f"{base}_mapped.csv"
        else:
            df.to_excel(buf, index=False)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            dl_name = f"{base}_mapped.xlsx"

        out_bytes = buf.getvalue()
        return Response(
            out_bytes,
            status=200,
            mimetype=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{dl_name}"',
                "Content-Length": str(len(out_bytes)),
                "X-Mapped":   str(mapped),
                "X-Unmapped": str(unmapped),
                "X-Total":    str(total),
            },
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
