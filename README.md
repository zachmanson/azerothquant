# azerothquant

A personal Auction House trading system for World of Warcraft: Forever. See `CONTEXT.md` for the domain language and `docs/adr/` for the design decisions.

- `addon/AzerothQuant/`: the in-game **Addon** (Lua). Logic lives in plain-Lua modules with no WoW API calls, so it runs under `busted`. Only thin glue files touch the WoW API.
- `addon/spec/`: busted specs for those modules.
- `brain/`: the offline **Brain** (Python), tested with `pytest` and linted/formatted with `ruff`.
- `.github/workflows/ci.yml`: runs both suites on every push and pull request.

## Running the tests on Windows

Commands are for PowerShell, run from the repo root.

### Brain (Python)

Needs Python 3.12 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e "brain[dev]"

cd brain
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\ruff check .
..\.venv\Scripts\ruff format --check .   # drop --check to reformat
cd ..
```

One test also loads the Lua the Brain writes into real Lua 5.1. It is skipped unless `lua` is on PATH or `$env:LUA` points at one, e.g. `$env:LUA = "..\.lua\bin\lua.exe"` after the Addon setup below.

The Brain reads `brain/config.toml`, which maps each WoW install folder to its Era. It is per-machine and not committed:

```powershell
Copy-Item brain\config.example.toml brain\config.toml
```

### Running the Brain

Installing the Brain (above) adds a `brain` command. Run it from `brain/` (or pass `--config <path>`):

```powershell
cd brain
..\.venv\Scripts\brain import   # import every SavedVariables file once
..\.venv\Scripts\brain watch    # keep running; import whenever the game rewrites the file
..\.venv\Scripts\brain rebuild  # recreate history.sqlite from the Scan Archive (stop watch first)
```

It reads `WTF\Account\*\SavedVariables\AzerothQuant.lua` in each configured install folder. The game writes that file on `/reload` or logout, so `brain watch` picks up a Scan a few seconds after you `/reload`. Stop it with Ctrl+C.

After each import it rewrites `Interface\AddOns\AzerothQuant\Recommendations.lua` in every install that has the Addon. The game reads it on the next `/reload` or login, and the Addon then deletes the Scans the Brain has already imported from SavedVariables. So a Scan leaves SavedVariables one `/reload` after the Brain imports it.

Before importing a Scan, the Brain saves it exactly as recorded to the Scan Archive (`brain\archive\` by default, or `archive_dir` in the config), one gzipped JSON file per Scan. The archive is the source of truth: `history.sqlite` can always be rebuilt from it, but the archive itself can't be recreated, so it's worth pointing `archive_dir` at a backed-up or synced folder. See ADR-0005.

### Addon (Lua)

WoW runs Lua 5.1, and busted needs a few C modules, so the easiest route on Windows is to build a local Lua 5.1 + LuaRocks into `.lua/` (gitignored) with [hererocks](https://github.com/luarocks/hererocks), using the MSVC compiler.

One-time setup:

1. Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with the "Desktop development with C++" workload.
2. Create the venv from the Brain section above, then:

```powershell
.\.venv\Scripts\python -m pip install hererocks
.\.venv\Scripts\hererocks .lua -l 5.1 -r latest --target vs
.\.lua\bin\luarocks.bat install busted
```

Run the specs:

```powershell
.\.lua\bin\busted.bat --directory=addon
```

To try the Addon in game, copy (or symlink) `addon\AzerothQuant` into `<WoW>\_classic_beta_\Interface\AddOns\`.

The Addon ships a stub `Recommendations.lua`, because the game only loads files that existed when it started. The Brain overwrites that file, so with a symlink it shows up as changed in git. Hide that with `git update-index --skip-worktree addon/AzerothQuant/Recommendations.lua`.

#### Troubleshooting the Lua setup

- **`CERTIFICATE_VERIFY_FAILED` while fetching Lua:** point Python at the certifi bundle, then rerun hererocks:
  `.\.venv\Scripts\python -m pip install certifi; $env:SSL_CERT_FILE = (.\.venv\Scripts\python -c "import certifi; print(certifi.where())")`
- **`'install.bat' is not recognized`:** your shell has `NoDefaultCurrentDirectoryInExePath` set, which stops hererocks from running the LuaRocks installer. Run `Remove-Item Env:NoDefaultCurrentDirectoryInExePath` and rerun hererocks.
