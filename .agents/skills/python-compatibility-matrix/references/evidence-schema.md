# Compatibility evidence

Record one entry per Python version:

```yaml
python: "3.14.x"
declared_by_project: true
upstream_metadata: supported | unsupported | unknown
resolution: passed | failed | not_run
install: passed | failed | not_run
import: passed | failed | not_run
smoke: passed | failed | not_run
tests: passed | failed | not_run
build: passed | failed | not_run
artifact_install: passed | failed | not_run
commands: []
artifacts: []
failure_class: null
risk: null
notes: null
```

A passing import does not imply passing tests or release support. When upstream metadata says a
version is unsupported but observed checks pass, keep `upstream_metadata: unsupported` and describe
the runtime evidence under `notes` and `risk`.
