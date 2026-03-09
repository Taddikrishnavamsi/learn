from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(directory=str(BASE_DIR))
router=APIRouter()


@router.get("/")
async def get():
    return HTMLResponse((BASE_DIR / "templetes/login.html").read_text(encoding="utf-8"))


@router.get("/login")
async def get_login():
    return HTMLResponse((BASE_DIR / "templetes/login.html").read_text(encoding="utf-8"))


@router.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session")
    return response

@router.get("/index")
async def get_index(request: Request):
    username = request.session.get("user")

    if not username:
        return RedirectResponse("/")

    return templates.TemplateResponse(
        "templetes/index.html",
        {
            "request": request,
            "username": username,
        },
    )


#videos page redirect
@router.get("/videos")
async def get_videos(request:Request):
    username = request.session.get("user")
    if not username:
        return RedirectResponse("/")
    return templates.TemplateResponse(
        "templetes/videos.html",
        {
            "request": request,
            "username": username,
        },
    )