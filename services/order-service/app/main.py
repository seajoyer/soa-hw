from fastapi import FastAPI

SERVICE_NAME = "order-service"

app = FastAPI(title="Order Service", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: the process is up and serving HTTP."""
    return {"status": "ok", "service": SERVICE_NAME}
