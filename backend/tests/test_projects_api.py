import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db.database import init_db


@pytest.fixture
def client_with_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig_path = settings.DATABASE_PATH
    settings.DATABASE_PATH = path
    init_db(db_path=path)

    from app.db.database import get_connection

    now = "2026-11-15T00:00:00.000Z"
    expires = "2026-11-25T00:00:00.000Z"
    with get_connection(path) as conn:
        conn.execute(
            "INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_test_123", "Test Architect", "architect@buildwise.ai", 1, now, now),
        )
        conn.execute(
            "INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_test_123", expires, "valid_test_token_abc", now, now, "user_test_123"),
        )
        conn.commit()

    with TestClient(app, cookies={"better-auth.session_token": "valid_test_token_abc.signature_xyz"}) as client:
        yield client

    settings.DATABASE_PATH = orig_path
    try:
        os.remove(path)
    except OSError:
        pass


def test_project_api_lifecycle(client_with_db):
    client = client_with_db

    # 1. Create project
    create_payload = {
        "name": "Jayanagar Residential Villa",
        "description": "South-facing 30x40 site",
        "latitude": 12.9250,
        "longitude": 77.5938,
        "formatted_address": "4th Block, Jayanagar, Bengaluru",
        "building_typology": "residential_single",
        "floors": 2,
        "built_up_area_sqft": 2400.0,
        "composite_score": 88.0,
        "total_cost_inr": 7200000.0,
        "is_bookmarked": True,
        "parameters": {
            "built_up_area_sqft": 2400,
            "quality_grade": "premium",
            "building_typology": "residential_single",
            "floors": 2,
            "ground_coverage_ratio": 0.6,
        },
        "boundary": {
            "origin": {"lat": 12.9250, "lon": 77.5938},
            "polygon": [{"lat": 12.9250, "lng": 77.5938}, {"lat": 12.9251, "lng": 77.5939}],
        },
        "analysis_data": {
            "composite_feasibility_score": 88.0,
        },
    }

    resp = client.post("/api/projects", json=create_payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"].startswith("proj_")
    assert created["name"] == "Jayanagar Residential Villa"
    assert created["is_bookmarked"] is True
    project_id = created["id"]

    # 2. List projects
    list_resp = client.get("/api/projects")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] == 1
    assert len(list_data["items"]) == 1
    assert list_data["items"][0]["id"] == project_id
    assert list_data["items"][0]["name"] == "Jayanagar Residential Villa"

    # Filter with bookmarks
    bm_resp = client.get("/api/projects?bookmarked=true")
    assert bm_resp.status_code == 200
    assert bm_resp.json()["total"] == 1

    # Search filter
    search_resp = client.get("/api/projects?search=Jayanagar")
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1

    # Search no match
    no_match_resp = client.get("/api/projects?search=NonexistentPlace123")
    assert no_match_resp.status_code == 200
    assert no_match_resp.json()["total"] == 0

    # 3. Retrieve project by ID
    get_resp = client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == project_id
    assert detail["boundary"]["origin"]["lat"] == 12.9250
    assert detail["parameters"]["quality_grade"] == "premium"

    # 4. Attempting to create a duplicate project with same name returns 409 Conflict
    dup_resp = client.post("/api/projects", json=create_payload)
    assert dup_resp.status_code == 409
    dup_detail = dup_resp.json()["detail"]
    assert dup_detail["code"] == "PROJECT_NAME_EXISTS"
    assert dup_detail["existing_id"] == project_id

    # 5. Saving with overwrite=true updates existing project
    create_payload["description"] = "Overwritten description"
    overwrite_resp = client.post("/api/projects?overwrite=true", json=create_payload)
    assert overwrite_resp.status_code == 201
    assert overwrite_resp.json()["id"] == project_id
    assert overwrite_resp.json()["description"] == "Overwritten description"

    # 6. Patch project
    patch_payload = {
        "name": "Updated Jayanagar Villa Study",
        "is_bookmarked": False,
    }
    patch_resp = client.patch(f"/api/projects/{project_id}", json=patch_payload)
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["name"] == "Updated Jayanagar Villa Study"
    assert patched["is_bookmarked"] is False

    # 7. Delete project
    del_resp = client.delete(f"/api/projects/{project_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 8. Verify 404 after deletion
    get_deleted = client.get(f"/api/projects/{project_id}")
    assert get_deleted.status_code == 404
