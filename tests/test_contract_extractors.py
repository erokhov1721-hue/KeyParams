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

def test_advance_payment_takes_the_rest_of_the_row():
    text = "3 Аванс, % 30% максимальная сумма не закрытого аванса 20%"

    assert contract_extractors.extract_advance_payment(text) == (
        "30% максимальная сумма не закрытого аванса 20%"
    )


def test_smr_term_joins_the_row_with_the_line_before_it():
    # OCR sometimes puts a wrapped value on the line above its label.
    text = "30 месяца, с даты передачи первой захватки\n1 Срок выполнения СМР, месяц"

    term = contract_extractors.extract_smr_term(text)

    assert "30 месяца" in term
    assert "Срок выполнения" in term


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
    # the line above its own clause.
    value = contract_extractors.extract_advance_payment(JOIS_CLAUSES)

    assert "до 20%" in value
    assert "на ОБС" in value


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

    assert contract_extractors.extract_advance_payment(text) == (
        "30% максимальная сумма не закрытого аванса 20%"
    )
    assert contract_extractors.extract_bank_guarantee(text) == "Не включено"


def test_a_clause_without_an_answer_above_it_stays_empty():
    text = "1.5. Банковская гарантия возврата авансового платежа:"

    assert contract_extractors.extract_bank_guarantee(text) is None
