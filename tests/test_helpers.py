"""The helpers the tests share are worth a test of their own."""

import pytest


def test_patiently_tries_again_while_windows_refuses(patiently):
    refusals = [PermissionError("Access is denied")] * 2
    done = []

    def operation(*args):
        if refusals:
            raise refusals.pop()
        done.append(args)
        return "result"

    assert patiently(operation, "a", "b", pause=0) == "result"

    assert done == [("a", "b")]
    assert refusals == []


def test_patiently_gives_up_in_the_end(patiently):
    calls = []

    def always_refused():
        calls.append(1)
        raise PermissionError("Access is denied")

    with pytest.raises(PermissionError):
        patiently(always_refused, attempts=3, pause=0)

    assert len(calls) == 3


def test_patiently_lets_other_errors_through_at_once(patiently):
    calls = []

    def broken():
        calls.append(1)
        raise FileNotFoundError("gone")

    with pytest.raises(FileNotFoundError):
        patiently(broken, pause=0)

    assert len(calls) == 1
