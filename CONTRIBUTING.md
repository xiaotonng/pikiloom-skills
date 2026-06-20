# Contributing

Thanks for contributing. These are non-official agent skills curated from real use;
the bar is that each one stays **atomic, scriptable, and honest about its
dependencies and secrets**. A few conventions keep the repo consistent.

## Principles

- **Atomic** — one skill does one capability well, driven from the command line.
- **Stdlib-first** — reach for a third-party package only when it earns its weight,
  and **lazy-import** heavy/optional deps inside the function that needs them
  (so importing a module never forces a `pip install` you don't use).
- **Honest about deps & keys** — every required binary, package, and API key is
  named in the skill's `SKILL.md` and in `.env.example`.
- **Drafts, not actions** — anything that publishes externally (e.g. tech-intel)
  produces a reviewable draft; it never auto-posts.

## Dev setup

```bash
git clone https://github.com/xiaotonng/pikiloom-skills && cd pikiloom-skills
python3 -m unittest discover -s tests -p 'test_*.py' -v   # zero deps, zero keys
```

Requires Python 3.10+. The test suite needs nothing else; see [TESTING.md](./TESTING.md).

## Repo layout

```text
skills/<name>/SKILL.md      # the agent-facing contract (frontmatter + usage)
skills/<name>/...           # scripts / packages for that skill
tests/                      # stdlib unittest, mirrors skills/
.github/workflows/ci.yml    # tests + demo smoke across Python 3.10–3.13
.env.example                # every env var, documented
```

## Adding or changing a skill

1. **`SKILL.md` frontmatter** — `name` (kebab-case, matches the directory) and a
   `description` that says *what it does and when to use it* (the agent matches on
   this — be specific). `argument-hint` and `allowed-tools` are optional.

   > ⚠️ **skills.sh YAML gotcha:** the frontmatter `description` is parsed as
   > unquoted YAML, so a `": "` (colon-space) inside it breaks the parser. Use
   > ` — `, `; `, or `:` without a trailing space. (This bit us once — see commit
   > `3c18a27`.)

2. **Key resolution** — follow the shared convention so users only manage one file:

   ```
   CLI flag  →  process env  →  skill-specific *_ENV_FILE  →  ~/.pikiloom/skills.env
   ```

   Read keys at runtime; never bake them into a script. Copy the `resolve_key`
   helper from an existing skill rather than inventing a new order.

3. **Tests** — add offline `unittest` coverage (use a `CannedLLM`-style double for
   any LLM/API path). Update the coverage table in `TESTING.md` to match.

4. **Docs** — update the skill table in `README.md`, add any new env var to
   `.env.example`, and add a line to `CHANGELOG.md` under `[Unreleased]`.

## Secrets — never commit

- API keys, tokens, or session/profile data.
- Your **real brand voice and banned-phrase list** (tech-intel): keep these in your
  own private files loaded at runtime. The shipped `prompts/*.example.md` and the
  `LintPolicy` defaults are deliberately neutral illustrations.
- Sink credentials (Feishu/Slack app id + secret + target).

`.gitignore` drops `*.env` and run artifacts, but the first line of defense is you.

## Style

Match the surrounding code — its naming, comment density, and idioms. Keep prose in
docstrings/`SKILL.md` tight and factual (no marketing language). Run the tests
before opening a PR; CI runs the same suite plus the `--demo` smoke on 3.10–3.13.

## Commits & PRs

Keep a PR focused on one skill or one concern. Conventional-commit style
(`feat(tech-intel): …`, `fix(image-gen): …`, `docs: …`) is appreciated. Fill in the
PR checklist — especially the "docs match the change, no phantom flags/files" box.
