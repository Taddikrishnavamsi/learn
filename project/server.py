from typing import List, Optional
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, Request, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.templating import Jinja2Templates
from google.cloud import storage
import os
import logging

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-this-secret")
logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR))

# Setup Google Cloud credentials for Railway
if os.getenv("RAILWAY_ENVIRONMENT"):
    service_account_json = os.getenv("service-account")
    if service_account_json:
        creds_path = BASE_DIR / "service-account-temp.json"
        creds_path.write_text(service_account_json)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
else:
    # Local development
    creds_path = BASE_DIR / "service-account.json"
    if creds_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)


app.mount("/photos", StaticFiles(directory=str(BASE_DIR / "photos")), name="photos")

@app.get("/loaderio-{token}.txt")
@app.get("/loaderio-{token}.html")
def verify(token: str):
    token_value = f"loaderio-{token}"
    token_path = BASE_DIR / f"{token_value}.txt"
    if token_path.exists():
        return PlainTextResponse(token_path.read_text(encoding="utf-8").strip())
  return PlainTextResponse(token)
ws_users = {}

# Load user phone numbers
userph = {}
with open(BASE_DIR / "users.json", "r", encoding="utf-8") as f:
    users = json.load(f)
for user in users:
    userph[user["username"]] = user["user_phone"]
print("Loaded user phone numbers:", userph)

chatusers = ["FamilyChat"] + list(userph.keys())

STATUS_FILE = BASE_DIR / "status.json"
def _load_status_map() -> dict:
    if not STATUS_FILE.exists():
        STATUS_FILE.write_text("{}", encoding="utf-8")
        return {}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_status_map(data: dict) -> None:
    STATUS_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
    
# ================= ROUTES ================= #

@app.get("/")
async def get():
    return HTMLResponse((BASE_DIR / "login.html").read_text(encoding="utf-8"))


@app.get("/login")
async def get_login():
    return HTMLResponse((BASE_DIR / "login.html").read_text(encoding="utf-8"))


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session")
    return response


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with open(BASE_DIR / "users.json", "r", encoding="utf-8") as f:
        users = json.load(f)

    for user in users:
        if user["username"] == username and user["password"] == password:
            request.session["user"] = username
            return RedirectResponse("/index", status_code=303)

    return JSONResponse({"message": "Invalid credentials"}, status_code=401)

@app.get("/videos")
async def get_videos(request:Request):
    username = request.session.get("user")
    if not username:
        return RedirectResponse("/")
    return templates.TemplateResponse(
        "videos.html",
        {
            "request": request,
            "username": username,
        },
    )



@app.get("/index")
async def get_index(request: Request):
    username = request.session.get("user")

    if not username:
        return RedirectResponse("/")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "username": username,
        },
    )


@app.get("/status")
async def get_status(request: Request):
    username = request.session.get("user")

    if not username:
        return RedirectResponse("/")
    blob_list = _load_status_map()

    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "username": username,
            "status_list": blob_list,
        },
    )
def _sanitize_filename(filename: str) -> str:
    """Remove unsafe characters from filename."""
    return "".join(c for c in filename if c.isalnum() or c in ("-", "_", ".")).lstrip(".")
#---------------------------------------------VIDEOS-------------------------------------------------------
#UPLOAD video backend ki vasthundhi and then blob loki pamputham and then manam public url extract chestham 
#next
video_url_list={}
@app.post('/upload_video')
async def upload_video(
    request: Request,
    file: Optional[UploadFile] = File(None),
    username: str = Form(None),
    description: str = Form(None),
    video_url: Optional[str] = Form(None),
):
    try:
        if username != request.session.get("user"):
            raise HTTPException(status_code=401, detail="Unauthorized")
        normalized_url = (video_url or "").strip()
        if normalized_url.lower() in {"", "none", "null"}:
            normalized_url = ""
        url = normalized_url or None

        has_file = file is not None and bool(getattr(file, "filename", ""))
        if not has_file and not url:
            raise HTTPException(status_code=400, detail="Provide file or video URL")
        if has_file and url:
            raise HTTPException(status_code=400, detail="Provide only one: file or video URL")

        if not description:
            description = f"{username} uploaded"

        existing_videos = video_url_list.get(username, [])
        if not isinstance(existing_videos, list):
            existing_videos = []

        for video in existing_videos:
            if video.get("description") == description:
                raise HTTPException(
                    status_code=409,
                    detail="Video with same description already exists for this user",
                )
        if url:
            existing_videos.append(
            {
                "description": description,
                "url": url,
            }
        )
            video_url_list[username] = existing_videos
            return {
            "username": username,
            "video_list": video_url_list,
        }
        safe_filename = _sanitize_filename(file.filename or "upload")
        if not safe_filename:
            safe_filename = "upload"
        object_name = f"{username}/{safe_filename}"

        client_video = _create_storage_client()
        bucket_video = client_video.bucket("video_store_123")
        blob = bucket_video.blob(object_name)

        # UBLA bucket: do not call blob.make_public()
        blob.upload_from_file(file.file, content_type=file.content_type)

        url = blob.public_url
        

        existing_videos.append(
            {
                "description": description,
                "url": url,
            }
        )
        video_url_list[username] = existing_videos

        return {
            "username": username,
            "video_list": video_url_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
#--------------------------------------------STATUS--------------------------------------------

# upload status to online
# Use absolute credentials path so uploads work regardless of launch directory.





# creating a new storage client
def _create_storage_client():
    """Create and return a Google Cloud Storage client."""
    return storage.Client()





@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...), username: str = Form(None)):
    bucket_name = "storage-media-status"
    try:
        session_user = request.session.get("user")
        effective_user = session_user or username
        if not effective_user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        safe_filename = _sanitize_filename(file.filename or "upload")
        if not safe_filename:
            safe_filename = "upload"
        object_name = f"{effective_user}/{safe_filename}"

        client = _create_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)

        # Upload file. Do not use object ACLs because UBLA buckets disable them.
        blob.upload_from_file(file.file, content_type=file.content_type)

        blob_url = blob.public_url
        blob_list = _load_status_map()

        # Normalize existing user statuses to a list and append the new blob URL.
        existing_statuses = blob_list.get(effective_user, [])
        if isinstance(existing_statuses, str):
            existing_statuses = [existing_statuses]
        elif not isinstance(existing_statuses, list):
            existing_statuses = []
        existing_statuses.append(blob_url)
        blob_list[effective_user] = existing_statuses

        # Write updated data back
        logger.warning(f"[status] writing upload for user='{effective_user}' to {STATUS_FILE}")
        print(f"[status] writing upload for user='{effective_user}' to {STATUS_FILE}", flush=True)
        _save_status_map(blob_list)
        logger.warning(f"[status] write complete: total_statuses={len(blob_list.get(effective_user, []))}")
        print(
            f"[status] write complete: total_statuses={len(blob_list.get(effective_user, []))}",
            flush=True,
        )

        return {
            "filename": safe_filename,
            "username": effective_user,
            "url": blob_url,
        }

    except Exception as e:
        logger.exception("[status] upload failed")
        raise HTTPException(status_code=500, detail=str(e))


#delete the status 
@app.delete("/upload")
def delete_status():
    pass
    
#---------------------------------------------STATUS------------------------------------------------
#-----------------------------------------------------------------------------------------------


@app.get("/chat")
async def get_chat(request: Request):
    username = request.session.get("user")

    if not username:
        return RedirectResponse("/")

    display_users = [user for user in chatusers if user != username]

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "username": username,
            "userph": userph.get(username, "No phone number available"),
            "chatusers": display_users,
        },
    )


@app.get("/messages")
async def get_messages(request: Request):
    username = request.session.get("user")

    if not username:
        return RedirectResponse("/")

    path = BASE_DIR / "messages.json"
    if not path.exists():
        return JSONResponse([])

    try:
        all_messages = json.loads(path.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        all_messages = []

    filtered_messages = [
        msg
        for msg in all_messages
        if (
            msg.get("to") == "FamilyChat"
            or msg.get("to") == username
            or msg.get("from") == username
            or msg.get("username") == username
        )
    ]
    return JSONResponse(filtered_messages)


# ================= MESSAGE STORAGE ================= #

file_lock = asyncio.Lock()


async def save_message(data):
    path = BASE_DIR / "messages.json"

    def write_sync():
        if not path.exists():
            path.write_text("[]", encoding="utf-8")

        try:
            messages = json.loads(path.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            messages = []

        messages.append(data)

        path.write_text(json.dumps(messages, indent=2), encoding="utf-8")

    async with file_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, write_sync)


# ================= WEBSOCKET ================= #

@app.websocket("/ws")
async def chat(websocket: WebSocket):
    await websocket.accept()

    session = websocket.scope.get("session")
    username = session.get("user") if session else None

    # Block unauthorized access
    if not username:
        await websocket.close()
        return

    # Handle duplicate login (multi-tab)
    if username in ws_users:
        try:
            await ws_users[username].close()
        except Exception:
            pass

    ws_users[username] = websocket

    try:
        while True:
            data = await websocket.receive_json()

            if "message" not in data:
                continue

            await save_message(data)

            # Group chat
            if data.get("to") == "FamilyChat":
                for ws in list(ws_users.values()):
                    try:
                        await ws.send_json(data)
                    except Exception:
                        pass

            # Private chat
            else:
                receiver = data.get("to")

                if receiver in ws_users:
                    await ws_users[receiver].send_json(data)

    except WebSocketDisconnect:
        if username in ws_users:
            del ws_users[username]


