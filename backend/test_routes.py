"""Test script to check registered routes"""
import sys
sys.path.insert(0, '.')

from app.main import app

print("=== All Registered Routes ===")
for route in app.routes:
    if hasattr(route, 'path'):
        methods = getattr(route, 'methods', [])
        print(f"{methods} {route.path}")
    else:
        print(f"  {route}")

print("\n=== Looking for /api/auth routes ===")
auth_routes = [r for r in app.routes if hasattr(r, 'path') and '/auth' in r.path]
print(f"Found {len(auth_routes)} auth routes:")
for r in auth_routes:
    print(f"  {getattr(r, 'methods', [])} {r.path}")
