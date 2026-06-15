"""
Database module: async SQLAlchemy engine, ORM models (users + analyses),
session lifecycle, and CRUD helpers called by the route layer.
"""
import uuid
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)

# Module-level singletons — set by init_db(), used by get_db() and helpers
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


# ── ORM models ────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    # users.email has a UNIQUE constraint, which PostgreSQL automatically backs
    # with a unique index (users_email_key).  No separate ix_users_email needed.

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        # Covers: WHERE user_id = ? (user-scoped history queries)
        sa.Index("ix_analyses_user_id", "user_id"),
        # Covers: WHERE status = ? (dashboard/admin filters)
        sa.Index("ix_analyses_status", "status"),
        # ix_analyses_created_at (DESC) is created by _run_migrations so that
        # both fresh installs and existing DBs get the same descending index.
        # Declaring it here (ASC) would conflict with the migration's DESC form,
        # so it is intentionally omitted from __table_args__.
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    # FK to users.id — ON DELETE CASCADE removes analyses when user is deleted.
    # Nullable so analyses created before authentication existed are preserved.
    user_id: Mapped[Optional[str]] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_analyses_user_id"),
        nullable=True,
    )
    project_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    project_name: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    resources_scanned: Mapped[int] = mapped_column(sa.Integer, default=0)
    issues_found: Mapped[int] = mapped_column(sa.Integer, default=0)
    estimated_monthly_savings: Mapped[str] = mapped_column(sa.Text, default="$0")
    estimated_annual_savings: Mapped[str] = mapped_column(sa.Text, default="$0")
    # Stores the complete Claude AI analysis result as JSON
    analysis_result: Mapped[Optional[Dict]] = mapped_column(sa.JSON, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    input_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    model_used: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    analysis_mode: Mapped[Optional[str]] = mapped_column(sa.String(50), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )


# ── Engine lifecycle ──────────────────────────────────────────────────────────

def _make_async_url(url: str) -> str:
    """
    asyncpg requires the 'postgresql+asyncpg://' scheme.
    Accept the plain 'postgresql://' form from .env and convert it.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


async def _run_migrations(conn) -> None:
    """
    Idempotent schema migrations — safe to run on every startup.

    Order matters:
      1. ADD COLUMN statements (column-level additions)
      2. CREATE INDEX statements (can run on existing data)
      3. Orphan cleanup (nullify broken user_id refs before FK is enforced)
      4. FK constraint (must come last — requires clean data)
    """
    migrations = [
        # ── Column additions ───────────────────────────────────────────────────
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS output_tokens INTEGER DEFAULT 0",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_email VARCHAR(255)",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS model_used VARCHAR(100)",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(50)",
        "ALTER TABLE analyses ADD COLUMN IF NOT EXISTS failure_reason TEXT",

        # ── Indexes ────────────────────────────────────────────────────────────
        #
        # users.email: the UNIQUE constraint already creates 'users_email_key',
        # a unique index that the planner uses for equality lookups.
        # A duplicate non-unique index would waste storage; skipped intentionally.
        #
        # analyses.user_id — equality lookup for user-scoped queries
        "CREATE INDEX IF NOT EXISTS ix_analyses_user_id ON analyses(user_id)",
        #
        # analyses.created_at DESC — matches ORDER BY created_at DESC LIMIT N
        # used by get_analyses().  Descending index eliminates the sort step.
        "CREATE INDEX IF NOT EXISTS ix_analyses_created_at ON analyses(created_at DESC)",
        #
        # analyses.status — equality filter on status in dashboard/admin views
        "CREATE INDEX IF NOT EXISTS ix_analyses_status ON analyses(status)",

        # ── Referential integrity ──────────────────────────────────────────────
        #
        # Nullify any user_id values that point to a deleted or non-existent user.
        # This makes the data consistent before the FK constraint is added so the
        # ALTER TABLE below does not fail on pre-existing orphan rows.
        """
        UPDATE analyses
        SET    user_id = NULL
        WHERE  user_id IS NOT NULL
          AND  user_id NOT IN (SELECT id FROM users)
        """,

        # Add FK with ON DELETE CASCADE — idempotent via pg_constraint check.
        # ON DELETE CASCADE: deleting a user automatically removes their analyses.
        # The constraint name matches the name declared in the ORM ForeignKey so
        # SQLAlchemy's create_all and this migration stay in sync.
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM   pg_constraint
            WHERE  conname    = 'fk_analyses_user_id'
              AND  conrelid   = 'analyses'::regclass
          ) THEN
            ALTER TABLE analyses
              ADD CONSTRAINT fk_analyses_user_id
              FOREIGN KEY (user_id)
              REFERENCES users(id)
              ON DELETE CASCADE;
          END IF;
        END $$
        """,
    ]
    for stmt in migrations:
        await conn.execute(sa.text(stmt))
    logger.debug("Schema migrations applied")


async def init_db(database_url: str) -> None:
    """
    Create the async engine, verify connectivity, and auto-create tables.
    Called once during FastAPI lifespan startup.
    """
    global _engine, _session_factory

    if not database_url:
        logger.warning("DATABASE_URL is not set — database features disabled")
        return

    async_url = _make_async_url(database_url)

    _engine = create_async_engine(
        async_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # recycle stale connections
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Verify connection and create tables
    try:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _run_migrations(conn)
        logger.info("Database connected and tables verified")

        # Create default admin user if it doesn't exist
        from config import config
        import bcrypt
        admin = await get_user_by_email(config.ADMIN_EMAIL)
        if not admin:
            password_hash = bcrypt.hashpw(config.ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
            await create_user(config.ADMIN_EMAIL, password_hash)
            logger.info(f"Created default admin user: {config.ADMIN_EMAIL}")

    except Exception as exc:
        logger.error(f"Database initialization failed: {exc}")
        # Don't crash the server — DB features will fail gracefully per-request
        _engine = None
        _session_factory = None


async def close_db() -> None:
    """Dispose the engine on FastAPI shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database connection closed")


# ── Session dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an AsyncSession, commits on success."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── CRUD helpers ──────────────────────────────────────────────────────────────

# ── User helpers ──────────────────────────────────────────────────────────────

async def create_user(email: str, password_hash: str) -> User:
    """Insert a new user row and return the ORM instance."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        user = User(id=str(uuid.uuid4()), email=email, password_hash=password_hash)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    logger.debug(f"Created user {email}")
    return user


async def get_user_by_email(email: str) -> Optional[User]:
    """Look up a user by email address, returns None if not found."""
    if _session_factory is None:
        return None
    async with _session_factory() as session:
        result = await session.execute(
            sa.select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: str) -> Optional[User]:
    """Look up a user by primary key, returns None if not found."""
    if _session_factory is None:
        return None
    async with _session_factory() as session:
        return await session.get(User, user_id)


async def get_all_users() -> List[User]:
    """Get all users ordered by created_at DESC."""
    if _session_factory is None:
        return []
    async with _session_factory() as session:
        result = await session.execute(
            sa.select(User).order_by(User.created_at.desc())
        )
        return list(result.scalars().all())


async def update_user_password(email: str, new_hash: str) -> None:
    """Update the password hash for a user by email."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        stmt = sa.update(User).where(User.email == email).values(password_hash=new_hash)
        await session.execute(stmt)
        await session.commit()
    logger.debug(f"Updated password for {email}")


async def delete_user(user_id: str) -> bool:
    """Delete a user by ID. Returns True if deleted, False if not found.

    ON DELETE CASCADE on fk_analyses_user_id means the database automatically
    removes all analyses owned by this user — no explicit cleanup needed here.
    """
    if _session_factory is None:
        logger.warning("DB unavailable — skipping delete_user")
        return False
    async with _session_factory() as session:
        stmt = sa.delete(User).where(User.id == user_id)
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount > 0
        if deleted:
            logger.debug(f"Deleted user {user_id} — associated analyses cascade-deleted by DB")
        return deleted


# ── Analysis helpers ──────────────────────────────────────────────────────────

async def create_analysis(
    analysis_id: str,
    project_id: str,
    project_name: str = "",
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    analysis_mode: Optional[str] = "balanced",
) -> None:
    """
    Insert a new analysis row with status='pending'.
    Called at the very start of POST /api/analyze so history records
    appear even if the analysis later fails.
    """
    if _session_factory is None:
        logger.warning("DB unavailable — skipping create_analysis")
        return

    async with _session_factory() as session:
        record = Analysis(
            id=analysis_id,
            project_id=project_id,
            project_name=project_name,
            status="pending",
            user_id=user_id,
            user_email=user_email,
            analysis_mode=analysis_mode,
        )
        session.add(record)
        await session.commit()
    logger.debug(f"Created analysis record {analysis_id}")


async def update_analysis(analysis_id: str, **kwargs: Any) -> None:
    """
    Partial-update an analysis row. Accepts any column kwargs:
      update_analysis(id, status="running")
      update_analysis(id, status="completed", issues_found=5, analysis_result={...})
    """
    if _session_factory is None:
        logger.warning("DB unavailable — skipping update_analysis")
        return

    async with _session_factory() as session:
        stmt = (
            sa.update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(**kwargs)
        )
        await session.execute(stmt)
        await session.commit()
    logger.debug(f"Updated analysis {analysis_id}: {list(kwargs.keys())}")


async def get_analyses(limit: int = 50) -> List[Analysis]:
    """Return recent analyses ordered by created_at DESC, shared across all users.

    Uses ix_analyses_created_at (DESC) to avoid a sort step.
    Excludes placeholder rows created by POST /api/analyze/reserve that have not
    yet been claimed by a full analysis run.
    """
    if _session_factory is None:
        return []

    async with _session_factory() as session:
        query = (
            sa.select(Analysis)
            .where(Analysis.project_id != "__reserved__")
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())


async def get_analysis_by_id(analysis_id: str) -> Optional[Analysis]:
    """Return a single analysis row by its primary key."""
    if _session_factory is None:
        return None
    async with _session_factory() as session:
        return await session.get(Analysis, analysis_id)
