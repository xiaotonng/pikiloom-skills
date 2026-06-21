"""Feishu (Lark) publisher — a reference ``Publisher`` that delivers the report as a
Feishu **doc** plus an interactive card with an "open doc" button.

It is generic plumbing, not project-specific: the only secrets are the app
credentials, which resolve from the env / ``~/.pikiloom/skills.env`` (same
convention as ``OpenRouterLLM``), never hard-coded. Drafts only — it creates a
doc and pings you; it never posts to a public channel on its own.

Feishu app setup (one-time):
1. open.feishu.cn → create an internal app
2. Permissions → enable ``docx:document`` (create/edit docs) and
   ``im:message:send_as_bot`` (bot sends messages); publish a version
3. DM the bot once from your Feishu client to open the private chat
4. Put the three values in ``~/.pikiloom/skills.env`` (or the process env):
     FEISHU_APP_ID=cli_xxxx
     FEISHU_APP_SECRET=xxxx
     FEISHU_RECEIVE_ID=ou_xxxx   # your open_id (the DM target)
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Any

from core.schemas import Output

FEISHU_BASE = "https://open.feishu.cn/open-apis"

_SKILLS_ENV = os.path.expanduser("~/.pikiloom/skills.env")


def _from_skills_env(name: str) -> str:
    try:
        with open(_SKILLS_ENV) as f:
            for line in f:
                s = line.strip()
                if s.startswith(f"{name}=") and not s.startswith("#"):
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_feishu_cred(name: str, override: str | None = None) -> str:
    """Resolve a Feishu credential, preferring ``~/.pikiloom/skills.env`` over the
    ambient process env.

    This deliberately inverts the usual env-first order **for the Feishu keys
    only**: a pikiloom host injects its OWN bot's ``FEISHU_APP_ID`` /
    ``FEISHU_APP_SECRET`` into the environment, and that bot is a different app
    (different open_id space, no ``docx:document`` scope) than the
    content-publishing app you want this sink to use. So the app in your
    gitignored ``skills.env`` must win over the ambient one.

    Order: explicit arg → ``TECH_INTEL_<name>`` env (dedicated override) →
    ``skills.env`` → generic ``<name>`` env (last-resort, for a clean host)."""
    if override:
        return override
    dedicated = os.getenv(f"TECH_INTEL_{name}", "")
    if dedicated:
        return dedicated
    in_file = _from_skills_env(name)
    if in_file:
        return in_file
    return os.getenv(name, "")


# ── Markdown → Feishu blocks ───────────────────────────────────────────────────


def _parse_inline(text: str) -> list[dict]:
    """Inline formatting: ``**bold**``, ``[text](url)``, and plain runs."""
    elements: list[dict] = []
    pattern = re.compile(r"\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            plain = text[last : m.start()]
            if plain:
                elements.append({"text_run": {"content": plain, "text_element_style": {}}})
        if m.group(1) is not None:
            elements.append({"text_run": {"content": m.group(1), "text_element_style": {"bold": True}}})
        else:
            elements.append(
                {"text_run": {"content": m.group(2), "text_element_style": {"link": {"url": m.group(3)}}}}
            )
        last = m.end()
    if last < len(text):
        tail = text[last:]
        if tail:
            elements.append({"text_run": {"content": tail, "text_element_style": {}}})
    if not elements:
        elements.append({"text_run": {"content": text, "text_element_style": {}}})
    return elements


def _text_block(block_type: int, key: str, elements: list[dict]) -> dict:
    return {"block_type": block_type, key: {"elements": elements}}


def md_to_feishu_blocks(md: str) -> list[dict]:
    """Convert the report Markdown to a Feishu doc ``block`` list.

    Covers what the report actually uses: H1–H3, divider, bullet / ordered lists,
    paragraphs, and inline bold / links. Lines inside a paragraph are joined with
    ``\\n`` into one block (Feishu renders that as a soft break; separate paragraph
    blocks would swallow the breaks)."""
    blocks: list[dict] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if re.match(r"^-{3,}\s*$", stripped):
            blocks.append({"block_type": 22, "divider": {}})
            i += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            bt, key = {1: (3, "heading1"), 2: (4, "heading2"), 3: (5, "heading3")}[len(heading.group(1))]
            blocks.append(_text_block(bt, key, _parse_inline(heading.group(2))))
            i += 1
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            blocks.append(_text_block(12, "bullet", _parse_inline(bullet.group(1))))
            i += 1
            continue
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ordered:
            blocks.append(_text_block(13, "ordered", _parse_inline(ordered.group(1))))
            i += 1
            continue
        # paragraph: gather until a blank or a special line
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or re.match(r"^(#{1,3}\s|[-*]\s|\d+[.)]\s|-{3,})", nxt):
                break
            para.append(nxt)
            i += 1
        blocks.append(_text_block(2, "text", _parse_inline("\n".join(para))))
    return blocks


# ── publisher ──────────────────────────────────────────────────────────────────


class FeishuPublisher:
    """Create a Feishu doc from the report Markdown and DM an interactive card.

    Credentials resolve from (first hit wins) the constructor args → env →
    ``~/.pikiloom/skills.env``: ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET`` /
    ``FEISHU_RECEIVE_ID``. With any missing it skips cleanly (returns
    ``{"ok": False, "skipped": ...}``) rather than raising — publish is non-fatal.
    """

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        receive_id: str | None = None,
        folder_token: str = "",
        title: str = "Tech-Intel Report",
        card_template: str = "blue",
        base_url: str = FEISHU_BASE,
        timeout: int = 30,
    ) -> None:
        self.app_id = resolve_feishu_cred("FEISHU_APP_ID", app_id)
        self.app_secret = resolve_feishu_cred("FEISHU_APP_SECRET", app_secret)
        self.receive_id = resolve_feishu_cred("FEISHU_RECEIVE_ID", receive_id)
        self.folder_token = folder_token
        self.title = title
        self.card_template = card_template
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}

    # ── auth ──
    def _token(self) -> str:
        now = time.time()
        if self._token_cache["token"] and now < self._token_cache["expires_at"]:
            return self._token_cache["token"]
        import requests

        resp = requests.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=min(self.timeout, 10),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu tenant_access_token failed: {data}")
        self._token_cache["token"] = data["tenant_access_token"]
        self._token_cache["expires_at"] = now + data.get("expire", 7200) - 100
        return self._token_cache["token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # ── doc + card ──
    def _create_doc(self, title: str) -> tuple[str, str]:
        import requests

        body: dict[str, Any] = {"title": title}
        if self.folder_token:
            body["folder_token"] = self.folder_token
        resp = requests.post(
            f"{self.base_url}/docx/v1/documents", headers=self._headers(), json=body, timeout=self.timeout
        )
        if not resp.ok:
            raise RuntimeError(f"feishu create doc HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu create doc failed: {data}")
        doc_id = data["data"]["document"]["document_id"]
        return doc_id, f"https://feishu.cn/docx/{doc_id}"

    def _write_blocks(self, doc_id: str, blocks: list[dict]) -> None:
        import requests

        for start in range(0, len(blocks), 50):  # Feishu caps children at 50/call
            batch = blocks[start : start + 50]
            resp = requests.post(
                f"{self.base_url}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
                "?document_revision_id=-1",
                headers=self._headers(),
                json={"children": batch, "index": 0 if start == 0 else -1},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"feishu write blocks failed: {data}")

    def _send_card(self, title: str, summary: str, doc_url: str) -> None:
        import requests

        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": self.card_template},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": summary}},
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "打开文档"},
                            "type": "primary",
                            "url": doc_url,
                        }
                    ],
                },
            ],
        }
        resp = requests.post(
            f"{self.base_url}/im/v1/messages?receive_id_type=open_id",
            headers=self._headers(),
            json={"receive_id": self.receive_id, "msg_type": "interactive", "content": json.dumps(card)},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"feishu send message failed: {data}")

    # ── Publisher protocol ──
    def publish(self, *, report_md: str, outputs: list[Output], run_id: str) -> dict[str, Any]:
        if not all([self.app_id, self.app_secret, self.receive_id]):
            return {
                "ok": False,
                "sink": "feishu",
                "skipped": "missing FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_RECEIVE_ID",
            }
        title = f"{self.title}（{datetime.now().strftime('%Y-%m-%d %H:%M')}）"
        doc_id, doc_url = self._create_doc(title)
        blocks = md_to_feishu_blocks(report_md)
        if blocks:
            self._write_blocks(doc_id, blocks)
        summary = "\n".join([ln.strip() for ln in report_md.split("\n") if ln.strip()][:3])
        self._send_card(title, summary, doc_url)
        return {"ok": True, "sink": "feishu", "document_id": doc_id, "doc_url": doc_url}
