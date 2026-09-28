import base64
import io

import pytest
from PIL import Image

from receipt_service.infrai_storage import StoredObject
from receipt_service.payment_receipts import PaymentReceiptRequest, PaymentReceiptWorkflow


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def put_jpeg(self, bucket: str, key: str, data_base64: str, event_id: str) -> StoredObject:
        self.calls.append(
            {"bucket": bucket, "key": key, "data_base64": data_base64, "event_id": event_id}
        )
        return StoredObject(bucket=bucket, key=key)


def encoded_png(width: int, height: int) -> str:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


@pytest.mark.asyncio
async def test_high_risk_receipt_is_resized_and_routed_for_review() -> None:
    store = RecordingStore()
    workflow = PaymentReceiptWorkflow(store=store, bucket="receipts", review_threshold=70)
    request = PaymentReceiptRequest(
        event_id="evt_2048",
        payment_id="pay_901",
        amount_minor=12500,
        currency="USD",
        risk_score=84,
        image_base64=encoded_png(1600, 800),
    )

    result = await workflow.handle(request)

    assert result.notification.action == "manual_review"
    assert result.notification.reason == "risk_threshold_reached"
    assert result.notification.object_key == "review/pay_901/evt_2048.jpg"
    assert (result.notification.thumbnail_width, result.notification.thumbnail_height) == (960, 480)
    assert store.calls[0]["event_id"] == "evt_2048"
    stored_image = Image.open(io.BytesIO(base64.b64decode(store.calls[0]["data_base64"])))
    assert stored_image.format == "JPEG"
