"""
Stage 4: recommend a KDP list price.

KDP royalty math (verify against current KDP terms before relying on this):
  eBook:
    - 35% royalty tier: any price $0.99-$200.
    - 70% royalty tier: price $2.99-$9.99, AND delivery cost (roughly $0.15/MB of
      file size) is deducted from royalty, AND book must be enrolled appropriately
      (some marketplaces/exclusivity conditions apply -- re-check KDP terms).
  Paperback:
    - Royalty = 60% * list_price - printing_cost. Printing cost is a function of
      page count, trim size, and whether interior is B&W or color (KDP's own
      calculator gives the exact number -- this stub approximates it linearly).

Strategy: maximize *expected* royalty = royalty_per_unit * estimated_conversion_rate,
not raw royalty per unit -- comparable-priced books in the same category are used
as the demand curve proxy.
"""
import argparse
import json


def ebook_royalty(price: float, file_size_mb: float = 3.0) -> float:
    if 2.99 <= price <= 9.99:
        return 0.70 * price - 0.15 * file_size_mb
    return 0.35 * price


def paperback_printing_cost(page_count: int, trim="6x9", color=False) -> float:
    # Linear approximation of KDP's US paperback B&W pricing; replace with the real
    # KDP print-cost calculator lookup before trusting this on a real listing.
    fixed = 0.85
    per_page = 0.012 if not color else 0.07
    return fixed + per_page * page_count


def paperback_royalty(price: float, page_count: int, trim="6x9", color=False) -> float:
    cost = paperback_printing_cost(page_count, trim, color)
    return 0.60 * price - cost


def recommend_price(comparable_prices: list[float], page_count: int, file_size_mb=3.0) -> dict:
    """Grid-search candidate ebook prices in the 70%-tier sweet spot, weighting by how
    close each candidate lands to the category's median comparable price (a proxy for
    conversion — being priced far above comparable titles hurts conversion even though
    royalty/unit is higher)."""
    if not comparable_prices:
        comparable_prices = [7.99]
    median_comp = sorted(comparable_prices)[len(comparable_prices) // 2]

    best = None
    for cents in range(299, 1000, 50):
        price = cents / 100
        royalty = ebook_royalty(price, file_size_mb)
        distance_penalty = abs(price - median_comp) / median_comp
        expected_value = royalty * (1 - min(distance_penalty, 0.9))
        if best is None or expected_value > best["expected_value"]:
            best = {"price": price, "royalty_per_unit": round(royalty, 2),
                    "expected_value": round(expected_value, 3)}

    paperback_price = round(median_comp + 2, 2)  # paperbacks typically price above ebook comps
    return {
        "ebook": best,
        "paperback": {
            "price": paperback_price,
            "royalty_per_unit": round(paperback_royalty(paperback_price, page_count), 2),
        },
        "category_median_comp_price": median_comp,
        "rationale": (
            f"Ebook priced near category median (${median_comp}) to preserve conversion "
            f"while staying in the 70% royalty band. Paperback priced ~$2 above the ebook "
            f"comp median, standard KDP pattern."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparable-prices", nargs="+", type=float, default=[])
    parser.add_argument("--page-count", type=int, default=180)
    args = parser.parse_args()
    result = recommend_price(args.comparable_prices, args.page_count)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
