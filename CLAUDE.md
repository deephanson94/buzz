# CLAUDE.md

Buzz is a fog-of-war game that teaches how a repo works. Product docs:
`README.md` (what/how), `docs/DESIGN_V1.md` (design), `docs/FINDINGS.md`
(playtest history), `docs/HANDOFF.md` (current session state - start a
fresh session with `/kickoff`, end one with `/handoff`).

## Layout

- `buzz/analyze.py` - AST import graph, roles, zones, git archaeology
- `buzz/questions.py` - quest generation (deterministic, graph-truthed)
- `buzz/engine.py` - fog, movement, answer verification, economy
- `buzz/cli.py` + `buzz/shell.py` - one-shot commands + interactive shell
- `buzz/render.py` / `atlas.py` / `recap.py` - text map, HTML map, field notes
- `buzz/calibrate.py` / `author.py` / `lore.py` - solver quality gate, LLM-authored semantic layer
- `tests/test_buzz.py` - the suite; `scripts/smoke.sh` - clean-install end-to-end

## Commands

```bash
pip install -e ".[dev]"        # + "[lore]" for the anthropic SDK
python -m pytest tests/        # must be green before any push
bash scripts/smoke.sh          # end-to-end on a generated fixture repo
mkdir game && cd game && buzz analyze <repo> [--lore] && buzz play
```

## Branching

- `main` is the default branch and must stay stable/playable - the owner
  dogfoods from it.
- New work happens on feature branches (`feature/<name>`) and merges into
  `main` via pull request. Do not push feature work directly to `main`.
- CI (pytest matrix + clean-install smoke) runs on pushes to `main`,
  `claude/**`, `feature/**`, and on all PRs. Green CI before merging.
- **If CI seems stuck** (2026-08-26 incident playbook): GitHub Actions can
  drop push webhooks (a push produces NO runs) or strand runs in a
  created-but-never-dispatched limbo ("queued" forever; even the cancel
  API 409s with "has not been queued yet"). Neither is this repo's fault -
  do not debug the YAML. Fix: trigger manually, `ci.yml` has
  `workflow_dispatch` exactly for this (`gh workflow run ci.yml
  --ref <branch>`, or the GitHub MCP `actions_run_trigger` with method
  `run_workflow`). Orphaned zombie runs on superseded commits are
  cosmetic; ignore them.

## Rules that are load-bearing

1. **Ground truth never comes from LLM prose.** Quest answers are verified
   against the import graph or git history. LLM-authored content (lore
   quests, briefs, glosses) is either mechanically validated or displayed
   as a clearly-marked unverified "scout's impression" worth 0 XP.
2. **Piped output stays plain.** Agents, CI, and the playtest panels drive
   the game through one-shot commands and piped stdin; color and
   interactivity live only behind a TTY check. Never break this.
3. **Gameplay changes get playtested.** The validation instrument is a
   panel of Sonnet subagents playing a real world and returning structured
   verdicts (methodology in `docs/FINDINGS.md`). Fix what converges;
   confirm with a small follow-up panel.
4. **Wrong answers never subtract XP or remove progress.**
