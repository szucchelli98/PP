import os
from flask import Flask, render_template


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "change-this-before-deploy")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

    from modules.email_generator.routes import email_bp
    from modules.bag_dimensions.routes import bag_bp
    from modules.file_splitter.routes import splitter_bp
    from modules.best_secret.routes import best_secret_bp

    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(bag_bp, url_prefix="/bag-dimensions")
    app.register_blueprint(splitter_bp, url_prefix="/file-splitter")
    app.register_blueprint(best_secret_bp, url_prefix="/best-secret")

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
