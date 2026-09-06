"""bd:shotockviz-5e7 — the new pipeline-health check must actually be wired
into celery-beat and the worker's include list, not just exist as a
module nobody schedules. Companion to test_beat_schedule_ict.py, which
this entry is deliberately NOT added to (see the comment on
"check-pipeline-health" in celery_app.py): that map only covers
crontab(hour=...) wall-clock entries, and this is a plain-interval
(seconds) schedule with no ICT/UTC concern.
"""
from workers.celery_app import celery_app

# Importing this module is what proves it is registered task-side (the
# @shared_task decorator binds to whatever Celery app is currently active
# the moment the module is imported) — celery_app.conf.include only
# matters for a real worker process autodiscovering modules by name.
import workers.pipeline_health  # noqa: F401


def test_pipeline_health_module_is_in_the_worker_include_list():
    assert "workers.pipeline_health" in celery_app.conf.include


def test_check_pipeline_health_beat_entry_exists_and_points_at_the_right_task():
    entry = celery_app.conf.beat_schedule["check-pipeline-health"]
    assert entry["task"] == "workers.pipeline_health.check_pipeline_health"


def test_check_pipeline_health_is_a_plain_interval_not_a_crontab():
    """Guards against someone "fixing" this into a crontab() later and
    silently reintroducing an ICT/UTC ambiguity for a task that was
    deliberately built to have no wall-clock-of-day meaning."""
    schedule = celery_app.conf.beat_schedule["check-pipeline-health"]["schedule"]
    assert isinstance(schedule, (int, float))


def test_check_pipeline_health_task_is_registered():
    assert "workers.pipeline_health.check_pipeline_health" in celery_app.tasks
