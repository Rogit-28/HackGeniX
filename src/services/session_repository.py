"""
MongoDB-backed interview session repository.

Provides async CRUD operations for persisting InterviewSession documents.
Uses the ``interview_sessions`` collection already defined in database.py.
"""
import logging
from datetime import datetime
from typing import List, Optional

from src.core.database import mongodb_client
from src.models.interview import InterviewSession, InterviewStatus

logger = logging.getLogger(__name__)


class SessionRepository:
    """
    Async persistence layer for InterviewSession objects.

    Design:
      - Uses session.id (our UUID) as the MongoDB ``_id``.
      - save() is an upsert so it works for both create and update.
      - load() / list() rehydrate into Pydantic models.
    """

    def __init__(self):
        self._collection = mongodb_client.interview_sessions

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(self, session: InterviewSession) -> None:
        """Upsert the full session document into MongoDB."""
        doc = session.model_dump()
        doc["_id"] = session.id  # use our UUID as Mongo _id
        doc.pop("id", None)      # avoid storing duplicate 'id' field

        await self._collection.replace_one(
            {"_id": session.id},
            doc,
            upsert=True,
        )
        logger.debug(f"Session {session.id} saved to MongoDB")

    async def delete(self, session_id: str) -> bool:
        """Delete a session by ID. Returns True if a document was deleted."""
        result = await self._collection.delete_one({"_id": session_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.debug(f"Session {session_id} deleted from MongoDB")
        return deleted

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def load(self, session_id: str) -> Optional[InterviewSession]:
        """Load a single session by ID. Returns None if not found."""
        doc = await self._collection.find_one({"_id": session_id})
        if doc is None:
            return None
        return self._doc_to_session(doc)

    async def list(
        self,
        status: Optional[InterviewStatus] = None,
        limit: int = 50,
    ) -> List[InterviewSession]:
        """
        List sessions, optionally filtered by status.

        Returns up to *limit* sessions sorted by last_activity_at descending.
        """
        query = {}
        if status is not None:
            status_val = status.value if hasattr(status, "value") else status
            query["status"] = status_val

        cursor = (
            self._collection
            .find(query)
            .sort("last_activity_at", -1)
            .limit(limit)
        )

        sessions = []
        async for doc in cursor:
            try:
                sessions.append(self._doc_to_session(doc))
            except Exception as e:
                logger.warning(f"Failed to deserialise session {doc.get('_id')}: {e}")
        return sessions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _doc_to_session(doc: dict) -> InterviewSession:
        """Convert a MongoDB document back into an InterviewSession."""
        # MongoDB stores _id; our model expects id
        if "_id" in doc and "id" not in doc:
            doc["id"] = doc.pop("_id")
        elif "_id" in doc:
            doc.pop("_id")
        return InterviewSession(**doc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_repo: Optional[SessionRepository] = None


def get_session_repository() -> SessionRepository:
    """Get or create the session repository singleton."""
    global _repo
    if _repo is None:
        _repo = SessionRepository()
    return _repo
