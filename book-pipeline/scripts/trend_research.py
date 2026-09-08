"""
Stage 1: find and score candidate book topics.

Sources (TODO — each is a stub until the corresponding API key is wired up in .env):
  - Google Trends (pytrends) — rising search interest per niche keyword.
  - Amazon Best Sellers / Movers & Shakers in the target categories, via the
    Product Advertising API (AMAZON_PAAPI_*) or SerpApi as a fallback.
  - Your own catalog (Drive "Writing Books" folder) — to avoid duplicating a topic
    you've already published.

Output: a ranked list of {topic, niche, rationale, est_demand_score} dicts, written to
output/<date>-topics.yaml for write_book.py to consume.
"""
import argparse
import datetime
import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "niches.yaml")


def load_niches():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_trending_for_niche(niche: dict) -> list[dict]:
    """TODO: replace with real pytrends + Amazon Best Sellers calls."""
    raise NotImplementedError(
        "Wire up pytrends and Amazon PA-API / SerpApi calls here. "
        "Stub intentionally raises so a scheduled run fails loudly instead of "
        "silently producing a fake 'trending topic'."
    )


def score_and_dedupe(candidates: list[dict], published_catalog: list[str]) -> list[dict]:
    """TODO: score by demand signal, filter anything near-duplicate to published_catalog
    (use e.g. embedding similarity once ANTHROPIC_API_KEY is available)."""
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-only", action="store_true",
                         help="Just scan Drive 'Writing Books' folder and print detected "
                              "titles, to help fill in config/niches.yaml:published_catalog.")
    args = parser.parse_args()

    if args.catalog_only:
        print("TODO: connect Google Drive folder scan here (list Doc/DOCX titles under "
              "'Writing Books'), then paste results into config/niches.yaml.")
        return

    config = load_niches()
    all_candidates = []
    for niche in config["niches"]:
        all_candidates.extend(fetch_trending_for_niche(niche))

    ranked = score_and_dedupe(all_candidates, config.get("published_catalog", []))

    today = datetime.date.today().isoformat()
    out_path = os.path.join(os.path.dirname(__file__), "..", "output", f"{today}-topics.yaml")
    with open(out_path, "w") as f:
        yaml.safe_dump(ranked, f)
    print(f"Wrote {len(ranked)} candidate topics to {out_path}")


if __name__ == "__main__":
    main()
