# Do not collect the baseline fixture modules as tests — they are
# strategy source files under test, not test code.
collect_ignore_glob = ["baselines/*/*.py"]
