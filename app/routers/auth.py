from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import os, hashlib

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "fagal2025")
SESSION_TOKEN = hashlib.sha256(MASTER_PASSWORD.encode()).hexdigest()

def is_authenticated(request: Request) -> bool:
    return request.cookies.get("session") == SESSION_TOKEN

def require_auth(request: Request):
    if not is_authenticated(request):
        raise Exception("not_authenticated")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@router.post("/login")
async def login(request: Request, password: str = Form("")):
    if not password:
        return RedirectResponse("/login?error=vazio", status_code=303)
    if password == MASTER_PASSWORD:
        response = RedirectResponse("/vendas", status_code=303)
        response.set_cookie("session", SESSION_TOKEN, httponly=True, max_age=86400*30)
        return response
    return RedirectResponse("/login?error=senha", status_code=303)

@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response
