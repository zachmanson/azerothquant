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

Predictions, your game-knowledge calls that some items will be worth much more after a raid or phase release, go in `brain/predictions.toml` next to it (see `brain/predictions.example.toml` and ADR-0006). It's optional, not committed, and can't be rebuilt from the Archive, so keep a copy of it. The Brain freezes each Prediction's Grade, and the cost of what you held when you wrote it, in `brain/grades.toml` beside it, along with each Flip Grade and the Flips to Sell named by the Scans before your Purchases. That file can't be rebuilt either (a new pricing rule would grade differently), so keep a copy of it too, and delete an entry only to have it worked out again.

### Running the Brain

Installing the Brain (above) adds a `brain` command. Run it from `brain/` (or pass `--config <path>`). With neither, it falls back to `%LOCALAPPDATA%\AzerothQuant\config.toml`, where the packaged Brain keeps its config (#115). The config's folder is the data folder: the history, the Archive, `brain.log` (rotated at 1 MB) and `brain.lock` all live there. Only one `brain watch` runs per data folder; a second one exits with "already running".

```powershell
cd brain
..\.venv\Scripts\brain import   # import every SavedVariables file once
..\.venv\Scripts\brain watch    # keep running; import whenever the game rewrites the file
..\.venv\Scripts\brain rebuild  # recreate history.sqlite from the Archive (stop watch first)
..\.venv\Scripts\brain recommend  # print Vendor, Sell or Hold for Holdings, and the Shopping List
..\.venv\Scripts\brain replay --since 2026-09-20  # grade the Brain against Auctionator and emulated TSM (ADR-0015)
..\.venv\Scripts\brain disenchants  # check the Disenchant tables against your Disenchant Results (ADR-0018)
..\.venv\Scripts\brain flips  # grade the Flips to Sell you made against what the Brain named (ADR-0023)
```

It reads `WTF\Account\*\SavedVariables\AzerothQuant.lua` in each configured install folder. The game writes that file on `/reload` or logout, so `brain watch` picks up a Scan (or a Mailbox Read, taken each time you open a mailbox, or a Character Read of your gold, bags and bank, taken on every `/reload` and logout) a few seconds after you `/reload`. Stop it with Ctrl+C.

After each import it rewrites `Interface\AddOns\AzerothQuant\Recommendations.lua` in every install that has the Addon. The game reads it on the next `/reload` or login, and the Addon then deletes the Scans, Mailbox Reads and Character Reads the Brain has already imported from SavedVariables. So each leaves SavedVariables one `/reload` after the Brain imports it.

It also writes the same file into `Interface\AddOns\AzerothQuant_Data\`, a load-on-demand addon the Brain creates (with its `.toc`) the first time, and the game reads it only when the Addon loads it (ADR-0021). So the cycle is: Scan, Reload, wait for the Brain, then click **Load** (or `/aq load`) on the Recommendation Table. The button switches from Reload to Load when the Recommendations the game read at the reload are from before the Brain imported what that reload saved. It starts to pulse once the Brain should be done (about a minute). Load works once per reload. If you click it too early, a chat line says so, and you Reload to try again. The game only finds a new addon folder when it starts, so after the Brain's first run, restart the game once. Until then the button stays Reload, which means a second Reload after the Brain.

Before importing a Scan, Mailbox Read or Character Read, the Brain saves it exactly as recorded to the Archive (`brain\archive\` by default, or `archive_dir` in the config), one gzipped JSON file each. The archive is the source of truth: `history.sqlite` can always be rebuilt from it, but the archive itself can't be recreated, so it's worth pointing `archive_dir` at a backed-up or synced folder. See ADR-0005.

### Releasing AzerothQuantBrain.exe

Guildies get one `AzerothQuantBrain.exe` (#115). To release one, bump `__version__` in `brain/src/brain/__init__.py`, commit, then tag and push it:

```powershell
git tag v0.2.0
git push origin v0.2.0
```

Once the rest of CI passes, the `brain-exe` job in `.github/workflows/ci.yml` checks the tag matches `__version__`, builds the exe on Windows and attaches it to a GitHub Release. To build it locally: `pip install -e ".[build]"`, then `pyinstaller AzerothQuantBrain.spec` in `brain/`, and the exe lands in `brain\dist\`. The bundled Addon comes from the last commit, not the working tree, so commit Addon changes first.

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

With no Lua at all, `scripts/busted.py` runs the same specs on [lupa](https://pypi.org/project/lupa/)'s Lua 5.1 (`pip install lupa`, then `python ..\scripts\busted.py` from `addon\`). It covers only what the specs use; CI runs the real busted.

To try the Addon in game, copy (or symlink) `addon\AzerothQuant` into `<WoW>\_classic_beta_\Interface\AddOns\`.

The Addon ships a stub `Recommendations.lua`, because the game only loads files that existed when it started. The Brain overwrites that file, so with a symlink it shows up as changed in git. Hide that with `git update-index --skip-worktree addon/AzerothQuant/Recommendations.lua`.

#### Troubleshooting the Lua setup

- **`CERTIFICATE_VERIFY_FAILED` while fetching Lua:** point Python at the certifi bundle, then rerun hererocks:
  `.\.venv\Scripts\python -m pip install certifi; $env:SSL_CERT_FILE = (.\.venv\Scripts\python -c "import certifi; print(certifi.where())")`
- **`'install.bat' is not recognized`:** your shell has `NoDefaultCurrentDirectoryInExePath` set, which stops hererocks from running the LuaRocks installer. Run `Remove-Item Env:NoDefaultCurrentDirectoryInExePath` and rerun hererocks.
