from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.db import get_connection
from routers import cccd, utility, ticket, contract

app = FastAPI(
    title="SmartRent AI Service",
    description="Microservice phân tích điện nước và tạo hóa đơn",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "SmartRent AI Service is running"}


@app.get("/db-test")
def db_test():
    conn = get_connection()

    if not conn:
        return {"status": "error", "message": "Cannot connect DB"}

    cur = conn.cursor()
    cur.execute("SELECT 1;")
    result = cur.fetchone()
    conn.close()

    return {"status": "ok", "result": result}

app.include_router(utility.router, prefix="/utility", tags=["Utility"])
app.include_router(cccd.router, prefix="/cccd", tags=["CCCD"])
app.include_router(ticket.router, prefix="/ticket", tags=["Ticket"])
app.include_router(contract.router, prefix="/contract", tags=["Contract"])

@app.get("/test-utility")
def test_utility():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM utility_logs LIMIT 5")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"rows": rows}
