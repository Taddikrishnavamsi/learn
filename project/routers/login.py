from fastapi import APIRouter, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, JSONResponse
from pathlib import Path
import json
import os



router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "fake_dbs"

@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with open(DB_DIR / "users.json", "r", encoding="utf-8") as f:
        users = json.load(f)

    for user in users:
        if user["username"] == username and user["password"] == password:
            request.session["user"] = username
            return RedirectResponse("/index", status_code=303)

    return JSONResponse({"message": "Invalid credentials"}, status_code=401)
