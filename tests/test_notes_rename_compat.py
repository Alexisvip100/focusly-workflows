"""The task field "notesEncrypted"/"notes_encrypted" was renamed to "notes"
(it never held encrypted data). Data written before the rename must still
read back correctly."""

from app.modules.ai.services.action_parser import extract_actions
from app.modules.task.infrastructure.persistence.repository import deserialize_task


def test_cached_task_with_old_column_name_keeps_its_notes():
    task = deserialize_task(
        {"id": "t1", "userId": "u1", "title": "Plan", "notesEncrypted": "old notes"}
    )
    assert task.notes == "old notes"


def test_cached_task_prefers_new_column_name():
    task = deserialize_task({"id": "t1", "notes": "new", "notesEncrypted": "old"})
    assert task.notes == "new"


def test_old_ai_message_with_valid_json_maps_to_notes():
    text = '[ACTION: CREATE_TASK {"title": "Write", "notes_encrypted": "How to"}]'
    [action] = extract_actions(text)
    assert action["payload"]["notes"] == "How to"
    assert "notes_encrypted" not in action["payload"]


def test_old_ai_message_with_broken_json_maps_to_notes():
    # Unescaped quotes force the regex fallback path.
    text = '[ACTION: CREATE_TASK {"title": "Write", "notes_encrypted": "Say "hi" first"}]'
    [action] = extract_actions(text)
    assert action["payload"]["notes"] == 'Say "hi" first'


def test_new_ai_message_uses_notes():
    text = '[ACTION: CREATE_TASK {"title": "Write", "notes": "Say "hi" first"}]'
    [action] = extract_actions(text)
    assert action["payload"]["notes"] == 'Say "hi" first'
