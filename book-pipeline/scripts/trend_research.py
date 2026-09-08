"""
Stage 1: find and score candidate book topics.

Sources:
  - Google Trends (pytrends) — no API key required. For each niche keyword, pulls
    12-week interest-over-time (for a growth score) and "rising" related queries
    (for concrete, specific topic candidates rather than just the seed keyword).
  - Amazon Best Sellers / your Drive catalog: TODO, gated on AMAZON_PAAPI_* /
    SERPAPI_KEY / Drive access — see fetch_amazon_bestsellers() and
    trend_research.py --catalog-only. Not required for a Google-Trends-only run.

Output: a ranked list of {topic, niche, rationale, est_demand_score} dicts, written to
output/<date>-topics.yaml for write_book.py to consume.
"""
import argparse
import datetime
import os
import time

import yaml
from pytrends.request import TrendReq

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "niches.yaml")

# Being polite to Google's unofficial endpoint avoids 429s on a scheduled run.
REQUEST_DELAY_SECONDS = 2


def load_niches():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _growth_score(interest_df, keyword: str) -> float:
    """Ratio of the last-4-week average interest to the prior-8-week average.
    >1.0 means rising, <1.0 means declining. Falls back to 0.0 if there's not
    enough signal (e.g. a niche keyword with too little search volume)."""
    if interest_df is None or interest_df.empty or keyword not in interest_df:
        return 0.0
    series = interest_df[keyword]
    if len(series) < 6:
        return 0.0
    recent = series.tail(4).mean()
    prior = series.iloc[:-4].tail(8).mean()
    if prior <= 0:
        return 0.0
    return round(recent / prior, 3)


def fetch_trending_for_niche(pytrends: TrendReq, niche: dict) -> list[dict]:
    """For each seed keyword in the niche, pull interest-over-time (growth score) and
    rising related queries (specific topic candidates) from Google Trends."""
    candidates = []
    for keyword in niche["keywords"]:
        try:
            pytrends.build_payload([keyword], timeframe="today 3-m")
            interest = pytrends.interest_over_time()
            score = _growth_score(interest, keyword)

            related = pytrends.related_queries()
            rising = related.get(keyword, {}).get("rising")

            if rising is not None and not rising.empty:
                for _, row in rising.head(5).iterrows():
                    candidates.append({
                        "topic": row["query"],
                        "niche": niche["name"],
                        "seed_keyword": keyword,
                        "est_demand_score": score,
                        "rationale": (
                            f"Rising Google Trends related query under seed "
                            f"'{keyword}' (niche interest growth ratio {score})."
                        ),
                    })
            else:
                # No rising related queries — still surface the seed keyword itself
                # if its own interest is growing, so a niche isn't silently dropped.
                if score > 1.0:
                    candidates.append({
                        "topic": keyword,
                        "niche": niche["name"],
                        "seed_keyword": keyword,
                        "est_demand_score": score,
                        "rationale": f"Seed keyword interest growth ratio {score}, no rising sub-queries.",
                    })
        except Exception as exc:
            print(f"WARN: Google Trends lookup failed for '{keyword}' ({niche['name']}): {exc}")
        time.sleep(REQUEST_DELAY_SECONDS)
    return candidates


def is_near_duplicate(topic: str, published_catalog: list[str]) -> bool:
    topic_words = set(topic.lower().split())
    for published_title in published_catalog:
        published_words = set(published_title.lower().split())
        if not topic_words or not published_words:
            continue
        overlap = len(topic_words & published_words) / len(topic_words | published_words)
        if overlap > 0.5:
            return True
    return False


def score_and_dedupe(candidates: list[dict], published_catalog: list[str]) -> list[dict]:
    deduped = [c for c in candidates if not is_near_duplicate(c["topic"], published_catalog)]
    return sorted(deduped, key=lambda c: c["est_demand_score"], reverse=True)


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
    pytrends = TrendReq(hl="en-US", tz=300)  # tz=300 == US Eastern offset in minutes

    all_candidates = []
    for niche in config["niches"]:
        all_candidates.extend(fetch_trending_for_niche(pytrends, niche))

    ranked = score_and_dedupe(all_candidates, config.get("published_catalog", []))

    if not ranked:
        raise RuntimeError(
            "No candidate topics survived trend research + dedup. Check config/niches.yaml "
            "keywords, or Google Trends may be rate-limiting this run — do not fall back to "
            "a fabricated topic."
        )

    today = datetime.date.today().isoformat()
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}-topics.yaml")
    with open(out_path, "w") as f:
        yaml.safe_dump(ranked, f)
    print(f"Wrote {len(ranked)} candidate topics to {out_path}")
    print(f"Top candidate: {ranked[0]['topic']} (score {ranked[0]['est_demand_score']})")


if __name__ == "__main__":
    main()
