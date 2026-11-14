import os
import tempfile
import pytest
from app.db.database import init_db
from app.db.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


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

