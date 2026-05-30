from datetime import datetime, timezone

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

# pycsw 2.x uses SQLAlchemy 1.x APIs removed in 2.0 — patch at import time
_orig_metadata_init = sqlalchemy.MetaData.__init__
_orig_table_create = sqlalchemy.Table.create
_orig_conn_execute = Connection.execute
_csw_engine = db.get_engine()


def _compat_metadata_init(self, bind=None, **kwargs):
    _orig_metadata_init(self, **kwargs)


def _compat_table_create(self, bind=None, checkfirst=False):
    _orig_table_create(self, _csw_engine, checkfirst=True)


def _compat_conn_execute(self, statement, *args, **kwargs):
    if isinstance(statement, str):
        statement = sa_text(statement)
    return _orig_conn_execute(self, statement, *args, **kwargs)


def _compat_declarative_base(bind=None, **kwargs):
    kwargs.pop("bind", None)
    return _orig_declarative_base(**kwargs)


sqlalchemy.MetaData.__init__ = _compat_metadata_init
sqlalchemy.Table.create = _compat_table_create
Connection.execute = _compat_conn_execute
_sa_orm.declarative_base = _compat_declarative_base



def _build_record_xml(layer: Layer):
    from lxml import etree

    nsmap = {k: v for k, v in _NS.items()}
    rec = etree.Element(f"{{{_NS['csw']}}}Record", nsmap=nsmap)

    dc = _NS["dc"]
    dct = _NS["dct"]
    ows = _NS["ows"]

    etree.SubElement(rec, f"{{{dc}}}identifier").text = layer.id
    etree.SubElement(rec, f"{{{dc}}}title").text = layer.code or layer.filename
    etree.SubElement(rec, f"{{{dc}}}type").text = "dataset"
    etree.SubElement(rec, f"{{{dc}}}format").text = layer.file_type
    etree.SubElement(rec, f"{{{dc}}}description").text = f"Layer type: {layer.layer_type}"
    if layer.file_metadata and isinstance(layer.file_metadata, dict):
        subject = layer.file_metadata.get("keywords", "geospatial")
        etree.SubElement(rec, f"{{{dc}}}subject").text = subject
    else:
        etree.SubElement(rec, f"{{{dc}}}subject").text = "geospatial"

    if layer.created_at:
        etree.SubElement(rec, f"{{{dc}}}date").text = layer.created_at.isoformat()
    if layer.updated_at:
        etree.SubElement(rec, f"{{{dct}}}modified").text = layer.updated_at.isoformat()
    if layer.tile_url_template:
        etree.SubElement(rec, f"{{{dc}}}URI").text = layer.tile_url_template

    if all(v is not None for v in [layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]):
        bbox = etree.SubElement(rec, f"{{{ows}}}BoundingBox", {"crs": "urn:ogc:def:crs:EPSG::4326"})
        etree.SubElement(bbox, f"{{{ows}}}LowerCorner").text = f"{layer.bbox_west} {layer.bbox_south}"
        etree.SubElement(bbox, f"{{{ows}}}UpperCorner").text = f"{layer.bbox_east} {layer.bbox_north}"

    return rec


def init_csw_db() -> None:
    from pycsw.core import admin

    admin.setup_db(
        CSW_DB_URL,
        "records",
        str(settings.BASE_DIR),
        create_sfsql_tables=False,
        create_plpythonu_functions=False,
    )


def sync_layer(layer: Layer) -> None:
    from lxml import etree

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml_str = etree.tostring(_build_record_xml(layer), encoding="unicode")
    anytext = " ".join(filter(None, [layer.code, layer.filename, layer.file_type, layer.layer_type]))
    subject = (layer.file_metadata or {}).get("keywords", "geospatial") if layer.file_metadata else "geospatial"

    with _csw_engine.connect() as conn:
        conn.execute(sa_text("DELETE FROM records WHERE identifier = :id"), {"id": layer.id})
        conn.execute(sa_text("""
            INSERT INTO records (
                identifier, typename, schema, mdsource, insert_date,
                xml, anytext, language, type, title, format,
                source, date, date_modified, keywords, links
            ) VALUES (
                :identifier, :typename, :schema, :mdsource, :insert_date,
                :xml, :anytext, :language, :type, :title, :format,
                :source, :date, :date_modified, :keywords, :links
            )
        """), {
            "identifier": layer.id,
            "typename": "csw:Record",
            "schema": "http://www.opengis.net/cat/csw/2.0.2",
            "mdsource": "local",
            "insert_date": now,
            "xml": xml_str,
            "anytext": anytext,
            "language": "en",
            "type": "dataset",
            "title": layer.code or layer.filename,
            "format": layer.file_type,
            "source": layer.tile_url_template or "",
            "date": layer.created_at.isoformat() if layer.created_at else now,
            "date_modified": layer.updated_at.isoformat() if layer.updated_at else now,
            "keywords": subject,
            "links": layer.tile_url_template or "",
        })
        conn.commit()


def delete_layer_from_csw(layer_id: str) -> None:
    with _csw_engine.connect() as conn:
        conn.execute(sa_text("DELETE FROM records WHERE identifier = :id"), {"id": layer_id})
        conn.commit()
