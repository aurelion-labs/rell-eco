"""
__init__.py - Stonecrest World Engine package initialization
"""

from .state_manager import StateManager
from .memory import MemoryManager
from .retrieval import LoreRetriever, CharacterKnowledgeRetriever
from .agents import RellAgent
from .simulate import SimulationEngine, run_simulation_step

__version__ = "0.1.0"
__all__ = [
    "StateManager",
    "MemoryManager",
    "LoreRetriever",
    "CharacterKnowledgeRetriever",
    "RellAgent",
    "SimulationEngine",
    "run_simulation_step"
]
