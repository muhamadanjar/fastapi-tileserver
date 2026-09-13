"""Temporary analysis workflow. File ownership never depends on catalogue visibility."""
import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
from sqlalchemy import func, text
from sqlmodel import select

from app.analysis.reference_intersection import intersect_reference, validate_frame
from app.domain.models import AnalysisReference, AnalysisUpload, ReferenceAnalysisJob, ActiveAnalysisSource, Layer
from app.infrastructure.services.analysis_reference_source import load_reference
from app.infrastructure.services.reference_analysis_files import read_shapefile_archive, write_json, export_results

logger = logging.getLogger(__name__)
ACTIVE = {"pending", "processing"}


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AnalysisError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def owner_hash(token):
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
        raise AnalysisError("Sesi analisis tidak tersedia. Muat ulang halaman.", 401)
    return hashlib.sha256(token.encode()).hexdigest()


def capacity_lock(session):
    # Serializes admission/cleanup, including cross-process workers on PostgreSQL.
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(728193420)"))


def guard_source_delete(session, layer_id):
    if session.get(AnalysisReference, layer_id) or session.exec(select(ActiveAnalysisSource).where(ActiveAnalysisSource.layer_id == layer_id)).first():
        raise AnalysisError("Layer masih menjadi acuan atau dipakai analisis aktif. Lepas konfigurasi acuan dan tunggu proses selesai.", 409)


async def guard_source_delete_async(session, layer_id):
    await session.exec(select(Layer).where(Layer.id == layer_id).with_for_update())
    reference = await session.get(AnalysisReference, layer_id)
    active = (await session.exec(select(ActiveAnalysisSource).where(ActiveAnalysisSource.layer_id == layer_id))).first()
    if reference or active:
        raise AnalysisError("Layer masih menjadi acuan atau dipakai analisis aktif. Lepas konfigurasi acuan dan tunggu proses selesai.", 409)


class ReferenceAnalysis:
    def __init__(self, session, settings, enqueue=None):
        self.session = session
        self.settings = settings
        self.enqueue = enqueue
        self.root = Path(settings.UPLOAD_DIR) / "analysis-workspace"

    def directory(self, identity):
        return self.root / identity

    def ttl(self):
        return timedelta(hours=self.settings.ANALYSIS_EPHEMERAL_TTL_HOURS)

    def references(self):
        return [r.model_dump(mode="json") for r in self.session.exec(select(AnalysisReference).order_by(AnalysisReference.name)).all()]

    def configure(self, layer_id, config):
        layer = self.session.exec(select(Layer).where(Layer.id == layer_id).with_for_update()).first()
        if layer is None:
            raise AnalysisError("Layer tidak ditemukan.", 404)
        frame, _ = load_reference(self.session, layer, self.settings)
        columns = set(frame.columns) - {frame.geometry.name}
        if config["category_field"] not in columns or not set(config["attributes"]).issubset(columns):
            raise AnalysisError("Kolom kategori atau atribut acuan tidak ditemukan.")
        ref = self.session.get(AnalysisReference, layer_id) or AnalysisReference(layer_id=layer_id, **config)
        for key, value in config.items():
            setattr(ref, key, value)
        ref.updated_at = now()
        self.session.add(ref)
        self.session.commit()
        self.session.refresh(ref)
        return ref.model_dump(mode="json")

    def remove_reference(self, layer_id):
        self.session.exec(select(Layer).where(Layer.id == layer_id).with_for_update()).first()
        ref = self.session.get(AnalysisReference, layer_id)
        if ref:
            self.session.delete(ref)
            self.session.commit()

    def upload(self, file, owner):
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise AnalysisError("Unggah ZIP berisi satu dataset SHP.")
        capacity_lock(self.session)
        count = self.session.exec(select(func.count()).select_from(AnalysisUpload)).one()
        own_count = self.session.exec(select(func.count()).select_from(AnalysisUpload).where(AnalysisUpload.owner_hash == owner)).one()
        if count >= self.settings.ANALYSIS_MAX_STORED_INPUTS or own_count >= self.settings.ANALYSIS_MAX_OWNER_INPUTS:
            raise AnalysisError("Batas unggahan sementara tercapai. Bersihkan hasil lama atau coba setelah kedaluwarsa.", 429)
        identity = str(uuid4())
        directory = self.directory(identity)
        directory.mkdir(parents=True)
        try:
            archive = directory / "source.zip"
            total = 0
            with archive.open("wb") as stream:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.ANALYSIS_MAX_UPLOAD_BYTES:
                        raise AnalysisError("Ukuran ZIP melebihi batas unggahan.", 413)
                    stream.write(chunk)
            frame = read_shapefile_archive(archive, directory / "source", self.settings)
            write_json(directory / "input.geojson", json.loads(frame.to_json(drop_id=True)))
            archive.unlink()
            shutil.rmtree(directory / "source")
            uploaded = now()
            record = AnalysisUpload(id=identity, owner_hash=owner, filename=Path(file.filename).name, feature_count=len(frame), geometry_types=sorted(set(frame.geom_type)), created_at=uploaded, expires_at=uploaded + self.ttl())
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            return record.model_dump(mode="json", exclude={"owner_hash"})
        except Exception:
            self.session.rollback()
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def start(self, input_id, reference_id, owner):
        capacity_lock(self.session)
        upload = self.session.exec(select(AnalysisUpload).where(AnalysisUpload.id == input_id).with_for_update()).first()
        if upload is None or upload.owner_hash != owner:
            raise AnalysisError("Unggahan tidak ditemukan.", 404)
        existing = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.input_id == input_id)).first()
        if existing:
            raise AnalysisError("Unggahan sudah digunakan. Unggah kembali untuk analisis baru.", 409)
        if aware(upload.expires_at) <= now():
            raise AnalysisError("Unggahan sudah kedaluwarsa.", 410)
        layer = self.session.exec(select(Layer).where(Layer.id == reference_id).with_for_update()).first()
        ref = self.session.get(AnalysisReference, reference_id)
        if layer is None or ref is None:
            raise AnalysisError("Acuan tidak tersedia. Pilih acuan aktif.", 409)
        active_count = self.session.exec(select(func.count()).select_from(ReferenceAnalysisJob).where(ReferenceAnalysisJob.status.in_(ACTIVE))).one()
        if active_count >= self.settings.ANALYSIS_MAX_ACTIVE_JOBS:
            raise AnalysisError("Antrean analisis penuh. Coba kembali sebentar lagi.", 429)
        identity = str(uuid4())
        job = ReferenceAnalysisJob(id=identity, input_id=input_id, owner_hash=owner, reference_id=reference_id, reference_config=ref.model_dump(mode="json"), task_id=str(uuid4()), created_at=now())
        self.session.add(job)
        self.session.flush()
        self.session.add(ActiveAnalysisSource(job_id=identity, layer_id=reference_id))
        self.session.commit()
        try:
            self.enqueue(identity, job.task_id)
        except Exception:
            logger.exception("Could not enqueue reference analysis %s", identity)
            self.fail(identity, "Antrean analisis tidak tersedia. Silakan unggah dan coba kembali.")
        return self.job(identity, owner)

    def job(self, identity, owner):
        job = self.session.get(ReferenceAnalysisJob, identity)
        if job is None or job.owner_hash != owner:
            raise AnalysisError("Hasil analisis tidak ditemukan.", 404)
        if job.expires_at and aware(job.expires_at) <= now():
            raise AnalysisError("Hasil analisis sudah kedaluwarsa.", 410)
        return job.model_dump(mode="json", exclude={"owner_hash", "task_id"})

    def list_jobs(self, owner):
        jobs = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.owner_hash == owner).order_by(ReferenceAnalysisJob.created_at.desc()).limit(50)).all()
        return [self.job(job.id, owner) for job in jobs if job.expires_at is None or aware(job.expires_at) > now()]

    def result(self, identity, owner):
        job = self.job(identity, owner)
        if job["status"] != "done":
            raise AnalysisError("Hasil belum tersedia.", 409)
        return self.directory(job["input_id"])

    def finish(self, job, status, error=None):
        job.status = status
        job.error = error
        job.completed_at = now()
        job.expires_at = job.completed_at + self.ttl()
        upload = self.session.get(AnalysisUpload, job.input_id)
        upload.expires_at = job.expires_at
        self.session.add(upload)
        self.session.add(job)
        active = self.session.get(ActiveAnalysisSource, job.id)
        if active:
            self.session.delete(active)
        self.session.commit()

    def fail(self, identity, error):
        self.session.rollback()
        job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.id == identity).with_for_update()).first()
        if job and job.status in ACTIVE:
            self.finish(job, "failed", error)

    def execute(self, identity):
        try:
            job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.id == identity).with_for_update()).first()
            if job is None or job.status != "pending":
                return
            job.status, job.started_at = "processing", now()
            self.session.add(job)
            self.session.commit()
            # Hold source row while reading; the independent pin survives config removal.
            layer = self.session.exec(select(Layer).where(Layer.id == job.reference_id).with_for_update()).first()
            if layer is None:
                raise AnalysisError("Sumber acuan tidak tersedia.")
            reference, version = load_reference(self.session, layer, self.settings)
            # Use latest configuration if it still exists, otherwise admitted configuration.
            config = self.session.get(AnalysisReference, job.reference_id)
            if config:
                job.reference_config = config.model_dump(mode="json")
            job.source_version = version
            self.session.add(job)
            self.session.commit()
            directory = self.directory(job.input_id)
            source = validate_frame(gpd.read_file(directory / "input.geojson"), max_features=self.settings.ANALYSIS_MAX_FEATURES, max_vertices=self.settings.ANALYSIS_MAX_VERTICES)
            result = intersect_reference(source, reference, job.reference_config["category_field"], job.reference_config["attributes"], job.id, self.settings.ANALYSIS_MAX_RESULTS, self.settings.ANALYSIS_MAX_EXTRACTED_BYTES, self.settings.ANALYSIS_MAX_VERTICES * 10)
            result["reference"] = {**job.reference_config, "source_version": version, "read_at": job.started_at.isoformat()}
            export_results(directory, result)
            job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.id == identity).with_for_update().execution_options(populate_existing=True)).one()
            if job.status != "processing":
                return
            job.result_count = len(result["features"])
            self.finish(job, "done")
        except ValueError as exc:
            self.fail(identity, str(exc))
        except Exception:
            logger.exception("Reference analysis %s failed", identity)
            self.fail(identity, "Analisis gagal membaca atau memproses data. Periksa sumber atau hubungi pengelola.")

    def cleanup(self):
        capacity_lock(self.session)
        current = now()
        identities = self.session.exec(select(ReferenceAnalysisJob.id).where(ReferenceAnalysisJob.status.in_(ACTIVE))).all()
        for identity in identities:
            job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.id == identity).with_for_update().execution_options(populate_existing=True)).first()
            if job is None or job.status not in ACTIVE:
                continue
            timeout = self.settings.ANALYSIS_QUEUE_TIMEOUT_SECONDS if job.status == "pending" else self.settings.ANALYSIS_JOB_TIMEOUT_SECONDS + 120
            since = job.started_at or job.created_at
            if aware(since) + timedelta(seconds=timeout) < current:
                self.finish(job, "failed", "Analisis melewati batas waktu. Silakan unggah ulang.")
        removed = 0
        for upload in self.session.exec(select(AnalysisUpload).where(AnalysisUpload.expires_at <= current)).all():
            job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.input_id == upload.id)).first()
            if job and job.status in ACTIVE:
                continue
            identity, owner = upload.id, upload.owner_hash
            try:
                self.remove_upload(identity, owner)
                removed += 1
            except Exception:
                self.session.rollback()
                logger.exception("Could not clean analysis upload %s; retry next sweep", identity)
        # Aborted HTTP uploads have no row. Remove orphan directories after TTL.
        if self.root.exists():
            known = set(self.session.exec(select(AnalysisUpload.id)).all())
            for path in self.root.iterdir():
                if path.is_dir() and path.name not in known and path.stat().st_mtime < (current - self.ttl()).timestamp():
                    try:
                        shutil.rmtree(path)
                    except OSError:
                        logger.exception("Could not clean orphan analysis directory %s", path.name)
        return {"removed": removed}

    def remove_upload(self, input_id, owner):
        capacity_lock(self.session)
        upload = self.session.exec(select(AnalysisUpload).where(AnalysisUpload.id == input_id).with_for_update()).first()
        if upload is None or upload.owner_hash != owner:
            raise AnalysisError("Unggahan tidak ditemukan.", 404)
        job = self.session.exec(select(ReferenceAnalysisJob).where(ReferenceAnalysisJob.input_id == input_id)).first()
        if job and job.status in ACTIVE:
            raise AnalysisError("Analisis masih berjalan.", 409)
        path = self.directory(input_id)
        if path.exists():
            shutil.rmtree(path)  # Leave DB rows for retry if deletion fails.
        if job:
            self.session.delete(job)
            self.session.flush()
        self.session.delete(upload)
        self.session.commit()
