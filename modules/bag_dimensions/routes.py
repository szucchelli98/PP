import json
import os
from io import BytesIO

import pandas as pd
import requests
from flask import Blueprint, Response, jsonify, render_template, request

bag_bp = Blueprint("bag", __name__, template_folder="templates")

SYSTEM_PROMPT = (
    "You are a luxury fashion product data specialist for Philipp Plein.\n"
    "Your task is to estimate realistic bag dimensions (length, width, height in cm, and volume in liters) "
    "based on the bag's category, microcategory, and title information.\n"
    "Rules:\n"
    "- Use ALL THREE fields together: CATEGORY_NAME, MICROCATEGORY_NAME, and TITLE to determine dimensions.\n"
    "- Volume = (length × width × height) / 1000 — result in LITERS.\n"
    "- Return ONLY a valid JSON array. No preamble, no markdown, no backticks.\n"
    "- Each element: { \"row_index\": number, \"length\": number, \"width\": number, \"height\": number, \"volume\": number }\n"
    "- Round length/width/height to 1 decimal. Round volume to 3 decimal places.\n"
    "Guidelines: Mini bag ~18×5×12cm, Clutch ~22×3×14cm, Small shoulder ~24×8×16cm, "
    "Medium shoulder ~30×10×20cm, Large shoulder ~36×13×26cm, Crossbody ~26×7×18cm, "
    "Tote ~40×14×30cm, Backpack ~28×14×38cm, Belt bag ~24×6×12cm, Bucket bag ~22×12×22cm, "
    "Hobo ~34×11×24cm, Duffle ~48×24×26cm, Wallet ~12×2×9cm. "
    "Cross-reference title keywords like mini, large, XL, chain, tote for refinement."
)


def _has_all_dims(row: dict) -> bool:
    for k in ("length", "width", "height", "volume"):
        v = row.get(k)
        if v is None or str(v).strip() == "":
            return False
    return True


def _has_context(row: dict) -> bool:
    return all(
        str(row.get(k, "")).strip() != ""
        for k in ("CATEGORY_NAME", "MICROCATEGORY_NAME", "TITLE")
    )


def _get_style(sku: str) -> str:
    parts = str(sku or "").split("-")
    return parts[1] if len(parts) >= 2 else ""


def _clean_val(v):
    """Convert NaN / pandas NA to None for JSON serialisation."""
    try:
        import math
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


@bag_bp.route("/")
def index():
    return render_template("bag_dimensions/index.html")


@bag_bp.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        df = pd.read_excel(BytesIO(file.read()))

        if "SKU" not in df.columns:
            return jsonify({"error": "File must include a SKU column"}), 400

        # Add dimension columns if they don't exist yet
        for col in ("length", "width", "height", "volume"):
            if col not in df.columns:
                df[col] = None

        headers = df.columns.tolist()
        rows = [
            {k: _clean_val(v) for k, v in record.items()}
            for record in df.to_dict(orient="records")
        ]

        already_filled = sum(1 for r in rows if _has_all_dims(r))
        to_fill = sum(1 for r in rows if not _has_all_dims(r) and _has_context(r))
        no_context = sum(1 for r in rows if not _has_all_dims(r) and not _has_context(r))

        return jsonify({
            "headers": headers,
            "rows": rows,
            "stats": {
                "total": len(rows),
                "already_filled": already_filled,
                "to_fill": to_fill,
                "no_context": no_context,
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bag_bp.route("/infer", methods=["POST"])
def infer():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured on the server"}), 500

    data = request.get_json(force=True, silent=True) or {}
    batch = data.get("batch", [])
    if not batch:
        return jsonify({"results": []}), 200

    msg = "\n".join(
        f"row_index:{i}, SKU:{r.get('SKU','')}, STYLE:{_get_style(str(r.get('SKU','')))},"
        f" TITLE:{r.get('TITLE','')}, CATEGORY_NAME:{r.get('CATEGORY_NAME','')},"
        f" MICROCATEGORY_NAME:{r.get('MICROCATEGORY_NAME','')}"
        for i, r in enumerate(batch)
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": msg}],
            },
            timeout=90,
        )
        resp_data = resp.json()
        text = "".join(c.get("text", "") for c in (resp_data.get("content") or []))
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)

        results = []
        for item in parsed:
            idx = item.get("row_index")
            if idx is None or idx >= len(batch):
                continue
            orig = batch[idx]
            vol = round(float(item["length"]) * float(item["width"]) * float(item["height"]) / 1000, 3)
            results.append({
                **orig,
                "length": item["length"],
                "width": item["width"],
                "height": item["height"],
                "volume": vol,
            })
        return jsonify({"results": results})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bag_bp.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True, silent=True) or {}
    headers = data.get("headers", [])
    rows = data.get("rows", [])

    if not rows:
        return jsonify({"error": "No rows to export"}), 400

    try:
        df = pd.DataFrame([{h: r.get(h, "") for h in headers} for r in rows])
        buf = BytesIO()
        df.to_excel(buf, index=False)
        xlsx_bytes = buf.getvalue()

        return Response(
            xlsx_bytes,
            status=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="philipp_plein_dimensions_filled.xlsx"',
                "Content-Length": str(len(xlsx_bytes)),
            },
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
