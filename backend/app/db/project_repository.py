import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.db.database import get_connection
from app.schemas.project import ProjectCreate, ProjectDetail, ProjectSummary, ProjectUpdate


def _serialize_json(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _deserialize_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _row_to_summary(row) -> ProjectSummary:
    keys = row.keys()
    return ProjectSummary(
        id=row["id"],
        user_id=row["user_id"] if "user_id" in keys else None,
        name=row["name"],
        description=row["description"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        formatted_address=row["formatted_address"],
        building_typology=row["building_typology"],
        floors=row["floors"],
        built_up_area_sqft=row["built_up_area_sqft"],
        composite_score=row["composite_score"],
        total_cost_inr=row["total_cost_inr"],
        is_bookmarked=bool(row["is_bookmarked"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_detail(row) -> ProjectDetail:
    keys = row.keys()
    return ProjectDetail(
        id=row["id"],
        user_id=row["user_id"] if "user_id" in keys else None,
        name=row["name"],
        description=row["description"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        formatted_address=row["formatted_address"],
        building_typology=row["building_typology"],
        floors=row["floors"],
        built_up_area_sqft=row["built_up_area_sqft"],
        composite_score=row["composite_score"],
        total_cost_inr=row["total_cost_inr"],
        is_bookmarked=bool(row["is_bookmarked"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        boundary=_deserialize_json(row["boundary_json"]),
        parameters=_deserialize_json(row["parameters_json"]) or {},
        analysis_summary=_deserialize_json(row["analysis_summary_json"]),
        analysis_data=_deserialize_json(row["analysis_result_json"]),
        floor_plan_data=_deserialize_json(row["floor_plan_json"]),
        site_vision_data=_deserialize_json(row["site_vision_json"]),
    )


class ProjectRepository:
    """Repository handling project persistence in SQLite with multi-user isolation."""

    @staticmethod
    def get_by_name(
        name: str,
        user_id: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[ProjectDetail]:
        with get_connection(db_path) as conn:
            if user_id:
                cursor = conn.execute(
                    "SELECT * FROM projects WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND user_id = ? LIMIT 1",
                    (name.strip(), user_id),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM projects WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1",
                    (name.strip(),),
                )
            row = cursor.fetchone()
            if not row:
                return None
            return _row_to_detail(row)

    @staticmethod
    def create(
        project: ProjectCreate,
        user_id: Optional[str] = None,
        overwrite: bool = False,
        db_path: Optional[str] = None,
    ) -> ProjectDetail:
        now = datetime.now(timezone.utc).isoformat()

        # Check for existing project with the same name for this user to prevent accidental duplicate saves
        existing = ProjectRepository.get_by_name(project.name, user_id=user_id, db_path=db_path)
        if existing:
            if overwrite:
                updated = ProjectRepository.overwrite(existing.id, project, user_id=user_id, db_path=db_path)
                if updated:
                    return updated
            raise ValueError(f"PROJECT_EXISTS:{existing.id}:{existing.name}")

        proj_id = f"proj_{uuid.uuid4().hex[:12]}"

        # Infer typology, floors, area, score from parameters or analysis if not explicitly provided
        typology = project.building_typology or project.parameters.get("building_typology")
        floors = project.floors or project.parameters.get("floors")
        built_up_area = project.built_up_area_sqft or project.parameters.get("built_up_area_sqft")

        composite_score = project.composite_score
        total_cost_inr = project.total_cost_inr

        if composite_score is None and project.analysis_data:
            composite_score = (
                project.analysis_data.get("overall_suitability_score")
                or project.analysis_data.get("composite_feasibility_score")
            )

        if total_cost_inr is None and project.analysis_data:
            cost_est = project.analysis_data.get("cost_estimate") or {}
            total_cost_inr = (
                cost_est.get("total_estimated_cost_inr")
                or cost_est.get("total_cost_inr")
            )

        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, user_id, name, description, latitude, longitude, formatted_address,
                    building_typology, floors, built_up_area_sqft, composite_score,
                    total_cost_inr, is_bookmarked, boundary_json, parameters_json,
                    analysis_summary_json, analysis_result_json, floor_plan_json,
                    site_vision_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    proj_id,
                    user_id,
                    project.name.strip(),
                    project.description.strip() if project.description else None,
                    project.latitude,
                    project.longitude,
                    project.formatted_address,
                    typology,
                    floors,
                    built_up_area,
                    composite_score,
                    total_cost_inr,
                    1 if project.is_bookmarked else 0,
                    _serialize_json(project.boundary),
                    _serialize_json(project.parameters),
                    _serialize_json(project.analysis_summary),
                    _serialize_json(project.analysis_data),
                    _serialize_json(project.floor_plan_data),
                    _serialize_json(project.site_vision_data),
                    now,
                    now,
                ),
            )
            conn.commit()

            cursor = conn.execute("SELECT * FROM projects WHERE id = ?", (proj_id,))
            row = cursor.fetchone()
            return _row_to_detail(row)

    @staticmethod
    def overwrite(
        project_id: str,
        project: ProjectCreate,
        user_id: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[ProjectDetail]:
        # First verify the project exists and belongs to this user (IDOR protection)
        current = ProjectRepository.get_by_id(project_id, user_id=user_id, db_path=db_path)
        if not current:
            return None

        # Check if renaming collides with another existing study owned by this user
        existing = ProjectRepository.get_by_name(project.name, user_id=user_id, db_path=db_path)
        if existing and existing.id != project_id:
            raise ValueError(f"PROJECT_EXISTS:{existing.id}:{existing.name}")

        now = datetime.now(timezone.utc).isoformat()
        typology = project.building_typology or project.parameters.get("building_typology")
        floors = project.floors or project.parameters.get("floors")
        built_up_area = project.built_up_area_sqft or project.parameters.get("built_up_area_sqft")
        composite_score = project.composite_score
        total_cost_inr = project.total_cost_inr

        if composite_score is None and project.analysis_data:
            composite_score = (
                project.analysis_data.get("overall_suitability_score")
                or project.analysis_data.get("composite_feasibility_score")
            )

        if total_cost_inr is None and project.analysis_data:
            cost_est = project.analysis_data.get("cost_estimate") or {}
            total_cost_inr = (
                cost_est.get("total_estimated_cost_inr")
                or cost_est.get("total_cost_inr")
            )

        where_clause = "WHERE id = ?"
        params: List[Any] = [
            project.name.strip(),
            project.description.strip() if project.description else None,
            project.latitude,
            project.longitude,
            project.formatted_address,
            typology,
            floors,
            built_up_area,
            composite_score,
            total_cost_inr,
            1 if project.is_bookmarked else 0,
            _serialize_json(project.boundary),
            _serialize_json(project.parameters),
            _serialize_json(project.analysis_summary),
            _serialize_json(project.analysis_data),
            _serialize_json(project.floor_plan_data),
            _serialize_json(project.site_vision_data),
            now,
            project_id,
        ]

        if user_id:
            where_clause += " AND user_id = ?"
            params.append(user_id)

        update_sql = f"""
            UPDATE projects SET
                name = ?,
                description = ?,
                latitude = ?,
                longitude = ?,
                formatted_address = ?,
                building_typology = ?,
                floors = ?,
                built_up_area_sqft = ?,
                composite_score = ?,
                total_cost_inr = ?,
                is_bookmarked = ?,
                boundary_json = ?,
                parameters_json = ?,
                analysis_summary_json = ?,
                analysis_result_json = ?,
                floor_plan_json = ?,
                site_vision_json = ?,
                updated_at = ?
            {where_clause}
        """

        with get_connection(db_path) as conn:
            cursor = conn.execute(update_sql, params)
            if cursor.rowcount == 0:
                return None
            conn.commit()

            cursor = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            return _row_to_detail(row) if row else None

    @staticmethod
    def get_by_id(
        project_id: str,
        user_id: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[ProjectDetail]:
        with get_connection(db_path) as conn:
            if user_id:
                cursor = conn.execute(
                    "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                    (project_id, user_id),
                )
            else:
                cursor = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return _row_to_detail(row)

    @staticmethod
    def list(
        user_id: Optional[str] = None,
        bookmarked_only: bool = False,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        db_path: Optional[str] = None,
    ) -> Tuple[List[ProjectSummary], int]:
        query_conditions = []
        params: List[Any] = []

        if user_id:
            query_conditions.append("user_id = ?")
            params.append(user_id)

        if bookmarked_only:
            query_conditions.append("is_bookmarked = 1")

        if search and search.strip():
            # Escape LIKE wildcards so search matches literally
            escaped = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            term = f"%{escaped}%"
            query_conditions.append(
                "(name LIKE ? ESCAPE '\\' OR formatted_address LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
            )
            params.extend([term, term, term])

        where_clause = f"WHERE {' AND '.join(query_conditions)}" if query_conditions else ""

        count_sql = f"SELECT COUNT(*) AS cnt FROM projects {where_clause}"
        select_sql = f"""
            SELECT id, user_id, name, description, latitude, longitude, formatted_address,
                   building_typology, floors, built_up_area_sqft, composite_score,
                   total_cost_inr, is_bookmarked, created_at, updated_at
            FROM projects
            {where_clause}
            ORDER BY is_bookmarked DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """

        with get_connection(db_path) as conn:
            count_cursor = conn.execute(count_sql, params)
            total = count_cursor.fetchone()["cnt"]

            items_params = list(params) + [max(1, min(100, limit)), max(0, offset)]
            cursor = conn.execute(select_sql, items_params)
            rows = cursor.fetchall()

            return [_row_to_summary(r) for r in rows], total

    @staticmethod
    def update(
        project_id: str,
        patch: ProjectUpdate,
        user_id: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[ProjectDetail]:
        updates = []
        params = []

        if patch.name is not None:
            # Check for rename collision within this user's projects
            if user_id:
                existing = ProjectRepository.get_by_name(patch.name, user_id=user_id, db_path=db_path)
                if existing and existing.id != project_id:
                    raise ValueError(f"PROJECT_EXISTS:{existing.id}:{existing.name}")
            updates.append("name = ?")
            params.append(patch.name.strip())

        if patch.description is not None:
            updates.append("description = ?")
            params.append(patch.description.strip())

        if patch.is_bookmarked is not None:
            updates.append("is_bookmarked = ?")
            params.append(1 if patch.is_bookmarked else 0)

        if not updates:
            return ProjectRepository.get_by_id(project_id, user_id=user_id, db_path=db_path)

        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)

        params.append(project_id)
        where_clause = "WHERE id = ?"
        if user_id:
            where_clause += " AND user_id = ?"
            params.append(user_id)

        update_sql = f"UPDATE projects SET {', '.join(updates)} {where_clause}"

        with get_connection(db_path) as conn:
            cursor = conn.execute(update_sql, params)
            if cursor.rowcount == 0:
                return None
            conn.commit()

            return ProjectRepository.get_by_id(project_id, user_id=user_id, db_path=db_path)

    @staticmethod
    def delete(
        project_id: str,
        user_id: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> bool:
        with get_connection(db_path) as conn:
            if user_id:
                cursor = conn.execute(
                    "DELETE FROM projects WHERE id = ? AND user_id = ?",
                    (project_id, user_id),
                )
            else:
                cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return cursor.rowcount > 0
