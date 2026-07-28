"""Project-local exposure_analyzer v1 example."""

from qlibx.reporting import AnalysisSection


def analyze(envelope, payload):
    gross = float(payload.abs().sum().sum())
    return AnalysisSection(
        "local_exposure",
        "1",
        (envelope.artifact_id,),
        {"gross": gross},
    )
