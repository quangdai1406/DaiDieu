"""
Stage 6 (MANUAL ONLY): drives the KDP Bookshelf web UI with Playwright to create a new
title from an approved review package.

This is never invoked by the scheduler. It requires --confirm and a package directory
that has already been through human review (kdp_prepare.py's REVIEW.md).

KDP has no public API — this necessarily automates the actual dashboard. Treat it as
fragile: KDP changes their form layout without notice, so expect to update selectors.
Run it once against a throwaway/test title before trusting it on a real one.
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright


def upload(package_dir: str):
    email = os.environ["KDP_EMAIL"]
    password = os.environ["KDP_PASSWORD"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # visible on purpose — supervise this
        page = browser.new_page()
        page.goto("https://kdp.amazon.com/en_US/sign-in")

        # TODO: fill in real selectors — KDP's sign-in and "Create new title" flow.
        # This is a skeleton; do not run against a real book until you've filled in
        # and manually verified every step below.
        raise NotImplementedError(
            "kdp_upload.py is a skeleton. Fill in the actual KDP form selectors and "
            "test against a throwaway title before using this for real."
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, help="output/<date>-<slug> directory")
    parser.add_argument("--confirm", action="store_true",
                         help="Required. Without this flag, the script refuses to run.")
    args = parser.parse_args()

    if not args.confirm:
        print("Refusing to run without --confirm. Review REVIEW.md in the package dir first.")
        sys.exit(1)

    upload(args.package)


if __name__ == "__main__":
    main()
