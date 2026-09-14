"""Rules that hold for any input, checked against inputs nobody chose.

Every other test in this suite is an example: someone picked the input and
said what should come back. That only ever checks what its author thought
of, and the inputs an author thinks of are the ones they already had in
mind while writing the code.

These state a rule instead — `unescaping what was escaped gives back what
went in` — and let Hypothesis look for something that breaks it. It tries
hundreds of strings per rule, the awkward ones first: empty, a lone
backslash, a string ending in one, a newline in the middle, a four-byte
emoji, ten thousand characters. When it finds a failure it shrinks it to
the smallest input that still fails, so the report is `'\\\\'` rather than
eight hundred characters of noise.

Aimed where it pays. Escaping is the classic place for this, and not
hypothetically: [CVE-2026-35601] in this very product was a line break in a
title escaping its own content line. Folding is the other, because it
counts octets while Python counts characters. And the rule about
credentials is here because a redaction that holds for the shapes someone
listed is not a redaction.

Stating a rule precisely is itself the exercise, and getting it wrong is
where the value shows. The first version of the escaping rule below was
`unescape(escape(x)) == x`. It is false, and Hypothesis shrank the reason
to a single character: a carriage return. The standard stores a line break
in TEXT as a line feed whichever of the three spellings went in, so the
round trip is exact only up to that — which the rule now says, because it
had to.

The same happened to the rule about credentials, one class down: the first
version put the token beside a generated structure instead of inside it, so
a redaction that looked only at the top level passed it. Both corrections
are left visible rather than tidied away.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from vikunja_qa.contracts.sweep import concrete_path
from vikunja_qa.domain import icalendar
from vikunja_qa.transport.response import ApiResponse

#: No deadline. These run beside the rest of the unit layer on whatever
#: machine happens to be free, and a per-example time limit turns a busy
#: runner into a failure that says nothing about the code.
settings.register_profile("suite", deadline=None, max_examples=300)
settings.load_profile("suite")

#: Text as it arrives from a person: anything they can type, including the
#: characters the standard gives meaning to.
ANY_TEXT = st.text()

#: One content line's worth. No newline, because a newline is what folding
#: and escaping exist to deal with and a raw one is not a content line. And
#: real text, which `codec="utf-8"` is what says so: a lone surrogate is not
#: a character, no UTF-8 decode can produce one, and `fold` refuses one by
#: name rather than failing with a codec error from inside a loop. That
#: boundary was found by leaving this out, and is pinned by an example in
#: test_icalendar.py rather than left to a generator to rediscover.
ONE_LINE = st.text(alphabet=st.characters(codec="utf-8", exclude_characters=chr(13) + chr(10)))


def as_the_standard_stores_it(value: str) -> str:
    """RFC 5545 §3.3.11: a line break in TEXT is stored as a line feed,
    whichever of the three spellings went in."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


class TestEscapingTextSurvivesTheRoundTrip:
    @given(ANY_TEXT)
    def test_what_was_escaped_unescapes_to_what_went_in(self, value: str) -> None:
        assert icalendar.unescape_text(icalendar.escape_text(value)) == as_the_standard_stores_it(
            value
        )

    @given(ANY_TEXT)
    def test_escaping_leaves_no_bare_delimiter(self, value: str) -> None:
        """The point of escaping: after it, a semicolon or a comma in the
        text can no longer be read as the end of a value."""
        escaped = icalendar.escape_text(value)
        for index, char in enumerate(escaped):
            if char in (";", ",", "\n", "\r"):
                preceding = escaped[:index]
                backslashes = len(preceding) - len(preceding.rstrip("\\"))
                assert char not in ("\n", "\r"), f"a raw line break survived at {index}"
                assert backslashes % 2 == 1, f"a bare {char!r} survived at {index}: {escaped!r}"

    @given(ANY_TEXT)
    def test_escaping_twice_is_not_the_same_as_once(self, value: str) -> None:
        """A guard against the obvious mistake of escaping a value that was
        escaped already: it must be visible, not silent."""
        once = icalendar.escape_text(value)
        twice = icalendar.escape_text(once)
        assert icalendar.unescape_text(twice) == as_the_standard_stores_it(once)


class TestFoldingObeysTheOctetLimit:
    @given(ONE_LINE)
    def test_no_folded_line_exceeds_the_limit(self, line: str) -> None:
        """Counted in octets, as the standard counts them. A Cyrillic title
        is twice as long on the wire as it looks, and an emoji four times."""
        for piece in icalendar.fold(line).split("\r\n"):
            assert len(piece.encode("utf-8")) <= icalendar.FOLD_AT_OCTETS, (
                f"{len(piece.encode('utf-8'))} octets in {piece!r}"
            )

    @given(ONE_LINE.filter(lambda line: line and line[0] not in " \t"))
    def test_unfolding_a_folded_line_gives_it_back(self, line: str) -> None:
        assert icalendar.content_lines(icalendar.fold(line)) == [line]

    @given(ONE_LINE)
    def test_folding_never_splits_a_character(self, line: str) -> None:
        """Every piece has to decode on its own, or a title is cut through
        the middle of a character and arrives as noise."""
        for piece in icalendar.fold(line).split("\r\n"):
            piece.encode("utf-8").decode("utf-8")


class TestADocumentSurvivesBeingWrittenAndRead:
    """The end-to-end rule, and the one worth having.

    Escaping, folding, unfolding and unescaping in one line each, over any
    summary a person could type. This is the path CVE-2026-35601 broke.
    """

    @given(
        uid=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1),
        summary=ANY_TEXT,
    )
    def test_a_summary_reads_back_as_it_was_written(self, uid: str, summary: str) -> None:
        document = icalendar.todo(uid=uid, summary=summary)

        parsed = icalendar.parse(document)
        (todo,) = parsed.children("VTODO")

        assert todo.text_of("SUMMARY") == as_the_standard_stores_it(summary)

    @given(summary=ANY_TEXT)
    def test_nothing_a_summary_contains_becomes_a_property(self, summary: str) -> None:
        """The defect itself: a summary must never add properties to the
        component it sits in, whatever it says."""
        document = icalendar.todo(uid="fixed", summary=summary)

        (todo,) = icalendar.parse(document).children("VTODO")

        assert {prop.name for prop in todo.properties} == {"UID", "DTSTAMP", "SUMMARY"}, (
            f"a summary introduced a property: {[p.name for p in todo.properties]}"
        )


class TestCredentialsNeverSurviveIntoTheReport:
    """A redaction that holds for the shapes someone listed is not one.

    Written the wrong way first, and worth keeping the correction visible.
    Version one put the token beside a generated structure rather than
    inside it, so a redaction that only looked at the top level passed —
    and the mutation that proves it did pass. The token has to be buried at
    a depth nobody chose, or the generator is decorating a test it is not
    testing.
    """

    SECRET = "s3cr3t-that-must-not-appear-anywhere"

    @staticmethod
    @st.composite
    def buried(draw: st.DrawFn, secret: str) -> object:
        """A body with a token somewhere inside it, under a few layers of
        whatever else a response might carry.

        Keys that are themselves credential names are kept out. One of
        those above the token would have the whole subtree redacted as a
        string, the secret would be gone, and the test would pass without
        saying anything about depth.
        """
        from vikunja_qa.transport.response import SECRET_FIELDS

        harmless = st.text(min_size=1, max_size=6).filter(
            lambda key: key.lower() not in SECRET_FIELDS
        )
        node: object = {"token": secret}
        for _ in range(draw(st.integers(min_value=0, max_value=5))):
            if draw(st.booleans()):
                node = [draw(st.integers()), node, draw(st.text(max_size=4))]
            else:
                node = {draw(harmless): node, draw(harmless): draw(st.integers())}
        return node

    @given(st.data())
    def test_a_token_is_redacted_however_deeply_it_is_buried(self, data: st.DataObject) -> None:
        body = data.draw(self.buried(self.SECRET))

        described = ApiResponse(
            method="POST",
            url="http://host/api/v1/login",
            status=200,
            headers={},
            body=body,
            elapsed_ms=1.0,
            request_body=body,
        ).describe(max_body=1_000_000)

        assert self.SECRET not in described

    @given(st.data())
    def test_the_rest_of_the_body_still_reaches_the_report(self, data: st.DataObject) -> None:
        """The other half: a redaction that removed everything would pass
        the rule above and make the report useless."""
        marker = "a-value-worth-keeping"
        body = {"context": marker, "buried": data.draw(self.buried(self.SECRET))}

        described = ApiResponse(
            method="POST",
            url="http://host/api/v1/login",
            status=200,
            headers={},
            body=body,
            elapsed_ms=1.0,
        ).describe(max_body=1_000_000)

        assert marker in described


class TestGeneratedPathsAreConcrete:
    @given(
        st.lists(
            st.one_of(
                st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
                st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8).map(
                    "{{{}}}".format
                ),
            ),
            min_size=1,
            max_size=6,
        )
    )
    def test_no_placeholder_reaches_the_product(self, segments: list[str]) -> None:
        """A template the sweep failed to fill would be sent literally, and
        `/projects/{id}` is a request for a project called `{id}`."""
        filled = concrete_path("/" + "/".join(segments))

        assert "{" not in filled
        assert "}" not in filled
