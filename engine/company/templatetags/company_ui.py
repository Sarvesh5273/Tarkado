"""Plain-language display without rounding measurements or rendering raw dictionaries."""

from django import template
from django.utils.html import format_html, format_html_join

from engine.privacy import redact_text

register = template.Library()


@register.filter
def known(value):
    if value is None or value == "":
        return "Unknown"
    if type(value) is bool:
        return "Yes" if value else "No"
    return redact_text(str(value))


@register.filter
def words(value):
    return known(value).replace("_", " ")


@register.simple_tag
def metadata(value):
    if isinstance(value, dict):
        return format_html("<dl class=\"metadata\">{}</dl>", format_html_join(
            "", "<dt data-field=\"{}\">{}</dt><dd>{}</dd>", ((key, words(key), metadata(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        if not value:
            return "None recorded"
        return format_html("<ul>{}</ul>", format_html_join("", "<li>{}</li>", ((metadata(item),) for item in value)))
    return format_html("{}", known(value))
