"""
Stage 5: assemble the human review package. Never touches your live KDP account.

Writes output/<date>-<slug>/REVIEW.md summarizing everything kdp_upload.py would need,
so you can approve/edit before anything goes live.
"""
import argparse
import datetime
import json
import os


def build_review_md(book: dict, pricing: dict, out_dir: str) -> str:
    lines = [
        f"# Review: {book['title']}",
        "",
        f"Generated {datetime.date.today().isoformat()}. Nothing has been published yet.",
        "",
        "## Files in this folder",
        "- `manuscript.docx` — full manuscript",
        "- `cover_front.png`, `cover_back.png` — cover art",
        "",
        "## Metadata for KDP listing",
        f"- **Title**: {book['title']}",
        f"- **Keywords**: {', '.join(book['keywords'])}",
        "",
        "## Back cover copy",
        book["back_cover"],
        "",
        "## Author bio",
        book["author_bio"],
        "",
        "## Pricing recommendation",
        f"- Ebook: ${pricing['ebook']['price']} (royalty ~${pricing['ebook']['royalty_per_unit']}/unit)",
        f"- Paperback: ${pricing['paperback']['price']} (royalty ~${pricing['paperback']['royalty_per_unit']}/unit)",
        f"- Rationale: {pricing['rationale']}",
        "",
        "## Next step",
        "Review the manuscript and covers. If approved, run:",
        "",
        "```",
        f"python scripts/kdp_upload.py --package {out_dir} --confirm",
        "```",
        "",
        "That script is intentionally separate and requires --confirm — it is never run "
        "by the nightly scheduler.",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--pricing", required=True, help="JSON output from pricing.py")
    args = parser.parse_args()

    out_dir = os.path.dirname(args.manuscript)
    with open(args.manuscript) as f:
        book = json.load(f)
    with open(args.pricing) as f:
        pricing = json.load(f)

    review_md = build_review_md(book, pricing, out_dir)
    review_path = os.path.join(out_dir, "REVIEW.md")
    with open(review_path, "w") as f:
        f.write(review_md)
    print(f"Review package ready: {review_path}")


if __name__ == "__main__":
    main()
