from io import BytesIO

from flask import Blueprint, Response, current_app, render_template, request

from . import excel_report, storage

excel_report_bp = Blueprint("excel_report", __name__)

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPORT_FILENAME = "analiz_stoimosti.xlsx"

NOTHING_SELECTED = (
    "Не выбрано ни одного проекта. Отметьте галочками нужные проекты в списке "
    "и нажмите «Выгрузить в Excel»."
)
NOTHING_FOUND = (
    "Выбранные проекты не найдены — возможно, они были удалены в другом окне. "
    "Вернитесь к списку и выберите заново."
)


def _selected_ids():
    """The projects the user ticked, in the order they were ticked.

    Reads the same ``slug`` parameters off the same GET request as the
    "Сравнить" button, so one form on the page can feed both buttons. Ids that
    aren't real projects are dropped here rather than trusted downstream.
    """
    root = current_app.config["PROJECTS_ROOT"]
    valid_slugs = set(storage.list_project_slugs(root))
    return list(dict.fromkeys(
        slug for slug in request.args.getlist("slug") if slug in valid_slugs
    ))


def _error(message):
    return render_template("report_error.html", message=message), 400


@excel_report_bp.route("/report/excel", methods=["GET"])
def excel_report_download():
    root = current_app.config["PROJECTS_ROOT"]
    slugs = _selected_ids()
    if not slugs:
        return _error(NOTHING_FOUND if request.args.getlist("slug") else NOTHING_SELECTED)

    buffer = BytesIO()
    try:
        projects = [
            excel_report.load_project(storage.project_dir(root, slug)) for slug in slugs
        ]
        excel_report.build_comparison_report(projects, buffer)
    except excel_report.ExcelReportError as e:
        # Everything the user can do something about arrives here as a
        # sentence already written for them, so the page just shows it.
        return _error(str(e))

    return Response(
        buffer.getvalue(),
        mimetype=XLSX_MIMETYPE,
        headers={"Content-Disposition": f"attachment; filename={REPORT_FILENAME}"},
    )
