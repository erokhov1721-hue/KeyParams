"""Отбор проектов по генподрядчику, классу и году подписания.

Варианты не заданы списком в коде: они собираются из самих проектов, так что
новый подрядчик появляется в фильтре сам, как только заведён проект с ним.
Рядом с каждым вариантом стоит число проектов — иначе непонятно, стоит ли
галочка чего-нибудь.

Внутри группы значения складываются по ИЛИ, между группами — по И:
(АНТТЕК или ГЭС) и (Бизнес) и (2024).
"""

import re
from urllib.parse import urlencode

# Проект, у которого поле не заполнено, попадает в отдельный вариант, а не
# исчезает из фильтра молча: пустое поле — это тоже ответ, и его бывает нужно
# найти.
NOT_SET = "не указано"
NOT_SET_LABEL = "Не указано"

_YEAR_RE = re.compile(r"(19|20)\d{2}")

# (ключ в адресе, поле паспорта, подпись группы, как сортировать)
GROUPS = [
    ("contractor", "general_contractor", "Генподрядчик", "alpha"),
    ("class", "building_class", "Класс объекта", "alpha"),
    ("year", "year_signed", "Год подписания договора", "desc"),
]

GROUP_KEYS = [key for key, _, _, _ in GROUPS]


def _value(passport, field):
    """Значение поля в том виде, в каком оно попадёт в фильтр."""
    raw = passport.get(field)
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return NOT_SET
    if field == "year_signed":
        # Год может быть записан как «от 2024 г.» — в фильтре нужен сам год,
        # иначе два одинаковых года разойдутся по разным вариантам.
        found = _YEAR_RE.search(text)
        return found.group() if found else text
    return text


def _sorted_values(values, order):
    """Варианты по порядку. «Не указано» всегда последним: это не значение, а
    его отсутствие, и оно не должно возглавлять список."""
    known = [value for value in values if value != NOT_SET]
    if order == "desc":
        known.sort(reverse=True)
    else:
        known.sort(key=str.casefold)
    return known + ([NOT_SET] if NOT_SET in values else [])


def _chosen(args):
    """Что выбрано в каждой группе, по данным адреса страницы."""
    return {key: [v for v in args.getlist(key) if v] for key in GROUP_KEYS}


def matches(passport, chosen):
    """Подходит ли проект под выбранное. Пустая группа не ограничивает."""
    for key, field, _label, _order in GROUPS:
        wanted = chosen.get(key) or []
        if wanted and _value(passport, field) not in wanted:
            return False
    return True


def _query_without(chosen, group_key, value):
    """Адрес страницы без одного выбранного значения — для крестика на чипе."""
    params = []
    for key in GROUP_KEYS:
        for chosen_value in chosen[key]:
            if key == group_key and chosen_value == value:
                continue
            params.append((key, chosen_value))
    return urlencode(params)


def build(passports, args):
    """Всё, что нужно панели фильтра и списку проектов.

    ``passports`` — ``{slug: паспорт}`` по всем проектам, ``args`` — параметры
    адреса. Возвращает выбранные слаги, группы вариантов со счётчиками и чипы
    применённых значений.
    """
    chosen = _chosen(args)

    groups = []
    for key, field, label, order in GROUPS:
        counts = {}
        for passport in passports.values():
            value = _value(passport, field)
            counts[value] = counts.get(value, 0) + 1
        groups.append({
            "key": key,
            "label": label,
            "options": [
                {
                    "value": value,
                    "label": NOT_SET_LABEL if value == NOT_SET else value,
                    "count": counts[value],
                    "checked": value in chosen[key],
                }
                for value in _sorted_values(counts, order)
            ],
        })

    chips = []
    for key, _field, label, _order in GROUPS:
        for value in chosen[key]:
            chips.append({
                "group": key,
                "group_label": label,
                "label": NOT_SET_LABEL if value == NOT_SET else value,
                "query": _query_without(chosen, key, value),
            })

    slugs = [slug for slug, passport in passports.items() if matches(passport, chosen)]
    return {
        "groups": groups,
        "chips": chips,
        "slugs": slugs,
        "active_count": len(chips),
        "any": bool(chips),
    }
