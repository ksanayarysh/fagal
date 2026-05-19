from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated

router = APIRouter(prefix="/materiais")
templates = Jinja2Templates(directory="app/templates")

UNITS = {"m2": "m²", "m3": "m³", "m": "m", "un": "un", "kg": "kg"}
UNIT_LABELS = [("m2","m² — metros quadrados"), ("m3","m³ — metros cúbicos"),
               ("m","m — metros lineares"), ("un","un — unidade"), ("kg","kg — quilograma")]

@router.get("", response_class=HTMLResponse)
async def list_materials(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    rows = await pool.fetch(
        "SELECT * FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    # group by category
    cats = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(dict(r))
    categories = await pool.fetch("SELECT id, name FROM categories ORDER BY name")
    return templates.TemplateResponse("materials.html", {
        "request": request, "cats": cats, "unit_labels": UNIT_LABELS, "units": UNITS,
        "categories": [dict(c) for c in categories],
    })

@router.post("/add")
async def add_material(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    price: float = Form(...),
):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute(
        "INSERT INTO materials (name, category, unit, price) VALUES ($1,$2,$3,$4)",
        name.strip(), category.strip(), unit, round(price, 2)
    )
    return RedirectResponse("/materiais", status_code=303)

@router.post("/{mid}/edit")
async def edit_material(
    request: Request, mid: int,
    name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    price: float = Form(...),
):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute(
        "UPDATE materials SET name=$1, category=$2, unit=$3, price=$4 WHERE id=$5",
        name.strip(), category.strip(), unit, round(price, 2), mid
    )
    return RedirectResponse("/materiais", status_code=303)

@router.post("/{mid}/delete")
async def delete_material(request: Request, mid: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute("UPDATE materials SET active=FALSE WHERE id=$1", mid)
    return RedirectResponse("/materiais", status_code=303)

@router.get("/api/list")
async def api_materials(request: Request):
    if not is_authenticated(request):
        return {"error": "unauthorized"}
    pool = request.app.state.db
    rows = await pool.fetch(
        "SELECT id, name, category, unit, price FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    result = []
    for r in rows:
        d = dict(r)
        d.pop("created_at", None)
        result.append(d)
    return result
