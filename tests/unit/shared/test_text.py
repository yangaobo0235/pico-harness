"""Tests for pico.shared.text."""

from pico.shared.text import clip, middle, tail_clip


def test_clip_keeps_short_text_untouched() -> None:
    """Text within the limit is returned as-is, with no truncation notice."""
    assert clip("readme", 100) == "readme"


def test_clip_appends_the_number_of_dropped_characters() -> None:
    """The truncation notice reports how much was cut, not just that something was cut."""
    result = clip("abcdefghij", 4)

    assert result.startswith("abcd")
    assert "truncated 6 chars" in result


def test_clip_silences_the_notice_when_marker_is_empty() -> None:
    """An empty marker yields a hard cut, used where the suffix would waste budget."""
    assert clip("abcdefghij", 4, marker="") == "abcd"


def test_clip_stringifies_non_text_input() -> None:
    """Tool results and exceptions reach `clip` as objects, so conversion happens here."""
    assert clip(12345, 3).startswith("123")


def test_middle_collapses_newlines_and_keeps_both_ends() -> None:
    """Single-line terminal cells need the head and the tail, joined by an ellipsis."""
    result = middle("first\nsecond\nthird", 14)

    assert "\n" not in result
    assert result.startswith("first")
    assert result.endswith("third")


def test_middle_hard_cuts_when_the_limit_leaves_no_room() -> None:
    """Below four characters both ends cannot be shown, so the head wins."""
    assert middle("abcdef", 3) == "abc"


def test_tail_clip_drops_everything_at_a_zero_budget() -> None:
    """A zero section budget renders nothing rather than a header alone."""
    assert tail_clip("anything", 0) == ""


def test_tail_clip_marks_the_removed_tail() -> None:
    """Section rendering keeps the head and signals the tail was clipped."""
    assert tail_clip("abcdefghij", 7) == "abcd..."
