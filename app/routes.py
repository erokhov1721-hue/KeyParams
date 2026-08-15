import shutil
from pathlib import Path

from flask import (
    Blueprint, Response, abort, current_app, redirect, render_template, request, send_file,
    url_for,
)

from . import estimate, extractors, passport as passport_module, pdf_export, storage
from .document_reader import DocxReadError

bp = Blueprint("main", __name__)

ALLOWED_EXTENSION = ".docx"
ALLOWED_ESTIMATE_EXTENSION = ".xlsx"
ALLOWED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_COVER_SIZE = 5 * 1024 * 1024
ALLOWED_CONTRACT_TERMS_EXTENSION = ".pdf"
MAX_CONTRACT_TERMS_SIZE = 15 * 1024 * 1024


def _projects_root():
    return current_app.config["PROJECTS_ROOT"]


def _selected_compare_slugs(root):
    valid_slugs = set(storage.list_project_slugs(root))
    return list(dict.fromkeys(
        s for s in request.args.getlist("slug") if s in valid_slugs
    ))


def _project_names(root, slugs):
    return {
        slug: passport_module.load_passport(storage.passport_path(root, slug)).get("project_name") or slug
        for slug in slugs
    }


def _cover_version(root, slug):
    path = storage.cover_path(root, slug)
    return int(path.stat().st_mtime) if path else None


@bp.app_context_processor
def inject_sidebar_projects():
    root = _projects_root()
    slugs = storage.list_project_slugs(root)
    return {
        "sidebar_slugs": slugs,
        "sidebar_names": _project_names(root, slugs),
        "sidebar_covers": {slug: _cover_version(root, slug) for slug in slugs},
    }


@bp.route("/")
def index():
    root = _projects_root()
    slugs = storage.list_project_slugs(root)
    project_names = _project_names(root, slugs)
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
    contract_terms_file = request.files.get("contract_terms_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400
    has_smeta = bool(smeta_file and smeta_file.filename)
    if has_smeta and not smeta_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return render_template("new_project.html", error="Смета должна быть в формате .xlsx"), 400
    has_contract_terms = bool(contract_terms_file and contract_terms_file.filename)
    if has_contract_terms:
        if not contract_terms_file.filename.lower().endswith(ALLOWED_CONTRACT_TERMS_EXTENSION):
            return render_template(
                "new_project.html",
                error="Протокол окончательных условий должен быть в формате PDF",
            ), 400
        contract_terms_file.seek(0, 2)
        if contract_terms_file.tell() > MAX_CONTRACT_TERMS_SIZE:
            contract_terms_file.seek(0)
            return render_template(
                "new_project.html",
                error="Файл протокола слишком большой — до 15 МБ",
            ), 400
        contract_terms_file.seek(0)

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

    problem = None
    if has_contract_terms:
        # Built after the passport so the VAT rule has the signing year.
        dest = storage.contract_terms_path(root, slug)
        contract_terms_file.save(dest)
        extracted, filled, problem = passport_module.build_contract_terms(
            dest, year_signed=data.get("year_signed"),
        )
        data.update(extracted)
        data["contract_auto_fields"] = filled

    passport_module.save_passport(data, storage.passport_path(root, slug))
    return redirect(url_for("main.project_page", slug=slug, problem=problem))


@bp.route("/projects/<slug>", methods=["GET"])
def project_page(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    estimate_file = storage.estimate_path(root, slug)
    has_estimate = estimate_file.exists()
    return render_template(
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
        ai_fields=data.get("ai_fields", []),
        price_per_sqm=passport_module.price_per_sqm(data),
        building_class_options=passport_module.BUILDING_CLASS_OPTIONS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        has_estimate=has_estimate,
        sheets=estimate.read_estimate(estimate_file) if has_estimate else [],
        cover_version=_cover_version(root, slug),
        has_contract_terms=storage.contract_terms_path(root, slug).exists(),
        contract_fields=passport_module.CONTRACT_FIELDS,
        contract_field_labels=passport_module.CONTRACT_FIELD_LABELS,
        contract_auto_fields=data.get("contract_auto_fields", []),
        # Looked up in a fixed table, so an arbitrary ?problem=... value
        # renders nothing rather than reaching the page.
        contract_problem=passport_module.CONTRACT_PROBLEM_MESSAGES.get(
            request.args.get("problem")
        ),
    )


@bp.route("/projects/<slug>/cover", methods=["GET"])
def project_cover(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.cover_path(root, slug)
    if not path:
        abort(404)
    return send_file(path)


@bp.route("/projects/<slug>/cover", methods=["POST"])
def upload_project_cover(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    cover_file = request.files.get("cover_file")
    ext = Path(cover_file.filename).suffix.lower() if cover_file and cover_file.filename else ""
    if not cover_file or ext not in ALLOWED_COVER_EXTENSIONS:
        abort(400)

    cover_file.seek(0, 2)
    size = cover_file.tell()
    cover_file.seek(0)
    if size > MAX_COVER_SIZE:
        abort(400)

    storage.save_cover(root, slug, cover_file, ext)
    return redirect(url_for("main.project_page", slug=slug))


@bp.route("/projects/<slug>/contract-terms", methods=["POST"])
def upload_contract_terms(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    pdf_file = request.files.get("contract_terms_file")
    if not pdf_file or not pdf_file.filename.lower().endswith(ALLOWED_CONTRACT_TERMS_EXTENSION):
        abort(400)

    pdf_file.seek(0, 2)
    size = pdf_file.tell()
    pdf_file.seek(0)
    if size > MAX_CONTRACT_TERMS_SIZE:
        abort(400)

    dest = storage.contract_terms_path(root, slug)
    pdf_file.save(dest)

    path = storage.passport_path(root, slug)
    data = passport_module.load_passport(path)
    extracted, filled, problem = passport_module.build_contract_terms(
        dest, year_signed=data.get("year_signed"),
    )
    data.update(extracted)
    data["contract_auto_fields"] = filled
    passport_module.save_passport(data, path)
    # A problem code travels back as a query parameter rather than a flash
    # message: flashing would need a SECRET_KEY, which this app doesn't set.
    return redirect(url_for("main.project_page", slug=slug, problem=problem))


@bp.route("/projects/<slug>/contract", methods=["POST"])
def update_contract_terms(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)

    data = passport_module.load_passport(path)
    auto_fields = list(data.get("contract_auto_fields", []))
    for field in passport_module.CONTRACT_FIELDS:
        old_value = data.get(field)
        new_value = request.form.get(field, "").strip() or None
        data[field] = new_value
        if new_value != old_value and field in auto_fields:
            auto_fields.remove(field)
    data["contract_auto_fields"] = auto_fields
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))


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
    ai_fields = list(data.get("ai_fields", []))
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
        if new_value != old_value and field in ai_fields:
            ai_fields.remove(field)
    data["ocr_fields"] = ocr_fields
    data["ai_fields"] = ai_fields
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))
