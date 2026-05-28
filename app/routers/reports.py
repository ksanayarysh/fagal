from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import is_authenticated
from datetime import date, timedelta

router = APIRouter(prefix="/relatorios")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
async def reports_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login")
    from fastapi.responses import RedirectResponse
    pool = request.app.state.db

    today = date.today()
    start_month = today.replace(day=1)
    start_week = today - timedelta(days=today.weekday())
    yesterday = today - timedelta(days=1)

    async with pool.acquire() as conn:
        # ── KPIs ──
        today_rev = await conn.fetchval(
            "SELECT COALESCE(SUM(total),0) FROM sales WHERE DATE(created_at)=$1 AND is_orcamento IS NOT TRUE", today)
        week_rev = await conn.fetchval(
            "SELECT COALESCE(SUM(total),0) FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE", start_week)
        month_rev = await conn.fetchval(
            "SELECT COALESCE(SUM(total),0) FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE", start_month)
        month_count = await conn.fetchval(
            "SELECT COUNT(*) FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE", start_month)
        avg_ticket = float(month_rev) / month_count if month_count else 0

        # avg daily (7 days)
        avg7 = await conn.fetchval(
            "SELECT COALESCE(SUM(total),0)/7.0 FROM sales WHERE created_at >= NOW()-INTERVAL '7 days' AND is_orcamento IS NOT TRUE")

        # ── Daily revenue this month ──
        daily_rows = await conn.fetch(
            """SELECT DATE(created_at) as d, SUM(total) as rev, COUNT(*) as cnt
               FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE
               GROUP BY DATE(created_at) ORDER BY d""", start_month)
        daily = [{"d": r["d"].day, "rev": float(r["rev"]), "cnt": r["cnt"]} for r in daily_rows]

        # ── Monthly comparison (6 months) ──
        monthly_rows = await conn.fetch(
            """SELECT DATE_TRUNC('month', created_at) as m, SUM(total) as rev, COUNT(*) as cnt
               FROM sales WHERE created_at >= NOW()-INTERVAL '6 months' AND is_orcamento IS NOT TRUE
               GROUP BY m ORDER BY m""")
        monthly = [{"m": r["m"].strftime("%b/%Y"), "rev": float(r["rev"]), "cnt": r["cnt"]} for r in monthly_rows]

        # ── By section ──
        section_rows = await conn.fetch(
            """SELECT si.section_name, SUM(si.subtotal) as rev, COUNT(DISTINCT si.sale_id) as cnt
               FROM sale_items si JOIN sales s ON s.id=si.sale_id
               WHERE DATE(s.created_at)>=$1 AND s.is_orcamento IS NOT TRUE AND si.section_name IS NOT NULL
               GROUP BY si.section_name ORDER BY rev DESC LIMIT 10""", start_month)
        by_section = [{"name": r["section_name"], "rev": float(r["rev"]), "cnt": r["cnt"]} for r in section_rows]

        # ── Top materials ──
        top_mats = await conn.fetch(
            """SELECT si.material_name, SUM(si.subtotal) as rev, SUM(si.qty) as qty, si.unit
               FROM sale_items si JOIN sales s ON s.id=si.sale_id
               WHERE DATE(s.created_at)>=$1 AND s.is_orcamento IS NOT TRUE
               GROUP BY si.material_name, si.unit ORDER BY rev DESC LIMIT 10""", start_month)
        top_materials = [{"name": r["material_name"], "rev": float(r["rev"]), "qty": float(r["qty"]), "unit": r["unit"]} for r in top_mats]

        # ── Top clients ──
        top_clients = await conn.fetch(
            """SELECT client_name, SUM(total) as rev, COUNT(*) as cnt
               FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE
               GROUP BY client_name ORDER BY rev DESC LIMIT 10""", start_month)
        clients = [{"name": r["client_name"], "rev": float(r["rev"]), "cnt": r["cnt"]} for r in top_clients]

        # ── By weekday ──
        weekday_rows = await conn.fetch(
            """SELECT EXTRACT(DOW FROM created_at) as dow, SUM(total) as rev
               FROM sales WHERE created_at >= NOW()-INTERVAL '90 days' AND is_orcamento IS NOT TRUE
               GROUP BY dow ORDER BY dow""")
        dow_map = {int(r["dow"]): float(r["rev"]) for r in weekday_rows}
        days_pt = ["Dom","Seg","Ter","Qua","Qui","Sex","Sáb"]
        by_weekday = [{"d": days_pt[i], "rev": dow_map.get(i, 0)} for i in range(7)]

        # ── Lucro estimado ──
        profit_row = await conn.fetchrow(
            """SELECT
                COALESCE(SUM(si.subtotal), 0) as revenue,
                COALESCE(SUM(si.qty * m.purchase_price), 0) as cost,
                COALESCE(SUM(s.labor), 0) as labor
               FROM sale_items si
               JOIN sales s ON s.id = si.sale_id
               LEFT JOIN materials m ON m.id = si.material_id
               WHERE DATE(s.created_at) >= $1
               AND s.is_orcamento IS NOT TRUE
               AND m.purchase_price IS NOT NULL""", start_month)
        profit_revenue = float(profit_row["revenue"] or 0)
        profit_cost = float(profit_row["cost"] or 0)
        profit_labor = float(profit_row["labor"] or 0)
        profit_est = profit_revenue - profit_cost + profit_labor

        # revenue without cost (items sem preço de compra)
        rev_no_cost = await conn.fetchval(
            """SELECT COALESCE(SUM(si.subtotal), 0)
               FROM sale_items si
               JOIN sales s ON s.id = si.sale_id
               LEFT JOIN materials m ON m.id = si.material_id
               WHERE DATE(s.created_at) >= $1
               AND s.is_orcamento IS NOT TRUE
               AND m.purchase_price IS NULL""", start_month)

        # ── Mão de obra vs materiais ──
        labor_total = await conn.fetchval(
            "SELECT COALESCE(SUM(labor),0) FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE AND labor>0", start_month)
        mat_total_month = await conn.fetchval(
            "SELECT COALESCE(SUM(total-labor),0) FROM sales WHERE DATE(created_at)>=$1 AND is_orcamento IS NOT TRUE", start_month)

        # ── Pending (orçamentos) ──
        pending = await conn.fetch(
            "SELECT * FROM sales WHERE (is_orcamento IS TRUE OR paid IS FALSE) AND is_orcamento IS NOT TRUE ORDER BY created_at DESC LIMIT 10")
        orcamentos = await conn.fetch(
            "SELECT * FROM sales WHERE is_orcamento IS TRUE ORDER BY created_at DESC LIMIT 10")

    max_daily = max((d["rev"] for d in daily), default=1)
    max_monthly = max((m["rev"] for m in monthly), default=1)
    max_weekday = max((d["rev"] for d in by_weekday), default=1)

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "today_rev": float(today_rev),
        "week_rev": float(week_rev),
        "month_rev": float(month_rev),
        "month_count": month_count,
        "avg_ticket": avg_ticket,
        "avg7": float(avg7 or 0),
        "daily": daily,
        "max_daily": max_daily,
        "monthly": monthly,
        "max_monthly": max_monthly,
        "by_section": by_section,
        "top_materials": top_materials,
        "clients": clients,
        "by_weekday": by_weekday,
        "max_weekday": max_weekday,
        "labor_total": float(labor_total),
        "mat_total_month": float(mat_total_month),
        "profit_est": profit_est,
        "profit_revenue": profit_revenue,
        "profit_cost": profit_cost,
        "rev_no_cost": float(rev_no_cost or 0),
        "pending": [dict(r) for r in pending],
        "orcamentos": [dict(r) for r in orcamentos],
        "today": today,
        "start_month": start_month,
    })
