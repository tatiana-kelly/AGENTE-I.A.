from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import actions, alerts, decisions, diagnoses, recommendations
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SAL Intelligence OS",
    description="Fila de decisões executivas — desvio -> causa -> impacto -> prioridade -> solução -> execução.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(alerts.router)
app.include_router(diagnoses.router)
app.include_router(recommendations.router)
app.include_router(decisions.router)
app.include_router(actions.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
