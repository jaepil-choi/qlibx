import json
from pathlib import Path
from unittest.mock import patch
from vqapr.workspace import Workspace
from vqapr.flow import orchestration as o

root = Path('.agent/runs/v060-call-flow-review/sample').resolve()
out = root.parent
workspace = Workspace.open(root)
frozen = o.preflight_run(workspace, workspace.run_definition('sample-run'))
sessions, writers = [], []
real_session, real_writer = o.ScanSession, o.RunRecordWriter
def session_factory():
    value = real_session()
    sessions.append(value)
    return value
def writer_factory(*args, **kwargs):
    value = real_writer(*args, **kwargs)
    writers.append(value)
    return value
closed, released = [], []
real_close, real_release = real_session.close, real_writer.release
def close(value):
    closed.append(id(value))
    return real_close(value)
def release(value):
    released.append(id(value))
    return real_release(value)
try:
    with patch.object(o,'ScanSession',session_factory), patch.object(o,'RunRecordWriter',writer_factory), patch.object(real_session,'close',close), patch.object(real_writer,'release',release), patch.object(o,'SimulationFlow',side_effect=ValueError('review: constructor failure')):
        try:
            o._run_strategy(root,frozen,frozen.strategies[0],store=out/'failure-store',replace_record=False,record_account_positions=True,roster=None)
        except ValueError as error:
            assert str(error) == 'review: constructor failure'
        else:
            raise AssertionError('injection did not execute')
    result = {'injected':'SimulationFlow constructor raises','sessions_created':len(sessions),'writers_opened':len(writers),'session_close_calls':len(closed),'writer_release_calls':len(released)}
    (out/'resource-failure.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
finally:
    for writer in writers: real_release(writer)
    for session in sessions: real_close(session)