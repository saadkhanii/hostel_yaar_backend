from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth
from app.routers import auth, hostels

# Creates tables if they don't exist yet. Fine for now; once this app is
# in production you'd switch to Alembic migrations instead.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Hostel Yaar API")

# Allows your Flutter app (mobile/web) to call this backend during dev.
# Tighten this to your real domain(s) before going to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(hostels.router)


@app.get("/")
def root():
    return {"status": "Hostel Yaar API is running"}
