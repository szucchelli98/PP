import os
import json
from pathlib import Path
from flask import Flask, Response, render_template


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "change-this-before-deploy")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

    from modules.email_generator.routes import email_bp
    from modules.bag_dimensions.routes import bag_bp
    from modules.file_splitter.routes import splitter_bp
    from modules.best_secret.routes import best_secret_bp
    from modules.promo_selection.routes import promo_bp

    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(bag_bp, url_prefix="/bag-dimensions")
    app.register_blueprint(splitter_bp, url_prefix="/file-splitter")
    app.register_blueprint(best_secret_bp, url_prefix="/best-secret")
    app.register_blueprint(promo_bp, url_prefix="/promo-selection")

    @app.errorhandler(Exception)
    def handle_exception(e):
        safe = str(e).replace('"', "'").replace("\n", " ")[:300]
        return Response(f'{{"error":"{safe}"}}', status=500, mimetype="application/json")

    @app.route("/")
    def dashboard():
        status = None
        status_file = Path(__file__).parent.parent / "scripts" / "materials_monitor" / "data" / "status.json"
        if status_file.exists():
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return render_template("dashboard.html", automation_status=status)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
