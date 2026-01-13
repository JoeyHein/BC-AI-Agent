"""Simple test server to verify auth endpoints work"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import the auth router
from app.api import auth

app = FastAPI(title="Test Server")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include auth router
print(f"Including auth router: {auth.router.prefix}")
app.include_router(auth.router)
print(f"Total routes: {len(app.routes)}")

@app.get("/")
def root():
    return {"message": "Test server", "routes": len(app.routes)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
