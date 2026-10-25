"""DEMO-ONLY scripted browser for the full-loop runner.

Drives the real company pages over the public HTTPS origin, exactly like a
person in a browser: it GETs each page, reuses the rendered form fields
(including CSRF tokens and hidden revisions), fills in only what a person would
type and POSTs back with the page's Origin. Authenticator codes come from each
persona's enrolled TOTP seed, waiting for a fresh 30-second window so a code is
never reused.
"""

import http.cookiejar
import re
import time
from base64 import b32decode
from html import unescape
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from django_otp.oath import TOTP


class Forms(HTMLParser):
    """Rendered fields/options, as a browser would submit them."""

    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.select = self.textarea = self.option = None
        self.multiple = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "values": {}, "options": {}}
            self.forms.append(self.current)
        if self.current is None:
            return
        if tag == "input" and attrs.get("name"):
            name, kind = attrs["name"], attrs.get("type")
            value = attrs.get("value", "on" if kind in ("checkbox", "radio") else "")
            if kind in ("checkbox", "radio"):
                self.current["options"].setdefault(name, []).append((value, ""))
                if "checked" in attrs:
                    self.current["values"].setdefault(name, []).append(value)
            elif kind in ("submit", "button"):
                return
            else:
                previous = self.current["values"].get(name)
                self.current["values"][name] = value if previous is None else (
                    previous + [value] if isinstance(previous, list) else [previous, value])
        elif tag == "select":
            self.select = attrs["name"]
            self.current["options"][self.select] = []
            self.multiple = "multiple" in attrs
        elif tag == "option" and self.select:
            self.option = attrs.get("value", "")
            self.current["options"][self.select].append((self.option, ""))
            if "selected" in attrs:
                if self.multiple:
                    self.current["values"].setdefault(self.select, []).append(self.option)
                else:
                    self.current["values"][self.select] = self.option
            elif not self.multiple and self.select not in self.current["values"]:
                self.current["values"][self.select] = self.option
        elif tag == "textarea":
            self.textarea = attrs["name"]
            self.current["values"][self.textarea] = ""

    def handle_data(self, data):
        if self.current and self.textarea:
            self.current["values"][self.textarea] += data
        if self.current and self.select and self.option is not None:
            value, label = self.current["options"][self.select][-1]
            self.current["options"][self.select][-1] = (value, label + data)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None
        elif tag == "select":
            self.select = self.option = None
        elif tag == "option":
            self.option = None
        elif tag == "textarea":
            self.textarea = None

    def containing(self, field):
        for form in self.forms:
            if field in form["values"] or field in form["options"]:
                return form
        raise LookupError(f"No rendered form contains {field!r}.")


def text_of(html):
    """Visible page text, for log lines and assertions (no markup)."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


class Browser:
    def __init__(self, origin, label):
        self.origin = origin
        self.label = label
        self.jar = http.cookiejar.CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.jar))
        self.authenticator = None
        self.last_window = None

    def _open(self, request):
        request.add_header("User-Agent", "tarkado-demo-runner/1")
        try:
            with self.client.open(request, timeout=90) as response:
                return SimpleNamespace(status=response.status, html=response.read().decode(), url=response.geturl(),
                                       path=response.geturl().removeprefix(self.origin))
        except HTTPError as error:
            body = error.read().decode(errors="replace")
            error.close()
            return SimpleNamespace(status=error.code, html=body, url=error.geturl() if hasattr(error, "geturl") else "",
                                   path=(error.geturl() or "").removeprefix(self.origin))

    def get(self, path):
        return self._open(Request(self.origin + path))

    def submit(self, path, values, field, *, page=None, expect=(200,)):
        page = page or self.get(path)
        form = Forms(page.html).containing(field)
        data = dict(form["values"])
        data.update(values)
        target = form["action"] or path
        if not target.startswith("/"):
            target = path
        request = Request(self.origin + target, data=urlencode(data, doseq=True).encode())
        request.add_header("Origin", self.origin)
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        result = self._open(request)
        if result.status not in expect:
            raise RuntimeError(f"{self.label}: POST {target} returned {result.status}: {text_of(result.html)[:600]}")
        return result

    def enroll(self, seed):
        self.authenticator = TOTP(b32decode(seed), 30, 0, 6, 0)

    def code(self):
        """A fresh authenticator code: never reuse a 30-second window."""
        while True:
            self.authenticator.time = time.time()
            window = self.authenticator.t()
            if window != self.last_window:
                self.last_window = window
                return str(self.authenticator.token()).zfill(6)
            time.sleep(1)
