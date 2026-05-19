from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated

router = APIRouter(prefix="/categorias")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
async def list_categories(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    cats = await pool.fetch("SELECT * FROM categories ORDER BY name")
    return templates.TemplateResponse("categories.html", {
        "request": request,
        "cats": [dict(c) for c in cats],
    })

@router.post("/add")
async def add_category(request: Request, name: str = Form(...)):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute(
        "INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
        name.strip()
    )
    return RedirectResponse("/categorias", status_code=303)

@router.post("/{cat_id}/edit")
async def edit_category(request: Request, cat_id: int, name: str = Form(...)):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute("UPDATE categories SET name=$1 WHERE id=$2", name.strip(), cat_id)
    return RedirectResponse("/categorias", status_code=303)

@router.post("/{cat_id}/delete")
async def delete_category(request: Request, cat_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    # check if in use
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM materials WHERE category=(SELECT name FROM categories WHERE id=$1) AND active=TRUE",
        cat_id
    )
    if count > 0:
        cats = await pool.fetch("SELECT * FROM categories ORDER BY name")
        return templates.TemplateResponse("categories.html", {
            "request": request,
            "cats": [dict(c) for c in cats],
            "error": f"Categoria em uso por {count} material(is). Remova os materiais primeiro."
        })
    await pool.execute("DELETE FROM categories WHERE id=$1", cat_id)
    return RedirectResponse("/categorias", status_code=303)

@router.get("/api/list")
async def api_categories(request: Request):
    if not is_authenticated(request):
        return {"error": "unauthorized"}
    pool = request.app.state.db
    cats = await pool.fetch("SELECT id, name FROM categories ORDER BY name")
    return [dict(c) for c in cats]
