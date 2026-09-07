import ast, contextlib, io, json, sys, tempfile
from collections import Counter
from pathlib import Path
ROOT = Path.cwd()
OUT = ROOT / '.agent/runs/v060-call-flow-review'
metrics, functions = [], []
for path in sorted((ROOT / 'src/vqapr').rglob('*.py')):
    source = path.read_text(encoding='utf-8-sig')
    metrics.append({'file':path.relative_to(ROOT).as_posix(),'lines':len(source.splitlines())})
    for n in ast.walk(ast.parse(source)):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            functions.append({'file':path.relative_to(ROOT).as_posix(),'name':n.name,'line':n.lineno,'span':n.end_lineno-n.lineno+1,'branches':sum(isinstance(x,(ast.If,ast.For,ast.While,ast.ExceptHandler,ast.IfExp,ast.Match)) for x in ast.walk(n))})
from vqapr.agent.sample.journey import install, RUN_ID
from vqapr.cli.main import main
calls, edges, constructors = Counter(), Counter(), Counter()
first_stacks = {}
package = (ROOT / 'src/vqapr').as_posix().lower() + '/'
def label(frame):
    filename = frame.f_code.co_filename.replace('\\','/')
    return filename[len(package):]+':'+str(frame.f_code.co_firstlineno)+':'+frame.f_code.co_qualname if filename.lower().startswith(package) else None

def profile(frame,event,arg):
    if event != 'call': return
    name = label(frame)
    if name is None: return
    calls[name] += 1
    if frame.f_code.co_name in ('__init__','__post_init__'): constructors[name] += 1
    parent = label(frame.f_back) if frame.f_back else None
    if parent: edges[(parent,name)] += 1
    if frame.f_code.co_name in ('decide','optimize','plan_orders','prepare_fill','execute_due','dispatch','_load') and name not in first_stacks:
        stack, current = [], frame
        while current:
            item = label(current)
            if item: stack.append(item)
            current = current.f_back
        first_stacks[name] = stack[::-1]
with contextlib.nullcontext(str(OUT / 'sample')) as temp:
    root = Path(temp)
    from datetime import datetime, time
    from vqapr.public import Workspace, register_run
    if not (root / '.vqapr/workspace.yaml').exists():
        install(root)
    ws = Workspace.open(root)
    original = ws.run_definition(RUN_ID)
    days = original.sessions[10:20]
    bounded = original.model_copy(update={'run_id':'review-bounded','sessions':days,'start':datetime.combine(days[0],time.min,tzinfo=original.start.tzinfo),'end':datetime.combine(days[-1],time.max,tzinfo=original.end.tzinfo)})
    register_run(root,bounded)
    RUN_ID = bounded.run_id
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        sys.setprofile(profile)
        try: exit_code = main(['--project-root',str(root),'run',RUN_ID,'--force'])
        finally: sys.setprofile(None)
    envelope = json.loads(stdout.getvalue())
    (OUT/'sample-envelope.json').write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
report = {'exit_code':exit_code,'modules':len(metrics),'lines':sum(x['lines'] for x in metrics),'largest_modules':sorted(metrics,key=lambda x:x['lines'],reverse=True)[:12],'largest_functions':sorted(functions,key=lambda x:x['span'],reverse=True)[:15],'called_functions':len(calls),'called_modules':len({x.split(':')[0] for x in calls}),'calls':dict(calls),'constructors':dict(constructors),'edges':[{'caller':a,'callee':b,'count':v} for (a,b),v in edges.items()],'first_stacks':first_stacks}
(OUT/'trace.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('calls','constructors','edges','first_stacks')},indent=2))
print('LOADS',json.dumps({k:v for k,v in calls.items() if 'loading.py' in k},indent=2))