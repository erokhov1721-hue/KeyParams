from pathlib import Path

from flask import Flask


def create_app(projects_root=None):
    app = Flask(__name__)
    app.config["PROJECTS_ROOT"] = Path(
        projects_root or Path(__file__).resolve().parent.parent / "storage" / "projects"
    )

    from . import excel_report_routes, routes
    app.register_blueprint(routes.bp)
    app.register_blueprint(excel_report_routes.excel_report_bp)

    return app
