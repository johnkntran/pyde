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

1. Bump the version with `uv version --bump patch` (or `minor`, `major`) and
   merge that change into `main`.
2. Tag the merged commit and push the tag:

   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```

GitHub Actions then tests the code, builds the `.dmg`, and publishes it as a
GitHub Release. The tag has to match the version in `pyproject.toml`, or the
build stops before publishing.
