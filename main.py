from __future__ import annotations

from flask import Flask, jsonify, request

from kocotree_skills_auth.auth_verify import require_auth
from flows.inventory_query import run_inventory_query
from flows.purchasein_query import run_purchasein_query
from flows.virtual_stock_query import run_virtual_stock_query

app = Flask(__name__)


@app.route("/api/inventory/query", methods=["POST"])
@require_auth
def inventory_query():
    body = request.get_json(force=True)
    query_type = body.get("query_type")
    query_values = body.get("query_values", [])
    page_index = body.get("page_index", 1)
    page_size = body.get("page_size", 100)
    timeout = body.get("timeout", 30)

    try:
        result = run_inventory_query(
            query_type=query_type,
            query_values=query_values,
            timeout=timeout,
            page_index=page_index,
            page_size=page_size,
        )
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e)}), 500


@app.route("/api/inventory/virtual-stock", methods=["POST"])
@require_auth
def virtual_stock_query():
    body = request.get_json(force=True)
    query_type = body.get("query_type")
    query_values = body.get("query_values", [])
    wms_co_id = body.get("wms_co_id")
    page_index = body.get("page_index", 1)
    page_size = body.get("page_size", 500)
    timeout = body.get("timeout", 30)

    try:
        result = run_virtual_stock_query(
            query_type=query_type,
            query_values=query_values,
            wms_co_id=wms_co_id,
            timeout=timeout,
            page_index=page_index,
            page_size=page_size,
        )
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"name": "jushuitan-skill-service", "status": "ok"})


@app.route("/api/purchasein/query", methods=["POST"])
@require_auth
def purchasein_query():
    body = request.get_json(force=True)
    modified_begin = body.get("modified_begin")
    modified_end = body.get("modified_end")
    supplier_ids = body.get("supplier_ids")
    po_ids = body.get("po_ids")
    io_ids = body.get("io_ids")
    page_index = body.get("page_index", 1)
    page_size = body.get("page_size", 100)
    timeout = body.get("timeout", 30)

    try:
        result = run_purchasein_query(
            modified_begin=modified_begin,
            modified_end=modified_end,
            supplier_ids=supplier_ids,
            po_ids=po_ids,
            io_ids=io_ids,
            timeout=timeout,
            page_index=page_index,
            page_size=page_size,
        )
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": -1, "msg": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5011)
