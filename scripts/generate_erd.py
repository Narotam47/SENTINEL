"""
Generates an ERD diagram of the SENTINEL PostgreSQL schema.

Queries information_schema for tables, columns, and FK relationships,
then renders a clean entity-relationship diagram with matplotlib.

Output: docs/erd.png

Usage:
    python scripts/generate_erd.py
    make erd
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import psycopg2
from dotenv import load_dotenv

load_dotenv()

ROOT     = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"


# ── DB connection ─────────────────────────────────────────────────────────────

def _get_conn():
    try:
        return psycopg2.connect(
            host     = os.getenv("POSTGRES_HOST",     "localhost"),
            port     = int(os.getenv("POSTGRES_PORT", "5433")),
            dbname   = os.getenv("POSTGRES_DB",       "sentinel_db"),
            user     = os.getenv("POSTGRES_USER",     "sentinel"),
            password = os.getenv("POSTGRES_PASSWORD", "sentinel_pass"),
        )
    except psycopg2.OperationalError as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        print("Is the stack running?  Run: make up")
        sys.exit(1)


# ── schema queries ────────────────────────────────────────────────────────────

COLUMNS_SQL = """
SELECT
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable,
    CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END AS is_pk
FROM information_schema.columns c
LEFT JOIN (
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema    = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema    = 'public'
) pk ON c.table_name = pk.table_name AND c.column_name = pk.column_name
WHERE c.table_schema = 'public'
  AND c.table_name IN (
      'secom_raw','secom_features','model_runs','predictions','yield_metrics'
  )
ORDER BY c.table_name, c.ordinal_position;
"""

FK_SQL = """
SELECT
    kcu.table_name       AS from_table,
    kcu.column_name      AS from_col,
    ccu.table_name       AS to_table,
    ccu.column_name      AS to_col
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema   = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
    AND ccu.table_schema   = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema    = 'public';
"""


def fetch_schema() -> tuple[dict, list]:
    """Returns (tables, fk_edges) where tables maps name → list of (col, type, is_pk)."""
    conn = _get_conn()
    tables: dict[str, list] = {}
    fk_edges: list          = []

    with conn:
        with conn.cursor() as cur:
            cur.execute(COLUMNS_SQL)
            for table_name, col_name, data_type, is_nullable, is_pk in cur.fetchall():
                tables.setdefault(table_name, []).append(
                    (col_name, data_type, bool(is_pk), is_nullable == "YES")
                )

            cur.execute(FK_SQL)
            fk_edges = cur.fetchall()

    conn.close()
    return tables, fk_edges


# ── layout ────────────────────────────────────────────────────────────────────

# Hand-tuned positions (x, y) in figure-coordinate inches for a 16×10 canvas
TABLE_POS = {
    "secom_raw":      (0.5,  5.5),
    "secom_features": (6.0,  5.5),
    "model_runs":     (11.0, 5.5),
    "predictions":    (6.0,  1.2),
    "yield_metrics":  (11.0, 1.2),
}

# Short type aliases for display
TYPE_ABBREV = {
    "integer":                    "INT",
    "smallint":                   "SMALLINT",
    "bigint":                     "BIGINT",
    "numeric":                    "NUMERIC",
    "double precision":           "FLOAT",
    "real":                       "FLOAT",
    "character varying":          "VARCHAR",
    "text":                       "TEXT",
    "boolean":                    "BOOL",
    "timestamp without time zone":"TIMESTAMP",
    "timestamp with time zone":   "TIMESTAMPTZ",
    "date":                       "DATE",
    "jsonb":                      "JSONB",
    "json":                       "JSON",
    "uuid":                       "UUID",
}

HEADER_COLOR  = "#1a3a5c"
HEADER_FG     = "white"
PK_BG         = "#e8f0fe"
REG_BG        = "#f8f9fa"
BORDER_COLOR  = "#2c5f8a"
FK_ARROW_COLOR= "#c0392b"
FONT_FAMILY   = "monospace"


# ── rendering ─────────────────────────────────────────────────────────────────

def _type_str(data_type: str) -> str:
    return TYPE_ABBREV.get(data_type.lower(), data_type.upper()[:10])


def draw_table(ax, name: str, columns: list, pos: tuple) -> dict:
    """
    Draw one entity box.  Returns a dict of column_name → (x, y) centre
    coordinates so FK arrows can connect to the right row.
    """
    x, y    = pos
    col_h   = 0.30   # row height in data units
    head_h  = 0.42
    box_w   = 3.8

    row_centres = {}

    # Header
    ax.add_patch(mpatches.FancyBboxPatch(
        (x, y), box_w, head_h,
        boxstyle="square,pad=0",
        linewidth=1.2, edgecolor=BORDER_COLOR, facecolor=HEADER_COLOR,
        zorder=2,
    ))
    ax.text(x + box_w / 2, y + head_h / 2, name,
            ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=HEADER_FG,
            fontfamily=FONT_FAMILY, zorder=3)

    # Column rows
    for i, (col_name, data_type, is_pk, nullable) in enumerate(columns):
        row_y   = y - (i + 1) * col_h
        bg      = PK_BG if is_pk else REG_BG
        prefix  = "🔑 " if is_pk else "   "
        type_s  = _type_str(data_type)
        null_s  = "" if not nullable else "?"

        ax.add_patch(mpatches.FancyBboxPatch(
            (x, row_y - col_h * 0.5), box_w, col_h,
            boxstyle="square,pad=0",
            linewidth=0.6, edgecolor=BORDER_COLOR, facecolor=bg,
            zorder=2,
        ))

        # Column name
        ax.text(x + 0.12, row_y, f"{prefix}{col_name}",
                ha="left", va="center",
                fontsize=7.2, color="#1a1a2e", fontfamily=FONT_FAMILY, zorder=3)

        # Type (right-aligned)
        ax.text(x + box_w - 0.10, row_y, f"{type_s}{null_s}",
                ha="right", va="center",
                fontsize=6.5, color="#555577", fontfamily=FONT_FAMILY, zorder=3)

        row_centres[col_name] = (x + box_w / 2, row_y)

    total_h = head_h + len(columns) * col_h
    return {"row_centres": row_centres, "box_x": x, "box_w": box_w,
            "box_y": y, "box_h": total_h}


def draw_fk(ax, boxes: dict, fk_edges: list):
    """Draw arrows from FK column in from_table to PK column in to_table."""
    for from_table, from_col, to_table, to_col in fk_edges:
        if from_table not in boxes or to_table not in boxes:
            continue
        from_info = boxes[from_table]
        to_info   = boxes[to_table]

        if from_col not in from_info["row_centres"]:
            continue
        if to_col not in to_info["row_centres"]:
            to_col = "id"  # fallback to PK
        if to_col not in to_info["row_centres"]:
            continue

        fx, fy = from_info["row_centres"][from_col]
        tx, ty = to_info["row_centres"][to_col]

        # Start from right/left edge of box rather than centre
        from_right = from_info["box_x"] + from_info["box_w"]
        to_right   = to_info["box_x"] + to_info["box_w"]
        from_left  = from_info["box_x"]
        to_left    = to_info["box_x"]

        # Choose which side of each box the arrow enters/leaves
        if tx > fx:
            sx, ex = from_right, to_left
        elif tx < fx:
            sx, ex = from_left, to_right
        else:
            sx, ex = from_right, to_left

        ax.annotate(
            "", xy=(ex, ty), xytext=(sx, fy),
            arrowprops=dict(
                arrowstyle="-|>",
                color=FK_ARROW_COLOR,
                lw=1.2,
                connectionstyle="arc3,rad=0.08",
            ),
            zorder=4,
        )

        # Tiny label near midpoint
        mx = (sx + ex) / 2
        my = (fy + ty) / 2
        ax.text(mx, my + 0.08, from_col,
                ha="center", va="bottom",
                fontsize=5.5, color=FK_ARROW_COLOR, fontstyle="italic", zorder=5)


# ── main ──────────────────────────────────────────────────────────────────────

def generate(output_path: Path):
    print("Fetching schema from PostgreSQL …")
    tables, fk_edges = fetch_schema()

    if not tables:
        print("ERROR: no tables found — run 'make up' and 'make migrate' first.")
        sys.exit(1)

    print(f"Found {len(tables)} tables, {len(fk_edges)} FK relationships.")

    fig_w, fig_h = 17, 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(-1.5, fig_h)
    ax.axis("off")
    ax.set_facecolor("#f0f4f8")
    fig.patch.set_facecolor("#f0f4f8")

    # Title
    ax.text(fig_w / 2, fig_h - 0.4,
            "SENTINEL — Database Schema (ERD)",
            ha="center", va="top",
            fontsize=14, fontweight="bold", color="#1a3a5c")
    ax.text(fig_w / 2, fig_h - 0.85,
            "secom_raw  •  secom_features  •  model_runs  •  predictions  •  yield_metrics",
            ha="center", va="top", fontsize=8, color="#666688")

    # Legend
    legend_x, legend_y = 0.3, 0.3
    ax.add_patch(mpatches.FancyBboxPatch(
        (legend_x, legend_y - 0.15), 3.2, 0.65,
        boxstyle="round,pad=0.05", linewidth=0.8,
        edgecolor="#aaaacc", facecolor="white", zorder=1))
    ax.text(legend_x + 0.10, legend_y + 0.35, "Legend",
            fontsize=7, fontweight="bold", color="#333", zorder=5)
    ax.add_patch(mpatches.FancyBboxPatch(
        (legend_x + 0.10, legend_y + 0.08), 0.35, 0.18,
        boxstyle="square,pad=0", facecolor=PK_BG, edgecolor=BORDER_COLOR, lw=0.5, zorder=5))
    ax.text(legend_x + 0.52, legend_y + 0.17, "🔑 Primary key",
            fontsize=6.5, va="center", zorder=5)
    ax.annotate("", xy=(legend_x + 1.9, legend_y + 0.17),
                xytext=(legend_x + 1.5, legend_y + 0.17),
                arrowprops=dict(arrowstyle="-|>", color=FK_ARROW_COLOR, lw=1.0),
                zorder=5)
    ax.text(legend_x + 1.95, legend_y + 0.17, "Foreign key",
            fontsize=6.5, va="center", color=FK_ARROW_COLOR, zorder=5)

    # Draw tables
    boxes = {}
    for table_name, pos in TABLE_POS.items():
        if table_name not in tables:
            print(f"  Warning: table '{table_name}' not found in DB schema")
            continue
        info = draw_table(ax, table_name, tables[table_name], pos)
        boxes[table_name] = info

    # Draw FK arrows
    draw_fk(ax, boxes, fk_edges)

    # Watermark
    ax.text(fig_w - 0.2, 0.1, "SENTINEL Phase 1",
            ha="right", va="bottom", fontsize=6, color="#aaaaaa")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"ERD saved → {output_path}")


if __name__ == "__main__":
    output = DOCS_DIR / "erd.png"
    generate(output)
