from __future__ import annotations

import json


def render(document):
    return json.dumps(
        {
            "report_id": document.report_id,
            "sections": [
                {"section_id": section.section_id, "data": section.data}
                for section in document.sections
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
