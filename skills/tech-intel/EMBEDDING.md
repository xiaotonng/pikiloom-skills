# Embedding `tech-intel` in your project

The core imports **none** of your code — it depends only on the adapter Protocols
in `core/adapters.py`. To embed it you write thin shims around what you already
have and hand them to `TechIntelPipeline`. Nothing here is a rewrite; each adapter
is a small wrapper over an existing function/class.

Make `core` / `adapters` importable from your project:

```bash
# A) point PYTHONPATH at the installed skill
export PYTHONPATH="$HOME/.claude/skills/tech-intel:$PYTHONPATH"
# B) or copy just the engine (the `core/` package is stdlib-only) into your repo
```

---

## Worked example: a "watch a feed → draft on-brand → push a draft" pipeline

Say you already have: an LLM client, a source that returns recent items, a place to
send drafts, and a knowledge base of style/blacklist. Wrap each as an adapter. The
names below (`yourproj.*`) are placeholders for *your* modules.

> Keep anything sensitive — your real brand voice + banned-phrase list, account /
> source ids, sink credentials, and KB — **in your own private code**. Only neutral
> wrappers and config touch this public engine.

```python
# yourproj/tech_intel_embed.py
from core.pipeline import TechIntelPipeline, PipelineConfig
from core.adapters import Persona, LintPolicy
from core.schemas import build_item

from yourproj.llm import chat              # your existing LLM call
from yourproj.sources import recent_items  # your existing collector
from yourproj.kb import KB                 # your existing knowledge base
from yourproj.sink import send_draft       # your existing publish path


# 1) LLMClient — wrap your chat call (one blocking completion → assistant text)
class MyLLM:
    def complete(self, system, prompt, *, model=None, temperature=None, reasoning=None):
        return chat(system=system, user=prompt, model=model, temperature=temperature)


# 2) SourceCollector — map your raw rows onto Items (only source_id + text required)
class MySource:
    def collect(self, *, run_id, spec):
        rows = recent_items(spec)          # your fetch (API / scrape / RSS / DB)
        items = [build_item(
            r["id"], r["text"],
            source="myfeed", author=r.get("author", ""), url=r.get("url", ""),
            context_text=r.get("thread", ""), created_at=r.get("ts", ""),
            metrics={"likes": r.get("likes", 0), "views": r.get("views", 0)},
            reference_urls=r.get("links", []),
        ) for r in rows]
        return items, {"count": len(items)}


# 3) KnowledgeStore — wrap your KB (blacklist, cross-run dedup, style anchors, sediment)
class MyStore:
    def __init__(self): self._kb = KB()
    def blacklist(self):              return set(self._kb.blacklisted_authors())
    def is_posted(self, key):         return self._kb.already_posted(key)
    def mark_posted(self, run_id, outputs):
        return self._kb.remember_posted(run_id, [o["url"] for o in outputs])
    def writing_context(self, *, topics):
        return self._kb.style_anchors_for(topics)   # injected into the draft prompt
    def record_run(self, run_id, refs):
        self._kb.append_lesson(run_id, refs)


# 4) Publisher — wrap your sink (drafts only; never auto-post)
class MyPublisher:
    def publish(self, *, report_md, outputs, run_id):
        send_draft(report_md)                         # e.g. a doc + a notification
        return {"ok": True, "sink": "mydoc"}


# 5) Persona — load YOUR real voice + format from private files (kept out of git)
def my_persona():
    return Persona(
        system=open("private/voice_system.md", encoding="utf-8").read(),
        generate_template=open("private/voice_generate.md", encoding="utf-8").read(),
        content_types=("post", "quote", "reply"),
        focus_topics="",                              # or a per-run topic string
    )


def run_tech_intel(*, publish=True):
    return TechIntelPipeline(
        llm=MyLLM(),
        source=MySource(),
        scorer=...,                                   # HeuristicScorer, or your own ranker
        persona=my_persona(),
        publisher=MyPublisher() if publish else None,
        store=MyStore(),
        lint_policy=LintPolicy(                       # your REAL banned list lives here, in private code
            banned_phrases=("game-changer", "revolutionary", "重磅", "炸裂"),  # … your full private list
            first_person_markers=("we're excited", "我们刚刚", "很高兴宣布"),
        ),
        config=PipelineConfig(
            min_per_type={"post": 2, "quote": 3, "reply": 0},
            hard_min_total=2,
            model="google/gemini-2.5-pro",
            temperature=0.4,
        ),
    ).run(spec={}, publish=publish)
```

### What stays private (never in a public repo)
- your real brand voice + banned-phrase list (loaded from your own files at runtime)
- the account / source ids and any pre-authenticated session/profile
- the sink credentials (Feishu/Slack/… app id + secret + target)
- the knowledge base (tier lists, style anchors, posted history)

### What you reuse from the public engine
- the orchestration (collect → score → draft → lint → publish → sediment)
- the **lint guardrail** (unsourced number/handle drop, negation preservation, thin-content, …)
- the run-artifact IO, schemas, JSON-retry draft call, and report builder

One generic engine, many private plug-ins — that is the whole point.
