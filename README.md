# lyrical-engine

Fork Tales Lyrical Engine — self-contained, judge-as-engine, no external API required.

## How it works

- `engine_v4.py` generates songs by randomly assembling components (titles, roles, styles, lyrics).
- An internal judge scores each song on six criteria: coherence, consistency, theme, connectivity, continuity, surprise.
- Scores decay over time so the engine naturally re-explores.
- A GitHub Actions workflow runs every day at 03:00 UTC, generates 10 new songs, then calls `opencode` with `big-pickle` to add new lyric components into the pool.
- All memory lives in `memory/` (gitignored locally, committed by the bot).
- All generated songs land in `generated/`.

## Run locally

```bash
python engine_v4.py          # 10 songs, random seed
python engine_v4.py --n 20   # more songs
python engine_v4.py --seed 7 # reproducible
```

## Automation

See `.github/workflows/daily-advance.yml`.
The workflow:
1. Runs `engine_v4.py --n 10`
2. Installs `opencode-ai` and calls it with `big-pickle` (free, no API key needed for public model)
3. opencode reads the run summary and top songs, then adds 3–6 new lyric components to `engine_v4.py`
4. Results are committed back to `main`

## World

Gates-of-Truth. Characters: duct, null, patch, sei, rin, ritsu.
Motifs: consent/boundary, drift/phase, scar/joint, distribution, truth-resolves, white-page, rail/lattice.
