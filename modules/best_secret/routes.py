import os
import requests
from flask import Blueprint, render_template, request, Response

best_secret_bp = Blueprint("best_secret", __name__, template_folder="templates")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


@best_secret_bp.route("/")
def index():
    return render_template("best_secret/index.html")


@best_secret_bp.route("/api/messages", methods=["POST"])
def proxy_messages():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured"}, 500
    resp = requests.post(
        ANTHROPIC_API_URL,
        json=request.get_json(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        timeout=120,
    )
    return Response(resp.content, status=resp.status_code, mimetype="application/json")
