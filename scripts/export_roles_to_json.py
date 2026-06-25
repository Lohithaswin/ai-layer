import sys
import json
import pyodbc
from pathlib import Path

# ── Connection ────────────────────────────────────────────────
SERVER   = 'PRODEUM132PINB4'
DATABASE = 'PROJECT_NAME'
DRIVER   = '{SQL Server}'

def main():
    print(f"Connecting to {SERVER}/{DATABASE} using Windows Authentication...")
    try:
        conn = pyodbc.connect(
            f"DRIVER={DRIVER};SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;",
            timeout=10
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    print("Connected!\n")
    cursor = conn.cursor()

    # ── Exact query built from confirmed schema ────────────────
    # Role.Id          → RoleAttributeMatrixs.RoleId
    # RoleAttribute.Id → RoleAttributeMatrixs.AttributeId
    # RoleAttributeGroup.Id → RoleAttribute.AttributeGroupId
    query = """
        SELECT
            r.Name              AS role_name,
            ra.Name             AS attribute_name,
            rag.Name            AS group_name,
            ra.StructuredName   AS structured_name,
            ra.Description      AS description,
            r.Description       AS role_description,
            r.IsHighRiskRole    AS is_high_risk,
            r.RoleStatus        AS role_status,
            ra.IsActive         AS attr_is_active
        FROM dbo.RoleAttributeMatrixs ram
        JOIN dbo.Role r
            ON r.Id = ram.RoleId
        JOIN dbo.RoleAttribute ra
            ON ra.Id = ram.AttributeId
        LEFT JOIN dbo.RoleAttributeGroup rag
            ON rag.Id = ra.AttributeGroupId
        WHERE ra.IsActive = 1
        ORDER BY r.Name, rag.Name, ra.Name
    """

    print("Running query...")
    try:
        cursor.execute(query)
        col_names = [c[0] for c in cursor.description]
        rows = cursor.fetchall()

        data = []
        for row in rows:
            record = dict(zip(col_names, row))
            # Convert non-serialisable types
            record['is_high_risk'] = bool(record.get('is_high_risk'))
            record['attr_is_active'] = bool(record.get('attr_is_active'))
            data.append(record)

        out_path = Path("roles_export.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        print(f"SUCCESS! Exported {len(data)} role-attribute mappings.")
        print(f"File saved to: {out_path.absolute()}")

        # Quick summary
        roles = len(set(r['role_name'] for r in data))
        attrs = len(set(r['attribute_name'] for r in data))
        groups = len(set(r['group_name'] for r in data if r['group_name']))
        print(f"\nSummary: {roles} roles | {attrs} unique attributes | {groups} groups")

    except Exception as e:
        print(f"Query failed: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
