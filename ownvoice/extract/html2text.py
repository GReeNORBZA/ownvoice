"""Small HTML event stream shared by structural cuts and text rendering."""

import re
from html.parser import HTMLParser

BLOCKS = {"p", "div", "li", "tr", "blockquote", "table", *(f"h{i}" for i in range(1, 7))}
DROP = {"head", "style", "script", "title"}
VOID = {"br", "hr", "img", "meta", "link", "input", "wbr", "area", "base", "embed", "source"}


class Events(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.events.append(("end", tag, {}))

    def handle_data(self, data):
        self.events.append(("text", data, {}))


def normalize(text):
    lines = [re.sub(r"[\t \xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def render(events):
    output, dropped = [], []

    def boundary():
        if output and not output[-1].endswith("\n"):
            output.append("\n")

    for kind, value, attrs in events:
        if kind == "start" and value in DROP:
            dropped.append(value)
        elif kind == "end" and dropped and value == dropped[-1]:
            dropped.pop()
        elif dropped:
            continue
        elif kind == "text":
            # Source-code newlines are HTML whitespace, never paragraph breaks.
            output.append(re.sub(r"\s+", " ", value.replace("\xa0", " ")))
        elif value in BLOCKS:
            boundary()
            if kind == "start" and value == "li":
                output.append("- ")
        elif value == "br" and kind == "start":
            output.append("\n")
        elif value in ("b", "strong"):
            output.append("*")
    return normalize("".join(output))
