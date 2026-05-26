from flask import Blueprint, render_template

splitter_bp = Blueprint("splitter", __name__, template_folder="templates")


@splitter_bp.route("/")
def index():
    return render_template("file_splitter/index.html")
