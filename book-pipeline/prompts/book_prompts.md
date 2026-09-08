# Prompt chain

Lifted from `Writing Books/Promt for AI.docx` in your Drive — same shape you've been using
by hand, just templated for `scripts/write_book.py`.

## 1. Title + Table of Contents
```
Topic: {topic}
Write a book title and a full table of contents (parts, chapters, and 3-5 bullet
sub-points per chapter) for a nonfiction book on this topic, aimed at {audience}.
```

## 2. Chapter body
```
Write {word_count} words for the topic below. Acting as an experienced {persona}.
Use an easy-to-understand tone. Give real-life examples{example_source_clause}.
This topic is in "{book_title}", {part_title}
Chapter {chapter_number}: {chapter_title}
Sub-points to cover: {sub_points}
```
`{example_source_clause}` = `, when possible, from {example_source}` if the niche calls
for named case studies (e.g. investing → legendary investors), else omit.

## 3. Book introduction
```
Write a 500-word introduction for the book below:
{full_table_of_contents}
```

## 4. Back cover copy
```
Write 200 words for the back cover of this book:
{book_title} — {one_line_premise}
```

## 5. Author bio
```
{author_bio_seed}
Write 100 words introducing the author of the book: {author_name}
```
`{author_bio_seed}` — keep your own established bio angle per niche, e.g. for
investing/tax titles: "Dai Tran is an experienced real estate investor."

## 6. Keywords
```
List 7 KDP keywords/phrases from the book below, optimized for Amazon search:
{book_title} — {table_of_contents_summary}
```
