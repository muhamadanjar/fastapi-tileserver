from datetime import datetime, timezone
from typing import Optional
import sys

import sqlalchemy
import sqlalchemy.orm as _sa_orm
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import declarative_base as _orig_declarative_base

from app.core.config import settings
from app.domain.models import Layer
from app.infrastructure.db.connection import db

CSW_DB_URL = db.config.get_database_url(sync=True)

_NS = {
    "csw": "http://www.opengis.net/cat/csw/2.0.2",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dct": "http://purl.org/dc/terms/",
    "ows": "http://www.opengis.net/ows",
}

# pycsw 2.x uses SQLAlchemy 1.x APIs removed in 2.0
# Patches must be applied before any pycsw imports happen

_orig_conn_execute = Connection.execute
_csw_engine = db.get_engine()


def _compat_conn_execute(self, statement, *args, **kwargs):
    if isinstance(statement, str):
        statement = sa_text(statement)
    return _orig_conn_execute(self, statement, *args, **kwargs)


def _compat_declarative_base(bind=None, **kwargs):
    kwargs.pop("bind", None)
    return _orig_declarative_base(**kwargs)


# Apply patches at import time — before pycsw is imported anywhere
Connection.execute = _compat_conn_execute
_sa_orm.declarative_base = _compat_declarative_base


def _build_wkt_polygon(west: Optional[float], south: Optional[float],
                       east: Optional[float], north: Optional[float]) -> Optional[str]:
    """Build WKT POLYGON from bbox for pycsw spatial queries."""
    if any(v is None for v in [west, south, east, north]):
        return None
    return (
        f"POLYGON(({west} {south}, {east} {south}, "
        f"{east} {north}, {west} {north}, {west} {south}))"
    )


def _build_record_xml(layer: Layer):
    from lxml import etree

    nsmap = {k: v for k, v in _NS.items()}
    rec = etree.Element(f"{{{_NS['csw']}}}Record", nsmap=nsmap)

    dc = _NS["dc"]
    dct = _NS["dct"]
    ows = _NS["ows"]

    # Core identification
    etree.SubElement(rec, f"{{{dc}}}identifier").text = layer.id
    etree.SubElement(rec, f"{{{dc}}}title").text = layer.code or layer.filename
    etree.SubElement(rec, f"{{{dc}}}type").text = "dataset"
    etree.SubElement(rec, f"{{{dc}}}format").text = layer.file_type or ""

    # Abstract — from dedicated column, fall back to file_metadata
    abstract = getattr(layer, 'abstract', None)
    if not abstract and layer.file_metadata:
        abstract = (layer.file_metadata.get('abstract')
                    or layer.file_metadata.get('description'))
    if not abstract:
        abstract = f"Layer type: {layer.layer_type}"
    etree.SubElement(rec, f"{{{dct}}}abstract").text = abstract

    # dc:description — human-readable summary (distinct from dct:abstract)
    etree.SubElement(rec, f"{{{dc}}}description").text = (
        abstract or f"Geospatial layer: {layer.filename} ({layer.file_type})"
    )

    # Keywords — emit one dc:subject per keyword
    raw_keywords = (layer.file_metadata or {}).get("keywords", "geospatial") if layer.file_metadata else "geospatial"
    if isinstance(raw_keywords, list):
        keyword_list = raw_keywords
    elif isinstance(raw_keywords, str) and raw_keywords:
        keyword_list = [k.strip() for k in raw_keywords.split(",")]
    else:
        keyword_list = ["geospatial"]
    for kw in keyword_list:
        if kw:
            etree.SubElement(rec, f"{{{dc}}}subject").text = kw

    # Language
    lang = getattr(layer, 'language', None) or "eng"
    etree.SubElement(rec, f"{{{dc}}}language").text = lang

    # Rights / access constraints
    etree.SubElement(rec, f"{{{dc}}}rights").text = "None"

    # Dates
    if layer.created_at:
        etree.SubElement(rec, f"{{{dc}}}date").text = layer.created_at.isoformat()
    if layer.updated_at:
        etree.SubElement(rec, f"{{{dct}}}modified").text = layer.updated_at.isoformat()

    # Distribution link — use dc:URI with protocol attribute
    if layer.tile_url_template:
        uri_el = etree.SubElement(rec, f"{{{dc}}}URI")
        uri_el.text = layer.tile_url_template
        uri_el.set("protocol", "OGC:WMS")
        uri_el.set("name", layer.code or layer.filename or "")

    # Bounding box
    if all(v is not None for v in [layer.bbox_west, layer.bbox_south,
                                    layer.bbox_east, layer.bbox_north]):
        bbox = etree.SubElement(
            rec, f"{{{ows}}}BoundingBox",
            {"crs": "urn:ogc:def:crs:EPSG::4326"}
        )
        etree.SubElement(bbox, f"{{{ows}}}LowerCorner").text = (
            f"{layer.bbox_west} {layer.bbox_south}"
        )
        etree.SubElement(bbox, f"{{{ows}}}UpperCorner").text = (
            f"{layer.bbox_east} {layer.bbox_north}"
        )

    return rec


def init_csw_db() -> None:
    """
    Create the pycsw 'records' table using raw SQL.
    Replaces admin.setup_db() to avoid SQLAlchemy 1.x API usage.
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    """
    with _csw_engine.connect() as conn:
        conn.execute(sa_text("""
            CREATE TABLE IF NOT EXISTS records (
                identifier       TEXT PRIMARY KEY,
                typename         TEXT NOT NULL DEFAULT 'csw:Record',
                schema           TEXT NOT NULL DEFAULT 'http://www.opengis.net/cat/csw/2.0.2',
                mdsource         TEXT NOT NULL DEFAULT 'local',
                insert_date      TEXT NOT NULL,
                xml              TEXT NOT NULL,
                anytext          TEXT NOT NULL,
                language         TEXT,
                type             TEXT,
                title            TEXT,
                title_alternate  TEXT,
                abstract         TEXT,
                keywords         TEXT,
                keywordstype     TEXT,
                parentidentifier TEXT,
                relation         TEXT,
                time_begin       TEXT,
                time_end         TEXT,
                topicategory     TEXT,
                resourcelanguage TEXT,
                creator          TEXT,
                publisher        TEXT,
                contributor      TEXT,
                organization     TEXT,
                securityconstraints TEXT,
                accessconstraints   TEXT,
                otherconstraints    TEXT,
                date             TEXT,
                date_revision    TEXT,
                date_creation    TEXT,
                date_publication TEXT,
                date_modified    TEXT,
                format           TEXT,
                source           TEXT,
                crs              TEXT,
                geodescode       TEXT,
                denominator      TEXT,
                distancevalue    TEXT,
                distanceuom      TEXT,
                wkt_geometry     TEXT,
                servicetype      TEXT,
                servicetypeversion TEXT,
                operation        TEXT,
                couplingtype     TEXT,
                operateson       TEXT,
                operatesonidentifier TEXT,
                operatesoname    TEXT,
                degree           TEXT,
                classification   TEXT,
                conditionapplyingtoaccessanduse TEXT,
                lineage          TEXT,
                responsiblepartyrole TEXT,
                specificationtitle TEXT,
                specificationdate TEXT,
                specificationdatetype TEXT,
                links            TEXT
            )
        """))

        # Note: PostgreSQL FTS GIN index skipped — requires PG 13+ for CREATE TRIGGER IF NOT EXISTS
        # pycsw's anytext column supports full-text search without explicit indexes
        conn.commit()


def sync_layer(layer: Layer) -> None:
    """Sync a Layer into the pycsw records catalog."""
    from lxml import etree

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml_str = etree.tostring(_build_record_xml(layer), encoding="unicode")

    # abstract: prefer dedicated column, fall back to file_metadata, then empty
    abstract = getattr(layer, 'abstract', None)
    if not abstract and layer.file_metadata:
        abstract = layer.file_metadata.get('abstract') or layer.file_metadata.get('description')
    abstract = abstract or ""

    # anytext: space-joined bag of all searchable text tokens
    anytext_parts = filter(None, [
        layer.code,
        layer.filename,
        layer.file_type,
        layer.layer_type,
        abstract,
        layer.file_metadata.get('keywords') if layer.file_metadata else None,
    ])
    anytext = " ".join(anytext_parts)

    # keywords: comma-separated string
    raw_keywords = (layer.file_metadata or {}).get("keywords", "")
    if isinstance(raw_keywords, list):
        keywords = ",".join(raw_keywords)
    else:
        keywords = raw_keywords or "geospatial"

    # wkt_geometry for BBOX spatial queries — CRITICAL for GetRecords BBOX filters
    wkt_geometry = _build_wkt_polygon(
        layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north
    )

    # links: pycsw format "name,description,protocol,url"
    links = ""
    if layer.tile_url_template:
        layer_title = layer.code or layer.filename or layer.id
        links = f"{layer_title},Tile Service,OGC:WMS,{layer.tile_url_template}"

    # topic_category and language from model columns (new in migration 0002)
    topic_category = getattr(layer, 'topic_category', None) or ""
    resource_language = getattr(layer, 'language', None) or "eng"

    with _csw_engine.connect() as conn:
        conn.execute(sa_text(
            "DELETE FROM records WHERE identifier = :id"
        ), {"id": layer.id})

        conn.execute(sa_text("""
            INSERT INTO records (
                identifier, typename, schema, mdsource, insert_date,
                xml, anytext, language, type, title, format,
                abstract, keywords, source, date, date_modified,
                topicategory, resourcelanguage, links, wkt_geometry
            ) VALUES (
                :identifier, :typename, :schema, :mdsource, :insert_date,
                :xml, :anytext, :language, :type, :title, :format,
                :abstract, :keywords, :source, :date, :date_modified,
                :topicategory, :resourcelanguage, :links, :wkt_geometry
            )
        """), {
            "identifier":       layer.id,
            "typename":         "csw:Record",
            "schema":           "http://www.opengis.net/cat/csw/2.0.2",
            "mdsource":         "local",
            "insert_date":      now,
            "xml":              xml_str,
            "anytext":          anytext,
            "language":         resource_language,
            "type":             "dataset",
            "title":            layer.code or layer.filename,
            "format":           layer.file_type,
            "abstract":         abstract,
            "keywords":         keywords,
            "source":           layer.tile_url_template or "",
            "date":             layer.created_at.isoformat() if layer.created_at else now,
            "date_modified":    layer.updated_at.isoformat() if layer.updated_at else now,
            "topicategory":     topic_category,
            "resourcelanguage": resource_language,
            "links":            links,
            "wkt_geometry":     wkt_geometry,
        })
        conn.commit()


def delete_layer_from_csw(layer_id: str) -> None:
    """Delete a layer's record from CSW catalog."""
    with _csw_engine.connect() as conn:
        conn.execute(sa_text("DELETE FROM records WHERE identifier = :id"), {"id": layer_id})
        conn.commit()
