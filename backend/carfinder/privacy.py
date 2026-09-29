from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w+])(?:(?:\+|00)381[\s/.-]*(?:\(0\)[\s/.-]*)?|0)\d(?:[\s/.-]?\d){6,10}(?!\w)")


def redact_contact_details(value: str) -> str:
    value = _EMAIL.sub("[email]", value)

    def replace_phone(match: re.Match[str]) -> str:
        return "[phone]" if sum(char.isdigit() for char in match.group(0)) >= 9 else match.group(0)

    return _PHONE.sub(replace_phone, value)
