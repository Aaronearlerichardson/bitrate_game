# bitrate_game

A Hex-o-Spell-inspired typing game that maximizes the BCI-style achieved
bit rate (Shenoy et al. 2021):

```
B = log2(N - 1) * max(S_c - S_i, 0) / t
```

## Play

Download `bitrate_game-binaries.zip` from the latest [release](../../releases)
and run the binary for your OS.

**macOS:** Gatekeeper blocks unsigned binaries downloaded from the
internet. Run once in Terminal to allow it:

```bash
xattr -d com.apple.quarantine bitrate_game-macos-arm64
chmod +x bitrate_game-macos-arm64
./bitrate_game-macos-arm64
```

Or right-click the binary in Finder → **Open** → **Open Anyway**.

## Controls

```
   Q  W  E
      HUD
   A  S  D
```

- **SPACE** — start practice from welcome; return to welcome from anywhere else
  (including aborting a scored run)
- **ENTER** — start the 60-second scored run (from welcome or practice)
- **ESC** — quit

Each target is selected in two keypresses: press the tile containing the
yellow target letter, then press the tile its letter expanded to.

## Design notes

- **N = 36** (six groups × six letters). `log2(35) ≈ 5.13` bits per selection.
- Cues are i.i.d. uniform — no language model, no predictive text.
- Q/W/E/A/S/D map spatially to tile positions; same six keys for both stages.
- Invalid keys are ignored, not penalized — we're benchmarking the selection
  paradigm, not typing accuracy.

## Build from source

```bash
pip install -r envs/requirements.txt
python scripts/build.py
```

Output: `dist/bitrate_game-<os>-<arch>[.exe]`. Then run via `./run.sh`
(POSIX) or `run.bat` (Windows). Nuitka doesn't cross-compile — build on
each target OS, or let `.github/workflows/build.yml`'s matrix do it.

## Architecture

```
src/bitrate_game/
  core.py       Session, BitRateTracker, TargetSource  (UI-free logic)
  mode.py       HexOSpellMode + GameMode protocol
  adapters.py   PygameKeyboardAdapter + InputAdapter protocol
  renderer.py   PygameHexRenderer + Renderer protocol
  config.py     all tunables (alphabet, keys, timing, colors)
  main.py       wires the components together
```

`core` and `mode` have zero pygame imports — swap renderer/adapter to
port to a browser or different input device without touching the logic.
