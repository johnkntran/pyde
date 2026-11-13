import json

import pytest

from pyde.devcontainer import compose
from pyde.devcontainer.config import load_config

DOCKER = "/usr/local/bin/docker"


def configure(folder, compose_file="docker-compose.yml", **properties):
    """A dev container configuration in `folder` with these extra properties."""
    content = {"dockerComposeFile": compose_file, "service": "app"}
    content.update(properties)
    path = folder / ".devcontainer" / "devcontainer.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content))
    return load_config(path, folder)


def inspected(env=(), labels=None, running=True):
    """What `docker inspect` says about a container."""
    return {
        "State": {"Running": running},
        "Config": {"Env": list(env), "Labels": labels or {}},
    }


def metadata(*pieces):
    return {"devcontainer.metadata": json.dumps(list(pieces))}


# The project name


def test_a_project_in_a_devcontainer_folder_is_named_after_the_workspace(tmp_path):
    folder = tmp_path / "My Project"
    config = configure(folder)

    # "devcontainer" is what Compose itself would call it.
    assert compose.project_name("devcontainer", config) == "myproject_devcontainer"


def test_a_name_the_user_chose_is_kept(tmp_path):
    config = configure(tmp_path / "project")

    assert compose.project_name("chosen-name", config) == "chosen-name"


def test_compose_files_elsewhere_keep_composes_own_name(tmp_path):
    config = configure(tmp_path / "project", compose_file="../docker-compose.yml")

    # Even if that name happens to be "devcontainer".
    assert compose.project_name("devcontainer", config) == "devcontainer"
    assert compose.project_name("project", config) == "project"


# The override file


def test_the_override_labels_the_service_for_vs_code(tmp_path):
    config = configure(tmp_path)

    assert compose.override(config) == {
        "services": {
            "app": {
                "labels": {
                    "devcontainer.local_folder": str(tmp_path),
                    "devcontainer.config_file": str(config.path),
                }
            }
        }
    }


def test_the_override_carries_environment_mounts_and_the_stay_alive_command(tmp_path):
    config = configure(
        tmp_path,
        containerEnv={"A": "1"},
        mounts=["source=cache,target=/cache,type=volume", "type=bind,src=/h,dst=/c"],
        overrideCommand=True,
    )

    document = compose.override(config)
    service = document["services"]["app"]

    assert service["environment"] == {"A": "1"}
    assert service["volumes"] == [
        {"type": "volume", "source": "cache", "target": "/cache"},
        {"type": "bind", "source": "/h", "target": "/c"},
    ]
    assert service["entrypoint"][:2] == ["/bin/sh", "-c"]
    assert service["command"] == []
    # Only the named volume is declared, under its own name.
    assert document["volumes"] == {"cache": {"name": "cache"}}


# The commands


def test_the_config_command_names_every_compose_file(tmp_path):
    config = configure(tmp_path, compose_file=["a.yml", "b.yml"])
    folder = tmp_path / ".devcontainer"

    assert compose.config_command(DOCKER, config) == [
        DOCKER,
        "compose",
        "-f",
        str(folder / "a.yml"),
        "-f",
        str(folder / "b.yml"),
        "config",
        "--format",
        "json",
    ]


def test_the_find_command_filters_by_project_and_service():
    assert compose.find_container_command(DOCKER, "proj", "app") == [
        DOCKER,
        "ps",
        "--all",
        "--quiet",
        "--filter",
        "label=com.docker.compose.project=proj",
        "--filter",
        "label=com.docker.compose.service=app",
    ]


def test_up_adds_the_override_file_and_starts_everything(tmp_path):
    config = configure(tmp_path)
    compose_file = str(tmp_path / ".devcontainer" / "docker-compose.yml")

    command = compose.up_command(
        DOCKER, "proj", config, "/data/override.json", container_exists=False
    )

    assert command == [
        DOCKER,
        "compose",
        "--project-name",
        "proj",
        "-f",
        compose_file,
        "-f",
        "/data/override.json",
        "up",
        "--detach",
    ]


def test_up_leaves_an_existing_container_as_it_is(tmp_path):
    config = configure(tmp_path)

    command = compose.up_command(DOCKER, "proj", config, "o.json", True)

    assert command[-1] == "--no-recreate"


@pytest.mark.parametrize(
    ("run_services", "started"),
    [(["db"], ["db", "app"]), (["app", "db"], ["app", "db"])],
)
def test_up_starts_the_chosen_services_and_always_the_one_to_work_in(
    tmp_path, run_services, started
):
    config = configure(tmp_path, runServices=run_services)

    command = compose.up_command(DOCKER, "proj", config, "o.json", False)

    assert command[command.index("--detach") + 1 :] == started


def test_stop_uses_the_project_and_its_own_files(tmp_path):
    config = configure(tmp_path)

    assert compose.stop_command(DOCKER, "proj", config) == [
        DOCKER,
        "compose",
        "--project-name",
        "proj",
        "-f",
        str(tmp_path / ".devcontainer" / "docker-compose.yml"),
        "stop",
    ]


# The shell inside the container


def test_the_shell_command_opens_a_terminal_in_the_workspace_folder(tmp_path):
    config = configure(tmp_path, workspaceFolder="/workspace")

    command = compose.shell_command(DOCKER, "abc123", config, inspected())

    assert command[:6] == [
        DOCKER,
        "exec",
        "--interactive",
        "--tty",
        "--workdir",
        "/workspace",
    ]
    assert "--user" not in command
    assert command[-4:-1] == ["abc123", "/bin/sh", "-c"]
    assert "--env" in command and "TERM=xterm-256color" in command


def test_the_user_comes_from_the_configuration_then_the_image(tmp_path):
    from_image = inspected(
        labels=metadata({"remoteUser": "base"}, {"remoteUser": "vscode"}, {})
    )
    plain = configure(tmp_path / "plain")
    chosen = configure(tmp_path / "chosen", remoteUser="ada")

    assert compose.remote_user(plain, inspected()) is None
    # Later pieces of the image's metadata override earlier ones.
    assert compose.remote_user(plain, from_image) == "vscode"
    assert compose.remote_user(chosen, from_image) == "ada"

    command = compose.shell_command(DOCKER, "abc123", chosen, from_image)
    assert command[command.index("--user") + 1] == "ada"


def test_the_terminal_environment_merges_the_image_and_the_configuration(tmp_path):
    config = configure(
        tmp_path,
        remoteEnv={"B": "from-config", "PATH": "${containerEnv:PATH}:/extra"},
    )
    container = inspected(
        env=["PATH=/usr/bin:/bin", "HOME=/root"],
        labels=metadata({"remoteEnv": {"A": "from-image", "B": "from-image"}}),
    )

    assert compose.remote_env(config, container) == {
        "A": "from-image",
        "B": "from-config",
        "PATH": "/usr/bin:/bin:/extra",
    }


def test_a_null_variable_is_unset_and_an_odd_name_is_skipped(tmp_path):
    config = configure(
        tmp_path, remoteEnv={"KEEP": "yes", "GONE": None, "bad name; rm -rf": "x"}
    )

    command = compose.shell_command(DOCKER, "abc123", config, inspected())

    assert "KEEP=yes" in command
    assert command[-1].startswith("unset GONE; ")
    assert not any("bad name" in argument for argument in command)


def test_metadata_that_is_not_what_it_should_be_is_ignored(tmp_path):
    config = configure(tmp_path)

    for label in ("not json", '"a string"', "[1, 2]"):
        container = inspected(labels={"devcontainer.metadata": label})
        assert compose.remote_user(config, container) is None


def test_a_single_object_of_metadata_counts_as_one_piece(tmp_path):
    config = configure(tmp_path)
    container = inspected(
        labels={"devcontainer.metadata": json.dumps({"remoteUser": "solo"})}
    )

    assert compose.remote_user(config, container) == "solo"


def test_is_running_reads_the_container_state():
    assert compose.is_running(inspected(running=True))
    assert not compose.is_running(inspected(running=False))
