from app.modules.automation.services.todo_detector import detect_todos, _make_hash


def test_detect_todos_explicit_prefix():
    content = '[{"type": "paragraph", "content": [{"type": "text", "text": "TODO: Implementar autenticación"}]}]'
    results = detect_todos(content)
    assert len(results) == 1
    assert results[0].text == "Implementar autenticación"
    assert results[0].hash == _make_hash("Implementar autenticación")


def test_detect_todos_markdown_checkbox():
    content = '[{"type": "paragraph", "content": [{"type": "text", "text": "- [ ] Crear endpoints de workspace"}]}]'
    results = detect_todos(content)
    assert len(results) == 1
    assert results[0].text == "Crear endpoints de workspace"


def test_detect_todos_empty_content():
    assert detect_todos("") == []
    assert detect_todos("   ") == []
