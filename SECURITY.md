# Security Policy

## Reporting a vulnerability

Please report security issues **privately** via a
[GitHub security advisory](https://github.com/xiaotonng/pikiloom-skills/security/advisories/new)
rather than opening a public issue. This is a small, non-official project maintained
on a best-effort basis — expect an acknowledgement within a few days.

## Supported versions

Only the tip of the default branch (`main`) is supported. The project is pre-1.0;
fixes land on `main` rather than being backported.

## How secrets are handled

- **No keys are stored in the repo.** Every skill resolves an API key at runtime in
  the order *CLI flag → process env → skill-specific `*_ENV_FILE` → `~/.pikiloom/skills.env`*.
  Nothing is baked into the scripts.
- `.gitignore` excludes `*.env` and generated run artifacts so a filled-in
  `skills.env` cannot be committed by accident. Keep your shared secrets file at
  `~/.pikiloom/skills.env` with `chmod 600`.
- Keep private material — real brand voice / banned-phrase lists, account ids, sink
  credentials, knowledge bases — in your own code, never in a PR here.
- **If a key leaks** (a paste in an issue, a stray commit), rotate it at the provider
  immediately; rotation is the only reliable remedy.

## Scope & expectations

These skills shell out to local tools (`ffmpeg`, Chrome) and call external APIs
(OpenAI, OpenRouter). Read a skill's `SKILL.md` before running it, and run untrusted
inputs in a throwaway directory. The tech-intel **lint guardrail** (unsourced-number
drop, negation preservation, anti-fluff) is a *content-safety* feature to keep drafts
honest — it is not a security sandbox and should not be relied on as one.
