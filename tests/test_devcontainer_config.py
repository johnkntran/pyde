import json

import pytest

from pyde.devcontainer.config import (
    ConfigError,
    find_config,
    load_config,
    substitute_container_env,
)


def write_config(folder, content, relative=".devcontainer/devcontainer.json"):
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def load(folder, **properties):
    """Load a Compose-based configuration with these extra properties."""
    content = {"dockerComposeFile": "docker-compose.yml", "service": "app"}
    content.update(properties)
    return load_config(write_config(folder, content), folder)


# Finding the file


def test_a_folder_without_a_configuration_has_none(tmp_path):
    assert find_config(tmp_path) is None


@pytest.mark.parametrize(
    "relative", [".devcontainer/devcontainer.json", ".devcontainer.json"]
)
def test_the_configuration_is_found_in_either_standard_place(tmp_path, relative):
    path = write_config(tmp_path, "{}", relative)

    assert find_config(tmp_path) == path


def test_the_one_in_the_devcontainer_folder_wins(tmp_path):
    write_config(tmp_path, "{}", ".devcontainer.json")
    preferred = write_config(tmp_path, "{}", ".devcontainer/devcontainer.json")

    assert find_config(tmp_path) == preferred


# Reading it


def test_the_basics_are_read_with_their_defaults(tmp_path):
    config = load(tmp_path)

    assert config.folder == tmp_path
    assert config.name == tmp_path.name
    assert config.compose_files == (tmp_path / ".devcontainer/docker-compose.yml",)
    assert config.service == "app"
    assert config.run_services == ()
    assert config.workspace_folder == "/"
    assert config.remote_user is None
    assert config.container_env == {}
    assert config.remote_env == {}
    assert config.mounts == ()
    assert config.override_command is False
    assert config.stop_on_close is True
    assert config.ignored == ()


def test_each_property_is_read(tmp_path):
    config = load(
        tmp_path,
        name="Sample",
        dockerComposeFile=["../compose.yml", "docker-compose.dev.yml"],
        runServices=["app", "db"],
        workspaceFolder="/workspace",
        remoteUser="vscode",
        containerEnv={"A": "1"},
        remoteEnv={"B": "2", "C": None},
        overrideCommand=True,
        shutdownAction="none",
    )

    assert config.name == "Sample"
    assert config.compose_files == (
        tmp_path / ".devcontainer/../compose.yml",
        tmp_path / ".devcontainer/docker-compose.dev.yml",
    )
    assert config.run_services == ("app", "db")
    assert config.workspace_folder == "/workspace"
    assert config.remote_user == "vscode"
    assert config.container_env == {"A": "1"}
    assert config.remote_env == {"B": "2", "C": None}
    assert config.override_command is True
    assert config.stop_on_close is False


def test_comments_and_trailing_commas_are_allowed(tmp_path):
    text = """
    // The dev container for this project.
    {
      "dockerComposeFile": "docker-compose.yml", /* beside this file */
      "service": "app",
    }
    """

    config = load_config(write_config(tmp_path, text), tmp_path)

    assert config.service == "app"


def test_compose_files_beside_a_top_level_configuration(tmp_path):
    content = {"dockerComposeFile": "docker-compose.yml", "service": "app"}
    path = write_config(tmp_path, content, ".devcontainer.json")

    assert load_config(path, tmp_path).compose_files == (
        tmp_path / "docker-compose.yml",
    )


# What Pyde cannot use


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{ not json", "could not be read"),
        ("[]", "does not hold a JSON object"),
        ('{"image": "python:3"}', "this one uses 'image'"),
        ('{"build": {"dockerfile": "Dockerfile"}}', "this one uses 'build'"),
        ('{"dockerFile": "Dockerfile"}', "this one uses 'dockerFile'"),
        ("{}", "this one has none"),
        ('{"dockerComposeFile": "c.yml"}', "does not name the service"),
        (
            '{"dockerComposeFile": "c.yml", "service": "app", "mounts": 5}',
            "malformed property",
        ),
    ],
)
def test_an_unusable_configuration_says_why(tmp_path, content, reason):
    path = write_config(tmp_path, content)

    with pytest.raises(ConfigError, match=reason):
        load_config(path, tmp_path)


def test_properties_pyde_does_not_act_on_are_listed(tmp_path):
    config = load(
        tmp_path,
        features={"ghcr.io/devcontainers/features/git:1": {}},
        forwardPorts=[8000],
        postCreateCommand="pip install -r requirements.txt",
        customizations={"vscode": {"extensions": ["ms-python.python"]}},
    )

    # Customizations are for other tools, so there is nothing to say about them.
    assert config.ignored == ("Features", "forwardPorts", "postCreateCommand")


def test_empty_values_of_those_properties_are_not_worth_mentioning(tmp_path):
    config = load(tmp_path, features={}, forwardPorts=[], postCreateCommand="")

    assert config.ignored == ()


# Variables


def test_local_variables_are_filled_in_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("PYDE_TEST_USER", "ada")
    monkeypatch.delenv("PYDE_TEST_MISSING", raising=False)

    config = load(
        tmp_path,
        workspaceFolder="/workspaces/${localWorkspaceFolderBasename}",
        containerEnv={
            "LOCAL": "${localWorkspaceFolder}",
            "USER_NAME": "${localEnv:PYDE_TEST_USER}",
            "MISSING": "[${localEnv:PYDE_TEST_MISSING}]",
            "DEFAULTED": "${localEnv:PYDE_TEST_MISSING:fallback}",
            "INSIDE": "${containerWorkspaceFolder}/src",
            "INSIDE_NAME": "${containerWorkspaceFolderBasename}",
            "UNKNOWN": "${notAVariable}",
        },
    )

    assert config.workspace_folder == f"/workspaces/{tmp_path.name}"
    assert config.container_env == {
        "LOCAL": str(tmp_path),
        "USER_NAME": "ada",
        "MISSING": "[]",
        "DEFAULTED": "fallback",
        "INSIDE": f"/workspaces/{tmp_path.name}/src",
        "INSIDE_NAME": tmp_path.name,
        "UNKNOWN": "${notAVariable}",
    }


def test_container_variables_wait_for_the_container(tmp_path):
    config = load(tmp_path, remoteEnv={"PATH": "${containerEnv:PATH}:/extra"})
    assert config.remote_env == {"PATH": "${containerEnv:PATH}:/extra"}

    filled = substitute_container_env(
        {**config.remote_env, "GONE": None, "D": "${containerEnv:NOPE:dflt}"},
        {"PATH": "/usr/bin"},
    )

    assert filled == {"PATH": "/usr/bin:/extra", "GONE": None, "D": "dflt"}


def test_the_id_is_stable_and_differs_between_folders(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"

    one = load(first, containerEnv={"ID": "${devcontainerId}"})
    again = load(first)
    two = load(second)

    assert len(one.id) == 52
    assert set(one.id) <= set("0123456789abcdefghijklmnopqrstuv")
    assert one.id == again.id != two.id
    assert one.container_env == {"ID": one.id}


def test_the_id_is_padded_to_a_fixed_width():
    from pyde.devcontainer.config import _base32

    assert _base32(0) == "0" * 52
    assert _base32(31) == "0" * 51 + "v"
    assert _base32(32, width=4) == "0010"


# Mounts


def test_mounts_become_compose_volumes(tmp_path):
    config = load(
        tmp_path,
        mounts=[
            "source=cache,target=/cache,type=volume",
            "type=bind,src=/host/path,dst=/in/container,readonly",
            {"type": "volume", "source": "data", "target": "/data"},
        ],
    )

    assert config.mounts == (
        {"type": "volume", "source": "cache", "target": "/cache"},
        {
            "type": "bind",
            "source": "/host/path",
            "target": "/in/container",
            "read_only": True,
        },
        {"type": "volume", "source": "data", "target": "/data"},
    )
