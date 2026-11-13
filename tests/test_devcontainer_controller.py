import json
import sys

import pytest

from pyde.devcontainer import controller
from pyde.devcontainer.config import find_config, load_config
from pyde.devcontainer.controller import DevContainer
from pyde.terminal import TerminalView

SCREEN = """
(() => {
  const buffer = terminal.buffer.active;
  let text = "";
  for (let row = 0; row < buffer.length; row++) {
    const line = buffer.getLine(row);
    text += (line.isWrapped ? "" : "\\n") + line.translateToString(true);
  }
  return text;
})()
"""


class Harness:
    """A terminal, and a dev container for the project that uses it."""

    def __init__(self, project, data_folder, wait_until, docker):
        self.wait_until = wait_until
        self.docker = docker
        self.terminal = TerminalView()
        self.terminal.set_folder(project)
        self.terminal.resize(900, 400)
        started = []
        self.terminal.started.connect(lambda: started.append(True))
        self.terminal.show()
        wait_until(lambda: started, timeout=30)

        config = load_config(find_config(project), project)
        self.container = DevContainer(config, self.terminal, data_folder)
        self.connections = 0
        self.failures = []
        self.warnings = []
        self.container.connected.connect(self._count_connection)
        self.container.failed.connect(self.failures.append)
        self.container.warned.connect(self.warnings.append)

    def _count_connection(self):
        self.connections += 1

    def start(self, rebuild=False):
        """Bring the container up and wait for it to succeed or fail."""
        self.container.start(rebuild)
        self.wait_until(lambda: self.connections or self.failures, timeout=30)
        if self.connections:
            # The shell is started a moment after the connection is announced.
            self.wait_until(lambda: self.docker.shell_calls)

    def screen(self):
        results = []
        self.terminal.page().runJavaScript(SCREEN, results.append)
        self.wait_until(lambda: results)
        return results[0]

    def type(self, text):
        self.terminal.page().runJavaScript(f"terminal.input({json.dumps(text)})")

    def wait_for(self, text):
        self.wait_until(lambda: text in self.screen(), timeout=15)


@pytest.fixture
def harness(qapp, project, tmp_path, wait_until, fake_docker):
    harness = Harness(project, tmp_path / "data", wait_until, fake_docker)
    yield harness
    harness.terminal.shutdown()
    harness.terminal.close()


def configure(project, **properties):
    """Add properties to the project's devcontainer.json."""
    path = project / ".devcontainer" / "devcontainer.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **properties}))


def test_bringing_it_up_ends_with_a_shell_inside_the_container(harness, fake_docker):
    harness.start()

    assert harness.connections == 1
    assert harness.failures == []
    harness.type("echo where=$INSIDE\r")
    harness.wait_for("where=fake-container")
    # The progress of `docker compose up` stays on screen above the prompt.
    assert "Starting the dev container: Sample" in harness.screen()
    assert "fake docker: containers started" in harness.screen()


def test_the_steps_run_in_order_with_the_right_project(harness, fake_docker, project):
    harness.start()

    steps = [
        next(word for word in call if word in ("config", "ps", "up", "inspect", "exec"))
        for call in fake_docker.calls
    ]
    # The first exec asks which lifecycle hooks are due; the second is the shell.
    assert steps == ["config", "ps", "up", "ps", "inspect", "exec", "exec"]

    [up] = fake_docker.calls_to("up")
    # Named the way VS Code names it, not "devcontainer" as Compose would.
    assert up[up.index("--project-name") + 1] == "project_devcontainer"
    assert "--no-recreate" not in up
    [ps, _] = fake_docker.calls_to("ps")
    assert "label=com.docker.compose.project=project_devcontainer" in ps
    assert "label=com.docker.compose.service=app" in ps


def test_the_override_file_is_written_outside_the_project(
    harness, fake_docker, project, tmp_path
):
    configure(project, containerEnv={"FROM_CONFIG": "yes"})
    harness.container.config = load_config(find_config(project), project)

    harness.start()

    [up] = fake_docker.calls_to("up")
    files = [up[index + 1] for index, word in enumerate(up) if word == "-f"]
    assert files[0] == str(project / ".devcontainer" / "docker-compose.yml")
    override = files[1]
    assert override.startswith(str(tmp_path / "data"))
    service = json.loads(open(override).read())["services"]["app"]
    assert service["environment"] == {"FROM_CONFIG": "yes"}
    assert service["labels"]["devcontainer.local_folder"] == str(project)


def test_an_existing_container_is_not_recreated(harness, fake_docker):
    fake_docker.container_exists()

    harness.start()

    [up] = fake_docker.calls_to("up")
    assert "--no-recreate" in up


def test_the_shell_runs_as_the_configured_user_with_the_terminal_environment(
    harness, fake_docker, project
):
    configure(
        project,
        remoteUser="ada",
        remoteEnv={"GREETING": "hello", "MORE": "${containerEnv:PATH}:/extra"},
    )
    harness.container.config = load_config(find_config(project), project)
    fake_docker.set_container(env=["PATH=/usr/bin:/bin"])

    harness.start()

    [shell] = fake_docker.shell_calls
    assert shell[shell.index("--user") + 1] == "ada"
    assert shell[shell.index("--workdir") + 1] == "/workspace"
    harness.type("echo [$GREETING] [$MORE]\r")
    harness.wait_for("[hello] [/usr/bin:/bin:/extra]")


def test_properties_pyde_does_not_act_on_are_named_in_the_terminal(
    harness, fake_docker, project
):
    configure(project, forwardPorts=[8000], features={"x": {}})
    harness.container.config = load_config(find_config(project), project)

    harness.start()

    harness.wait_for("Pyde does not act on these devcontainer.json properties")
    assert "Features, forwardPorts" in harness.screen()


def test_a_failing_compose_up_is_reported_and_no_shell_is_opened(harness, fake_docker):
    fake_docker.set_up_exit_code(1)

    harness.start()

    assert harness.connections == 0
    assert harness.failures == [
        "docker compose up failed. Its output is in the terminal."
    ]
    assert fake_docker.shell_calls == []
    assert "fake docker: could not start" in harness.screen()


def test_a_service_missing_from_the_compose_files_is_reported(harness, fake_docker):
    fake_docker.set_project({"name": "devcontainer", "services": {"web": {}}})

    harness.start()

    assert harness.failures == ["The Compose files have no service named 'app'."]
    assert fake_docker.calls_to("up") == []


def test_a_container_that_is_not_running_is_reported_with_advice(harness, fake_docker):
    fake_docker.set_container(running=False)

    harness.start()

    [failure] = harness.failures
    assert "is not running" in failure
    assert "overrideCommand" in failure
    assert fake_docker.calls_to("exec") == []


def test_a_docker_command_that_fails_reports_its_last_line(harness, fake_docker):
    program = fake_docker.bin / "docker"
    program.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "print('some detail', file=sys.stderr)\n"
        "print('Cannot connect to the Docker daemon', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )

    harness.start()

    assert harness.failures == ["Cannot connect to the Docker daemon"]


def test_docker_missing_everywhere_is_reported(harness, fake_docker, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SHELL", "/bin/sh")

    harness.start()

    assert harness.failures == [
        "Docker was not found. Is it installed and on your PATH?"
    ]


def test_docker_is_found_through_the_shell_when_it_is_not_on_the_path(
    harness, fake_docker, monkeypatch, tmp_path
):
    # As when launched from the Finder: a bare PATH, and a shell whose startup
    # files add the folder docker is in.
    shell = tmp_path / "users-shell"
    shell.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        f"os.environ['PATH'] = {str(fake_docker.bin)!r} + ':/usr/bin:/bin'\n"
        "os.environ['FROM_PROFILE'] = 'yes'\n"
        "print('a banner from a startup file')\n"
        "sys.exit(subprocess.call(['/bin/sh', '-c', sys.argv[-1]]))\n"
    )
    shell.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SHELL", str(shell))

    harness.start()

    assert harness.failures == []
    assert harness.connections == 1
    harness.type("echo profile=$FROM_PROFILE\r")
    harness.wait_for("profile=yes")


def test_a_shell_that_hangs_while_reporting_its_environment_is_given_up_on(
    harness, fake_docker, monkeypatch, tmp_path
):
    shell = tmp_path / "hanging-shell"
    shell.write_text("#!/bin/sh\nsleep 60\n")
    shell.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SHELL", str(shell))
    monkeypatch.setattr(controller, "ENVIRONMENT_TIMEOUT_MS", 300)

    harness.start()

    assert harness.failures == [
        "Docker was not found. Is it installed and on your PATH?"
    ]


def test_leaving_stops_the_containers_by_default(harness, fake_docker, wait_until):
    harness.start()

    harness.container.leave()

    wait_until(lambda: fake_docker.stopped)
    [stop] = fake_docker.calls_to("stop")
    assert stop[stop.index("--project-name") + 1] == "project_devcontainer"


def test_leaving_keeps_the_containers_when_the_configuration_says_so(
    harness, fake_docker, project, wait_until
):
    configure(project, shutdownAction="none")
    harness.container.config = load_config(find_config(project), project)
    harness.start()

    harness.container.leave()

    # Give a stop command, if one were wrongly sent, time to arrive.
    with pytest.raises(AssertionError):
        wait_until(lambda: fake_docker.stopped, timeout=1)


def test_leaving_before_anything_started_stops_nothing(harness, fake_docker):
    harness.container.leave()

    assert fake_docker.calls == []


def test_leaving_partway_abandons_the_rest(harness, fake_docker, wait_until):
    harness.container.start()
    harness.container.leave()

    with pytest.raises(AssertionError):
        wait_until(lambda: harness.connections or harness.failures, timeout=1.5)
    # The first command was cut short, and none of the later ones ran.
    assert fake_docker.calls_to("up") == []
    assert fake_docker.calls_to("exec") == []


# Lifecycle commands


ALL_HOOKS = {
    "initializeCommand": "echo initialized > initialized.txt",
    "onCreateCommand": "on-create",
    "updateContentCommand": "update-content",
    "postCreateCommand": "post-create",
    "postStartCommand": "post-start",
    "postAttachCommand": "post-attach",
}


def reconfigure(harness, project, **properties):
    configure(project, **properties)
    harness.container.config = load_config(find_config(project), project)


def test_the_lifecycle_commands_run_in_order_before_the_shell_opens(
    harness, fake_docker, project
):
    reconfigure(harness, project, **ALL_HOOKS)

    harness.start()

    # The first one runs on this Mac, in the project folder, before `up`.
    assert (project / "initialized.txt").read_text() == "initialized\n"
    # The rest run inside the container.
    assert fake_docker.hook_commands == [
        ["on-create"],
        ["update-content"],
        ["post-create"],
        ["post-start"],
        ["post-attach"],
    ]
    assert harness.warnings == []
    screen = harness.screen()
    assert "\nRunning onCreateCommand\n" in screen
    assert screen.index("postCreateCommand") < screen.index(
        "fake docker: ran post-start"
    )


def test_the_once_only_commands_are_recorded_as_done_but_post_attach_is_not(
    harness, fake_docker, project
):
    reconfigure(harness, project, **ALL_HOOKS)

    harness.start()

    assert fake_docker.recorded_hooks == [
        ".onCreateCommandMarker",
        ".updateContentCommandMarker",
        ".postCreateCommandMarker",
        ".postStartCommandMarker",
    ]


def test_commands_already_run_in_this_container_are_not_run_again(
    harness, fake_docker, project
):
    reconfigure(harness, project, **ALL_HOOKS)
    # As on a later start of the same container.
    fake_docker.set_stale_hooks("postStartCommand")

    harness.start()

    assert fake_docker.hook_commands == [["post-start"], ["post-attach"]]


def test_an_object_of_commands_runs_each_and_is_recorded_after_the_last(
    harness, fake_docker, project
):
    reconfigure(
        harness, project, postCreateCommand={"first": "one", "second": ["two", "words"]}
    )

    harness.start()

    assert fake_docker.hook_commands == [["one"], ["two", "words"]]
    kinds = [
        call[call.index("pyde") + 3]
        for call in fake_docker.calls_to("exec")
        if "markers" not in call and call[-1] != "pyde"
    ]
    assert kinds == ["shell", "exec"]
    assert fake_docker.recorded_hooks == [".postCreateCommandMarker"]


def test_a_failing_command_skips_the_rest_but_still_opens_the_shell(
    harness, fake_docker, project
):
    reconfigure(harness, project, **ALL_HOOKS)
    fake_docker.set_failing_command("update-content")

    harness.start()

    assert fake_docker.hook_commands == [["on-create"], ["update-content"]]
    assert harness.connections == 1
    assert harness.failures == []
    assert harness.warnings == [
        "updateContentCommand failed with exit status 9, so the lifecycle"
        " commands after it were skipped."
    ]
    # Not recorded, so it is tried again next time.
    assert fake_docker.recorded_hooks == [".onCreateCommandMarker"]


def test_a_failing_initialize_command_stops_before_any_container_starts(
    harness, fake_docker, project
):
    reconfigure(harness, project, initializeCommand="exit 4")

    harness.start()

    assert harness.failures == [
        "initializeCommand failed with exit status 4. See the terminal."
    ]
    assert harness.connections == 0
    assert fake_docker.calls_to("up") == []


def test_a_rebuild_builds_again_and_replaces_the_containers(harness, fake_docker):
    fake_docker.container_exists()

    harness.start(rebuild=True)

    [up] = fake_docker.calls_to("up")
    assert "--build" in up and "--force-recreate" in up
    assert "--no-recreate" not in up
