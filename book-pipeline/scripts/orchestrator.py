"""
Nightly entry point (scheduled ~2:00 AM local, see config/settings.yaml). Runs stages
1-5 only. Never calls kdp_upload.py — that stays manual, gated on human review of the
REVIEW.md package this produces.
"""
import datetime
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)


def run(cmd: list[str]):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main():
    today = datetime.date.today().isoformat()

    run([sys.executable, os.path.join(HERE, "trend_research.py")])
    topic_file = os.path.join(HERE, "..", "output", f"{today}-topics.yaml")

    run([sys.executable, os.path.join(HERE, "write_book.py"),
         "--topic-file", topic_file, "--topic-index", "0"])

    # write_book.py names its own output dir from the generated title's slug; find the
    # most recently created manuscript.json to chain into the next stages.
    candidates = glob.glob(os.path.join(HERE, "..", "output", "*", "manuscript.json"))
    latest = max(candidates, key=os.path.getmtime)
    out_dir = os.path.dirname(latest)

    run([sys.executable, os.path.join(HERE, "generate_cover.py"),
         "--manuscript", latest, "--out-dir", out_dir])

    with open(latest) as f:
        book = json.load(f)
    pricing_out = os.path.join(out_dir, "pricing.json")
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, "pricing.py"), "--page-count", "180"],
        check=True, capture_output=True, text=True,
    )
    with open(pricing_out, "w") as f:
        f.write(result.stdout)

    run([sys.executable, os.path.join(HERE, "kdp_prepare.py"),
         "--manuscript", latest, "--pricing", pricing_out])

    print(f"\nDone. Review package: {out_dir}/REVIEW.md")
    # TODO: send a notification (email/Slack/push) pointing at REVIEW.md instead of
    # relying on someone checking the output folder.


if __name__ == "__main__":
    main()
