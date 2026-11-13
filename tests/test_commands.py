import pytest
from PySide6.QtWidgets import QWidget

from pyde.commands import CommandRegistry


@pytest.fixture
def registry(qapp):
    owner = QWidget()
    yield CommandRegistry(owner)
    owner.deleteLater()


def test_triggering_a_registered_command_runs_its_callback(registry):
    calls = []

    action = registry.register("demo.run", "Run Demo", lambda: calls.append("ran"))
    action.trigger()

    assert calls == ["ran"]
    assert action.text() == "Run Demo"


def test_commands_are_looked_up_by_id_and_listed_in_order(registry):
    registry.register("demo.first", "First", lambda: None, key="cmd+1")
    registry.register("demo.second", "Second", lambda: None)

    assert "demo.first" in registry
    assert "demo.missing" not in registry
    assert registry["demo.first"].default_key == "cmd+1"
    assert [command.id for command in registry] == ["demo.first", "demo.second"]


def test_registering_the_same_id_twice_is_an_error(registry):
    registry.register("demo.run", "Run Demo", lambda: None)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("demo.run", "Run Demo Again", lambda: None)
