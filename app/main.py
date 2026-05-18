from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import asyncpg, os

from app.routers import materials, sales, auth

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
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                client_name TEXT NOT NULL,
                note TEXT,
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
        """)

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(materials.router)
app.include_router(sales.router)

@app.get("/")
async def root():
    return RedirectResponse("/vendas")
