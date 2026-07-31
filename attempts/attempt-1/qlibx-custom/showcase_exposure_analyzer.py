from __future__ import annotations

from qlibx.reporting import AnalysisSection


def analyze(envelope, payload):
    gross = payload.abs().sum(axis=1)
    net = payload.sum(axis=1)
    return AnalysisSection(
        "local_exposure",
        "1",
        (envelope.artifact_id,),
        {
            "mean_gross": float(gross.mean()),
            "maximum_gross": float(gross.max()),
            "mean_net": float(net.mean()),
        },
    )
