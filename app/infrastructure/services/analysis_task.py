"""Celery-based task enqueuer for async overlay analysis."""


class CeleryAnalysisTaskEnqueuer:
    """Enqueue analysis tasks via Celery."""

    def enqueue(
        self,
        request: dict,
        result_id: str,
        layer_id: str,
        analysis_result_id: str,
    ) -> str:
        """Enqueue analysis work. Returns task_id."""
        from app.workers.tasks import run_analysis_task

        task = run_analysis_task.delay(request, result_id, layer_id, analysis_result_id)
        return task.id
