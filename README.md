# Pyde - The code editor written in Python

Pyde is a desktop code editor built with Python and Qt (PySide6). It targets
macOS 14 or later on Apple Silicon.

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

## Develop

You need [uv](https://docs.astral.sh/uv/); it installs Python and the
dependencies for you.

```sh
uv run pyde             # launch the app
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
