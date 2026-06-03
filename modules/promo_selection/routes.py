from io import BytesIO
import re

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request

promo_bp = Blueprint("promo_selection", __name__, template_folder="templates")

# ── Discount column detection ─────────────────────────────────────────────────
DISCOUNT_SUFFIX = " discount"

STOCK_COLUMNS = [
    "TOTAL STOCK (ALL REGIONS)",
    "EU STOCK",
    "US STOCK",
    "RU STOCK",
    "ASIA STOCK",
    "AMERICAS STOCK",
    "ITG STOCK",
    "SPEDIMEX STOCK",
    "EU DOS STOCK",
    "DISPLAY ZONE STOCK",
]


def _discount_columns(df: pd.DataFrame) -> list[str]:
    """Return all columns whose name ends with ' discount'."""
    return [c for c in df.columns if c.lower().endswith(DISCOUNT_SUFFIX)]


def _channel_name(col: str) -> str:
    """'bestSecret discount' → 'bestSecret'"""
    return col[: -len(DISCOUNT_SUFFIX)]


def _available_stock_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in STOCK_COLUMNS if c in df.columns]


# ── Routes ────────────────────────────────────────────────────────────────────

@promo_bp.route("/")
def index():
    return render_template("promo_selection/index.html")


@promo_bp.route("/parse", methods=["POST"])
def parse():
    """Read the uploaded file and return channels, categories, microcategories, stock columns.
    Uses openpyxl read-only streaming to avoid loading the full file into memory."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        import openpyxl

        wb = openpyxl.load_workbook(BytesIO(file.read()), read_only=True, data_only=True)
        ws = wb.active

        # First row = headers
        headers = []
        cat_idx = micro_idx = None
        rows_iter = ws.rows

        for cell in next(rows_iter):
            headers.append(cell.value)

        for i, h in enumerate(headers):
            if h == "CATEGORY":
                cat_idx = i
            elif h == "MICROCATEGORY":
                micro_idx = i

        # Detect channels and stock columns from headers alone
        header_series = pd.Series(headers)
        dummy_df = pd.DataFrame(columns=headers)
        channels   = [_channel_name(c) for c in _discount_columns(dummy_df)]
        stock_cols = _available_stock_cols(dummy_df)

        # Stream rows to collect unique categories/microcategories
        categories_set      = set()
        microcategories_set = set()

        for row in rows_iter:
            if cat_idx is not None and cat_idx < len(row) and row[cat_idx].value:
                categories_set.add(str(row[cat_idx].value))
            if micro_idx is not None and micro_idx < len(row) and row[micro_idx].value:
                microcategories_set.add(str(row[micro_idx].value))

        wb.close()

        return jsonify({
            "channels":        channels,
            "categories":      sorted(categories_set),
            "microcategories": sorted(microcategories_set),
            "stock_columns":   stock_cols,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@promo_bp.route("/export", methods=["POST"])
def export():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    # ── Read params ───────────────────────────────────────────────────────────
    channel          = request.form.get("channel", "").strip()
    adjustment_type  = request.form.get("adjustment_type", "extra_discount")   # "extra_discount" | "new_discount"
    adjustment_value = _float(request.form.get("adjustment_value"))             # %

    min_final_price  = _float(request.form.get("min_final_price"))
    max_final_price  = _float(request.form.get("max_final_price"))

    min_channel_disc = _float(request.form.get("min_channel_discount"))
    max_channel_disc = _float(request.form.get("max_channel_discount"))

    stock_col        = request.form.get("stock_column", "").strip()             # e.g. "EU STOCK"
    exclude_zero_stock = request.form.get("exclude_zero_stock") == "true"

    include_cats     = _list(request.form.get("include_categories"))
    exclude_cats     = _list(request.form.get("exclude_categories"))
    include_micros   = _list(request.form.get("include_microcategories"))
    exclude_micros   = _list(request.form.get("exclude_microcategories"))

    try:
        df = pd.read_excel(BytesIO(file.read()))

        # ── Find discount column ──────────────────────────────────────────────
        disc_col = f"{channel}{DISCOUNT_SUFFIX}"
        if disc_col not in df.columns:
            return jsonify({"error": f"Discount column '{disc_col}' not found in file."}), 400

        df[disc_col] = pd.to_numeric(df[disc_col], errors="coerce").fillna(0)
        df["PRICE"]  = pd.to_numeric(df["PRICE"],  errors="coerce").fillna(0)

        # ── Compute final price ───────────────────────────────────────────────
        channel_disc_pct = df[disc_col] / 100.0

        if adjustment_type == "new_discount" and adjustment_value is not None:
            # Override channel discount entirely with the new value
            effective_disc_pct = adjustment_value / 100.0
        else:
            effective_disc_pct = channel_disc_pct  # base

        if adjustment_type == "extra_discount" and adjustment_value is not None:
            # Apply extra % on top of already-discounted price
            df["FINAL PRICE"] = df["PRICE"] * (1 - effective_disc_pct) * (1 - adjustment_value / 100.0)
        else:
            df["FINAL PRICE"] = df["PRICE"] * (1 - effective_disc_pct)

        df["FINAL PRICE"] = df["FINAL PRICE"].round(2)

        # ── Filters ───────────────────────────────────────────────────────────

        # Final price range
        if min_final_price is not None:
            df = df[df["FINAL PRICE"] >= min_final_price]
        if max_final_price is not None:
            df = df[df["FINAL PRICE"] <= max_final_price]

        # Channel discount range
        if min_channel_disc is not None:
            df = df[df[disc_col] >= min_channel_disc]
        if max_channel_disc is not None:
            df = df[df[disc_col] <= max_channel_disc]

        # Stock filter
        if exclude_zero_stock and stock_col and stock_col in df.columns:
            df[stock_col] = pd.to_numeric(df[stock_col], errors="coerce").fillna(0)
            df = df[df[stock_col] > 0]

        # Category filters
        if "CATEGORY" in df.columns:
            if include_cats:
                df = df[df["CATEGORY"].isin(include_cats)]
            if exclude_cats:
                df = df[~df["CATEGORY"].isin(exclude_cats)]

        # Microcategory filters
        if "MICROCATEGORY" in df.columns:
            if include_micros:
                df = df[df["MICROCATEGORY"].isin(include_micros)]
            if exclude_micros:
                df = df[~df["MICROCATEGORY"].isin(exclude_micros)]

        # ── Build output ──────────────────────────────────────────────────────
        # Move FINAL PRICE right after PRICE for readability
        cols = list(df.columns)
        if "PRICE" in cols and "FINAL PRICE" in cols:
            cols.remove("FINAL PRICE")
            price_idx = cols.index("PRICE")
            cols.insert(price_idx + 1, "FINAL PRICE")
            df = df[cols]

        buf = BytesIO()
        df.to_excel(buf, index=False)
        xlsx_bytes = buf.getvalue()

        base = file.filename.rsplit(".", 1)[0]
        return Response(
            xlsx_bytes,
            status=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{base}_promo_selection.xlsx"',
                "Content-Length": str(len(xlsx_bytes)),
                "X-Row-Count": str(len(df)),
            },
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── Helpers ───────────────────────────────────────────────────────────────────

def _float(val) -> float | None:
    try:
        return float(val) if val not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _list(val) -> list[str]:
    """Parse a JSON-encoded list or comma-separated string into a Python list."""
    if not val:
        return []
    val = val.strip()
    if val.startswith("["):
        import json
        try:
            return [str(v) for v in json.loads(val)]
        except Exception:
            pass
    return [v.strip() for v in val.split(",") if v.strip()]
