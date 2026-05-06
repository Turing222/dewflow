from backend.services.chunking_service import ChunkingService


def test_split_markdown_tracks_heading_section_path():
    service = ChunkingService(chunk_size=200, chunk_overlap=20)

    chunks = service.split_text(
        "# Guide\n\nIntro text.\n\n## Setup\n\nInstall steps.\n\n### API\n\nCall details.",
        file_suffix=".md",
    )

    assert [chunk["section_path"] for chunk in chunks] == [
        "Guide",
        "Guide / Setup",
        "Guide / Setup / API",
    ]
    assert chunks[2]["content"].startswith("### API")
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1, 2]


def test_split_markdown_keeps_fenced_code_block_together():
    service = ChunkingService(chunk_size=200, chunk_overlap=20)

    chunks = service.split_text(
        "## Example\n\n```python\nprint('hello')\n\nprint('world')\n```\n\nDone.",
        file_suffix=".md",
    )

    assert len(chunks) == 1
    assert "print('hello')\n\nprint('world')" in chunks[0]["content"]
    assert chunks[0]["section_path"] == "Example"


def test_split_text_merges_small_paragraphs():
    service = ChunkingService(chunk_size=200, chunk_overlap=20)

    chunks = service.split_text(
        "first paragraph\n\nsecond paragraph", file_suffix=".txt"
    )

    assert len(chunks) == 1
    assert chunks[0]["content"] == "first paragraph\n\nsecond paragraph"


def test_split_text_falls_back_to_fixed_window_for_long_paragraph():
    service = ChunkingService(chunk_size=200, chunk_overlap=20)

    chunks = service.split_text("x" * 260, file_suffix=".txt")

    assert len(chunks) == 2
    assert chunks[0]["content"] == "x" * 200
    assert chunks[1]["content"] == "x" * 80
