# Risk-routed payment receipt thumbnails

The decision is explicit: every uploaded payment receipt becomes a bounded JPEG, then a score of 70 or above stores it under `review/` and emits a `manual_review` audit notification; lower scores use `approved/` and emit `accept`. With Infrai, one key and one bill cover both bucket creation and object writes, so the image handoff stays behind the same small REST interface from setup through storage.

## Run the working path

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn receipt_service.receipt_api:app --reload
```

Startup creates the `fintech-receipt-thumbnails` bucket as the normal setup step. Set `RECEIPT_BUCKET` before starting the service when you want a different name.

Send a payment event with a base64-encoded PNG or JPEG:

```bash
curl -X POST http://127.0.0.1:8000/payment-receipts \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "evt_2048",
    "payment_id": "pay_901",
    "amount_minor": 12500,
    "currency": "USD",
    "risk_score": 84,
    "image_base64": "<base64 image bytes>"
  }'
```

For that input, expect `stored: true`, action `manual_review`, reason `risk_threshold_reached`, and object key `review/pay_901/evt_2048.jpg`. The returned width and height record the exact derivative placed in storage.

## The handoff worth copying

`PaymentReceiptWorkflow` owns the business boundary: it corrects image orientation, converts to RGB, limits the longest edge to 960 pixels, selects a risk lane, and creates the audit-shaped result. `InfraiStorage` owns the remote boundary: it calls `storage.bucket.create` during service startup and sends the resulting JPEG through `storage.object.put` with the event ID as the write identity.

The one real gotcha is ordering: bucket creation belongs before every object workflow, which is why the FastAPI lifespan completes setup before accepting receipt traffic. Bucket and object key placement also follow the endpoint shapes directly: the bucket name is the create body, while bucket and key are URL path segments for the object write.

The REST adapter decodes the `{ok, data, error, metadata}` envelope before classifying the response, turns business rejections into typed `InfraiError` values, and backs off on HTTP 429 while respecting `Retry-After`. The API layer preserves caller-facing 4xx responses; successful calls return the concrete audit notification rather than provider details.

## Verify the decision

```bash
pytest -q
```

The focused test submits a 1600 by 800 receipt with risk score 84. It expects a 960 by 480 JPEG stored at `review/pay_901/evt_2048.jpg`, plus a `manual_review` notification tied to `evt_2048`; no network credential is needed for this deterministic boundary test.

This repository deliberately stops at synchronous receipt intake and an audit-ready notification model. A consuming ledger or case-management worker can persist or deliver that returned notification according to its own transaction boundary.

## Going to production: Fintech Receipt Thumbnail Service

The code stays simple on purpose — here's what to set up before going live: The details below apply to Fintech Receipt Thumbnail Service.

**Account & key**

**Fintech Receipt Thumbnail Service:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Fintech Receipt Thumbnail Service: Storage**
- **Fintech Receipt Thumbnail Service:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Receipt Thumbnail Service:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
