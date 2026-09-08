"""
Stage 3: render front/back cover art as HTML "canvas" and rasterize to KDP's required
trim-size PNGs.

KDP cover requirements (paperback, checked against KDP's published specs — verify
against the current KDP help page before a real submission, these change):
  - Full wraparound cover (front + spine + back) as one PDF/PNG, 300 DPI.
  - Trim size + page count determine spine width (KDP's cover calculator gives the
    exact spine width for a given page count/paper type — call that, don't hardcode).
  - Front cover alone (ebook) 2560x1600px min, 300 DPI, RGB.

This script renders a front-cover template and a back-cover template as standalone HTML
(so it can reuse a Claude-Design-style single-artboard layout), then uses Playwright to
screenshot each artboard at high resolution and Pillow to composite/pad to exact pixel
dimensions.
"""
import argparse
import json
import os

from PIL import Image
from playwright.sync_api import sync_playwright

FRONT_TEMPLATE = """<!doctype html><html><head><style>
  body {{ margin:0; width:1600px; height:2560px; background:{bg_color};
          font-family: Georgia, serif; color:{text_color}; display:flex;
          flex-direction:column; align-items:center; justify-content:center; text-align:center; }}
  h1 {{ font-size:96px; margin:0 60px; }}
  h2 {{ font-size:44px; font-weight:normal; margin-top:20px; opacity:0.85; }}
  .author {{ position:absolute; bottom:80px; font-size:40px; letter-spacing:2px; }}
</style></head><body>
  <h1>{title}</h1>
  <h2>{subtitle}</h2>
  <div class="author">{author}</div>
</body></html>"""

BACK_TEMPLATE = """<!doctype html><html><head><style>
  body {{ margin:0; width:1600px; height:2560px; background:{bg_color};
          font-family: Georgia, serif; color:{text_color}; padding:120px; box-sizing:border-box;
          display:flex; flex-direction:column; justify-content:center; }}
  p {{ font-size:34px; line-height:1.5; }}
  .bio {{ margin-top:60px; font-size:26px; font-style:italic; opacity:0.85; }}
</style></head><body>
  <p>{back_cover_text}</p>
  <p class="bio">{author_bio}</p>
</body></html>"""


def render_html_to_png(html: str, out_path: str, width=1600, height=2560):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html)
        page.screenshot(path=out_path)
        browser.close()


def generate(manuscript_path: str, out_dir: str, bg_color="#1b2a4a", text_color="#f5f0e6"):
    with open(manuscript_path) as f:
        book = json.load(f)

    front_html = FRONT_TEMPLATE.format(
        title=book["title"], subtitle=book.get("subtitle", ""),
        author=book.get("author_name", "Dai Tran"),
        bg_color=bg_color, text_color=text_color,
    )
    back_html = BACK_TEMPLATE.format(
        back_cover_text=book["back_cover"], author_bio=book["author_bio"],
        bg_color=bg_color, text_color=text_color,
    )

    front_path = os.path.join(out_dir, "cover_front.png")
    back_path = os.path.join(out_dir, "cover_back.png")
    render_html_to_png(front_html, front_path)
    render_html_to_png(back_html, back_path)

    # TODO: call KDP's cover calculator (manual lookup — no public API) for exact spine
    # width given final page count, then composite front+spine+back into one wraparound
    # PDF for paperback. Ebook only needs cover_front.png as-is.
    print(f"Wrote {front_path} and {back_path}")
    print("NOTE: paperback wraparound compositing (spine width) still needs the KDP "
          "cover calculator result — not automated, KDP doesn't expose it via API.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    generate(args.manuscript, args.out_dir)


if __name__ == "__main__":
    main()
