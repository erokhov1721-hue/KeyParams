from app.anonymize import anonymize_text, deanonymize_value


def test_anonymize_text_replaces_organization_name():
    text = 'Договор заключён с ООО «Ромашка», далее именуемым Генподрядчик.'
    anonymized, token_map = anonymize_text(text)
    assert "Ромашка" not in anonymized
    assert any("Ромашка" in original for original in token_map.values())


def test_anonymize_text_replaces_person_name():
    text = 'Договор подписан со стороны Заказчика Ивановым Иваном Ивановичем.'
    anonymized, token_map = anonymize_text(text)
    assert "Ивановым Иваном Ивановичем" not in anonymized
    assert any("Иван" in original for original in token_map.values())


def test_anonymize_text_replaces_inn_10_digits():
    text = 'Генподрядчик ООО «Ромашка», ИНН 7701234567.'
    anonymized, token_map = anonymize_text(text)
    assert "7701234567" not in anonymized
    assert any(value == "7701234567" for value in token_map.values())


def test_anonymize_text_replaces_inn_12_digits():
    text = 'ИП Петров П.П., ИНН 771234567890, выступает субподрядчиком.'
    anonymized, token_map = anonymize_text(text)
    assert "771234567890" not in anonymized
    assert any(value == "771234567890" for value in token_map.values())


def test_anonymize_text_reuses_token_for_repeated_mention():
    text = 'ООО «Ромашка» подписывает договор. Далее ООО «Ромашка» обязуется выполнить работы.'
    anonymized, token_map = anonymize_text(text)
    org_tokens = [t for t in token_map if t.startswith("<ORGANIZATION_")]
    assert len(org_tokens) == 1
    assert anonymized.count(org_tokens[0]) == 2


def test_anonymize_text_numbers_inn_tokens_in_order_of_first_mention():
    text = (
        'Первый субподрядчик, ИНН 7701234567, указан здесь. '
        'Второй субподрядчик, ИНН 7809876543, указан позже.'
    )
    _, token_map = anonymize_text(text)
    assert token_map["<INN_1>"] == "7701234567"
    assert token_map["<INN_2>"] == "7809876543"


def test_deanonymize_value_restores_original():
    token_map = {"<ORGANIZATION_1>": 'ООО «Ромашка»'}
    assert deanonymize_value("<ORGANIZATION_1>", token_map) == 'ООО «Ромашка»'


def test_deanonymize_value_passes_through_unknown_string():
    assert deanonymize_value("Бизнес", {}) == "Бизнес"


def test_deanonymize_value_passes_through_non_string():
    assert deanonymize_value(2025, {}) == 2025
