from app import contract_extractors


# --- performance bond ---

def test_performance_bond_is_read_from_a_clean_line():
    text = "5 Performance bond, % (Банковская гарантия на исполнение контракта) 3%"

    assert contract_extractors.extract_performance_bond(text) == "3%"


def test_performance_bond_survives_a_mangled_latin_word():
    # A real scan: recognition turned "Performance" into Cyrillic-looking
    # nonsense while "bond" came through untouched.
    text = "5 Реноггтлапсе bond, % (Банковская гарантия на исполнение контракта) 3%"

    assert contract_extractors.extract_performance_bond(text) == "3%"


def test_performance_bond_does_not_reach_across_the_page_for_a_figure():
    text = "Performance bond, %\n" + "прочий текст\n" * 40 + "НДС 20%"

    assert contract_extractors.extract_performance_bond(text) is None


def test_performance_bond_is_none_when_the_row_is_absent():
    text = "Аванс, % 30%\nБанковская гарантия на возврат аванса Не включено"

    assert contract_extractors.extract_performance_bond(text) is None


# Настоящий протокол Jois, распознанный со скана. Таблица в две колонки:
# слева «1.8. Performance bond:», справа «Банковская гарантия исполнения — 3 %
# от цены работ». Правая клетка переносится на две строки, и распознаватель
# кладёт её начало выше подписи, а хвост («цены работ.») приклеивает к самой
# подписи. Строкой ниже начинается уже другое условие — гарантийное удержание.
JOIS_BOND = """П ичинение в еда - 300 млн. б.
Банковская исполнения З %
гарантия — от
1.8. Performance bond: цены работ.
- 1,5 % после итогового акта;
1.9. Гарантийное удержание: 1 % под банковскую гарантию;
- 0,3 % де живаются на 24 месяца.
"""


def test_bond_is_read_from_its_own_row_even_when_it_wraps_above_the_label():
    # 3 %, а не 1,5 % из следующего условия. Цифру 3 распознаватель отдал
    # кириллической «З» — перед знаком процента одинокая буква не бывает
    # ничем иным.
    assert contract_extractors.extract_performance_bond(JOIS_BOND) == "3%"


def test_bond_does_not_borrow_a_percentage_from_another_condition_above():
    # Настоящий протокол «проспект мира»: у подписи своего процента нет, и
    # значение находится дальше по тексту. Строка, начинающая другое условие,
    # — граница: 30% из аванса к bond отношения не имеет.
    text = (
        "3 Аванс, % 30% максимальная сумма не закрытого аванса 20%\n"
        "4 Банковская гарантия на возврат аванса Не включено\n"
        "5 Performance bond, % (Банковская гарантия на исполнение контракта)\n"
        "6 Страхование Включено\n"
        "7 Согласие с условиями гарантийного удержания ГУ удерживается "
        "с промежуточного платежа в размере 3%\n"
    )

    assert contract_extractors.extract_performance_bond(text) == "3%"


# --- банковская гарантия ---

def test_bank_guarantee_is_normalised():
    text = "4 Банковская гарантия на возврат аванса Не включено - 90 134 910,00 руб."

    assert contract_extractors.extract_bank_guarantee(text) == "Не включено"


def test_bank_guarantee_recognises_a_latin_ne():
    # "Не" read as the Latin "He": the glyphs are identical in most fonts.
    text = "4 Банковская гарантия на возврат аванса He включено"

    assert contract_extractors.extract_bank_guarantee(text) == "Не включено"


def test_bank_guarantee_included_is_read_as_included():
    text = "4 Банковская гарантия на возврат аванса Включено, 5%"

    assert contract_extractors.extract_bank_guarantee(text) == "Включено"


# --- аванс и срок ---

def test_advance_payment_takes_only_the_first_figure_of_the_row():
    # "30% максимальная сумма не закрытого аванса 20%" is one condition's
    # number followed by a different condition's — only the first is the
    # actual advance percentage, and it keeps its own "%" but none of the
    # surrounding sentence.
    text = "3 Аванс, % 30% максимальная сумма не закрытого аванса 20%"

    assert contract_extractors.extract_advance_payment(text) == "30%"


def test_smr_term_is_the_number_of_months():
    # Срок — это число месяцев, а не абзац вокруг него, и приходит как
    # голое число, без единицы. Значение из-за переноса стоит над своей
    # подписью.
    text = "30 месяца, с даты передачи первой захватки\n1 Срок выполнения СМР, месяц"

    assert contract_extractors.extract_smr_term(text) == "30"


def test_smr_term_survives_a_mangled_unit():
    # Настоящий протокол VEER UB9: распознавание прочло «мес» как «мас».
    # Единица не переносится в паспорт вовсе — оттуда берётся только число.
    text = (
        "п1п Наименование Верейская UB9\n"
        "38 мас с даты передачи первой захватки с ртом\n"
        "Срок выполнения СМР и MR Вте до Итогого акта, месяч поэтапной "
        "лередачи площадки под строительство\n"
    )

    assert contract_extractors.extract_smr_term(text) == "38"


def test_smr_term_is_not_taken_from_a_number_that_is_not_months():
    # Настоящий протокол Тушино: в строку попал ИНН и номер строки таблицы.
    # Срок — то число, рядом с которым стоит слово про месяцы.
    text = (
        "(инн 7701380579) 1 Срок выполнения СМР, месяц 35 мес. "
        "с учетом поэтапной передачи котлована\n"
    )

    assert contract_extractors.extract_smr_term(text) == "35"


def test_smr_term_of_a_clause_ignores_whatever_stands_above_it():
    # Настоящий протокол Jois, распознанный со скана: пункт сам несёт срок
    # после двоеточия, а над ним стоит строка из таблицы стоимости работ.
    # Приклеивать её незачем — к сроку она отношения не имеет. Слово «месяца»
    # здесь написано словами, а единицу назвала сама подпись условия.
    text = (
        "14. Рабочая документация 278 156 068,22 Р\n"
        "15. Отделка MR Base 1 256 837 680,96 Р\n"
        "1.2. Срок выполнения работ, мес.: 33 (тридцать три месяца) до момента\n"
    )

    assert contract_extractors.extract_smr_term(text) == "33"


def test_smr_term_is_none_when_no_number_can_be_made_out():
    # Ничего не разобрав, лучше вернуть None: человек впишет число сам, а
    # предложение там, где полагается быть цифре, — не то, что нужно
    # паспорту.
    text = "по графику производства работ\n1 Срок выполнения СМР, месяц"

    assert contract_extractors.extract_smr_term(text) is None


def test_smr_term_is_none_when_the_row_is_absent():
    assert contract_extractors.extract_smr_term("Аванс, % 30%") is None


# --- протокол, написанный пунктами, а не таблицей ---

JOIS_CLAUSES = """- 24 мес. (2 года) — отделочные работы,
благоустройство и озеленение.
- Авансы до 20%
1.4. Авансовый платеж, % от общей стоимости работ: - Выплата аванса производится на ОБС, без
БГ.
нет
1.5. Банковская гарантия возврата авансового платежа: Банк-эмитент должен быть согласован с
Управляющим проектом АО «МРГ»
1.6 Банковская гарантия гарантийного срока 1,2%
"""


def test_advance_is_read_from_a_clause_with_the_figure_above_it():
    # Not every protocol is a table: in a written-out one the value lands on
    # the line above its own clause — "Авансы до 20%" — and only that figure
    # with its own "%" comes back, not the sentence that follows the clause
    # itself.
    value = contract_extractors.extract_advance_payment(JOIS_CLAUSES)

    assert value == "20%"


def test_bank_guarantee_of_a_clause_reads_the_answer_above_it():
    assert contract_extractors.extract_bank_guarantee(JOIS_CLAUSES) == "Не включено"


def test_a_clause_worded_the_other_way_round_is_still_matched():
    # "возврата авансового платежа" rather than "на возврат аванса".
    text = "да\n1.5. Банковская гарантия возврата авансового платежа:"

    assert contract_extractors.extract_bank_guarantee(text) == "Включено"


def test_the_table_wording_still_wins_where_it_is_present():
    # A protocol that has both must be read as the table it is.
    text = (
        "3 Аванс, % 30% максимальная сумма не закрытого аванса 20%\n"
        "нет\n"
        "1.4. Авансовый платеж, % от общей стоимости работ:\n"
        "4 Банковская гарантия на возврат аванса Не включено\n"
    )

    assert contract_extractors.extract_advance_payment(text) == "30%"
    assert contract_extractors.extract_bank_guarantee(text) == "Не включено"


def test_a_clause_without_an_answer_above_it_stays_empty():
    text = "1.5. Банковская гарантия возврата авансового платежа:"

    assert contract_extractors.extract_bank_guarantee(text) is None
