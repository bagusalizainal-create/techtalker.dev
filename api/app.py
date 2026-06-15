"""TechTalkerID - Notes CRUD API
REST API dengan SQLite untuk subdomain api.techtalkerid.dev
- Full CRUD: create, read, update, delete
- Search endpoint
- Validasi input + error handling
- Auto-generated OpenAPI docs di /docs
"""
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from datetime import datetime
import os

# ============ DATABASE SETUP ============
DB_PATH = os.environ.get("NOTES_DB", "/opt/api/notes.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    content = Column(Text, nullable=False, default="")
    tag = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============ SCHEMAS ============
class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Judul note")
    content: str = Field("", description="Isi note")
    tag: str | None = Field(None, max_length=50, description="Tag kategori (opsional)")


class NoteUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = None
    tag: str | None = Field(None, max_length=50)


class NoteOut(BaseModel):
    id: int
    title: str
    content: str
    tag: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ APP ============
app = FastAPI(
    title="TechTalkerID Notes API",
    description="""
REST API untuk catatan pribadi. Data tersimpan di SQLite lokal.

**Endpoints:**
- `GET /notes` — list semua notes
- `POST /notes` — buat note baru
- `GET /notes/{id}` — ambil note by ID
- `PUT /notes/{id}` — update note
- `DELETE /notes/{id}` — hapus note
- `GET /notes/search?q=...` — search by title/content/tag
- `GET /stats` — statistik notes
""",
    version="2.0.0",
    contact={"name": "techtalkerid.dev", "url": "https://www.techtalkerid.dev"},
)


@app.get("/", tags=["meta"])
def root():
    return {
        "message": "TechTalkerID Notes API",
        "version": "2.0.0",
        "docs": "/docs",
        "endpoints": {
            "list":   "GET    /notes",
            "create": "POST   /notes",
            "read":   "GET    /notes/{id}",
            "update": "PUT    /notes/{id}",
            "delete": "DELETE /notes/{id}",
            "search": "GET    /notes/search?q=keyword",
            "stats":  "GET    /stats",
        },
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "notes-api", "db": "sqlite"}


@app.get("/notes", response_model=list[NoteOut], tags=["notes"])
def list_notes(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None, description="Filter by tag"),
    db: Session = Depends(get_db),
):
    """List semua notes (dengan pagination & filter tag)."""
    q = db.query(Note).order_by(Note.updated_at.desc())
    if tag:
        q = q.filter(Note.tag == tag)
    return q.offset(skip).limit(limit).all()


@app.post("/notes", response_model=NoteOut, status_code=201, tags=["notes"])
def create_note(payload: NoteCreate, db: Session = Depends(get_db)):
    """Buat note baru."""
    note = Note(title=payload.title, content=payload.content, tag=payload.tag)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@app.get("/notes/search", response_model=list[NoteOut], tags=["notes"])
def search_notes(
    q: str = Query(..., min_length=1, description="Keyword yang dicari"),
    db: Session = Depends(get_db),
):
    """Search notes by title, content, atau tag."""
    pattern = f"%{q}%"
    results = (
        db.query(Note)
        .filter(
            (Note.title.ilike(pattern))
            | (Note.content.ilike(pattern))
            | (Note.tag.ilike(pattern))
        )
        .order_by(Note.updated_at.desc())
        .limit(50)
        .all()
    )
    return results


@app.get("/notes/{note_id}", response_model=NoteOut, tags=["notes"])
def get_note(note_id: int, db: Session = Depends(get_db)):
    """Ambil note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return note


@app.put("/notes/{note_id}", response_model=NoteOut, tags=["notes"])
def update_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db)):
    """Update note (partial update — field kosong di-skip)."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    data = payload.model_dump(exclude_unset=True)
    for key, val in data.items():
        setattr(note, key, val)
    db.commit()
    db.refresh(note)
    return note


@app.delete("/notes/{note_id}", tags=["notes"])
def delete_note(note_id: int, db: Session = Depends(get_db)):
    """Hapus note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    db.delete(note)
    db.commit()
    return {"deleted": True, "id": note_id}


@app.get("/stats", tags=["meta"])
def stats(db: Session = Depends(get_db)):
    """Statistik notes."""
    total = db.query(Note).count()
    tags = (
        db.query(Note.tag, Note.id)
        .filter(Note.tag.isnot(None))
        .all()
    )
    tag_count: dict[str, int] = {}
    for tag, _ in tags:
        tag_count[tag] = tag_count.get(tag, 0) + 1
    return {
        "total_notes": total,
        "tags": tag_count,
        "db_path": DB_PATH,
    }
