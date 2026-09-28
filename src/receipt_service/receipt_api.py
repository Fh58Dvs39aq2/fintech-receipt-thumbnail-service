from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException

from .infrai_storage import InfraiError, InfraiStorage
from .payment_receipts import PaymentReceiptRequest, PaymentReceiptResult, PaymentReceiptWorkflow

BUCKET = os.environ.get("RECEIPT_BUCKET", "fintech-receipt-thumbnails")
storage: InfraiStorage | None = None
workflow: PaymentReceiptWorkflow | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global storage, workflow
    storage = InfraiStorage()
    await storage.create_bucket(BUCKET)
    workflow = PaymentReceiptWorkflow(store=storage, bucket=BUCKET)
    yield
    await storage.close()


app = FastAPI(title="Payment receipt thumbnail service", lifespan=lifespan)


@app.post("/payment-receipts", response_model=PaymentReceiptResult)
async def store_payment_receipt(request: PaymentReceiptRequest) -> PaymentReceiptResult:
    if workflow is None:
        raise HTTPException(status_code=503, detail="Service is starting")
    try:
        return await workflow.handle(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
