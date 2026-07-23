"""
redrum-memory: Standalone memory and persistence engine for AI companions.
"""

from redrum_memory.database import (
    DatabaseHealth,
    db_session,
    check_database,
    get_user_preferences,
    list_knowledge_entries,
    list_memory_facts,
    fetch_table_names,
    # Include other queries imported by redrum-ai
)
from redrum_memory.migrations import run_migrations
from redrum_memory.memory_core import AIMemory, LANCEDB_AVAILABLE
from redrum_memory.federation import (
    HMACSigner, JobEnvelope, QuarantineScanner, VectorClock,
    CapabilityBroker, FederatedControlPlane,
)
from redrum_memory.policy import AccessContext, PolicyStore, Sensitivity
from redrum_memory.service import MemoryService, ServiceAuthenticator
