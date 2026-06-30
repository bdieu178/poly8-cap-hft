"""
Temporal Knowledge Graph (TKG) implementation using NetworkX.
Operates at Layer 3 (Cognition) to track regime shifts and evolution.
"""
import networkx as nx
import pickle
import os
from datetime import datetime

class TemporalKnowledgeGraph:
    def __init__(self, db_path="data/cognition/tkg.gpickle"):
        self.db_path = db_path
        self.graph = nx.MultiDiGraph()
        self.last_node_id = None
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.load()

    def add_regime_state(self, timestamp_ms: int, regime_enum: int, multiplier: float, metrics: dict):
        """Add a new market state as a node and link it chronologically."""
        node_id = f"state_{timestamp_ms}"
        
        self.graph.add_node(
            node_id, 
            timestamp_ms=timestamp_ms,
            regime_enum=regime_enum,
            multiplier=multiplier,
            **metrics
        )
        
        # Add temporal edge
        if self.last_node_id is not None:
            self.graph.add_edge(self.last_node_id, node_id, relationship="TEMPORAL_TRANSITION")
            
        self.last_node_id = node_id

    def get_current_regime(self):
        """Retrieve the most recent regime node."""
        if not self.last_node_id:
            return None
        return self.graph.nodes[self.last_node_id]

    def save(self):
        with open(self.db_path, "wb") as f:
            pickle.dump((self.graph, self.last_node_id), f)

    def load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "rb") as f:
                self.graph, self.last_node_id = pickle.load(f)
