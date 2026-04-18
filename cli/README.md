# kaizen-cli

Command-line interface for the Kaizen CD-AOR autonomous code engineering system.

## Install

```
pip install -e .
```

Run from the repo root (`C:\RepoEx\Kaizen-beta`).

## Commands

### `kaizen run`

Runs the bootstrap orchestrator against a workspace. Two task-spec modes:

```
# ADR-driven (canonical):
kaizen run --target-adr ADR-0008 --workspace ./myrepo --provider anthropic

# Free-text (wraps the task in a synthetic ADR-9999 on disk):
kaizen run --task "modernize auth module" --workspace ./myrepo
```

Key flags:

- `--workspace PATH`   workspace directory (default: `.`)
- `--adr-dir PATH`     ADR directory (default: `<workspace>/.architecture/decisions`)
- `--max-steps N`      maximum denoising steps (default: `5`)
- `--theta F`, `--epsilon F`   convergence thresholds
- `--adaptive-convergence` / `--no-adaptive-convergence`   Thompson-sampling gate (default: on)
- `--priors-file PATH` Thompson priors JSON (loaded at start, saved at end)
- `--provider {anthropic,openai,ollama,litellm,mixed}`
- `--api-key`, `--ollama-host`, `--reasoning-model`, `--litellm-base-url`
- `--dry-run`          print the resolved plan and exit without running
- `--format {human,json}`   output format (default: `human`)

### `kaizen status`

Scans the current directory for `taor_observations.jsonl` and `priors.json`
artifacts and prints a summary (most recent run timestamp, last confidence
trajectory). Prints `No prior Kaizen runs detected in this directory` on a
clean tree.

```
kaizen status
kaizen status --path ./benchmarks
```

### `kaizen priors`

```
kaizen priors show [PATH]     # pretty-print a priors file (default: ./priors.json)
kaizen priors reset [PATH]    # delete a priors file with confirmation (--yes to skip)
```

### `kaizen version`

Prints the CLI version.

## Global flags

- `--verbose`   print stack traces on error and enable extra logs
- `--no-color`  disable ANSI color output (also honors `NO_COLOR` env var)

## Exit codes

- `0`   success (for `run`, implies convergence)
- `1`   convergence failed / aborted / unhandled exception
- `2`   usage error (bad args, missing workspace, missing credentials)
- `130` interrupted (Ctrl-C); priors are persisted if enabled

## Output

- All normal output goes to **stdout**.
- Errors and warnings go to **stderr**.
- Color is emitted only when stdout is a TTY and `--no-color` / `NO_COLOR`
  are not set.
