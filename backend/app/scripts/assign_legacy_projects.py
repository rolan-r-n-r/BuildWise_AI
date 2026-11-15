#!/usr/bin/env python3
"""
assign_legacy_projects.py — Administrative script to safely assign unowned/legacy projects
to an authenticated user account.

Usage:
    python -m app.scripts.assign_legacy_projects --email user@example.com [--all | --project-id proj_xxx]
"""

import argparse
import sys
from app.db.database import get_connection


def assign_projects(user_email: str, project_id: str = None, assign_all: bool = False, db_path: str = None):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Find the target user
        user = cursor.execute("SELECT id, name, email FROM user WHERE LOWER(email) = LOWER(?)", (user_email.strip(),)).fetchone()
        if not user:
            print(f"[ERROR] User with email '{user_email}' not found.")
            sys.exit(1)

        user_id = user["id"]
        print(f"[INFO] Found target user: {user['name']} ({user['email']}, ID: {user_id})")

        if project_id:
            row = cursor.execute("SELECT id, name, user_id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                print(f"[ERROR] Project '{project_id}' not found.")
                sys.exit(1)
            cursor.execute("UPDATE projects SET user_id = ? WHERE id = ?", (user_id, project_id))
            conn.commit()
            print(f"[SUCCESS] Assigned project '{row['name']}' ({project_id}) to {user['email']}.")

        elif assign_all:
            legacy_rows = cursor.execute("SELECT id, name FROM projects WHERE user_id = 'legacy_unassigned' OR user_id IS NULL").fetchall()
            if not legacy_rows:
                print("[INFO] No unassigned legacy projects found.")
                return

            print(f"[INFO] Reassigning {len(legacy_rows)} legacy projects to {user['email']}...")
            cursor.execute("UPDATE projects SET user_id = ? WHERE user_id = 'legacy_unassigned' OR user_id IS NULL", (user_id,))
            conn.commit()
            for r in legacy_rows:
                print(f"  - Assigned: {r['name']} ({r['id']})")
            print(f"[SUCCESS] Reassigned {len(legacy_rows)} projects to {user['email']}.")
        else:
            print("[ERROR] Must specify either --project-id or --all.")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assign legacy projects to a user account.")
    parser.add_argument("--email", required=True, help="Registered email of the owner")
    parser.add_argument("--project-id", help="Specific project ID to reassign")
    parser.add_argument("--all", action="store_true", help="Assign all legacy_unassigned projects")
    args = parser.parse_args()

    assign_projects(user_email=args.email, project_id=args.project_id, assign_all=args.all)
