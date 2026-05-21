from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated

router = APIRouter(prefix="/vendas")
templates = Jinja2Templates(directory="app/templates")

UNIT_LABEL = {"m2": "m²", "m3": "m³", "m": "m", "un": "un", "kg": "kg"}

@router.get("", response_class=HTMLResponse)
async def list_sales(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    sales = await pool.fetch("SELECT * FROM sales ORDER BY created_at DESC LIMIT 100")
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
        "SELECT id, name, category, unit, price, qty_stock FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    mats = []
    for m in materials:
        d = dict(m)
        d["price"] = float(d["price"])
        d["qty_stock"] = float(d["qty_stock"])
        mats.append(d)
    return templates.TemplateResponse("sale_new.html", {
        "request": request,
        "materials": mats,
        "page_title": "Nova venda",
        "page_subtitle": "Busque materiais e monte o carrinho",
        "edit_sale_id": None,
        "prefill": None,
    })

@router.post("/nova")
async def create_sale(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    body = await request.json()
    client = body.get("client", "").strip()
    note = body.get("note", "").strip()
    items = body.get("items", [])
    paid = body.get("paid", False)
    labor = float(body.get("labor", 0) or 0)
    labor_desc = body.get("labor_desc", "").strip()
    orcamento = body.get("orcamento", False)
    phone = body.get("phone", "").strip()
    address = body.get("address", "").strip()

    if not client or not items:
        return JSONResponse({"error": "Dados incompletos"}, status_code=400)

    materials_total = sum(float(i["subtotal"]) for i in items)
    total = round(materials_total + labor, 2)
    # orçamento = not paid, no stock deduction
    is_paid = False if orcamento else paid

    pool = request.app.state.db
    async with pool.acquire() as conn:
        sale_id = await conn.fetchval(
            """INSERT INTO sales (client_name, note, phone, address, labor, labor_desc, total, paid, is_orcamento)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
            client, note or None, phone or None, address or None, round(labor, 2), labor_desc or None, total, is_paid, orcamento
        )
        for item in items:
            mid = item.get("material_id")
            qty = float(item["qty"])
            await conn.execute(
                """INSERT INTO sale_items
                   (sale_id, material_id, material_name, unit, qty, unit_price, subtotal, section_name)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                sale_id, mid, item["material_name"], item["unit"],
                qty, float(item["unit_price"]), round(float(item["subtotal"]), 2),
                item.get("section_name") or None,
            )
            # deduct from stock only for real sales, not orçamentos
            if mid and not orcamento:
                await conn.execute(
                    "UPDATE materials SET qty_stock = GREATEST(0, qty_stock - $1) WHERE id=$2",
                    qty, mid
                )
                await conn.execute(
                    """INSERT INTO stock_movements (material_id, type, qty, ref_id, note)
                       VALUES ($1,'sale',$2,$3,$4)""",
                    mid, qty, sale_id, client
                )

    return JSONResponse({"ok": True, "sale_id": sale_id})

@router.get("/{sale_id}/editar", response_class=HTMLResponse)
async def edit_sale_page(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    sale = await pool.fetchrow("SELECT * FROM sales WHERE id=$1", sale_id)
    if not sale or (not sale["is_orcamento"] and sale["paid"]):
        return RedirectResponse(f"/vendas/{sale_id}")
    sale_items = await pool.fetch("SELECT * FROM sale_items WHERE sale_id=$1", sale_id)
    materials = await pool.fetch(
        "SELECT id, name, category, unit, price, qty_stock FROM materials WHERE active=TRUE ORDER BY category, name"
    )
    mats = []
    for m in materials:
        d = dict(m)
        d["price"] = float(d["price"])
        d["qty_stock"] = float(d["qty_stock"])
        mats.append(d)

    prefill = {
        "client": sale["client_name"],
        "phone": sale["phone"] or "",
        "address": sale["address"] or "",
        "note": sale["note"] or "",
        "labor": float(sale["labor"] or 0),
        "labor_desc": sale["labor_desc"] or "",
        "items": [{
            "material_id": i["material_id"],
            "material_name": i["material_name"],
            "unit": i["unit"],
            "unit_price": float(i["unit_price"]),
            "qty": float(i["qty"]),
            "subtotal": float(i["subtotal"]),
            "section_name": i["section_name"] if i["section_name"] else i["material_name"],
            "length": 1, "width": 1, "height": 1,
        } for i in sale_items]
    }
    return templates.TemplateResponse("sale_new.html", {
        "request": request,
        "materials": mats,
        "page_title": f"Editar orçamento #{sale_id}",
        "page_subtitle": "Altere os itens e salve",
        "edit_sale_id": sale_id,
        "prefill": prefill,
    })

@router.post("/{sale_id}/editar")
async def update_sale(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    body = await request.json()
    client = body.get("client", "").strip()
    note = body.get("note", "").strip()
    items = body.get("items", [])
    paid = body.get("paid", False)
    labor = float(body.get("labor", 0) or 0)
    labor_desc = body.get("labor_desc", "").strip()
    orcamento = body.get("orcamento", False)
    phone = body.get("phone", "").strip()
    address = body.get("address", "").strip()

    if not client or not items:
        return JSONResponse({"error": "Dados incompletos"}, status_code=400)

    materials_total = sum(float(i["subtotal"]) for i in items)
    total = round(materials_total + labor, 2)
    is_paid = False if orcamento else paid

    pool = request.app.state.db
    async with pool.acquire() as conn:
        # restore old stock before updating
        old_items = await conn.fetch("SELECT * FROM sale_items WHERE sale_id=$1", sale_id)
        old_sale = await conn.fetchrow("SELECT is_orcamento FROM sales WHERE id=$1", sale_id)
        if old_sale and not old_sale["is_orcamento"]:
            for oi in old_items:
                if oi["material_id"]:
                    await conn.execute(
                        "UPDATE materials SET qty_stock = qty_stock + $1 WHERE id=$2",
                        float(oi["qty"]), oi["material_id"]
                    )

        await conn.execute(
            """UPDATE sales SET client_name=$1, note=$2, phone=$3, address=$4,
               labor=$5, labor_desc=$6, total=$7, paid=$8, is_orcamento=$9
               WHERE id=$10""",
            client, note or None, phone or None, address or None,
            round(labor, 2), labor_desc or None, total, is_paid, orcamento, sale_id
        )
        await conn.execute("DELETE FROM sale_items WHERE sale_id=$1", sale_id)
        for item in items:
            mid = item.get("material_id")
            qty = float(item["qty"])
            await conn.execute(
                """INSERT INTO sale_items
                   (sale_id, material_id, material_name, unit, qty, unit_price, subtotal, section_name)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                sale_id, mid, item["material_name"], item["unit"],
                qty, float(item["unit_price"]), round(float(item["subtotal"]), 2),
                item.get("section_name") or None,
            )
            if mid and not orcamento:
                await conn.execute(
                    "UPDATE materials SET qty_stock = GREATEST(0, qty_stock - $1) WHERE id=$2",
                    qty, mid
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
    sale_d = dict(sale)
    sale_d["labor"] = float(sale_d.get("labor") or 0)
    sale_d["total"] = float(sale_d.get("total") or 0)
    return templates.TemplateResponse("sale_detail.html", {
        "request": request,
        "sale": sale_d,
        "items": [dict(i) for i in items],
        "unit_label": UNIT_LABEL,
    })

@router.post("/{sale_id}/paid")
async def toggle_paid(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute("UPDATE sales SET paid = NOT paid, is_orcamento = FALSE WHERE id=$1", sale_id)
    return RedirectResponse(f"/vendas/{sale_id}", status_code=303)

@router.post("/{sale_id}/delete")
async def delete_sale(request: Request, sale_id: int):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    pool = request.app.state.db
    await pool.execute("DELETE FROM sales WHERE id=$1", sale_id)
    return RedirectResponse("/vendas", status_code=303)
