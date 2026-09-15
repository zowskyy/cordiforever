# Fixture repositories and hidden oracle tests are only valid inside isolated workspace copies
# (benchmark/repo_task_eval.py); the project suite must not collect them.
collect_ignore_glob = ["benchmark/repos/*", "benchmark/oracle/*"]
