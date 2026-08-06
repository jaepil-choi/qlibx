import importlib.util

import qlibx.flow as flow
from tests.acceptance.real_dw_support import RealDwProject, run_real_daily_flow


def test_uc_exec_001_future_intraday_is_a_seam_not_an_installable_runtime(
    characterization_dw_case: RealDwProject,
) -> None:
    parent = run_real_daily_flow(
        characterization_dw_case,
        run_id="future-intraday-seam-parent",
    )
    intent = parent.result.decision_intents[0]

    assert intent.targets
    assert "execution_profile_id" not in type(intent).model_fields
    assert "IntradayExecutionFlow" not in flow.__all__
    assert not hasattr(flow, "IntradayExecutionFlow")
    assert importlib.util.find_spec("qlibx.flow.intraday") is None
