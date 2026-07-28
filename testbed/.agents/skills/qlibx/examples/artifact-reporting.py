from qlibx import Project
from qlibx.artifacts import ArtifactStore
from qlibx.reporting import analyze_stored_run, render_report
project = Project.load('.')
store = ArtifactStore.from_project(project)
envelope = store.load('artifact-id', run_id='run-id')
payload = store.load_payload(envelope.artifact_id, run_id='run-id')
document = analyze_stored_run('runs.duckdb', 'backtest-run-id')
rendered = render_report(document, 'report.html', renderer='html')
