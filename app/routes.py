import shutil

from flask import (
    Blueprint, Response, abort, current_app, redirect, render_template, request, url_for,
)

from . import estimate, extractors, passport as passport_module, pdf_export, storage
from .document_reader import DocxReadError

bp = Blueprint("main", __name__)

ALLOWED_EXTENSION = ".docx"
ALLOWED_ESTIMATE_EXTENSION = ".xlsx"


def _projects_root():
    return current_app.config["PROJECTS_ROOT"]


def _selected_compare_slugs(root):
    valid_slugs = set(storage.list_project_slugs(root))
    return list(dict.fromkeys(
        s for s in request.args.getlist("slug") if s in valid_slugs
    ))


@bp.route("/")
def index():
    root = _projects_root()
    slugs = storage.list_project_slugs(root)
    project_names = {
        slug: passport_module.load_passport(storage.passport_path(root, slug)).get("project_name") or slug
        for slug in slugs
    }
    return render_template("index.html", slugs=slugs, project_names=project_names)


@bp.route("/compare", methods=["GET"])
def compare_projects():
    root = _projects_root()
    slugs = _selected_compare_slugs(root)
    if not slugs:
        return redirect(url_for("main.index"))

    passports = {
        slug: passport_module.load_passport(storage.passport_path(root, slug))
        for slug in slugs
    }
    return render_template(
        "compare.html",
        slugs=slugs,
        passports=passports,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        charts=passport_module.build_comparison_charts(passports, slugs),
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
    )


@bp.route("/compare/pdf", methods=["GET"])
def compare_projects_pdf():
    root = _projects_root()
    slugs = _selected_compare_slugs(root)
    if not slugs:
        return redirect(url_for("main.index"))

    passports = {
        slug: passport_module.load_passport(storage.passport_path(root, slug))
        for slug in slugs
    }
    pdf_bytes = pdf_export.build_compare_pdf(
        passports, slugs,
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS,
        passport_module.build_comparison_charts(passports, slugs),
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
    )
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=sravnenie_proektov.pdf"},
    )


@bp.route("/projects/new", methods=["GET"])
def new_project_form():
    return render_template("new_project.html", error=None)


@bp.route("/projects", methods=["POST"])
def create_project():
    root = _projects_root()
    project_name = request.form.get("project_name", "").strip()
    dgp_file = request.files.get("dgp_file")
    tz_file = request.files.get("tz_file")
    smeta_file = request.files.get("smeta_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400
    has_smeta = bool(smeta_file and smeta_file.filename)
    if has_smeta and not smeta_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return render_template("new_project.html", error="Смета должна быть в формате .xlsx"), 400

    try:
        slug = storage.create_project(root, project_name)
    except ValueError:
        # The name is non-empty but consists only of characters slugify
        # strips (e.g. "***"), so there is no usable folder name for it.
        return render_template(
            "new_project.html",
            error="Название проекта должно содержать хотя бы одну букву или цифру",
        ), 400

    raw = storage.raw_dir(root, slug)
    dgp_path = raw / "dgp.docx"
    tz_path = raw / "tz.docx"
    dgp_file.save(dgp_path)
    tz_file.save(tz_path)

    if has_smeta:
        smeta_path = storage.estimate_path(root, slug)
        smeta_file.save(smeta_path)
        try:
            estimate.read_estimate(smeta_path)
        except estimate.EstimateReadError as e:
            current_app.logger.warning("Не удалось разобрать смету: %s", e)
            shutil.rmtree(storage.project_dir(root, slug), ignore_errors=True)
            return render_template(
                "new_project.html",
                error="Не удалось прочитать смету — убедитесь, что это корректный файл .xlsx",
            ), 400

    try:
        data = passport_module.build_passport(project_name, dgp_path, tz_path)
    except DocxReadError as e:
        # Don't let a cleanup failure (file lock, permissions) turn the
        # intended 400 into a 500 — the orphan directory is harmless anyway,
        # storage.list_project_slugs ignores directories without a passport.
        current_app.logger.warning("Не удалось разобрать загруженный файл: %s", e)
        shutil.rmtree(storage.project_dir(root, slug), ignore_errors=True)
        return render_template(
            "new_project.html",
            error="Не удалось прочитать файл — убедитесь, что это корректный .docx",
        ), 400

    passport_module.save_passport(data, storage.passport_path(root, slug))
    return redirect(url_for("main.project_page", slug=slug))


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
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
        price_per_sqm=passport_module.price_per_sqm(data),
        building_class_options=passport_module.BUILDING_CLASS_OPTIONS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        has_estimate=storage.estimate_path(root, slug).exists(),
    )


@bp.route("/projects/<slug>/smeta", methods=["GET"])
def estimate_page(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.estimate_path(root, slug)
    if not path.exists():
        abort(404)
    sheets = estimate.read_estimate(path)
    project_name = passport_module.load_passport(storage.passport_path(root, slug)).get("project_name") or slug
    return render_template("estimate.html", slug=slug, project_name=project_name, sheets=sheets)


@bp.route("/projects/<slug>/delete", methods=["POST"])
def delete_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    storage.delete_project(root, slug)
    return redirect(url_for("main.index"))


@bp.route("/projects/<slug>/rename", methods=["POST"])
def rename_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    new_name = request.form.get("project_name", "").strip()
    if not new_name:
        abort(400)
    path = storage.passport_path(root, slug)
    data = passport_module.load_passport(path)
    data["project_name"] = new_name
    passport_module.save_passport(data, path)
    return redirect(url_for("main.index"))


@bp.route("/projects/<slug>", methods=["POST"])
def update_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    ocr_fields = list(data.get("ocr_fields", []))
    for field in passport_module.PASSPORT_FIELDS:
        if field == "project_name":
            continue
        old_value = data.get(field)
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            new_value = None
        elif field in passport_module.NUMERIC_FIELDS:
            new_value = extractors.parse_number(raw_value)
        else:
            new_value = raw_value
        data[field] = new_value
        if new_value != old_value and field in ocr_fields:
            ocr_fields.remove(field)
    data["ocr_fields"] = ocr_fields
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))
