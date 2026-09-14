"""The iCalendar reader and writer the calendar slice depends on.

A mistake here would not fail loudly. It would make a vulnerable server
look fixed, or a fixed one look vulnerable, so the parts that decide that
are pinned down with the exact inputs that matter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vikunja_qa.domain import icalendar

HOSTILE = "innocent\r\nSUMMARY:forged\r\nX-INJECTED:yes"


class TestReading:
    def test_folded_lines_are_joined_whatever_the_line_break(self) -> None:
        document = "SUMMARY:a long\r\n  title\nDESCRIPTION:x\n\ty"

        assert icalendar.content_lines(document) == ["SUMMARY:a long title", "DESCRIPTION:xy"]

    def test_the_value_starts_at_the_first_colon_outside_quotes(self) -> None:
        line = 'ATTENDEE;CN="Doe; John";DIR="http://x/a:b":mailto:j@example.com'

        parsed = icalendar.parse_line(line)

        assert parsed.name == "ATTENDEE"
        assert parsed.parameters == {"CN": "Doe; John", "DIR": "http://x/a:b"}
        assert parsed.value == "mailto:j@example.com"

    @pytest.mark.parametrize(
        ("escaped", "text"),
        [
            ("a\\nb", "a\nb"),
            ("a\\Nb", "a\nb"),
            ("a\\;b\\,c", "a;b,c"),
            ("back\\\\slash", "back\\slash"),
            ("\\\\n", "\\n"),
        ],
    )
    def test_text_escapes_are_undone(self, escaped: str, text: str) -> None:
        assert icalendar.unescape_text(escaped) == text

    def test_an_escaped_injection_stays_one_property(self) -> None:
        """The case the CVE regression rests on: the forged names are still
        in the body, and the parser must not count them as properties."""
        document = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VTODO\n"
            f"SUMMARY:{icalendar.escape_text(HOSTILE)}\n"
            "END:VTODO\n"
            "END:VCALENDAR\n"
        )
        assert "X-INJECTED" in document

        (todo,) = icalendar.parse(document).children("VTODO")

        assert todo.all("X-INJECTED") == []
        assert len(todo.all("SUMMARY")) == 1
        assert todo.text_of("SUMMARY") == "innocent\nSUMMARY:forged\nX-INJECTED:yes"

    def test_an_unescaped_injection_is_seen_as_forged_properties(self) -> None:
        """And the converse, so the check can fail at all."""
        document = f"BEGIN:VCALENDAR\nBEGIN:VTODO\nSUMMARY:{HOSTILE}\nEND:VTODO\nEND:VCALENDAR\n"

        (todo,) = icalendar.parse(document).children("VTODO")

        assert len(todo.all("SUMMARY")) == 2
        assert todo.first("X-INJECTED") is not None

    def test_bytes_are_read_as_utf8_whatever_a_header_claimed(self) -> None:
        document = "BEGIN:VCALENDAR\nBEGIN:VTODO\nSUMMARY:отчёт\nEND:VTODO\nEND:VCALENDAR\n"

        (todo,) = icalendar.parse(document.encode("utf-8")).children("VTODO")

        assert todo.text_of("SUMMARY") == "отчёт"

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param("BEGIN:VCALENDAR\nBEGIN:VTODO\nEND:VCALENDAR\n", id="mismatched-end"),
            pytest.param("BEGIN:VCALENDAR\nSUMMARY:x\n", id="never-closed"),
            pytest.param("SUMMARY:x\n", id="property-outside-component"),
            pytest.param(
                "BEGIN:VCALENDAR\nno colon here\nEND:VCALENDAR\n", id="line-without-value"
            ),
            pytest.param("", id="empty"),
        ],
    )
    def test_malformed_documents_are_refused_rather_than_half_read(self, document: str) -> None:
        with pytest.raises(icalendar.ICalendarError):
            icalendar.parse(document)


class TestWriting:
    @pytest.mark.parametrize(
        "text",
        [HOSTILE, "a;b,c\\d", "line one\nline two", "trailing backslash\\", "plain"],
    )
    def test_escaping_round_trips(self, text: str) -> None:
        expected = text.replace("\r\n", "\n")

        assert icalendar.unescape_text(icalendar.escape_text(text)) == expected

    def test_folding_counts_octets_and_never_splits_a_character(self) -> None:
        line = "SUMMARY:" + "Проверить отчёт ✓ " * 12

        folded = icalendar.fold(line)

        pieces = folded.split("\r\n")
        assert len(pieces) > 1, "a line this long must be folded"
        assert all(len(piece.encode("utf-8")) <= icalendar.FOLD_AT_OCTETS for piece in pieces)
        assert all(piece.startswith(" ") for piece in pieces[1:])
        assert icalendar.content_lines(folded) == [line]

    def test_a_written_todo_reads_back_as_written(self) -> None:
        due = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)

        document = icalendar.todo("uid-1", HOSTILE, due=due)

        assert all(line.endswith("\r") for line in document.split("\n")[:-1]), (
            "content lines must end in CRLF when written"
        )
        (written,) = icalendar.parse(document).children("VTODO")
        assert written.text_of("UID") == "uid-1"
        assert written.text_of("SUMMARY") == HOSTILE.replace("\r\n", "\n")
        due_property = written.first("DUE")
        assert due_property is not None
        assert icalendar.parse_utc(due_property.value) == due


#: A lone surrogate, built rather than written: a source file holding one
#: cannot itself be saved as UTF-8, which is the whole point of the case.
LONE_SURROGATE = chr(0xD800)


def test_a_line_that_cannot_be_written_as_utf8_is_refused_by_name() -> None:
    """Found by a property test that left surrogates in its alphabet.

    A lone surrogate is not a character and no UTF-8 decode produces one, so
    it cannot arrive inside a document. It can arrive in JSON: `json.loads`
    hands back this character for the escape sequence without complaint, so a
    server can put one in a task title and a test can carry it here. What
    happened then was a UnicodeEncodeError thrown from the middle of the
    folding loop, saying nothing about what had gone wrong or where it came
    from.
    """
    with pytest.raises(icalendar.ICalendarError, match="cannot be written as UTF-8"):
        icalendar.fold(f"a title with {LONE_SURROGATE} in it")
