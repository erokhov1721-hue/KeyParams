import io
from pathlib import Path

from flask import (
    Blueprint, Response, abort, current_app, redirect, render_template, request, send_file,
    url_for,
)

from . import (
    comparison, cost_increase, estimate, estimate_sections, excel_report, extractors,
    passport as passport_module, pdf_export, pdf_reader, project_filter, storage,
    upload_guard, workbook_cache,
)
from .document_reader import DocxReadError

bp = Blueprint("main", __name__)

ALLOWED_EXTENSION = ".docx"
ALLOWED_ESTIMATE_EXTENSION = ".xlsx"
ALLOWED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_COVER_SIZE = 5 * 1024 * 1024
ALLOWED_CONTRACT_TERMS_EXTENSION = ".pdf"
MAX_CONTRACT_TERMS_SIZE = 15 * 1024 * 1024
MAX_COST_INCREASE_SIZE = 15 * 1024 * 1024


def _projects_root():
    return current_app.config["PROJECTS_ROOT"]


def _selected_compare_slugs(root):
    valid_slugs = set(storage.list_project_slugs(root))
    return list(dict.fromkeys(
        s for s in request.args.getlist("slug") if s in valid_slugs
    ))


def _safe_passport(root, slug):
    """The project's passport, or an empty one if the file can't be read.

    A passport that can't be parsed falls back rather than raising: this runs
    from the sidebar context processor and the dashboard list, so one
    corrupted file would otherwise take down every page in the app —
    including the dashboard itself, which is where the project can actually
    be deleted from. A page that reads the passport as its whole reason for
    being there (project_page and the rest) instead lets PassportReadError
    reach the errorhandler below, which says so explicitly rather than
    showing a broken project as a quietly empty one.
    """
    try:
        return passport_module.load_passport(storage.passport_path(root, slug))
    except passport_module.PassportReadError:
        return {}


def _project_name(root, slug):
    """The project's own name, falling back to its folder name."""
    return _safe_passport(root, slug).get("project_name") or slug


def _project_names(root, slugs):
    return {slug: _project_name(root, slug) for slug in slugs}


def _cover_problem(cover_file):
    """Why this photo can't be used, in words, or None if it can.

    Shared by the two places a cover arrives — the create form and the camera
    button on the project list — so neither can quietly accept what the other
    refuses.
    """
    ext = Path(cover_file.filename).suffix.lower() if cover_file.filename else ""
    if ext not in ALLOWED_COVER_EXTENSIONS:
        return "Фото объекта должно быть в формате JPG, PNG или WEBP"
    if not upload_guard.is_image(cover_file, ext):
        return "Файл не похож на изображение JPG, PNG или WEBP — проверьте, что это оно"
    cover_file.seek(0, 2)
    size = cover_file.tell()
    cover_file.seek(0)
    if size > MAX_COVER_SIZE:
        return "Файл фото слишком большой — до 5 МБ"
    return None


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


def _project_list_context(root):
    """Список проектов и фильтр к нему.

    Одно и то же нужно двум страницам — общему списку проектов и выбору
    проектов для сравнения. Собирается здесь, чтобы фильтр на них работал
    ровно одинаково и не мог разойтись.
    """
    slugs = storage.list_project_slugs(root)
    passports = {slug: _safe_passport(root, slug) for slug in slugs}
    filters = project_filter.build(passports, request.args)
    return {
        "slugs": filters["slugs"],
        "project_names": {
            slug: passport.get("project_name") or slug
            for slug, passport in passports.items()
        },
        "filters": filters,
        "has_projects": bool(slugs),
    }


@bp.route("/")
def index():
    root = _projects_root()
    # Finish off any delete that a file in use left unfinished. The dashboard
    # is where the user lands after deleting and every time they come back,
    # so it's the one place a retry is guaranteed to get its chance.
    storage.purge_deleted(root)
    return render_template("index.html", **_project_list_context(root))


@bp.route("/compare/select", methods=["GET"])
def compare_select():
    """Выбор проектов для сравнения — на своей странице.

    Список и фильтр здесь те же, что на главной; разница в том, что у строк
    стоят галочки, а наверху — «Сравнить проекты» и «Выгрузить в Excel».
    Заведение проектов и их сравнение начинаются с разных ссылок в боковом
    меню, и ни одна страница не делает обе работы сразу.
    """
    return render_template("compare_select.html", **_project_list_context(_projects_root()))


@bp.route("/compare", methods=["GET"])
def compare_projects():
    root = _projects_root()
    slugs = _selected_compare_slugs(root)
    if not slugs:
        # Сравнивать нечего — значит, человеку нужно выбрать проекты, и вести
        # его следует туда, где выбирают, а не на общий список.
        return redirect(url_for("main.compare_select"))

    passports = {
        slug: passport_module.load_passport(storage.passport_path(root, slug))
        for slug in slugs
    }
    adjustments = comparison.adjustments_from_args(request.args)
    costs = _section_costs(root, slugs)
    left, right = _pair_choice(slugs)
    concrete_coefficients = _concrete_coefficients(root, slugs, passports)
    facade_coefficients = _facade_coefficients(root, slugs, passports)
    group_by = _averages_group_by(request.args)
    return render_template(
        "compare.html",
        pair=comparison.build_pair_cards(left, right, passports, costs, adjustments),
        pair_left=left,
        pair_right=right,
        slugs=slugs,
        passports=passports,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        charts=passport_module.build_comparison_charts(
            passports, slugs,
            concrete_coefficients=concrete_coefficients,
            facade_coefficients=facade_coefficients,
        ),
        project_colors=passport_module.project_colors(slugs),
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        sections=comparison.build_section_table(slugs, passports, costs, adjustments),
        terms=comparison.build_terms_table(slugs, passports),
        increase=comparison.build_increase_summary(
            slugs, passports, _increase_reports(root, slugs, costs), adjustments,
        ),
        averages=comparison.build_averages_table(
            slugs, passports, costs, adjustments, group_by=group_by,
        ),
        averages_group_by=group_by,
        averages_group_options=project_filter.GROUPS,
        adjustments=adjustments,
    )


def _averages_group_by(args):
    """Какое поле выбрано в переключателе таблицы средних, или None — вкладка
    «Все объекты». Значение из адреса, которого нет среди известных ключей
    группировки (чужой параметр, опечатка), читается как «Все объекты», а не
    как ошибка.
    """
    group_by = args.get("avg_group")
    return group_by if group_by in project_filter.GROUP_KEYS else None


def _pair_choice(slugs):
    """Which two projects the cards put head to head.

    Whatever was picked in the two selectors, as long as both are among the
    projects on the page; otherwise the first two, so the cards are there to
    look at without having to choose first.
    """
    chosen = [request.args.get("left"), request.args.get("right")]
    left, right = (slug if slug in slugs else None for slug in chosen)
    if left is None:
        left = slugs[0] if slugs else None
    if right is None:
        right = next((slug for slug in slugs if slug != left), None)
    return left, right


def _increase_reports(root, slugs, costs):
    """Удорожание каждого проекта — ``{slug: отчёт | None}``.

    None у проекта без файла удорожания и у проекта, чей файл прочитать не
    удалось: сравнение из-за одного испорченного файла падать не должно, а
    в расчёт такой проект всё равно не идёт.

    Смета берётся уже прочитанная — та же, что легла в таблицу разделов, —
    чтобы удорожание на этой странице считалось от той же базы, что и цифры
    рядом с ним.
    """
    reports = {}
    for slug in slugs:
        path = storage.cost_increase_path(root, slug)
        if not path.exists():
            reports[slug] = None
            continue
        try:
            reports[slug] = cost_increase.read_report(path, costs.get(slug) or {})
        except cost_increase.CostIncreaseError as e:
            current_app.logger.warning(
                "Проект «%s»: файл удорожания не прочитан: %s", slug, e
            )
            reports[slug] = None
    return reports


def _section_costs(root, slugs):
    """Each project's estimate, read into the report's cost lines.

    Goes through the same reader the Excel export uses, so a figure on the
    page and the same figure in the downloaded workbook cannot disagree.
    """
    return {slug: excel_report.estimate_costs(root, slug)[0] for slug in slugs}


@bp.route("/compare/pdf", methods=["GET"])
def compare_projects_pdf():
    root = _projects_root()
    slugs = _selected_compare_slugs(root)
    if not slugs:
        return redirect(url_for("main.compare_select"))

    passports = {
        slug: passport_module.load_passport(storage.passport_path(root, slug))
        for slug in slugs
    }
    # Ровно то же, что собирает страница сравнения, и из того же места: файл
    # должен показывать её целиком, включая поправки на НДС и инфляцию и
    # выбранную пару объектов, — иначе цифра на экране и цифра в файле
    # расходятся, а виновата в этом выгрузка.
    adjustments = comparison.adjustments_from_args(request.args)
    costs = _section_costs(root, slugs)
    left, right = _pair_choice(slugs)
    concrete_coefficients = _concrete_coefficients(root, slugs, passports)
    facade_coefficients = _facade_coefficients(root, slugs, passports)
    pdf_bytes = pdf_export.build_compare_pdf(
        passports, slugs,
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS,
        passport_module.build_comparison_charts(
            passports, slugs,
            concrete_coefficients=concrete_coefficients,
            facade_coefficients=facade_coefficients,
        ),
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        sections=comparison.build_section_table(slugs, passports, costs, adjustments),
        pair=comparison.build_pair_cards(left, right, passports, costs, adjustments),
        terms=comparison.build_terms_table(slugs, passports),
        increase=comparison.build_increase_summary(
            slugs, passports, _increase_reports(root, slugs, costs), adjustments,
        ),
        averages=comparison.build_averages_table(
            slugs, passports, costs, adjustments,
            group_by=_averages_group_by(request.args),
        ),
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
    cover_file = request.files.get("cover_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not upload_guard.is_office_zip(dgp_file):
        return render_template(
            "new_project.html",
            error="Файл Договора повреждён или не является настоящим .docx",
        ), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400
    if not upload_guard.is_office_zip(tz_file):
        return render_template(
            "new_project.html", error="Файл ТЗ повреждён или не является настоящим .docx",
        ), 400
    has_smeta = bool(smeta_file and smeta_file.filename)
    if has_smeta and not smeta_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return render_template("new_project.html", error="Смета должна быть в формате .xlsx"), 400
    if has_smeta and not upload_guard.is_office_zip(smeta_file):
        return render_template(
            "new_project.html", error="Файл сметы повреждён или не является настоящим .xlsx",
        ), 400
    has_contract_terms = bool(contract_terms_file and contract_terms_file.filename)
    if has_contract_terms:
        if not contract_terms_file.filename.lower().endswith(ALLOWED_CONTRACT_TERMS_EXTENSION):
            return render_template(
                "new_project.html",
                error="Протокол окончательных условий должен быть в формате PDF",
            ), 400
        if not upload_guard.is_pdf(contract_terms_file):
            return render_template(
                "new_project.html",
                error="Файл протокола повреждён или не является настоящим PDF",
            ), 400
        contract_terms_file.seek(0, 2)
        if contract_terms_file.tell() > MAX_CONTRACT_TERMS_SIZE:
            contract_terms_file.seek(0)
            return render_template(
                "new_project.html",
                error="Файл протокола слишком большой — до 15 МБ",
            ), 400
        contract_terms_file.seek(0)
    has_cover = bool(cover_file and cover_file.filename)
    if has_cover:
        problem = _cover_problem(cover_file)
        if problem:
            return render_template("new_project.html", error=problem), 400

    try:
        slug, staging_root = storage.begin_project(root, project_name)
    except ValueError:
        # The name is non-empty but consists only of characters slugify
        # strips (e.g. "***"), so there is no usable folder name for it.
        return render_template(
            "new_project.html",
            error="Название проекта должно содержать хотя бы одну букву или цифру",
        ), 400

    # Built in a staging directory — root/.staging/<slug>, not root/<slug> —
    # and published by rename only once the passport is written. A creation
    # that fails partway (a corrupt upload, a crash) then leaves its debris
    # in staging, invisible to list_project_slugs and swept away on the next
    # restart, rather than a half-built project sitting in the real project
    # list with documents on disk and no way to reach it through the UI.
    raw = storage.raw_dir(staging_root, slug)
    dgp_path = raw / "dgp.docx"
    tz_path = raw / "tz.docx"
    dgp_file.save(dgp_path)
    tz_file.save(tz_path)

    if has_cover:
        storage.save_cover(
            staging_root, slug, cover_file, Path(cover_file.filename).suffix.lower(),
        )

    if has_smeta:
        smeta_path = storage.estimate_path(staging_root, slug)
        smeta_file.save(smeta_path)
        try:
            estimate.read_estimate(smeta_path)
        except estimate.EstimateReadError as e:
            current_app.logger.warning("Не удалось разобрать смету: %s", e)
            storage.discard_staging(staging_root, slug)
            return render_template(
                "new_project.html",
                error="Не удалось прочитать смету — убедитесь, что это корректный файл .xlsx",
            ), 400

    try:
        data = passport_module.build_passport(project_name, dgp_path, tz_path)
    except DocxReadError as e:
        current_app.logger.warning("Не удалось разобрать загруженный файл: %s", e)
        storage.discard_staging(staging_root, slug)
        return render_template(
            "new_project.html",
            error="Не удалось прочитать файл — убедитесь, что это корректный .docx",
        ), 400

    problem = None
    if has_contract_terms:
        # Built after the passport so the VAT rule has the signing year.
        dest = storage.contract_terms_path(staging_root, slug)
        contract_terms_file.save(dest)
        try:
            extracted, filled, problem = passport_module.build_contract_terms(
                dest, year_signed=data.get("year_signed"), project_name=project_name,
            )
        except pdf_reader.PdfReadError as e:
            current_app.logger.warning("Не удалось прочитать протокол: %s", e)
            storage.discard_staging(staging_root, slug)
            return render_template(
                "new_project.html",
                error="Не удалось прочитать протокол — убедитесь, что это корректный PDF",
            ), 400
        data.update(extracted)
        data["contract_auto_fields"] = filled

    passport_module.save_passport(data, storage.passport_path(staging_root, slug))
    storage.publish_project(root, slug, staging_root)
    return redirect(url_for("main.project_page", slug=slug, problem=problem))


def _estimate_totals(root, slug):
    """Стоимость по видам работ из сметы проекта — то, с чем сверяется столбец
    «было» файла удорожания. Пустой словарь, если сметы нет или её не удалось
    разобрать: тогда сверять просто не с чем, и об этом честно говорится на
    странице, а не выдаётся за сошедшуюся проверку.

    Читается тем же кодом, что и сравнение проектов, — иначе одна и та же
    смета давала бы здесь одни цифры, а там другие.
    """
    return excel_report.estimate_costs(root, slug)[0]


def _estimate_unmatched_sections(root, slug):
    """Названия разделов сметы, которым не нашлось строки в отчёте — то же,
    что тихо уходит в лог estimate_sections, но здесь для показа на
    странице: раздел, пропавший из отчёта, не должен быть виден только
    тому, кто читает лог продакшна.
    """
    return excel_report.estimate_costs(root, slug)[2]


def _concrete_volume_from_estimate(root, slug):
    """Объём монолита по смете проекта, в м³ — «Предлагаемое количество» из
    раздела «Возведение несущих конструкций здания». None, если сметы нет, её
    не удалось разобрать, или в ней нет такого раздела: коэффициент бетона
    тогда посчитать не из чего, и страница должна честно об этом сказать, а
    не подставлять ноль.
    """
    path = storage.estimate_path(root, slug)
    if not path.exists():
        return None
    try:
        return estimate_sections.read_concrete_volume(path)
    except estimate_sections.EstimateSectionsError as e:
        current_app.logger.warning("Не удалось прочитать смету: %s", e)
        return None


def _concrete_volume(root, slug, passport_data):
    """Действующий объём монолита: вписанный вручную в паспорте, а если там
    пусто — тот, что нашёлся в смете. Ручное значение важнее смeтного — оно и
    существует ради тех случаев, где разбор смет ошибается, смета устроена не
    так, как он ожидает, или её вовсе нет.
    """
    manual = passport_data.get(passport_module.CONCRETE_VOLUME_FIELD)
    if manual is not None:
        return manual
    return _concrete_volume_from_estimate(root, slug)


def _concrete_coefficients(root, slugs, passports):
    """``{slug: коэффициент}`` для сравнения проектов — та же формула, что и
    на странице проекта, посчитанная для каждого выбранного проекта."""
    return {
        slug: passport_module.concrete_coefficient(
            passports[slug], _concrete_volume(root, slug, passports[slug])
        )
        for slug in slugs
    }


def _facade_area_from_estimate(root, slug):
    """Площадь фасада по смете проекта, в м² — «Предлагаемое количество» из
    раздела сметы, в заголовке которого встречается «фасад». None, если
    сметы нет, её не удалось разобрать, или в ней нет такого раздела."""
    path = storage.estimate_path(root, slug)
    if not path.exists():
        return None
    try:
        return estimate_sections.read_facade_area(path)
    except estimate_sections.EstimateSectionsError as e:
        current_app.logger.warning("Не удалось прочитать смету: %s", e)
        return None


def _facade_area(root, slug, passport_data):
    """Действующая площадь фасада: вписанная вручную в паспорте, а если там
    пусто — та, что нашлась в смете. Ручное значение важнее смeтного: оно и
    существует ради тех случаев, где разбор смет ошибается или смета устроена
    не так, как он ожидает.
    """
    manual = passport_data.get(passport_module.FACADE_AREA_FIELD)
    if manual is not None:
        return manual
    return _facade_area_from_estimate(root, slug)


def _facade_coefficients(root, slugs, passports):
    """``{slug: коэффициент}`` для сравнения проектов — та же формула, что и
    на странице проекта, посчитанная для каждого выбранного проекта."""
    return {
        slug: passport_module.facade_coefficient(
            passports[slug], _facade_area(root, slug, passports[slug])
        )
        for slug in slugs
    }


def _cost_increase_report(root, slug):
    """Удорожание по видам работ, или None, если читать нечего.

    None и там, где файл есть, но прочитать его не удалось: файл, который
    после загрузки успели поправить в Excel, не должен ронять всю страницу
    проекта — на ней, кроме удорожания, есть и паспорт, и смета.
    """
    path = storage.cost_increase_path(root, slug)
    if not path.exists():
        return None
    try:
        return cost_increase.read_report(path, _estimate_totals(root, slug))
    except cost_increase.CostIncreaseError as e:
        current_app.logger.warning("Не удалось прочитать файл удорожания: %s", e)
        return None


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
    increase_file = storage.cost_increase_path(root, slug)
    concrete_volume = _concrete_volume(root, slug, data)
    concrete_coefficient = passport_module.concrete_coefficient(data, concrete_volume)
    facade_area = _facade_area(root, slug, data)
    facade_coefficient = passport_module.facade_coefficient(data, facade_area)
    estimate_unmatched_sections = (
        _estimate_unmatched_sections(root, slug) if has_estimate else []
    )
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
        concrete_volume=concrete_volume,
        concrete_coefficient=concrete_coefficient,
        facade_area=facade_area,
        facade_coefficient=facade_coefficient,
        estimate_unmatched_sections=estimate_unmatched_sections,
        cover_version=_cover_version(root, slug),
        has_contract_terms=storage.contract_terms_path(root, slug).exists(),
        has_cost_increase=increase_file.exists(),
        cost_increase_report=_cost_increase_report(root, slug),
        format_percent=cost_increase.format_percent,
        format_delta=cost_increase.format_delta,
        cost_increase_problem=cost_increase.PROBLEM_MESSAGES.get(
            request.args.get("increase")
        ),
        dgp_problem=passport_module.DGP_PROBLEM_MESSAGES.get(request.args.get("dgp")),
        estimate_problem=estimate.PROBLEM_MESSAGES.get(request.args.get("estimate")),
        contract_fields=passport_module.CONTRACT_FIELDS,
        contract_field_labels=passport_module.CONTRACT_FIELD_LABELS,
        contract_auto_fields=data.get("contract_auto_fields", []),
        # Looked up in a fixed table, so an arbitrary ?problem=... value
        # renders nothing rather than reaching the page.
        contract_problem=passport_module.CONTRACT_PROBLEM_MESSAGES.get(
            request.args.get("problem")
        ),
    )


@bp.route("/projects/<slug>/pdf", methods=["GET"])
def project_pdf(slug):
    """Справка по объекту одним файлом — то же, что и на странице, кроме
    самой сметы: она нужна отдельно, а тысячи её строк только раздули бы
    файл.
    """
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    has_estimate = storage.estimate_path(root, slug).exists()
    concrete_volume = _concrete_volume(root, slug, data)
    concrete_coefficient = passport_module.concrete_coefficient(data, concrete_volume)
    facade_area = _facade_area(root, slug, data)
    facade_coefficient = passport_module.facade_coefficient(data, facade_area)
    pdf_bytes = pdf_export.build_project_pdf(
        data,
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        has_contract_terms=storage.contract_terms_path(root, slug).exists(),
        contract_fields=passport_module.CONTRACT_FIELDS,
        contract_field_labels=passport_module.CONTRACT_FIELD_LABELS,
        cover_path=storage.cover_path(root, slug),
        has_estimate=has_estimate,
        concrete_volume=concrete_volume,
        concrete_coefficient=concrete_coefficient,
        facade_area=facade_area,
        facade_coefficient=facade_coefficient,
        cost_increase_report=_cost_increase_report(root, slug),
        format_percent=cost_increase.format_percent,
        format_delta=cost_increase.format_delta,
    )
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        # Не имя слага: он бывает кириллическим, а Content-Disposition без
        # RFC 5987 кодировки такое не переживает.
        headers={"Content-Disposition": "attachment; filename=spravka_obekta.pdf"},
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
    if not cover_file or not cover_file.filename or _cover_problem(cover_file):
        abort(400)

    storage.save_cover(root, slug, cover_file, Path(cover_file.filename).suffix.lower())
    return redirect(url_for("main.project_page", slug=slug))


@bp.route("/projects/<slug>/contract-terms", methods=["POST"])
def upload_contract_terms(slug):
    """Заменить протокол условий.

    Файл сначала разбирается во временном месте и только при успехе занимает
    место старого — как и у ДГП со сметой: файл, чья подпись PDF настоящая,
    но содержимое повреждено, не должен стирать протокол, который уже
    успешно читался.
    """
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    pdf_file = request.files.get("contract_terms_file")
    if not pdf_file or not pdf_file.filename.lower().endswith(ALLOWED_CONTRACT_TERMS_EXTENSION):
        abort(400)
    if not upload_guard.is_pdf(pdf_file):
        abort(400)

    pdf_file.seek(0, 2)
    size = pdf_file.tell()
    pdf_file.seek(0)
    if size > MAX_CONTRACT_TERMS_SIZE:
        abort(400)

    dest = storage.contract_terms_path(root, slug)
    tmp = dest.with_name(dest.name + ".upload")
    pdf_file.save(tmp)

    path = storage.passport_path(root, slug)
    data = passport_module.load_passport(path)
    try:
        extracted, filled, problem = passport_module.build_contract_terms(
            tmp, year_signed=data.get("year_signed"), project_name=data.get("project_name"),
        )
    except pdf_reader.PdfReadError as e:
        current_app.logger.warning("Протокол отклонён: %s", e)
        tmp.unlink(missing_ok=True)
        return redirect(url_for(
            "main.project_page", slug=slug,
            problem=passport_module.CONTRACT_PROBLEM_UNREADABLE,
        ))

    tmp.replace(dest)
    data.update(extracted)
    data["contract_auto_fields"] = filled
    passport_module.save_passport(data, path)
    # A problem code travels back as a query parameter rather than a flash
    # message: flashing would need a SECRET_KEY, which this app doesn't set.
    return redirect(url_for("main.project_page", slug=slug, problem=problem))


@bp.route("/projects/<slug>/cost-increase", methods=["POST"])
def upload_cost_increase(slug):
    """Загрузить или заменить файл удорожания.

    Файл сначала читается и только потом сохраняется. Иначе неудачная замена —
    не тот файл, испорченный файл — стирала бы прежний, рабочий, и человек
    оставался бы вообще без удорожания вместо того, чтобы просто повторить
    загрузку.
    """
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    xlsx_file = request.files.get("cost_increase_file")
    if not xlsx_file or not xlsx_file.filename:
        abort(400)

    def refuse(code):
        return redirect(url_for("main.project_page", slug=slug, increase=code))

    if not xlsx_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return refuse("format")

    data = xlsx_file.read()
    if len(data) > MAX_COST_INCREASE_SIZE:
        return refuse("too_big")
    if not upload_guard.is_office_zip(io.BytesIO(data)):
        return refuse("format")
    try:
        lines = cost_increase.read_lines(io.BytesIO(data))
    except cost_increase.CostIncreaseError as e:
        current_app.logger.warning("Файл удорожания отклонён: %s", e)
        return refuse("unreadable")

    # Удорожание считается здесь же, при загрузке, и попадает в журнал: если
    # цифра на странице потом вызовет вопросы, будет видно, что программа
    # получила из этого файла в момент загрузки.
    report = cost_increase.build_report(lines, _estimate_totals(root, slug))
    current_app.logger.info(
        "Проект «%s»: удорожание %.2f руб. от %s",
        slug, report.total.delta,
        "сметы" if report.from_estimate else "столбца «было»",
    )

    storage.cost_increase_path(root, slug).write_bytes(data)
    return redirect(url_for("main.project_page", slug=slug))


@bp.route("/projects/<slug>/dgp", methods=["POST"])
def upload_dgp(slug):
    """Заменить ДГП и пересобрать паспорт заново — из нового ДГП и уже
    сохранённого при создании проекта ТЗ, тем же способом, что при создании.

    Новый файл сначала разбирается во временном месте и только при успехе
    занимает место старого — как и у файла удорожания: неудачная попытка
    (не тот файл, испорченный файл) не должна оставлять проект без
    рабочего ДГП. Перезапись полная: как и у протокола, новый файл
    считается верным целиком, а не сверяется построчно со старыми
    значениями — включая те, что были поправлены вручную.
    """
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    dgp_file = request.files.get("dgp_file")
    if not dgp_file or not dgp_file.filename:
        abort(400)

    def refuse(code):
        return redirect(url_for("main.project_page", slug=slug, dgp=code))

    if not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return refuse("format")
    if not upload_guard.is_office_zip(dgp_file):
        return refuse("format")

    tz = storage.tz_path(root, slug)
    if not tz.exists():
        abort(404)

    path = storage.passport_path(root, slug)
    data = passport_module.load_passport(path)

    dest = storage.dgp_path(root, slug)
    # Расширение настоящее — не .tmp: пока это только ДГП не заметит разницы
    # (zipfile её не проверяет), но смета ниже читается openpyxl, а он
    # отказывается открывать файл не по расширению, даже если содержимое
    # ровно то же самое.
    tmp = dest.with_stem(dest.stem + "_upload")
    dgp_file.save(tmp)
    try:
        fresh = passport_module.build_passport(data.get("project_name") or slug, tmp, tz)
    except DocxReadError as e:
        current_app.logger.warning("ДГП отклонён: %s", e)
        tmp.unlink(missing_ok=True)
        return refuse("unreadable")

    tmp.replace(dest)
    data.update(fresh)
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))


@bp.route("/projects/<slug>/estimate", methods=["POST"])
def upload_estimate(slug):
    """Заменить смету проекта.

    Файл сначала разбирается во временном месте и только при успехе
    занимает место старой сметы — как и у файла удорожания: неудачная
    попытка не должна оставлять проект без рабочей сметы. Само удорожание
    отдельного пересчёта не требует: страница читает смету заново при
    каждой загрузке (``_estimate_totals``), так что новые суммы подхватятся
    сами на следующем же открытии страницы.
    """
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)

    xlsx_file = request.files.get("estimate_file")
    if not xlsx_file or not xlsx_file.filename:
        abort(400)

    def refuse(code):
        return redirect(url_for("main.project_page", slug=slug, estimate=code))

    if not xlsx_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return refuse("format")
    if not upload_guard.is_office_zip(xlsx_file):
        return refuse("format")

    dest = storage.estimate_path(root, slug)
    # Расширение настоящее, не .tmp: openpyxl отказывается открывать файл не
    # по расширению, даже когда содержимое — рабочая книга как рабочая книга.
    tmp = dest.with_stem(dest.stem + "_upload")
    xlsx_file.save(tmp)
    try:
        estimate.read_estimate(tmp)
    except estimate.EstimateReadError as e:
        current_app.logger.warning("Смета отклонена: %s", e)
        tmp.unlink(missing_ok=True)
        return refuse("unreadable")

    tmp.replace(dest)
    # (path, mtime, size) alone could in principle still match the estimate
    # this just replaced; dropping the cache outright is what actually
    # guarantees the next read reflects the new file, not a coincidence.
    workbook_cache.invalidate(dest)
    return redirect(url_for("main.project_page", slug=slug))


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


# Все три поля вписываются вручную в одной форме «Расчётных коэффициентов»
# — арматуру считать пока не из чего вовсе, а объём монолита и площадь
# фасада иногда проще поправить самому, чем чинить разбор смет (или смету
# вовсе не загружать ради одной цифры).
MANUAL_COEFFICIENT_FIELDS = (
    passport_module.REBAR_COEFFICIENT_FIELD, passport_module.FACADE_AREA_FIELD,
    passport_module.CONCRETE_VOLUME_FIELD,
)


@bp.route("/projects/<slug>/manual-coefficients", methods=["POST"])
def update_manual_coefficients(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)

    data = passport_module.load_passport(path)
    for field in MANUAL_COEFFICIENT_FIELDS:
        raw_value = request.form.get(field, "").strip()
        value = extractors.parse_number(raw_value) if raw_value else None
        data[field] = _non_negative(value)
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))


# Куда вернуть человека после правки в списке. Значение в форме — название
# страницы из этого короткого списка, а не адрес: подставить в форму чужой
# адрес и увести куда угодно так нельзя.
RETURN_PAGES = {"select": "main.compare_select"}


def _back_to(default="main.index"):
    """На ту страницу, где человек и был, — или на общий список.

    Переименовать и удалить проект можно из двух списков, и выбрасывать со
    страницы выбора на главную только потому, что там правили название, не за
    что.
    """
    return redirect(url_for(RETURN_PAGES.get(request.form.get("back"), default)))


@bp.route("/projects/<slug>/delete", methods=["POST"])
def delete_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        # Nothing to delete means the user already got what they asked for,
        # so send them back where they were. Aborting here put a repeated
        # delete — a double-clicked button, a re-submitted form — on a bare
        # "Not Found" page with no way back.
        return _back_to()
    storage.delete_project(root, slug)
    return _back_to()


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
    return _back_to()


def _non_negative(value):
    """The value, or None if it's negative — an area, a volume, or a price
    can't be, and a negative one downstream turns a ₽/м² figure negative or
    flips a comparison's sign rather than raising anything a person would
    notice. Treated the same as unreadable input: the field goes back to
    empty rather than keeping a number that can't be true."""
    return value if value is None or value >= 0 else None


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
            new_value = _non_negative(extractors.parse_number(raw_value))
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


@bp.errorhandler(passport_module.PassportReadError)
def _passport_read_error(exc):
    """One outcome for a corrupted passport.json, wherever it's hit.

    Before this, whether a broken passport 500'd or quietly showed an empty
    project depended on which of routes.py's ten load_passport call sites
    happened to run — project_page and friends never caught it at all,
    _safe_passport swallowed it into {} for the dashboard and sidebar only.
    Routing every uncaught PassportReadError here instead gives the same
    diagnosable page everywhere: what's broken, and a way to delete the
    project (which only needs the slug to exist on disk, not its passport
    to parse) rather than being stuck with it forever.
    """
    slug = request.view_args.get("slug") if request.view_args else None
    current_app.logger.error("Паспорт проекта «%s» повреждён: %s", slug or "?", exc)
    return render_template("passport_broken.html", slug=slug), 500
