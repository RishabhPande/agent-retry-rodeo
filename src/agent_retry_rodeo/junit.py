"""JUnit-compatible directional regression evidence, not adapter pass/fail results."""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

# XML 1.0 cannot represent these characters, even when entity-escaped.
_INVALID_XML = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _text(value: object) -> str:
    return _INVALID_XML.sub("\ufffd", str(value))


def render_junit(comparison: dict) -> str:
    """Render the output of compare(), with one test per matching scenario/seed.

    A passing test means no directional regression, not that the adapter solved
    the case. Do not include adapter traces, commands, errors or credentials.
    """
    cases = comparison["cases"]
    failures = sum(bool(case["regressions"]) for case in cases)
    suite = ET.Element("testsuite", name="retry-rodeo directional regressions",
                       tests=str(len(cases)), failures=str(failures), errors="0")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="scope", value=_text(comparison["scope"]))
    ET.SubElement(properties, "property", name="passing_case_meaning",
                  value="No directional regression. Unchanged failures can pass this comparison.")
    for case in cases:
        test = ET.SubElement(suite, "testcase", classname="retry_rodeo.regression",
                             name=_text(f"{case['scenario_id']} [seed={case['seed']}]"))
        if case["regressions"]:
            message = ", ".join(case["regressions"])
            failure = ET.SubElement(test, "failure", type="DirectionalRegression",
                                    message=_text(message))
            failure.text = _text(message)
    ET.indent(suite, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"
