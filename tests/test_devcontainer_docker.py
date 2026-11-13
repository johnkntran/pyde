"""The dev container flow against a real Docker, where there is one.

Everything else tests against a stand-in docker program. This checks that the
commands Pyde builds mean to Docker what Pyde thinks they mean. It is skipped
where Docker is not running, as on GitHub's macOS runners.
"""

import json
import shutil
import subprocess
import uuid

import pytest

from pyde.main_window import MainWindow

IMAGE = "alpine:3.20"

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


def docker(*args, timeout=120):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


def docker_is_running():
    if shutil.which("docker") is None:
        return False
    try:
        return docker("info", timeout=20).returncode == 0
    except subprocess.TimeoutExpired:
        return False


pytestmark = pytest.mark.skipif(
    not docker_is_running(), reason="needs a running Docker"
)


@pytest.fixture
def project(tmp_path):
    """A real Compose dev container, in a folder with a name of its own."""
    folder = tmp_path / f"pyde-test-{uuid.uuid4().hex[:8]}"
    (folder / ".devcontainer").mkdir(parents=True)
    (folder / "hello.txt").write_text("from the Mac\n")
    (folder / ".devcontainer" / "docker-compose.yml").write_text(
        f"""
services:
  app:
    image: {IMAGE}
    command: sleep infinity
    volumes:
      - ..:/workspace
    environment:
      FROM_COMPOSE: "yes"
  helper:
    image: {IMAGE}
    command: sleep infinity
"""
    )
    (folder / ".devcontainer" / "devcontainer.json").write_text(
        """
// A dev container for testing Pyde against a real Docker.
{
  "name": "Real",
  "dockerComposeFile": "docker-compose.yml",
  "service": "app",
  "workspaceFolder": "/workspace",
  "containerEnv": { "FROM_DEVCONTAINER": "${localWorkspaceFolderBasename}" },
  "remoteEnv": { "GREETING": "hello", "MORE": "${containerEnv:FROM_COMPOSE}-more" },
}
"""
    )
    yield folder
    name = f"{folder.name}_devcontainer"
    docker("compose", "--project-name", name, "down", "--timeout", "0")


def containers(folder, running_only=False):
    """The names of the project's containers."""
    name = f"{folder.name}_devcontainer"
    args = ["ps", "--format", "{{.Names}}"]
    args += [] if running_only else ["--all"]
    args += ["--filter", f"label=com.docker.compose.project={name}"]
    return sorted(docker(*args).stdout.split())


def test_reopen_in_container_with_a_real_docker(qapp, tmp_path, project, wait_until):
    window = MainWindow(config_dir=tmp_path / "config")
    window.resize(1000, 700)
    window.show()
    window.open_folder(project)

    def screen():
        results = []
        window.terminal_view.page().runJavaScript(SCREEN, results.append)
        wait_until(lambda: results)
        return results[0]

    # The first run may have to pull the image.
    window.notice_bar.action_button.click()
    wait_until(
        lambda: (
            window.container_label.isVisibleTo(window)
            or "did not start" in window.notice_bar.label.text()
        ),
        timeout=300,
    )
    assert window.container_label.text() == "Dev Container: Real", (
        window.notice_bar.label.text() + screen()
    )

    # Both services are up, named the way VS Code would name them.
    name = f"{project.name}_devcontainer"
    assert containers(project, running_only=True) == [
        f"{name}-app-1",
        f"{name}-helper-1",
    ]

    # The terminal is a shell inside the service's container.
    command = (
        'echo "os=$(. /etc/os-release; echo $ID) pwd=$(pwd) file=$(cat hello.txt)'
        " compose=$FROM_COMPOSE devcontainer=$FROM_DEVCONTAINER"
        ' greeting=$GREETING more=$MORE"\r'
    )
    typed = json.dumps(command)
    wait_until(lambda: window.terminal_view.running)
    window.terminal_view.page().runJavaScript(f"terminal.input({typed})")
    expected = (
        "os=alpine pwd=/workspace file=from the Mac"
        f" compose=yes devcontainer={project.name}"
        " greeting=hello more=yes-more"
    )
    wait_until(lambda: f"\n{expected}" in screen(), timeout=30)

    # Docker carries the labels VS Code looks for.
    labels = docker(
        "inspect", f"{name}-app-1", "--format", "{{json .Config.Labels}}"
    ).stdout
    assert json.loads(labels)["devcontainer.local_folder"] == str(project)

    # Closing the window stops the containers, but leaves them in place.
    window.close()
    wait_until(lambda: containers(project, running_only=True) == [], timeout=60)
    assert len(containers(project)) == 2
