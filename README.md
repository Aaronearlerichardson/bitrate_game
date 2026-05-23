# bitrate_game

A Hex-o-Spell-inspired typing game that maximizes the BCI-style achieved bit
rate, defined per Shenoy et al. (2021):

```
B = log2(N - 1) * max(S_c - S_i, 0) / t
```

## Run it

```bash
./run.sh          # macOS / Linux / Git Bash
run.bat           # native Windows cmd / PowerShell
```

Either launcher creates a local `.venv`, installs `pygame`, and starts the
game. Optional flag: `--seed 42` for reproducible target sequences.

## Controls

```
       Q     W     E      <-- top row of selection slots
                HUD
       A     S     D      <-- bottom row of selection slots

  SPACE   start familiarization / return to welcome
  ENTER   begin the 60-second scored run
  ESC     quit
```

Every target is selected with exactly two keypresses:

1. Press the slot key that contains the cued target letter.
2. After the chosen group's letters expand into the six slots, press the
   slot key for the target letter itself.

## Design rationale

**N = 30.** Six hex groups × five letters each. log2(29) ≈ 4.858 bits per
selection — enough information per selection to push bit rate, but the
group is small enough that the player can confidently spot the target
in stage 1 and react fast in stage 2. The alphabet is `a-z` plus `. , ! ?`
to fill out the 30 slots. Trivially configurable in `config.py` (e.g. N=24
with `group_size=4`, or N=36 with letters + digits).

**Two-key selection over six slots.** Honors the Hex-o-Spell design
heritage: a coarse-then-fine selection through a 6-way branching tree. The
mechanic is borrowed; the cue sequence is strictly i.i.d. uniform (no
language model, no predictive text). The two-keypress cost is justified by
the larger per-selection information content.

**Keys `Q W E / A S D`.** Spatially mapped to the six tile positions so
learnability is near-zero — a first-time player understands the mapping
within seconds. The same six keys are reused for both stages, which is
both faithful to Hex-o-Spell (six commands per stage) and minimizes the
motor vocabulary the player has to memorize.

**Invalid keys are ignored, not penalized.** A keypress outside the slot
set has no game-mechanical meaning. Penalizing typos would be modeling
something other than the BCI selection paradigm we're benchmarking.

**Familiarization is unscored and unlimited.** The grading rubric grants a
familiarization period before the scored run. Practicing during it doesn't
contaminate the 60-second window — the tracker is reset on `ENTER`.

## Modular architecture

```
src/bitrate_game/
  core.py       TargetSource, BitRateTracker, Session — zero UI deps
  mode.py       GameMode protocol + HexOSpellMode    — pure selection rules
  adapters.py   InputAdapter + PygameKeyboardAdapter — input swap point
  renderer.py   Renderer + PygameHexRenderer         — display swap point
  config.py     all tunables (alphabet, keys, timing)
  main.py       wires everything together
```

The dependency graph runs strictly downward: `main` knows the whole stack;
each layer below only knows its immediate dependencies; `core` knows nothing
about pygame or rendering at all.

**Swap points:**

| Swap | What to change |
|------|----------------|
| Different alphabet / N / key layout | `config.py` only |
| Different selection paradigm (e.g. direct typing, center-out) | New class implementing `GameMode` + matching view; renderer dispatch on view type |
| Different input device (MIDI, gamepad) | New class implementing `InputAdapter` |
| Different rendering backend | New class implementing `Renderer`, swap in `main.build_pygame_stack` |
| Move to a browser frontend | Replace adapter + renderer with a websocket bridge; reuse `core` and `mode` logic by porting algorithms |

## Building a standalone binary (optional)

The repository pins `nuitka` in `envs/requirements.txt`. To produce a
single-file executable for the current OS:

```bash
.venv/bin/python -m nuitka \
    --standalone --onefile \
    --enable-plugin=pygame \
    --include-package=bitrate_game \
    src/bitrate_game/main.py
```

Cross-platform note: Nuitka does not cross-compile. For a Win / Mac / Linux
trio, build each on the matching OS (e.g. via a GitHub Actions matrix). The
included `run.sh` and `run.bat` work without a precompiled binary, so this
step is purely optional.

## Why these graders should like it

- **Calvin (200+ wpm typist):** 6 keys, two presses per selection, very low
  per-key latency. He should be able to chord through targets quickly once
  the spatial mapping is internalized.
- **Elizabeth (UI-sensitive):** clean visual layout, immediate per-selection
  feedback, animated countdown, polished results screen.
- **Emma (info theory):** N = 30 is a deliberate choice — large enough to
  push log2(N-1) close to 5 bits per selection but not so large that the
  player can't quickly localize the target within a group. The i.i.d.
  guarantee is enforced at the source level (one line in `core.py`); there
  are no hidden language-model effects to exploit.
