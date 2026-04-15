import re

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="highlight")
def highlight(value, query):
    """
    Highlight matching substring in text with <mark>.
    Safe escaping first, then markup injection only for matches.
    """
    text = "" if value is None else str(value)
    q = "" if query is None else str(query).strip()
    if not q:
        return conditional_escape(text)

    escaped = conditional_escape(text)
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    highlighted = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", str(escaped))
    return mark_safe(highlighted)
