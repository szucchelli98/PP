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
    """Load the Amazon catalogue keeping only the two relevant columns."""
    needed = ["seller-sku", "asin1"]
    fname = filename.lower()
    if fname.endswith(".csv") or fname.endswith(".txt") or fname.endswith(".tsv"):
        sep = "\t" if (fname.endswith(".txt") or fname.endswith(".tsv")) else ","
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, sep=sep, low_memory=False, usecols=needed)
    else:
        df = pd.read_excel(BytesIO(file_bytes), dtype=str, usecols=needed)

    missing = set(needed) - set(df.columns)
    if missing:
        raise ValueError(f"Amazon file is missing columns: {', '.join(sorted(missing))}")

    return df[needed].fillna("")


def _process_sheet(sku_list: list, amazon_df: pd.DataFrame) -> list:
    """
    Given a list of seller-SKUs and the Amazon DataFrame, return a list of ASINs
    (one per unique style).

    Steps:
      1. seller-sku → style  (strip last _ segment)
      2. deduplicate by style
      3. style → asin1  (via seller-sku column)
    """
    sku_to_asin = (
        amazon_df[amazon_df["seller-sku"] != ""]
        .drop_duplicates(subset="seller-sku")
        .set_index("seller-sku")["asin1"]
        .to_dict()
    )

    seen_styles = set()
    asins = []

    for sku in sku_list:
        sku_str = str(sku).strip()
        if not sku_str or sku_str.lower() == "nan":
            continue

        style = _strip_size(sku_str)
        if style in seen_styles:
            continue
        seen_styles.add(style)

        asin = sku_to_asin.get(style, "")
        if not asin:
            # Fallback: try the original full SKU
            asin = sku_to_asin.get(sku_str, "")

        asins.append(asin if asin else f"NOT FOUND ({style})")

    return asins


# ── Routes ────────────────────────────────────────────────────────────────────

@amazon_brand_bp.route("/")
def index():
    return render_template("amazon_brand_page/index.html")


@amazon_brand_bp.route("/process", methods=["POST"])
def process():
    sku_file = request.files.get("sku_file")
    amazon_file = request.files.get("amazon_file")

    if not sku_file or not amazon_file:
        return jsonify({"error": "Both files are required"}), 400

    try:
        amazon_bytes = amazon_file.read()
        amazon_df = _load_amazon_file(amazon_bytes, amazon_file.filename)
    except Exception as exc:
        return jsonify({"error": f"Amazon file error: {exc}"}), 400

    try:
        sku_bytes = sku_file.read()
        xl = pd.ExcelFile(BytesIO(sku_bytes))
        sheet_names = xl.sheet_names
    except Exception as exc:
        return jsonify({"error": f"SKU file error: {exc}"}), 400

    try:
        output_buf = BytesIO()
        with pd.ExcelWriter(output_buf, engine="openpyxl") as writer:
            for sheet in sheet_names:
                raw_df = xl.parse(sheet, header=None, dtype=str)
                sku_list = (
                    raw_df.values.flatten().tolist()
                    if not raw_df.empty
                    else []
                )
                asins = _process_sheet(sku_list, amazon_df)
                out_df = pd.DataFrame({"ASIN": asins})
                out_df.to_excel(writer, sheet_name=sheet, index=False)

        xlsx_bytes = output_buf.getvalue()
        base = sku_file.filename.rsplit(".", 1)[0]
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
