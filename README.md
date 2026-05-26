# bitrate_game

**GridQuest** — a spatial-selection game that maximizes the BCI-style
achieved bit rate (Shenoy et al. 2021):

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
   A  S  D
   Z  X  C
```

- **SPACE** — start practice from welcome; return to welcome from anywhere else
  (including aborting a scored run)
- **ENTER** — start the 60-second scored run (from welcome or practice)
- **ESC** — quit

Each target is selected in two keypresses: read the cue (a mini 9×9 board
with one cell highlighted in yellow), press the key for the **outer** 3×3
group containing it, then press the key for the **inner** position the
target sat in.

## Design notes

- **N = 81** (9 outer groups × 9 inner positions). `log2(80) ≈ 6.32` bits
  per selection — the spatial encoding squeezes more information out of
  each two-key chord than the 6-tile letter version did.
- Cues are i.i.d. uniform — no language model, no patterns.
- Q/W/E/A/S/D/Z/X/C map spatially to the 3×3 tile positions; same nine
  keys for both stages, so motor vocabulary stays tiny.
- Pure spatial selection — no letters, no language. Works for any
  alphabet, any locale.
- Invalid keys are ignored, not penalized — we're benchmarking the
  selection paradigm, not typing accuracy.

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
  mode.py       GridQuestMode + GameMode protocol
  adapters.py   PygameKeyboardAdapter + InputAdapter protocol
  renderer.py   PygameGridRenderer + Renderer protocol
  config.py     all tunables (grid size, keys, timing, colors)
  main.py       wires the components together
```

`core` and `mode` have zero pygame imports — swap renderer/adapter to
port to a browser or different input device without touching the logic.
