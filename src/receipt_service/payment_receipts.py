from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from .infrai_storage import StoredObject


class PaymentReceiptRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    payment_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    risk_score: int = Field(ge=0, le=100)
    image_base64: str = Field(min_length=1)


class AuditNotification(BaseModel):
    event_id: str
    payment_id: str
    action: str
    reason: str
    object_key: str
    thumbnail_width: int
    thumbnail_height: int


class PaymentReceiptResult(BaseModel):
    stored: bool
    notification: AuditNotification


class ReceiptStore(Protocol):
    async def put_jpeg(
        self, bucket: str, key: str, data_base64: str, event_id: str
    ) -> StoredObject:
        """Store one JPEG under the event's stable write identity."""


@dataclass(frozen=True)
class Thumbnail:
    data_base64: str
    width: int
    height: int


def make_thumbnail(encoded_image: str, max_edge: int = 960) -> Thumbnail:
    try:
        source = base64.b64decode(encoded_image, validate=True)
        with Image.open(io.BytesIO(source)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
            return Thumbnail(
                data_base64=base64.b64encode(output.getvalue()).decode("ascii"),
                width=image.width,
                height=image.height,
            )
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise ValueError("image_base64 must contain a supported image") from exc


class PaymentReceiptWorkflow:
    def __init__(self, store: ReceiptStore, bucket: str, review_threshold: int = 70) -> None:
        self.store = store
        self.bucket = bucket
        self.review_threshold = review_threshold

    async def handle(self, request: PaymentReceiptRequest) -> PaymentReceiptResult:
        thumbnail = make_thumbnail(request.image_base64)
        needs_review = request.risk_score >= self.review_threshold
        action = "manual_review" if needs_review else "accept"
        reason = "risk_threshold_reached" if needs_review else "risk_below_threshold"
        lane = "review" if needs_review else "approved"
        key = f"{lane}/{request.payment_id}/{request.event_id}.jpg"

        await self.store.put_jpeg(
            bucket=self.bucket,
            key=key,
            data_base64=thumbnail.data_base64,
            event_id=request.event_id,
        )
        return PaymentReceiptResult(
            stored=True,
            notification=AuditNotification(
                event_id=request.event_id,
                payment_id=request.payment_id,
                action=action,
                reason=reason,
                object_key=key,
                thumbnail_width=thumbnail.width,
                thumbnail_height=thumbnail.height,
            ),
        )
