from io import BytesIO

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request

amazon_brand_bp = Blueprint(
    "amazon_brand_page", __name__, template_folder="templates"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_size(sku: str) -> str:
    """Remove the last underscore-separated segment (the size part).

    '100012_02_1_S'   → '100012_02_1'
    '100046_01_21_35' → '100046_01_21'
    """
    s = str(sku or "").strip()
    idx = s.rfind("_")
    return s[:idx] if idx != -1 else s


def _load_amazon_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Load the Amazon catalogue keeping only the three relevant columns."""
    needed = {"product-id", "seller-sku", "asin1"}
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, low_memory=False)
    else:
        df = pd.read_excel(BytesIO(file_bytes), dtype=str)

    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Amazon file is missing columns: {', '.join(sorted(missing))}")

    return df[list(needed)].fillna("")


def _process_sheet(ean_list: list, amazon_df: pd.DataFrame) -> list:
    """
    Given a list of EANs and the Amazon DataFrame, return a list of ASINs
    (one per unique style derived from the EAN lookup).

    Steps:
      1. EAN → seller-sku  (via product-id column)
      2. seller-sku → style  (strip last _ segment)
      3. deduplicate by style
      4. style → asin1  (via seller-sku column)
    """
    # Build lookup maps once
    ean_to_sku = (
        amazon_df[amazon_df["product-id"] != ""]
        .drop_duplicates(subset="product-id")
        .set_index("product-id")["seller-sku"]
        .to_dict()
    )
    sku_to_asin = (
        amazon_df[amazon_df["seller-sku"] != ""]
        .drop_duplicates(subset="seller-sku")
        .set_index("seller-sku")["asin1"]
        .to_dict()
    )

    seen_styles = set()
    asins = []

    for ean in ean_list:
        ean_str = str(ean).strip()
        if not ean_str or ean_str.lower() == "nan":
            continue

        sku = ean_to_sku.get(ean_str, "")
        if not sku:
            continue

        style = _strip_size(sku)
        if style in seen_styles:
            continue
        seen_styles.add(style)

        # Look up ASIN using the full style SKU (style without size suffix)
        asin = sku_to_asin.get(style, "")
        if not asin:
            # Fallback: try the original full SKU
            asin = sku_to_asin.get(sku, "")

        asins.append(asin if asin else f"NOT FOUND ({style})")

    return asins


# ── Routes ────────────────────────────────────────────────────────────────────

@amazon_brand_bp.route("/")
def index():
    return render_template("amazon_brand_page/index.html")


@amazon_brand_bp.route("/process", methods=["POST"])
def process():
    ean_file = request.files.get("ean_file")
    amazon_file = request.files.get("amazon_file")

    if not ean_file or not amazon_file:
        return jsonify({"error": "Both files are required"}), 400

    try:
        amazon_bytes = amazon_file.read()
        amazon_df = _load_amazon_file(amazon_bytes, amazon_file.filename)
    except Exception as exc:
        return jsonify({"error": f"Amazon file error: {exc}"}), 400

    try:
        ean_bytes = ean_file.read()
        xl = pd.ExcelFile(BytesIO(ean_bytes))
        sheet_names = xl.sheet_names
    except Exception as exc:
        return jsonify({"error": f"EAN file error: {exc}"}), 400

    try:
        output_buf = BytesIO()
        with pd.ExcelWriter(output_buf, engine="openpyxl") as writer:
            for sheet in sheet_names:
                raw_df = xl.parse(sheet, header=None, dtype=str)
                # Flatten all cells, treat every non-empty cell as an EAN
                ean_list = (
                    raw_df.values.flatten().tolist()
                    if not raw_df.empty
                    else []
                )
                asins = _process_sheet(ean_list, amazon_df)
                out_df = pd.DataFrame({"ASIN": asins})
                out_df.to_excel(writer, sheet_name=sheet, index=False)

        xlsx_bytes = output_buf.getvalue()
        base = ean_file.filename.rsplit(".", 1)[0]
        dl_name = f"{base}_ASINs.xlsx"

        return Response(
            xlsx_bytes,
            status=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{dl_name}"',
                "Content-Length": str(len(xlsx_bytes)),
                "X-Sheets": str(len(sheet_names)),
            },
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
