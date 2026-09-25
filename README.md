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

The Brain reads `brain/config.toml`, which maps each WoW install folder to its Era. It is per-machine and not committed:

```powershell
Copy-Item brain\config.example.toml brain\config.toml
```

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

#### Troubleshooting the Lua setup

- **`CERTIFICATE_VERIFY_FAILED` while fetching Lua:** point Python at the certifi bundle, then rerun hererocks:
  `.\.venv\Scripts\python -m pip install certifi; $env:SSL_CERT_FILE = (.\.venv\Scripts\python -c "import certifi; print(certifi.where())")`
- **`'install.bat' is not recognized`:** your shell has `NoDefaultCurrentDirectoryInExePath` set, which stops hererocks from running the LuaRocks installer. Run `Remove-Item Env:NoDefaultCurrentDirectoryInExePath` and rerun hererocks.
