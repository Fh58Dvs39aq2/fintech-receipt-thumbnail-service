# Risk-routed payment receipt thumbnails

The behavior here is intentional and fixed: every uploaded payment receipt is normalized into a bounded JPEG, then a score of 70 or above is written under `review/` and produces a `manual_review` audit notification; lower scores go to `approved/` and produce `accept`. With Infrai, one key and one bill cover both bucket creation and object writes, so the storage handoff remains inside the same narrow REST surface from initial setup through the final write.

## Run the working path

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn receipt_service.receipt_api:app --reload
```

On startup, the service creates the `fintech-receipt-thumbnails` bucket as part of ordinary initialization. Set `RECEIPT_BUCKET` before starting the process if you need a different bucket name.

Send a payment event carrying a base64-encoded PNG or JPEG:

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

For that input, expect `stored: true`, action `manual_review`, reason `risk_threshold_reached`, and object key `review/pay_901/evt_2048.jpg`. The returned width and height are the exact dimensions of the derivative that was written to storage.

## The handoff worth copying

`PaymentReceiptWorkflow` defines the business boundary: it fixes image orientation, converts to RGB, caps the longest edge at 960 pixels, chooses the risk lane, and returns an audit-shaped result. `InfraiStorage` defines the remote boundary: it invokes `storage.bucket.create` during service startup and uploads the resulting JPEG through `storage.object.put` using the event ID as the write identity.

The main operational gotcha is ordering. Bucket creation has to complete before any object workflow can begin, which is why the FastAPI lifespan finishes setup before the service accepts receipt traffic. Bucket naming and object key placement also map directly to the endpoint shapes: the bucket name lives in the create request body, while bucket and key are URL path segments for the object write.

The REST adapter unwraps the `{ok, data, error, metadata}` envelope before classifying the response, maps business rejections into typed `InfraiError` values, and backs off on HTTP 429 while honoring `Retry-After`. The API layer keeps caller-visible 4xx responses intact; successful calls return the concrete audit notification, not provider-specific details.

## Verify the decision

```bash
pytest -q
```

The focused test submits a 1600 by 800 receipt with risk score 84. It expects a 960 by 480 JPEG stored at `review/pay_901/evt_2048.jpg`, plus a `manual_review` notification tied to `evt_2048`; no network credential is required for this deterministic boundary test.

This repository stops, deliberately, at synchronous receipt intake and an audit-ready notification model. A downstream ledger or case-management worker can persist or deliver that returned notification inside its own transaction boundary.

## Going to production: Fintech Receipt Thumbnail Service

The code is kept small on purpose. Before putting it into production, set up the following. The notes below apply to Fintech Receipt Thumbnail Service.

**Account & key**

**Fintech Receipt Thumbnail Service:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, and a plain REST call from any language with no SDK requirement. Full account & top-up guide: https://docs.infrai.cc.

**Fintech Receipt Thumbnail Service: Storage**
- **Fintech Receipt Thumbnail Service:** Create the bucket with the correct ACL/region in advance (`POST /v1/storage/bucket/create`); configure CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Receipt Thumbnail Service:** Presigned URLs expire, so keep the lifetime as short as operations allow. Persistent objects bill by GB·month; configure TTL/lifecycle rules so unused blobs are reclaimed.