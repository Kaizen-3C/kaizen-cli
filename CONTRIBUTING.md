# Contributing to Kaizen-3C / kaizen-cli

Thanks for considering a contribution. `kaizen` is a compliance-driven
modernization CLI — contributions that improve correctness, coverage,
extensibility, or developer experience are all welcome.

## License

By contributing to this repository, you agree that your contributions
will be licensed under the **Apache License, Version 2.0** (the same
license that covers the rest of this repository — see [`LICENSE`](LICENSE)).
You retain copyright in your contributions; you are granting the project
and its users an Apache-2.0 license grant.

## Developer Certificate of Origin (DCO)

We use the **Developer Certificate of Origin** (DCO) to attest that
contributors have the right to submit their work under the project's
license. The DCO is a lightweight, sign-your-commits convention used by
the Linux kernel, Docker, Kubernetes, and many other major OSS projects.

The full text is at <https://developercertificate.org>. In summary, by
signing off on a commit you are certifying that:

1. The contribution was created by you, OR
2. The contribution is based on previous work that, to the best of your
   knowledge, is covered under an appropriate open-source license that
   allows you to submit it under this project's license, OR
3. The contribution was provided directly to you by some other person who
   certified (1), (2), or (3), and you have not modified it.

**To sign off**, add `-s` to your git commit:

```bash
git commit -s -m "feat: add foo subcommand"
```

Git will append a `Signed-off-by: Your Name <you@example.com>` trailer
to your commit message. PRs without DCO sign-off will be asked to amend
before merge.

## Code style

- **Python:** PEP 8; 4-space indent; `ruff` is the project linter
  (`pip install kaizen-cli[dev]` pulls it in). Run `ruff check .` before
  opening a PR. We do not currently enforce `black` formatting, but
  consistent style matching the surrounding file is expected.
- **Type hints:** encouraged on all public functions and CLI entry points;
  required on new code in `cli/main.py` and `cli/pipeline/`.
- **Docstrings:** public CLI entry points and any function that is part
  of the programmatic API surface must have a one-line summary docstring.
  Full NumPy/Google-style docstrings are welcome but not required for
  internal helpers.
- **Markdown:** 80-char soft wrap; ATX-style headings (`#`, not
  underlines).
- **Commit messages:** imperative mood; conventional-commit prefixes
  (`feat:`, `fix:`, `docs:`, `chore:`, `test:`) preferred but not
  enforced.

## Setting up a development environment

```bash
# 1. Create a fresh virtual environment (Python 3.10+)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install the CLI in editable mode with dev extras
pip install -e ".[dev,web,mcp]"

# 3. Smoke-test the install
kaizen --help
```

Always run the smoke test in a fresh venv before opening a PR — this
catches packaging issues (missing `package-data`, import path problems)
that unit tests alone won't catch.

## Running tests

Tests live under `cli/tests/`. We use `pytest`.

```bash
# Run all tests
pytest cli/tests/

# Run tests for a specific subcommand
pytest cli/tests/test_<subcommand>.py -v

# Run with output captured (useful for CLI integration tests)
pytest cli/tests/ -s
```

Each new subcommand or feature should ship with at least:

1. A unit test for the core logic (mock external API calls).
2. An integration test that invokes the subcommand via `cli.main:main`
   using `click.testing.CliRunner` (or equivalent) and asserts on exit
   code and key output strings.

## How to add a new subcommand

1. **Create the module.** Add `cli/<subcommand>.py` (or
   `cli/<subcommand>/` for larger commands). Keep the Typer/Click
   command object at the top level of that module.

2. **Wire it into `cli/main.py`.** Import your command object and
   register it with the top-level `app` (Typer) or `cli` (Click) group:

   ```python
   # cli/main.py
   from cli.<subcommand> import <subcommand>_app
   app.add_typer(<subcommand>_app, name="<subcommand>")
   ```

3. **Add tests.** Create `cli/tests/test_<subcommand>.py`. Cover at
   minimum: `--help` exits 0, happy-path invocation, and at least one
   error/edge case.

4. **Update the README.** Add a one-line entry in the `Commands` table
   in `README.md` (or the equivalent quick-reference section).

5. **Update the CHANGELOG.** Add an entry under `[Unreleased]` in
   `CHANGELOG.md` following the Keep-a-Changelog format.

6. **Open a PR.** Reference the relevant GitHub issue if one exists.
   PRs introducing a new subcommand without tests will be asked to add
   them before merge.

## What we welcome

- **New subcommands** that fit the Code/Compose/Compliance framing —
  decompose, recompose, audit.
- **Pipeline improvements** — better prompts, caching, retry logic,
  support for additional LLM providers.
- **Test coverage** — new tests for existing subcommands, especially
  edge cases and error paths.
- **Documentation fixes** — clarifications, examples, correcting
  outdated descriptions.
- **Dependency hygiene** — security patches, version-constraint fixes,
  compatibility with new Python versions.

For larger changes (new subsystems, breaking changes to the CLI surface,
new optional-dependency groups), open an issue first to discuss approach
before investing in a full implementation. Check the open issues and the
roadmap tracked in the repository's GitHub Issues for current priorities.

## What we may decline

- **Cosmetic-only PRs** (whitespace cleanups, minor grammar tweaks that
  don't affect meaning). We will fix these ourselves when we see them.
- **Provider-specific lock-in** in shared pipeline code. Provider
  differences belong in provider-specific adapter modules.
- **Features that belong in the commercial tier.** If you are unsure
  whether a feature is appropriate for the open-source core, open an
  issue and ask before building it.

## Code of conduct

Be civil. Disagree with ideas, not people. Assume good faith. If you
encounter behavior that violates this principle, contact the maintainers
at hello@kaizen-3c.dev.

We may adopt a more formal code of conduct (Contributor Covenant or
similar) as the contributor base grows. Until then: be kind, be
specific, and remember that everyone is doing their best.

## Where to ask questions

- **Bugs / feature requests:** open a GitHub Issue.
- **Methodology / design questions:** open a GitHub Issue with the
  `question` label.
- **Anything else:** hello@kaizen-3c.dev.

---

Thank you for contributing.
