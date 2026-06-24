import json
import sys
import os

# Add the parent directory to sys.path so we can import the api module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app

def generate():
    openapi_schema = app.openapi()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    print(f"OpenAPI schema generated and saved to {output_path}")

if __name__ == "__main__":
    generate()
