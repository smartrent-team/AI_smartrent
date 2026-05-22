# main.py
from fastapi import FastAPI

app = FastAPI(
    title="SmartRent AI Service",
    description="Microservice phân tích điện nước và tạo hóa đơn",
    version="1.0.0",
)

@app.get("/")
def root():
    return {"message": "SmartRent AI Service is running"}