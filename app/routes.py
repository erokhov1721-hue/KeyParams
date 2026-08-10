import shutil

from flask import Blueprint, abort, current_app, make_response, redirect, render_template, request, url_for

from . import extractors, passport as passport_module, storage
from .document_reader import DocxReadError

bp = Blueprint("main", __name__)

ALLOWED_EXTENSION = ".docx"
AREA_FIELDS = {"underground_area_sqm", "aboveground_area_sqm", "total_area_sqm"}


def _projects_root():
    return current_app.config["PROJECTS_ROOT"]


@bp.route("/")
def index():
    slugs = storage.list_project_slugs(_projects_root())
    return render_template("index.html", slugs=slugs)


@bp.route("/projects/new", methods=["GET"])
def new_project_form():
    return render_template("new_project.html", error=None)


@bp.route("/projects", methods=["POST"])
def create_project():
    root = _projects_root()
    project_name = request.form.get("project_name", "").strip()
    dgp_file = request.files.get("dgp_file")
    tz_file = request.files.get("tz_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400

    slug = storage.create_project(root, project_name)
    raw = storage.raw_dir(root, slug)
    dgp_path = raw / "dgp.docx"
    tz_path = raw / "tz.docx"
    dgp_file.save(dgp_path)
    tz_file.save(tz_path)

    try:
        data = passport_module.build_passport(project_name, dgp_path, tz_path)
    except DocxReadError as e:
        shutil.rmtree(storage.project_dir(root, slug))
        return render_template("new_project.html", error=f"Не удалось прочитать файл: {e}"), 400

    passport_module.save_passport(data, storage.passport_path(root, slug))
    resp = make_response("", 302)
    resp.headers["Location"] = f"/projects/{slug}"
    return resp


@bp.route("/projects/<slug>", methods=["GET"])
def project_page(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    return render_template(
        "project.html", slug=slug, passport=data, fields=passport_module.PASSPORT_FIELDS
    )


@bp.route("/projects/<slug>", methods=["POST"])
def update_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    for field in passport_module.PASSPORT_FIELDS:
        if field == "project_name":
            continue
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            data[field] = None
        elif field in AREA_FIELDS:
            data[field] = extractors.parse_number(raw_value)
        else:
            data[field] = raw_value
    passport_module.save_passport(data, path)
    resp = make_response("", 302)
    resp.headers["Location"] = f"/projects/{slug}"
    return resp
