"""Project-local report_renderer v1 example."""


def render(document):
    return "\n".join(section.section_id for section in document.sections)
