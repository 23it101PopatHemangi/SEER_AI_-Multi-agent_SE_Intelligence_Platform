import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

# Load environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./seer_ai.db")

# Setup database connection arguments (SQLite requires check_same_thread=False)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    jira_auto_create_enabled = Column(Boolean, nullable=False, default=False)

    repositories = relationship("Repository", back_populates="project", cascade="all, delete-orphan")
    jira_connection = relationship("JiraConnection", back_populates="project", uselist=False, cascade="all, delete-orphan")
    jira_story_drafts = relationship("JiraStoryDraft", back_populates="project", cascade="all, delete-orphan")
    srs_documents = relationship("SRSDocument", back_populates="project", cascade="all, delete-orphan")

class Repository(Base):
    __tablename__ = "repositories"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    github_url = Column(String, nullable=False)
    owner = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    default_branch = Column(String, nullable=False, default="main")
    primary_language = Column(String, nullable=True)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    open_issues_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    last_pushed_at = Column(DateTime, nullable=False)

    project = relationship("Project", back_populates="repositories")
    jira_connection = relationship("JiraRepositoryConnection", back_populates="repository", uselist=False, cascade="all, delete-orphan")

class UserToken(Base):
    __tablename__ = "user_tokens"

    user_email = Column(String, primary_key=True, index=True)
    github_access_token = Column(String, nullable=False)
    github_username = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class JiraUserToken(Base):
    __tablename__ = "jira_user_tokens"

    user_email = Column(String, primary_key=True, index=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    cloud_id = Column(String, nullable=True)
    site_url = Column(String, nullable=True)
    jira_user_id = Column(String, nullable=True)
    jira_display_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    jira_project_key = Column(String, nullable=False)
    jira_project_name = Column(String, nullable=False)
    jira_project_id = Column(String, nullable=True)
    jira_cloud_id = Column(String, nullable=True)
    site_url = Column(String, nullable=True)
    connected_by_email = Column(String, nullable=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="jira_connection")


class JiraRepositoryConnection(Base):
    __tablename__ = "jira_repository_connections"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    jira_project_key = Column(String, nullable=False)
    jira_project_name = Column(String, nullable=False)
    jira_project_id = Column(String, nullable=True)
    jira_cloud_id = Column(String, nullable=True)
    site_url = Column(String, nullable=True)
    connected_by_email = Column(String, nullable=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    repository = relationship("Repository", back_populates="jira_connection")

class JiraStoryDraft(Base):
    __tablename__ = "jira_story_drafts"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_jira_draft_project_fingerprint"),
    )

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    parent_draft_id = Column(String, ForeignKey("jira_story_drafts.id", ondelete="SET NULL"), nullable=True, index=True)
    jira_project_key = Column(String, nullable=True)
    jira_project_name = Column(String, nullable=True)
    jira_project_id = Column(String, nullable=True)
    jira_cloud_id = Column(String, nullable=True)
    jira_site_url = Column(String, nullable=True)
    fingerprint = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    issue_type = Column(String, nullable=False, default="Story")
    description = Column(Text, nullable=True)
    acceptance_criteria = Column(Text, nullable=True)
    priority = Column(String, nullable=False, default="Medium")
    source_type = Column(String, nullable=True)
    source_ref = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")
    jira_issue_key = Column(String, nullable=True)
    jira_issue_id = Column(String, nullable=True)
    jira_issue_url = Column(String, nullable=True)
    creation_error = Column(Text, nullable=True)
    created_by_email = Column(String, nullable=True)
    approved_by_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="jira_story_drafts")
    parent_draft = relationship("JiraStoryDraft", remote_side=[id], back_populates="child_drafts")
    child_drafts = relationship("JiraStoryDraft", back_populates="parent_draft")

class SRSDocument(Base):
    __tablename__ = "srs_documents"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=False)
    created_by_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="srs_documents")

# Create tables
def init_db():
    Base.metadata.create_all(bind=engine)
    # Self-healing column checks for existing SQLite databases
    if str(DATABASE_URL).startswith("sqlite"):
        import sqlite3
        try:
            db_path = str(DATABASE_URL).replace("sqlite:///", "").replace("sqlite://", "").split("?")[0]
            if os.path.exists(db_path):
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                cur.execute("PRAGMA table_info(jira_connections)")
                cols = [r[1] for r in cur.fetchall()]
                if cols and "connected_at" not in cols:
                    cur.execute("ALTER TABLE jira_connections ADD COLUMN connected_at DATETIME")
                if cols and "connected_by_email" not in cols:
                    cur.execute("ALTER TABLE jira_connections ADD COLUMN connected_by_email VARCHAR")
                cur.execute("PRAGMA table_info(projects)")
                project_cols = [r[1] for r in cur.fetchall()]
                if project_cols and "jira_auto_create_enabled" not in project_cols:
                    cur.execute("ALTER TABLE projects ADD COLUMN jira_auto_create_enabled BOOLEAN DEFAULT 0")
                cur.execute("PRAGMA table_info(jira_story_drafts)")
                draft_cols = [r[1] for r in cur.fetchall()]
                for column in ("jira_project_key", "jira_project_name", "jira_project_id", "jira_cloud_id", "jira_site_url"):
                    if draft_cols and column not in draft_cols:
                        cur.execute(f"ALTER TABLE jira_story_drafts ADD COLUMN {column} VARCHAR")
                cur.execute("PRAGMA table_info(jira_story_drafts)")
                draft_cols = [r[1] for r in cur.fetchall()]
                if draft_cols and "issue_type" not in draft_cols:
                    cur.execute("ALTER TABLE jira_story_drafts ADD COLUMN issue_type VARCHAR DEFAULT 'Story'")
                if draft_cols and "parent_draft_id" not in draft_cols:
                    cur.execute("ALTER TABLE jira_story_drafts ADD COLUMN parent_draft_id VARCHAR")
                con.commit()
                con.close()
        except Exception as e:
            print(f"Warning: SQLite schema auto-heal skipped: {e}")


# Dependency to get db session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
