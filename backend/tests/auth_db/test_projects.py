from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import get_connection, init_db
from app.db.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate


@pytest.fixture
def temp_db(temp_db_path):
    init_db(db_path=temp_db_path)
    return temp_db_path


@pytest.fixture
def client_with_db(isolated_db):
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires = (now_dt + timedelta(days=7)).isoformat()
    with get_connection(isolated_db) as conn:
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


def test_create_and_get_project(temp_db):
    req = ProjectCreate(
        name="Indiranagar Feasibility Study",
        description="Corner plot facing 12m road",
        latitude=12.9716,
        longitude=77.5946,
        formatted_address="Indiranagar, Bengaluru, Karnataka, India",
        parameters={
            "built_up_area_sqft": 2400,
            "quality_grade": "premium",
            "building_typology": "residential_single",
            "floors": 2,
            "ground_coverage_ratio": 0.6,
        },
        boundary={
            "polygon": [{"lat": 12.9716, "lng": 77.5946}, {"lat": 12.9717, "lng": 77.5947}],
            "area_sqm": 250.0,
        },
        analysis_data={
            "composite_feasibility_score": 84.5,
            "cost_estimate": {"total_cost_inr": 8500000.0},
        },
        is_bookmarked=True,
    )

    created = ProjectRepository.create(req, db_path=temp_db)
    assert created.id.startswith("proj_")
    assert created.name == "Indiranagar Feasibility Study"
    assert created.description == "Corner plot facing 12m road"
    assert created.is_bookmarked is True
    assert created.floors == 2
    assert created.building_typology == "residential_single"
    assert created.composite_score == 84.5
    assert created.total_cost_inr == 8500000.0
    assert created.boundary["area_sqm"] == 250.0

    retrieved = ProjectRepository.get_by_id(created.id, db_path=temp_db)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.name == created.name
    assert retrieved.boundary == created.boundary
    assert retrieved.parameters["quality_grade"] == "premium"


def test_list_and_filter_projects(temp_db):
    p1 = ProjectRepository.create(
        ProjectCreate(
            name="Whitefield Villa",
            latitude=12.9698,
            longitude=77.7500,
            parameters={"floors": 3, "building_typology": "residential_multi"},
            is_bookmarked=False,
        ),
        db_path=temp_db,
    )
    p2 = ProjectRepository.create(
        ProjectCreate(
            name="Koramangala Commercial",
            latitude=12.9352,
            longitude=77.6245,
            parameters={"floors": 4, "building_typology": "commercial"},
            is_bookmarked=True,
        ),
        db_path=temp_db,
    )

    all_items, total = ProjectRepository.list(db_path=temp_db)
    assert total == 2
    assert len(all_items) == 2
    # Bookmarked items should appear first
    assert all_items[0].id == p2.id

    bookmarked_items, b_total = ProjectRepository.list(bookmarked_only=True, db_path=temp_db)
    assert b_total == 1
    assert bookmarked_items[0].name == "Koramangala Commercial"

    searched_items, s_total = ProjectRepository.list(search="Whitefield", db_path=temp_db)
    assert s_total == 1
    assert searched_items[0].id == p1.id


def test_update_and_delete_project(temp_db):
    created = ProjectRepository.create(
        ProjectCreate(
            name="Initial Title",
            latitude=13.0,
            longitude=77.0,
            parameters={},
            is_bookmarked=False,
        ),
        db_path=temp_db,
    )

    updated = ProjectRepository.update(
        created.id,
        ProjectUpdate(name="Renamed Title", is_bookmarked=True),
        db_path=temp_db,
    )
    assert updated is not None
    assert updated.name == "Renamed Title"
    assert updated.is_bookmarked is True

    deleted = ProjectRepository.delete(created.id, db_path=temp_db)
    assert deleted is True

    assert ProjectRepository.get_by_id(created.id, db_path=temp_db) is None


def test_duplicate_name_rejection_and_overwrite(temp_db):
    req1 = ProjectCreate(
        name="Indiranagar Study",
        latitude=12.97,
        longitude=77.59,
        parameters={"floors": 1},
        is_bookmarked=False,
    )
    p1 = ProjectRepository.create(req1, db_path=temp_db)
    assert p1.name == "Indiranagar Study"

    # Saving again with the same name without overwrite must raise ValueError
    req2 = ProjectCreate(
        name="  Indiranagar Study  ",
        latitude=12.97,
        longitude=77.59,
        parameters={"floors": 2},
        is_bookmarked=True,
    )
    with pytest.raises(ValueError) as excinfo:
        ProjectRepository.create(req2, overwrite=False, db_path=temp_db)
    assert "PROJECT_EXISTS:" in str(excinfo.value)

    # Saving with overwrite=True updates the existing project without creating a duplicate row
    p1_updated = ProjectRepository.create(req2, overwrite=True, db_path=temp_db)
    assert p1_updated.id == p1.id
    assert p1_updated.floors == 2
    assert p1_updated.is_bookmarked is True

    items, total = ProjectRepository.list(db_path=temp_db)
    assert total == 1


def test_analysis_data_metric_fallbacks(temp_db):
    req = ProjectCreate(
        name="Fallback Metrics Study",
        latitude=12.97,
        longitude=77.59,
        parameters={"floors": 1},
        analysis_data={
            "overall_suitability_score": 77.5,
            "cost_estimate": {
                "total_estimated_cost_inr": 4500000.0,
            },
        },
    )
    p = ProjectRepository.create(req, db_path=temp_db)
    assert p.composite_score == 77.5
    assert p.total_cost_inr == 4500000.0


def test_overwrite_rename_collision(temp_db):
    p1 = ProjectRepository.create(
        ProjectCreate(name="Study Alpha", latitude=12.97, longitude=77.59),
        db_path=temp_db,
    )
    p2 = ProjectRepository.create(
        ProjectCreate(name="Study Beta", latitude=12.98, longitude=77.60),
        db_path=temp_db,
    )

    # Attempt to rename Study Beta to Study Alpha during overwrite must raise collision
    with pytest.raises(ValueError) as excinfo:
        ProjectRepository.overwrite(
            p2.id,
            ProjectCreate(name="Study Alpha", latitude=12.98, longitude=77.60),
            db_path=temp_db,
        )
    assert f"PROJECT_EXISTS:{p1.id}:Study Alpha" in str(excinfo.value)


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
