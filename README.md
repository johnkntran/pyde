# Pyde - The code editor written in Python

Pyde is a desktop code editor built with Python and Qt (PySide6), with syntax
highlighting by Pygments and a built-in terminal. It targets macOS 14 or later
on Apple Silicon.

## Install

Download the latest `.dmg` from the
[Releases page](https://github.com/johnkntran/pyde/releases/latest), open it,
and drag Pyde into Applications.

Pyde is not code-signed, so macOS blocks it the first time you open each
downloaded version. Either approve it under System Settings → Privacy &
Security → Open Anyway, or clear the quarantine flag:

```sh
xattr -dr com.apple.quarantine /Applications/Pyde.app
```

## Terminal

Press ``ctrl+` `` to show the terminal and type in it, and again to hide it
and return to your file. It runs your login shell, so the tools on your usual
path are available, and it starts in the folder you have open. Opening another
folder restarts the shell there.

## Dev containers

When the folder you open has a `.devcontainer/devcontainer.json` (or a
`.devcontainer.json`) based on Docker Compose, Pyde offers to **Reopen in
Container**. That starts the Compose project and turns the terminal into a
shell inside the service's container, in `workspaceFolder`, as `remoteUser`.
Your files are still edited where they are; the container sees them through
the mount in your Compose file. **Reopen Folder Locally**, in the File menu,
goes back.

- **Read from `devcontainer.json`:** `dockerComposeFile`, `service`,
  `runServices`, `workspaceFolder`, `remoteUser`, `containerEnv`, `remoteEnv`,
  `mounts`, `overrideCommand`, `shutdownAction`, and the lifecycle commands,
  with variables such as `${localWorkspaceFolder}`, `${localEnv:NAME}`, and
  `${containerEnv:NAME}`.
- **Lifecycle commands** run in the terminal before the shell opens.
  `initializeCommand` runs on your Mac; the rest run in the container.
  `onCreateCommand`, `updateContentCommand`, and `postCreateCommand` run once
  per container, `postStartCommand` once each time it starts, and
  `postAttachCommand` every time you reopen in it. A command that fails is
  tried again next time. Where the specification runs an object of commands
  side by side, Pyde runs them one after another.
- **Rebuild Container**, in the File menu, builds the images again and
  replaces the containers, so the once-per-container commands run again. Use
  it after changing a Dockerfile or the Compose file.
- **Not supported:** configurations based on an `image` or a Dockerfile,
  Features, and `forwardPorts`; publish ports in your Compose file instead.
  `customizations` are for other editors and are ignored.
- **Shared with VS Code:** Pyde gives the Compose project the same name and
  labels VS Code does, so the two use the same containers. Each keeps its own
  record of which lifecycle commands have run, so the first time Pyde opens a
  container VS Code created, the once-per-container commands run again.
- **On close:** the containers are stopped, unless `shutdownAction` is
  `"none"`.

## Settings

Choose **Settings…** from the Pyde menu (`cmd+,`) to edit
`~/Library/Application Support/Pyde/settings.json`. Changes apply as soon as
you save it.

```jsonc
{
  // Which Pygments style colors the code, in light mode and in dark mode.
  "theme": { "light": "xcode", "dark": "monokai" }
}
```

- The file lists the styles to choose from, and
  [pygments.org/styles](https://pygments.org/styles/) shows what each looks
  like.
- A mode you leave out keeps its usual style: `default` in light mode and
  `github-dark` in dark mode.
- Only the code's colors change. The background, the rest of the window, and
  the terminal keep their own colors, so a style made for a dark background
  is hard to read in light mode, and the other way around.

## Keyboard shortcuts

Choose **Open Keyboard Shortcuts** from the Pyde menu (`cmd+k cmd+s`) to edit
`~/Library/Application Support/Pyde/keybindings.json`. The file maps commands
to keys, and changes apply as soon as you save it:

```jsonc
{
  "view.toggleTerminal": "cmd+j", // a different key
  "preferences.openKeybindings": "" // no shortcut at all
}
```

- Keys are written like `cmd+p` or `cmd+shift+f`. The modifiers are `cmd`,
  `ctrl`, `alt` (or `option`), and `shift`.
- A two-step shortcut is two keys separated by a space, like `cmd+k cmd+s`.
- **Open Default Keyboard Shortcuts**, also in the Pyde menu, lists every
  command with its default key.
- If something in the file is wrong, the status bar at the bottom of the
  window says what.
- Only Pyde's own commands can be rebound. The standard text-editing keys,
  such as copy, paste, undo, and cursor movement, are fixed.

## Develop

You need [uv](https://docs.astral.sh/uv/); it installs Python and the
dependencies for you.

```sh
uv run pyde             # launch the app
uv run pyde .           # launch it on a folder (or pass a file)
uv run pytest           # run the tests
uv run ruff check       # lint
uv run ruff format      # format
scripts/build_dmg.sh    # build dist/Pyde.app and dist/Pyde-<version>-arm64.dmg
```

To check a packaged build without clicking through it, run
`dist/Pyde.app/Contents/MacOS/Pyde --smoke-test`. It starts the app, waits for
the embedded web engine to load a page, and exits with status 0 on success.

## Release

Create a new version tag, such as `v0.2.0`, in either of two ways:

- On GitHub, draft a new release that creates the tag, and publish it. Your
  title and notes are kept.
- From the command line, push the tag. The release is created for you with
  generated notes.

  ```sh
  git tag v0.2.0
  git push origin v0.2.0
  ```

GitHub Actions then tests the code, builds the `.dmg`, and attaches it to the
release a few minutes later.

The tag is the only place the version is set: `v0.2.0` builds Pyde 0.2.0. The
version in `pyproject.toml` is a placeholder that development builds report.

## Credits

Pyde's syntax highlighter adapts code from
[qtconsole](https://github.com/jupyter/qtconsole) and
[Pygments](https://pygments.org), both BSD-licensed. Its terminal is
[xterm.js](https://xtermjs.org), MIT-licensed, which is included in
`src/pyde/resources/xterm/` unmodified. Their license texts are in
`src/pyde/licenses/` and ship inside the app.
