from __future__ import annotations

from typing import Any

from core.auth import LOGGER
from core.client import JushuitanClient
from core.config import PURCHASEIN_QUERY_PATH


def validate_purchasein_query_options(
    modified_begin: str | None,
    modified_end: str | None,
    page_index: int,
    page_size: int,
) -> None:
    if not modified_begin or not modified_end:
        raise RuntimeError("modified_begin and modified_end are required")
    if page_index <= 0:
        raise RuntimeError("page_index must be greater than or equal to 1")
    if page_size <= 0 or page_size > 100:
        raise RuntimeError("page_size must be between 1 and 100")


def _extract_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    records = data.get("datas")
    return records if isinstance(records, list) else []


def _flatten_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        io_id = record.get("io_id")
        if io_id is None:
            continue
        io_date = str(record.get("io_date") or "")
        po_id = record.get("po_id")
        for item in record.get("items") or []:
            rows.append(
                {
                    "io_id": io_id,
                    "io_date": io_date,
                    "po_id": po_id,
                    "ioi_id": item.get("ioi_id"),
                    "sku_id": str(item.get("sku_id") or ""),
                    "name": str(item.get("name") or ""),
                    "properties_value": str(item.get("properties_value") or ""),
                    "qty": item.get("qty", 0),
                    "cost_price": item.get("cost_price"),
                    "remark": str(item.get("remark") or ""),
                }
            )
    return rows


def query_purchasein(
    client: JushuitanClient,
    modified_begin: str,
    modified_end: str,
    supplier_ids: list[int] | None,
    po_ids: list[int] | None,
    io_ids: list[int] | None,
    start_page_index: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    page_index = start_page_index

    while True:
        biz: dict[str, Any] = {
            "modified_begin": modified_begin,
            "modified_end": modified_end,
            "page_index": page_index,
            "page_size": page_size,
        }
        if supplier_ids:
            biz["seller_ids"] = supplier_ids
        if po_ids:
            biz["po_ids"] = po_ids
        if io_ids:
            biz["io_ids"] = io_ids

        result = client.call(api_path=PURCHASEIN_QUERY_PATH, biz_params=biz)
        if result.get("code") != 0:
            failures.append(
                {
                    "source": "purchasein",
                    "page": page_index,
                    "code": result.get("code"),
                    "msg": result.get("msg"),
                }
            )
            break

        page_records = _extract_records(result)
        all_records.extend(page_records)

        data = result.get("data") or {}
        if not data.get("has_next"):
            break
        page_index += 1

    rows = _flatten_items(all_records)
    return rows, failures


def run_purchasein_query(
    modified_begin: str,
    modified_end: str,
    supplier_ids: list[int] | None = None,
    po_ids: list[int] | None = None,
    io_ids: list[int] | None = None,
    timeout: int = 30,
    page_index: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    validate_purchasein_query_options(
        modified_begin=modified_begin,
        modified_end=modified_end,
        page_index=page_index,
        page_size=page_size,
    )

    client = JushuitanClient(timeout=timeout)
    rows, failures = query_purchasein(
        client=client,
        modified_begin=modified_begin,
        modified_end=modified_end,
        supplier_ids=supplier_ids,
        po_ids=po_ids,
        io_ids=io_ids,
        start_page_index=page_index,
        page_size=page_size,
    )

    LOGGER.info(
        "purchasein query finished modified=%s~%s row_count=%s failure_count=%s",
        modified_begin,
        modified_end,
        len(rows),
        len(failures),
    )

    return {
        "modified_begin": modified_begin,
        "modified_end": modified_end,
        "rows": rows,
        "failures": failures,
    }
