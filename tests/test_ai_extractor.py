import json

from app import ai_extractor
from app.document_reader import DocxContent


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, content_text):
        self.content = [_FakeTextBlock(content_text)]


class _FakeMessages:
    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self.response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


class _RaisingClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("no network")


def test_build_context_text_combines_paragraphs_and_tables_from_both_docs():
    dgp = DocxContent(paragraphs=["Пункт 1 ДГП"], tables=[[["Генподрядчик", "ООО «Ромашка»"]]])
    tz = DocxContent(paragraphs=["Пункт 1 ТЗ"], tables=[[["Площадь", "67413"]]])

    text = ai_extractor.build_context_text(dgp, tz)

    assert "Пункт 1 ДГП" in text
    assert "Генподрядчик ООО «Ромашка»" in text
    assert "Пункт 1 ТЗ" in text
    assert "Площадь 67413" in text


def test_extract_missing_fields_sends_anonymized_text_not_real_names(monkeypatch):
    fake_client = _FakeClient(json.dumps({"general_contractor": "<ORGANIZATION_1>"}))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    context = 'Генподрядчик ООО «Ромашка», ИНН 7701234567, выполняет работы.'
    result = ai_extractor.extract_missing_fields(["general_contractor"], context)

    sent_text = fake_client.messages.calls[0]["messages"][0]["content"]
    assert "Ромашка" not in sent_text
    assert "7701234567" not in sent_text
    assert result["general_contractor"] == 'ООО «Ромашка»'


def test_extract_missing_fields_returns_only_non_null_fields(monkeypatch):
    fake_client = _FakeClient(json.dumps({
        "general_contractor": None, "year_signed": "2024",
    }))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(
        ["general_contractor", "year_signed"], "какой-то текст без реальных имён",
    )

    assert result == {"year_signed": "2024"}


def test_extract_missing_fields_parses_numeric_field_through_parse_number(monkeypatch):
    fake_client = _FakeClient(json.dumps({"total_area_sqm": "67 413,00"}))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(["total_area_sqm"], "текст")

    assert result == {"total_area_sqm": 67413.0}


def test_extract_missing_fields_empty_list_returns_empty_without_calling_client(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: calls.append(1))

    result = ai_extractor.extract_missing_fields([], "текст")

    assert result == {}
    assert calls == []


def test_extract_missing_fields_client_error_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: _RaisingClient())

    result = ai_extractor.extract_missing_fields(["general_contractor"], "текст")

    assert result == {}


def test_extract_missing_fields_malformed_json_returns_empty_dict(monkeypatch):
    fake_client = _FakeClient("not valid json")
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(["general_contractor"], "текст")

    assert result == {}


def test_extract_missing_fields_non_dict_json_returns_empty_dict(monkeypatch):
    fake_client = _FakeClient(json.dumps([1, 2, 3]))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(["general_contractor"], "текст")

    assert result == {}
