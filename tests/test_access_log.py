"""Access log của uvicorn không ghi secret admin hay verify token của Facebook (Render giữ log)."""

import logging

import pytest

import app.main  # noqa: F401  (cài filter lên logger uvicorn.access)

# Định dạng uvicorn.protocols.http: client, method, path kèm query, HTTP version, status.
ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


def access_line(caplog, path):
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(ACCESS_FORMAT, "10.0.0.7:51234", "POST", path, "1.1", 200)
    (record,) = [r for r in caplog.records if r.name == "uvicorn.access"]
    return record.getMessage()


@pytest.mark.parametrize(
    ("path", "logged"),
    [
        ("/followup/run?secret=tg-secret_webhook&dry_run=true", "/followup/run?secret=***&dry_run=true"),
        ("/customers?verbose=1&secret=tg-secret_webhook", "/customers?verbose=1&secret=***"),
        (
            "/webhook?hub.mode=subscribe&hub.verify_token=fb-verify-tok&hub.challenge=42",
            "/webhook?hub.mode=subscribe&hub.verify_token=***&hub.challenge=42",
        ),
    ],
)
def test_access_log_masks_secret_query_values(caplog, path, logged):
    line = access_line(caplog, path)

    assert line == f'10.0.0.7:51234 - "POST {logged} HTTP/1.1" 200'
    assert "tg-secret_webhook" not in caplog.text and "fb-verify-tok" not in caplog.text


def test_access_log_keeps_paths_without_secret(caplog):
    line = access_line(caplog, "/dashboard?days=7&secretary=lan")

    assert line == '10.0.0.7:51234 - "POST /dashboard?days=7&secretary=lan HTTP/1.1" 200'
