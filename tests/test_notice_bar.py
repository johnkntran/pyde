import pytest

from pyde.notice_bar import NoticeBar


@pytest.fixture
def bar(qapp):
    bar = NoticeBar()
    yield bar
    bar.deleteLater()


def test_the_bar_is_hidden_until_there_is_something_to_say(bar):
    assert bar.isHidden()

    bar.show_notice("Something happened.")

    assert not bar.isHidden()
    assert bar.label.text() == "Something happened."
    assert bar.action_button.isHidden()


def test_a_notice_can_offer_an_action_which_also_dismisses_it(bar):
    done = []

    bar.show_notice("Try again?", "Retry", lambda: done.append("retried"))
    assert bar.action_button.text() == "Retry"
    assert not bar.action_button.isHidden()
    bar.action_button.click()

    assert done == ["retried"]
    assert bar.isHidden()


def test_an_action_may_show_a_new_notice(bar):
    bar.show_notice("First.", "Next", lambda: bar.show_notice("Second."))

    bar.action_button.click()

    assert not bar.isHidden()
    assert bar.label.text() == "Second."


def test_dismiss_hides_the_notice_without_acting(bar):
    done = []
    bar.show_notice("Try again?", "Retry", lambda: done.append("retried"))

    bar.dismiss_button.click()

    assert bar.isHidden()
    assert done == []


def test_a_new_notice_replaces_the_old_one_and_its_action(bar):
    done = []
    bar.show_notice("First.", "Do it", lambda: done.append("first"))

    bar.show_notice("Second.")

    assert bar.label.text() == "Second."
    assert bar.action_button.isHidden()
