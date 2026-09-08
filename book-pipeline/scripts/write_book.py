"""
Stage 2: draft a full manuscript from a chosen topic, using the prompt chain in
prompts/book_prompts.md against the Claude API.

Output: output/<date>-<slug>/manuscript.docx plus manuscript.json (structured chapters,
for generate_cover.py and kdp_prepare.py to reuse title/blurb/keywords).
"""
import argparse
import json
import os
import re

import anthropic
import yaml
from docx import Document

MODEL = "claude-sonnet-5"
PROMPTS_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "book_prompts.md")


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int = 4000) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def draft_book(client: anthropic.Anthropic, topic: dict, settings: dict) -> dict:
    audience = topic.get("audience", "general readers new to the subject")

    toc_prompt = (
        f"Topic: {topic['topic']}\n"
        f"Write a book title and a full table of contents (parts, chapters, and 3-5 "
        f"bullet sub-points per chapter) for a nonfiction book on this topic, aimed at "
        f"{audience}. Respond as JSON: "
        '{"title": str, "parts": [{"part_title": str, "chapters": '
        '[{"chapter_title": str, "sub_points": [str, ...]}]}]}'
    )
    toc_raw = call_claude(client, toc_prompt)
    toc = json.loads(toc_raw)

    chapters = []
    chapter_num = 0
    for part in toc["parts"]:
        for ch in part["chapters"]:
            chapter_num += 1
            body_prompt = (
                f"Write {settings['book']['chapter_word_count']} words for the topic "
                f"below. Acting as an experienced expert in this field. Use an "
                f"easy-to-understand tone. Give real-life examples.\n"
                f"This topic is in \"{toc['title']}\", {part['part_title']}\n"
                f"Chapter {chapter_num}: {ch['chapter_title']}\n"
                f"Sub-points to cover: {', '.join(ch['sub_points'])}"
            )
            body = call_claude(client, body_prompt, max_tokens=3000)
            chapters.append({"number": chapter_num, "title": ch["chapter_title"], "body": body})

    intro = call_claude(client, f"Write a 500-word introduction for the book below:\n{toc_raw}")
    back_cover = call_claude(
        client,
        f"Write 200 words for the back cover of this book: {toc['title']}",
    )
    author_bio = call_claude(
        client,
        f"Dai Tran is an experienced professional in this field. Write 100 words "
        f"introducing the author of the book: {settings['book']['author_name']}",
    )
    keywords_raw = call_claude(
        client,
        f"List 7 KDP keywords/phrases from the book below, optimized for Amazon search, "
        f"as a JSON array of strings: {toc['title']} — {toc_raw}",
    )
    keywords = json.loads(keywords_raw)

    return {
        "title": toc["title"],
        "toc": toc,
        "intro": intro,
        "chapters": chapters,
        "back_cover": back_cover,
        "author_bio": author_bio,
        "keywords": keywords,
    }


def write_docx(book: dict, out_dir: str):
    doc = Document()
    doc.add_heading(book["title"], level=0)
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph(book["intro"])
    for ch in book["chapters"]:
        doc.add_heading(f"Chapter {ch['number']}: {ch['title']}", level=1)
        doc.add_paragraph(ch["body"])
    doc.save(os.path.join(out_dir, "manuscript.docx"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-file", required=True, help="YAML file from trend_research.py")
    parser.add_argument("--topic-index", type=int, default=0)
    args = parser.parse_args()

    with open(args.topic_file) as f:
        topics = yaml.safe_load(f)
    topic = topics[args.topic_index]

    settings_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    with open(settings_path) as f:
        settings = yaml.safe_load(f)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    book = draft_book(client, topic, settings)

    slug = slugify(book["title"])
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output", f"{slug}")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "manuscript.json"), "w") as f:
        json.dump(book, f, indent=2)
    write_docx(book, out_dir)
    print(f"Draft written to {out_dir}")


if __name__ == "__main__":
    main()
