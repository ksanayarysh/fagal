from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated

router = APIRouter(prefix="/estoque")
templates = Jinja2Templates(directory="app/templates")

UNIT_LABEL = {"m2": "m²", "m3": "m³", "m": "m", "un": "un", "kg": "kg"}

@router.get("", response_class=HTMLResponse)
async def stock_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db

    materials = await pool.fetch(
        "SELECT id, name, category, unit, price, qty_stock FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    purchases = await pool.fetch(
        """SELECT p.*, m.name as material_name, m.unit
           FROM purchases p JOIN materials m ON m.id=p.material_id
           ORDER BY p.created_at DESC LIMIT 50"""
    )

    mats = []
    for m in materials:
        d = dict(m)
        d["price"] = float(d["price"])
        d["qty_stock"] = float(d["qty_stock"])
        d["unit_label"] = UNIT_LABEL.get(d["unit"], d["unit"])
        mats.append(d)

    purch = []
    for p in purchases:
        d = dict(p)
        d["unit_cost"] = float(d["unit_cost"])
        d["total_cost"] = float(d["total_cost"])
        d["qty"] = float(d["qty"])
        d["unit_label"] = UNIT_LABEL.get(d["unit"], d["unit"])
        purch.append(d)

    return templates.TemplateResponse("stock.html", {
        "request": request,
        "materials": mats,
        "purchases": purch,
    })

@router.post("/compra")
async def add_purchase(
    request: Request,
    material_id: int = Form(...),
    qty: float = Form(...),
    unit_cost: float = Form(...),
    supplier: str = Form(""),
    note: str = Form(""),
):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    total_cost = round(qty * unit_cost, 2)

    async with pool.acquire() as conn:
        purchase_id = await conn.fetchval(
            """INSERT INTO purchases (material_id, qty, unit_cost, total_cost, supplier, note)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            material_id, qty, round(unit_cost, 2), total_cost,
            supplier.strip() or None, note.strip() or None
        )
        await conn.execute(
            "UPDATE materials SET qty_stock = qty_stock + $1 WHERE id=$2",
            qty, material_id
        )
        await conn.execute(
            """INSERT INTO stock_movements (material_id, type, qty, ref_id, note)
               VALUES ($1,'purchase',$2,$3,$4)""",
            material_id, qty, purchase_id, supplier.strip() or None
        )

    return RedirectResponse("/estoque", status_code=303)

@router.post("/ajuste")
async def adjust_stock(
    request: Request,
    material_id: int = Form(...),
    qty: float = Form(...),
    note: str = Form(""),
):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE materials SET qty_stock = $1 WHERE id=$2",
            qty, material_id
        )
        await conn.execute(
            """INSERT INTO stock_movements (material_id, type, qty, note)
               VALUES ($1,'adjustment',$2,$3)""",
            material_id, qty, note.strip() or "Ajuste manual"
        )
    return RedirectResponse("/estoque", status_code=303)

@router.post("/compra/{purchase_id}/delete")
async def delete_purchase(request: Request, purchase_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM purchases WHERE id=$1", purchase_id)
        if p:
            await conn.execute(
                "UPDATE materials SET qty_stock = GREATEST(0, qty_stock - $1) WHERE id=$2",
                float(p["qty"]), p["material_id"]
            )
            await conn.execute("DELETE FROM purchases WHERE id=$1", purchase_id)
            await conn.execute(
                "DELETE FROM stock_movements WHERE ref_id=$1 AND type='purchase'",
                purchase_id
            )
    return RedirectResponse("/estoque", status_code=303)
