from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated
import json

router = APIRouter(prefix="/vendas")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
async def list_sales(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    sales = await pool.fetch(
        "SELECT * FROM sales ORDER BY created_at DESC LIMIT 100"
    )
    # total do mês
    month_total = await pool.fetchval(
        "SELECT COALESCE(SUM(total),0) FROM sales WHERE date_trunc('month',created_at)=date_trunc('month',NOW())"
    )
    return templates.TemplateResponse("sales.html", {
        "request": request,
        "sales": [dict(s) for s in sales],
        "month_total": float(month_total),
    })

@router.get("/nova", response_class=HTMLResponse)
async def new_sale_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    materials = await pool.fetch(
        "SELECT id, name, category, unit, price FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    mats = []
    for m in materials:
        d = dict(m)
        d["price"] = float(d["price"])
        mats.append(d)
    return templates.TemplateResponse("sale_new.html", {
        "request": request,
        "materials": mats,
    })

@router.post("/nova")
async def create_sale(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    body = await request.json()
    client = body.get("client","").strip()
    note = body.get("note","").strip()
    items = body.get("items", [])
    paid = body.get("paid", False)

    if not client or not items:
        return JSONResponse({"error": "Dados incompletos"}, status_code=400)

    total = sum(i["subtotal"] for i in items)

    pool = request.app.state.db
    async with pool.acquire() as conn:
        sale_id = await conn.fetchval(
            "INSERT INTO sales (client_name, note, total, paid) VALUES ($1,$2,$3,$4) RETURNING id",
            client, note, round(total,2), paid
        )
        for item in items:
            await conn.execute(
                """INSERT INTO sale_items
                   (sale_id, material_id, material_name, unit, qty, unit_price, subtotal)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                sale_id,
                item.get("material_id"),
                item["material_name"],
                item["unit"],
                float(item["qty"]),
                float(item["unit_price"]),
                round(float(item["subtotal"]),2),
            )

    return JSONResponse({"ok": True, "sale_id": sale_id})

@router.get("/{sale_id}", response_class=HTMLResponse)
async def sale_detail(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    sale = await pool.fetchrow("SELECT * FROM sales WHERE id=$1", sale_id)
    if not sale:
        return RedirectResponse("/vendas")
    items = await pool.fetch("SELECT * FROM sale_items WHERE sale_id=$1", sale_id)
    return templates.TemplateResponse("sale_detail.html", {
        "request": request,
        "sale": dict(sale),
        "items": [dict(i) for i in items],
    })

@router.post("/{sale_id}/paid")
async def toggle_paid(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute(
        "UPDATE sales SET paid = NOT paid WHERE id=$1", sale_id
    )
    return RedirectResponse(f"/vendas/{sale_id}", status_code=303)

@router.post("/{sale_id}/delete")
async def delete_sale(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute("DELETE FROM sales WHERE id=$1", sale_id)
    return RedirectResponse("/vendas", status_code=303)
