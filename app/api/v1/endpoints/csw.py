import configparser
from io import BytesIO
from pathlib import Path
from typing import Optional

import pycsw
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.config import settings
from app.infrastructure.services.csw_sync import CSW_DB_URL

router = APIRouter(prefix="/csw", tags=["csw"])

_PYCSW_HOME = str(Path(pycsw.__file__).parent)


def _make_config(csw_url: str, base_url: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read_dict({
        "server": {
            "home": _PYCSW_HOME,
            "url": csw_url,
            "mimetype": "application/xml; charset=UTF-8",
            "encoding": "UTF-8",
            "language": "en-US",
            "maxrecords": "10",
            "loglevel": "ERROR",
            "logfile": str(settings.BASE_DIR / "logs" / "csw.log"),
            "federatedcatalogues": "",
            "pretty_print": "true",
            "gzip_compresslevel": "9",
            "domainquerytype": "list",
            "domaincounts": "false",
            "profiles": "",
        },
        "manager": {
            "transactions": "false",
            "allowed_ips": "",
        },
        "metadata:main": {
            "identification_title": "TileServer Catalogue",
            "identification_abstract": "OGC CSW 2.0.2 catalogue for geospatial layers",
            "identification_keywords": "catalogue,geospatial,tiles",
            "identification_keywords_type": "theme",
            "identification_fees": "None",
            "identification_accessconstraints": "None",
            "provider_name": "TileServer",
            "provider_url": base_url,
            "contact_name": "",
            "contact_position": "",
            "contact_address": "",
            "contact_city": "",
            "contact_stateorprovince": "",
            "contact_postalcode": "",
            "contact_country": "",
            "contact_phone": "",
            "contact_fax": "",
            "contact_email": "",
            "contact_url": "",
            "contact_hours": "",
            "contact_instructions": "",
            "contact_role": "pointOfContact",
        },
        "repository": {
            "database": CSW_DB_URL,
            "table": "records",
        },
    })
    return config


@router.get("")
@router.post("")
async def csw(request: Request):
    from pycsw.server import Csw as PycswServer

    body = await request.body()
    base_url = str(request.base_url).rstrip("/")
    csw_url = f"{base_url}{request.url.path}"
    config = _make_config(csw_url, base_url)

    environ = {
        "REQUEST_METHOD": request.method,
        "QUERY_STRING": str(request.url.query),
        "SERVER_NAME": request.url.hostname or "localhost",
        "SERVER_PORT": str(request.url.port or 8000),
        "PATH_INFO": request.url.path,
        "HTTP_HOST": request.headers.get("host", "localhost"),
        "wsgi.input": BytesIO(body),
        "CONTENT_TYPE": request.headers.get("content-type", ""),
        "CONTENT_LENGTH": str(len(body)),
    }

    csw_obj = PycswServer(config, environ)
    http_status, response = csw_obj.dispatch()

    status_code = int(http_status.split(" ")[0]) if isinstance(http_status, str) else 200
    return Response(
        content=response if isinstance(response, bytes) else response.encode(),
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
    )
