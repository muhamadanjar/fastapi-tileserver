from app.workers.celery_app import celery_app
from app.core.config import settings
from app.infrastructure.db.connection import db
from app.application.reference_analysis import ReferenceAnalysis


@celery_app.task(name="reference_analysis.run", soft_time_limit=settings.ANALYSIS_JOB_TIMEOUT_SECONDS, time_limit=settings.ANALYSIS_JOB_TIMEOUT_SECONDS + 30)
def run_reference_analysis(job_id):
    with db.get_session() as session:
        ReferenceAnalysis(session, settings).execute(job_id)


@celery_app.task(name="reference_analysis.cleanup")
def cleanup_reference_analysis():
    with db.get_session() as session:
        return ReferenceAnalysis(session, settings).cleanup()
