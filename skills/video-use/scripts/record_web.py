"""通用 Web 录屏器(Playwright):登录(可选)→ 逐页访问 → webm + 导航时间清单。

产出两件套是后续剪辑的地基:
  - <out>/raw_tour.webm        1080p 录屏(无音轨)
  - <out>/nav_manifest.json    每页 enter/settled/leave 相对视频起点的秒数

经验铸进默认值:
  - SPA 路由切换下 networkidle 秒过,settled≠数据到位;真实骨架屏窗口约 enter 后
    1s+(剪辑时用 compose_narrated 的 load_window 压缩)。
  - 登录成功断言 = 等一个登录后才渲染的元素文本(--ready-text),
    绝不用 wait_for_url(sign-in 同前缀会假通过)。
  - 每页导航后校验未被弹回登录页,弹回即 fail-fast。

用仓库根 .venv 跑(playwright 在那):
    .venv/bin/python record_web.py --base http://127.0.0.1:9000/admin \
      --login-path /sign-in --email a@b.c --password '…' --ready-text Personas \
      --page 'Dashboard=/' --page 'Personas=/personas' --out-dir ~/Desktop/demo
凭据也可走环境变量 RECORD_WEB_EMAIL / RECORD_WEB_PASSWORD(不进 ps)。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser(description="Playwright web tour recorder")
    ap.add_argument("--base", required=True, help="应用根 URL(含挂载前缀)")
    ap.add_argument("--page", action="append", required=True,
                    metavar="TITLE=PATH", help="可重复;TITLE 同时用作侧边栏链接文本")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--linger", type=float, default=6.0, help="每页停留秒数")
    ap.add_argument("--viewport", default="1920x1080")
    ap.add_argument("--login-path", help="如 /sign-in;不给则跳过登录")
    ap.add_argument("--email", default=os.getenv("RECORD_WEB_EMAIL", ""))
    ap.add_argument("--password", default=os.getenv("RECORD_WEB_PASSWORD", ""))
    ap.add_argument("--email-placeholder", default="name@example.com")
    ap.add_argument("--password-placeholder", default="********")
    ap.add_argument("--submit-name", default="Sign in")
    ap.add_argument("--ready-text", help="登录成功后才出现的链接文本(断言用),默认第一个 page 的 TITLE")
    args = ap.parse_args()

    pages = []
    for spec in args.page:
        title, _, path = spec.partition("=")
        if not path:
            ap.error(f"--page 需要 TITLE=PATH 形态: {spec!r}")
        pages.append((title, path))
    ready_text = args.ready_text or pages[0][0]
    width, height = (int(x) for x in args.viewport.split("x"))
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    with sync_playwright() as p:
        # Prefer the system Chrome channel so a global install needs no
        # `playwright install chromium` download; fall back to bundled chromium.
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(out_dir),
            record_video_size={"width": width, "height": height},
        )
        t0 = time.monotonic()
        rel = lambda: round(time.monotonic() - t0, 3)  # noqa: E731
        page = context.new_page()

        if args.login_path:
            if not (args.email and args.password):
                raise SystemExit("登录需要 --email/--password(或 RECORD_WEB_* env)")
            enter = rel()
            page.goto(f"{args.base}{args.login_path}", wait_until="domcontentloaded")
            page.get_by_placeholder(args.email_placeholder).fill(args.email)
            page.get_by_placeholder(args.password_placeholder).fill(args.password)
            time.sleep(1.0)  # 让填好的表单在录像里可见
            submit = rel()
            page.get_by_role("button", name=args.submit_name).click()
            page.get_by_role("link", name=ready_text, exact=True).wait_for(timeout=20000)
            manifest.append({"page": "Login", "enter": enter, "submit": submit})

        for title, path in pages:
            enter = rel()
            already_there = manifest and manifest[-1].get("page") == "Login" and path == "/"
            if not already_there:
                try:
                    link = page.get_by_role("link", name=title, exact=True)
                    link.first.click(timeout=5000)
                except Exception:
                    page.goto(f"{args.base}{path}", wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            if args.login_path and args.login_path in page.url:
                raise SystemExit(f"被弹回登录页(打开 {title} 时)—— 凭据或会话失效")
            settled = rel()
            time.sleep(args.linger)
            manifest.append({"page": title, "enter": enter, "settled": settled, "leave": rel()})
            print(f"[{enter:7.2f}s → {rel():7.2f}s] {title}")

        total = rel()
        video = page.video
        context.close()
        browser.close()
        video_path = Path(video.path())

    final = out_dir / "raw_tour.webm"
    video_path.rename(final)
    (out_dir / "nav_manifest.json").write_text(
        json.dumps({"total": total, "events": manifest}, indent=2, ensure_ascii=False)
    )
    print(f"video: {final}\nmanifest: {out_dir / 'nav_manifest.json'}\ntotal: {total:.1f}s")


if __name__ == "__main__":
    main()
