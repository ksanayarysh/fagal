from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import asyncpg, os

from app.routers import materials, sales, auth, stock, categories

DATABASE_URL = os.environ["DATABASE_URL"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await run_migrations(app.state.db)
    yield
    await app.state.db.close()

async def run_migrations(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Geral',
                unit TEXT NOT NULL CHECK (unit IN ('m2','m3','m','un','kg')),
                price NUMERIC(10,2) NOT NULL,
                qty_stock NUMERIC(10,4) NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                client_name TEXT NOT NULL,
                note TEXT,
                labor NUMERIC(10,2) NOT NULL DEFAULT 0,
                labor_desc TEXT,
                total NUMERIC(10,2) NOT NULL,
                paid BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sale_items (
                id SERIAL PRIMARY KEY,
                sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
                material_id INTEGER REFERENCES materials(id),
                material_name TEXT NOT NULL,
                unit TEXT NOT NULL,
                qty NUMERIC(10,4) NOT NULL,
                unit_price NUMERIC(10,2) NOT NULL,
                subtotal NUMERIC(10,2) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                qty NUMERIC(10,4) NOT NULL,
                unit_cost NUMERIC(10,2) NOT NULL,
                total_cost NUMERIC(10,2) NOT NULL,
                supplier TEXT,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS stock_movements (
                id SERIAL PRIMARY KEY,
                material_id INTEGER NOT NULL REFERENCES materials(id),
                type TEXT NOT NULL CHECK (type IN ('purchase','sale','adjustment')),
                qty NUMERIC(10,4) NOT NULL,
                ref_id INTEGER,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

        """)
        # run column additions separately so they always execute
        await conn.execute("ALTER TABLE materials ADD COLUMN IF NOT EXISTS qty_stock NUMERIC(10,4) NOT NULL DEFAULT 0")
        await conn.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS labor NUMERIC(10,2) NOT NULL DEFAULT 0")
        await conn.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS labor_desc TEXT")
        await conn.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS is_orcamento BOOLEAN NOT NULL DEFAULT FALSE")
        await conn.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS phone TEXT")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS address TEXT")

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(materials.router)
app.include_router(sales.router)
app.include_router(stock.router)
app.include_router(categories.router)

@app.get("/")
async def root():
    return RedirectResponse("/vendas")
