"""Just enough of RFC 5545 to read and write what the calendar door speaks.

Parsed by the rules rather than by searching the text, and the difference
is the whole point. A title carrying `\\r\\nX-INJECTED:yes` comes back from a
correct server as one escaped value that still contains the characters
`X-INJECTED`. Searching the body for them calls a fixed server broken; only
unfolding the content lines and splitting each into name and value tells a
real property from text that merely looks like one.

Deliberately partial: content lines, folding, parameters, TEXT escaping and
the component tree. Recurrence, time zones and value types beyond TEXT and
UTC date-times are not read, because nothing here asks about them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: RFC 5545 §3.1: lines longer than this many octets are folded.
FOLD_AT_OCTETS = 75

#: RFC 5545 §3.3.5, the UTC form: 19980119T070000Z.
UTC_DATE_TIME = "%Y%m%dT%H%M%SZ"


class ICalendarError(ValueError):
    pass


# --- reading ----------------------------------------------------------------


@dataclass(frozen=True)
class Property:
    """One content line: `NAME;PARAM=value:VALUE`."""

    name: str
    value: str
    parameters: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The value read as TEXT, with its escapes undone."""
        return unescape_text(self.value)


@dataclass
class Component:
    """`BEGIN:NAME` ... `END:NAME`, with its properties and subcomponents."""

    name: str
    properties: list[Property] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)

    def all(self, name: str) -> list[Property]:
        wanted = name.upper()
        return [prop for prop in self.properties if prop.name == wanted]

    def first(self, name: str) -> Property | None:
        found = self.all(name)
        return found[0] if found else None

    def text_of(self, name: str) -> str | None:
        prop = self.first(name)
        return prop.text if prop is not None else None

    def children(self, name: str) -> list[Component]:
        wanted = name.upper()
        return [child for child in self.components if child.name == wanted]

    def walk(self) -> Iterator[Component]:
        yield self
        for child in self.components:
            yield from child.walk()


def parse(document: str | bytes) -> Component:
    """The top-level component of an iCalendar stream.

    Bytes are decoded as UTF-8, which RFC 5545 §3.1.4 makes the default. That
    matters in practice: a response labelled `text/calendar` with no charset
    is decoded as ISO-8859-1 by HTTP libraries following the older HTTP rule,
    and every non-Latin title turns to noise.
    """
    text = document.decode("utf-8") if isinstance(document, bytes) else document
    stack: list[Component] = []
    root: Component | None = None

    for line in content_lines(text):
        prop = parse_line(line)
        if prop.name == "BEGIN":
            component = Component(prop.value.upper())
            if stack:
                stack[-1].components.append(component)
            elif root is None:
                root = component
            else:
                raise ICalendarError(f"a second top-level component begins: {prop.value}")
            stack.append(component)
        elif prop.name == "END":
            if not stack or stack[-1].name != prop.value.upper():
                open_name = stack[-1].name if stack else "nothing"
                raise ICalendarError(f"END:{prop.value} closes {open_name}")
            stack.pop()
        elif stack:
            stack[-1].properties.append(prop)
        else:
            raise ICalendarError(f"a property outside any component: {line!r}")

    if root is None:
        raise ICalendarError("no component in the document")
    if stack:
        raise ICalendarError(f"{stack[-1].name} is never closed")
    return root


def content_lines(text: str) -> list[str]:
    """Unfolded content lines.

    Accepts a bare LF as well as the CRLF the standard requires, because
    servers emit both, and reading is not where conformance is judged.
    """
    unfolded: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        elif raw:
            unfolded.append(raw)
    return unfolded


def parse_line(line: str) -> Property:
    """Split one unfolded line into name, parameters and value.

    The value starts at the first colon outside a quoted parameter value;
    everything after it, colons included, is the value.
    """
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:index], line[index + 1 :]
            break
    else:
        raise ICalendarError(f"a content line with no value: {line!r}")

    name, *raw_parameters = _split_outside_quotes(head, ";")
    if not name:
        raise ICalendarError(f"a content line with no name: {line!r}")
    parameters = {}
    for raw in raw_parameters:
        key, _, parameter_value = raw.partition("=")
        parameters[key.upper()] = parameter_value.strip('"')
    return Property(name=name.upper(), value=value, parameters=parameters)


def _split_outside_quotes(text: str, separator: str) -> list[str]:
    """A quoted parameter value may hold the separator itself: CN="Doe; John"."""
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        if char == separator and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def unescape_text(value: str) -> str:
    """RFC 5545 §3.3.11, reversed: `\\n` and `\\N` are newlines, and a
    backslash before `\\`, `;` or `,` stands for that character."""
    out: list[str] = []
    chars = iter(value)
    for char in chars:
        if char != "\\":
            out.append(char)
            continue
        following = next(chars, "")
        out.append("\n" if following in ("n", "N") else following)
    return "".join(out)


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, UTC_DATE_TIME).replace(tzinfo=UTC)


# --- writing ----------------------------------------------------------------


def escape_text(value: str) -> str:
    """RFC 5545 §3.3.11. The backslash goes first, so the escapes this adds
    are not escaped again."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(UTC_DATE_TIME)


def fold(line: str) -> str:
    """Fold one content line at 75 octets without splitting a character.

    Octets rather than characters, as the standard counts them: a Cyrillic
    title is twice as long on the wire as it looks.
    """
    pieces: list[str] = []
    current = ""
    budget = FOLD_AT_OCTETS
    for char in line:
        if len((current + char).encode("utf-8")) > budget:
            pieces.append(current)
            current = char
            budget = FOLD_AT_OCTETS - 1  # the continuation's leading space counts
        else:
            current += char
    pieces.append(current)
    return "\r\n ".join(pieces)


def todo(
    uid: str,
    summary: str,
    *,
    due: datetime | None = None,
    stamped: datetime | None = None,
    product: str = "-//vikunja-qa//tests//EN",
) -> str:
    """A VCALENDAR holding one VTODO, as a CalDAV client would send it."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{product}",
        "BEGIN:VTODO",
        f"UID:{escape_text(uid)}",
        f"DTSTAMP:{format_utc(stamped or datetime.now(UTC))}",
        f"SUMMARY:{escape_text(summary)}",
    ]
    if due is not None:
        lines.append(f"DUE:{format_utc(due)}")
    lines += ["END:VTODO", "END:VCALENDAR"]
    return "".join(fold(line) + "\r\n" for line in lines)
