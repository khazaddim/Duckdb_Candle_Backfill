#!/usr/bin/env python3
"""
Generate an EPUB from the Turso backfill design document.
Focus: Turso concurrency model + practical local deployment introduction.
"""

import sys
from pathlib import Path
from datetime import datetime

try:
    from ebooklib import epub
except ImportError:
    print("ERROR: ebooklib not installed. Install with: pip install ebooklib")
    sys.exit(1)


def create_chapter(chapter_id: str, title: str, content: str) -> epub.EpubHtml:
    """Create an EPUB chapter from title and HTML content."""
    chapter = epub.EpubHtml()
    chapter.file_name = f"chap_{chapter_id}.xhtml"
    chapter.title = title
    chapter.content = f"""
    <h1>{title}</h1>
    {content}
    """
    return chapter


def read_design_file(path: str) -> str:
    """Read the design file."""
    return Path(path).read_text(encoding="utf-8")


def extract_sections(content: str) -> dict:
    """Extract major sections from the design file."""
    sections = {}
    current_section = None
    current_content = []
    
    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_content)
            current_section = line.replace("## ", "").strip()
            current_content = []
        else:
            if current_section:
                current_content.append(line)
    
    if current_section:
        sections[current_section] = "\n".join(current_content)
    
    return sections


def markdown_to_html(text: str) -> str:
    """Simple markdown-to-HTML conversion for EPUB."""
    # This is a basic converter; ebooklib handles rendering
    lines = text.split("\n")
    html_lines = []
    
    for line in lines:
        if line.startswith("### "):
            html_lines.append(f"<h3>{line.replace('### ', '')}</h3>")
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f"<strong>{line.replace('**', '')}</strong>")
        elif line.strip().startswith("-"):
            html_lines.append(f"<li>{line.strip()[1:].strip()}</li>")
        elif line.strip().startswith("`"):
            html_lines.append(f"<code>{line.strip()}</code>")
        elif line.strip():
            html_lines.append(f"<p>{line.strip()}</p>")
    
    return "\n".join(html_lines)


def main():
    design_file = Path("backfill_module_design_Turso.md")
    
    if not design_file.exists():
        print(f"ERROR: {design_file} not found")
        sys.exit(1)
    
    print(f"Reading {design_file}...")
    content = read_design_file(str(design_file))
    
    # Create book
    book = epub.EpubBook()
    book.set_identifier(f"turso-candle-backfill-{datetime.now().isoformat()}")
    book.set_title("Turso Concurrency Model & Local Candle Backfill Design")
    book.set_language("en")
    book.add_author("Design Document")
    
    chapters = []
    
    # Chapter 1: What is Turso?
    intro_chapter = create_chapter("01", "1. What is Turso?",
        """
        <p><strong>Turso</strong> is a local, embedded database engine built on SQLite, 
        with a Python API through <code>pyturso</code>. Key features:</p>
        <ul>
            <li>Embedded in your process - no server needed</li>
            <li>Single local <code>.db</code> file - portable across machines</li>
            <li>SQLite-compatible SQL and Python <code>sqlite3</code> API</li>
            <li><code>turso.aio</code> for native async/await support</li>
            <li>MVCC (Multi-Version Concurrency Control) for concurrent writers</li>
            <li>Perfect for local GUI applications, dev environments, and portable tools</li>
        </ul>
        <p><strong>For this project:</strong> We use local Turso to store candle history, 
        backfill jobs, tasks, and validation state - all in one portable database file 
        that sits next to your Python code.</p>
        """
    )
    chapters.append(intro_chapter)
    
    # Chapter 2: Why Not DuckDB or PostgreSQL?
    comparison_chapter = create_chapter("02", "2. Why Turso? (vs DuckDB & PostgreSQL)",
        """
        <h2>DuckDB</h2>
        <ul>
            <li>✓ Embedded, fast OLAP analytics</li>
            <li>✗ Synchronous only - requires <code>asyncio.to_thread()</code> wrapping</li>
            <li>✗ Manual threading for non-blocking GUI integration</li>
        </ul>
        
        <h2>PostgreSQL</h2>
        <ul>
            <li>✓ Native async via <code>asyncpg</code></li>
            <li>✓ Server-side row locking for queue coordination</li>
            <li>✗ Requires external server - not portable</li>
            <li>✗ Added DevOps complexity</li>
        </ul>
        
        <h2>Local Turso (Selected)</h2>
        <ul>
            <li>✓ Embedded, portable (single .db file)</li>
            <li>✓ Native async via <code>turso.aio</code> - no manual threading needed</li>
            <li>✓ MVCC supports concurrent local writers</li>
            <li>✓ Optimistic conflict detection works for this workload</li>
            <li>✓ Perfect for local GUI apps on Windows/Mac/Linux</li>
            <li>✗ Not PostgreSQL row-locking - must use optimistic claiming</li>
        </ul>
        
        <p><strong>Bottom line:</strong> Turso gives you async-first simplicity + 
        MVCC concurrency without server infrastructure.</p>
        """
    )
    chapters.append(comparison_chapter)
    
    # Chapter 3: The Concurrency Model
    concurrency_chapter = create_chapter("03", "3. The Turso Concurrency Model",
        """
        <h2>Three Key Concepts</h2>
        
        <h3>1. MVCC (Multi-Version Concurrency Control)</h3>
        <p>Multiple async workers can read and write simultaneously to the same database:</p>
        <ul>
            <li>Each writer operates in its own transaction</li>
            <li>Readers see consistent snapshots (no dirty reads)</li>
            <li>Enabled with: <code>PRAGMA journal_mode = 'mvcc';</code></li>
        </ul>
        
        <h3>2. Optimistic Conflict Detection</h3>
        <p>Unlike PostgreSQL's row-locking, Turso detects conflicts at <strong>commit time</strong>:</p>
        <ul>
            <li>Worker 1 reads row X, modifies it, tries to commit</li>
            <li>Worker 2 reads same row X, modifies it, commits first</li>
            <li>Worker 1's commit fails with a retryable conflict error</li>
            <li>Worker 1 retries: re-reads, re-modifies, commits successfully</li>
        </ul>
        
        <h3>3. Retry Loop Pattern</h3>
        <p>All write operations use bounded retry loops:</p>
        <pre><code>
max_retries = 3
for attempt in range(max_retries):
    try:
        await conn.execute("BEGIN CONCURRENT")
        await conn.execute("UPDATE ... WHERE id = ? AND status = ?", (task_id, 'pending'))
        await conn.commit()
        break
    except ConflictError:
        await conn.rollback()
        if attempt == max_retries - 1:
            raise
        await asyncio.sleep(0.01 * (2 ** attempt))  # exponential backoff
        </code></pre>
        
        <h2>Why This Works for Backfill</h2>
        <ul>
            <li><strong>Task claiming:</strong> Workers optimistically try to claim pending tasks. 
            Conflicts are rare and quickly resolved.</li>
            <li><strong>Candle insertion:</strong> No conflicts expected (different timestamp ranges).</li>
            <li><strong>Job updates:</strong> Infrequent, small contention window.</li>
            <li><strong>Not a bottleneck:</strong> Retry overhead is negligible compared to network I/O.</li>
        </ul>
        """
    )
    chapters.append(concurrency_chapter)
    
    # Chapter 4: Practical Local Deployment
    deployment_chapter = create_chapter("04", "4. Practical Local Deployment",
        """
        <h2>Single Python Process, Multiple Async Workers</h2>
        <p>On Windows, Turso's multi-process file sharing is ineffective. 
        The recommended architecture is:</p>
        <ul>
            <li>One Python process owning the backfill</li>
            <li>Multiple async workers inside that process</li>
            <li>Each worker has its own <code>turso.aio</code> connection</li>
            <li>MVCC + optimistic retry handles concurrency</li>
        </ul>
        
        <h2>Integration with DearCyGui</h2>
        <pre><code>
# In your DearCyGui event loop:
backfill_task = asyncio.create_task(
    run_backfill(config, provider)
)

# GUI remains responsive - no blocking!
# Query progress from database without coupling to worker internals
        </code></pre>
        
        <h2>Database as Source of Truth</h2>
        <p>All progress is durable in Turso:</p>
        <ul>
            <li>Job status, tasks, candles - all in database</li>
            <li>GUI can query progress without tight coupling</li>
            <li>Easy resumability: restart process, backfill resumes</li>
            <li>Crash-safe: no in-memory state to lose</li>
        </ul>
        
        <h2>Key Implementation Details</h2>
        <pre><code>
# Enable MVCC for concurrent writes
async def initialize_connection(db_path: str):
    conn = await turso.connect(db_path)
    await conn.execute("PRAGMA journal_mode = 'mvcc'")
    return conn

# Use BEGIN CONCURRENT for multi-writer transactions
async def claim_task(conn, worker_id: str):
    await conn.execute("BEGIN CONCURRENT")
    try:
        # SELECT best pending task
        task = await conn.fetchone(
            "SELECT task_id FROM backfill_tasks WHERE status = 'pending' LIMIT 1"
        )
        # Optimistically UPDATE
        await conn.execute(
            "UPDATE backfill_tasks SET status = 'running', claimed_by = ? WHERE task_id = ? AND status = 'pending'",
            (worker_id, task['task_id'])
        )
        await conn.commit()
        return task
    except ConflictError:
        await conn.rollback()
        # Retry logic in caller
        </code></pre>
        """
    )
    chapters.append(deployment_chapter)
    
    # Chapter 5: Core Design Sections (from design file)
    sections = extract_sections(content)
    
    # Add key design sections
    key_sections = [
        "Database-first ingestion",
        "Key Architectural Changes from the PostgreSQL Version",
        "Storage Layer Design",
        "Concurrency Model",
        "Implementation Milestones"
    ]
    
    for i, section_title in enumerate(key_sections, start=5):
        for original_title, content_text in sections.items():
            if section_title.lower() in original_title.lower():
                chapter = create_chapter(
                    f"{i:02d}",
                    f"{i}. {original_title}",
                    markdown_to_html(content_text[:1000])  # First 1000 chars
                )
                chapters.append(chapter)
                break
    
    # Chapter 6: Quick Reference - SQL Patterns
    sql_chapter = create_chapter("06", "6. Quick Reference: SQL Patterns",
        """
        <h2>Gap Detection</h2>
        <pre><code>
SELECT expected.value AS missing_ts
FROM generate_series(start_ts, end_ts, timeframe_s) AS expected
LEFT JOIN candles c ON c.timestamp = expected.value
  AND c.provider = ?
  AND c.market_type = ?
  AND c.symbol = ?
  AND c.timeframe_seconds = ?
WHERE c.timestamp IS NULL
        </code></pre>
        
        <h2>Contiguous Gap Grouping</h2>
        <pre><code>
WITH missing AS (...gap detection query...),
numbered AS (
    SELECT ts, 
        ROW_NUMBER() OVER (ORDER BY ts) -
        CAST(ts / timeframe_s AS INTEGER) AS grp
    FROM missing
)
SELECT MIN(ts) AS gap_start, MAX(ts) AS gap_end
FROM numbered
GROUP BY grp
        </code></pre>
        
        <h2>Optimistic Task Claiming</h2>
        <pre><code>
BEGIN CONCURRENT;
SELECT task_id FROM backfill_tasks 
WHERE status = 'pending' AND retry_count <= max_retries
ORDER BY priority, created_at
LIMIT 1;

UPDATE backfill_tasks 
SET status = 'running', claimed_by = ?, claimed_at = unixepoch()
WHERE task_id = ? AND status = 'pending';
COMMIT;  -- May fail with conflict, retry the whole block
        </code></pre>
        """
    )
    chapters.append(sql_chapter)
    
    # Add all chapters to book
    for chapter in chapters:
        book.add_item(chapter)
    
    # Create table of contents
    toc = []
    for chapter in chapters:
        toc.append(chapter)
    book.toc = tuple(toc)
    
    # Add navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Write EPUB
    output_path = Path("turso_concurrency_guide.epub")
    epub.write_epub(str(output_path), book, {})
    
    print(f"\n✅ EPUB created: {output_path}")
    print(f"   Focus: Turso concurrency model + practical local deployment")
    print(f"   Chapters: {len(chapters)}")
    print(f"   Size: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
