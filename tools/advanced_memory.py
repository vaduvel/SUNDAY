"""J.A.R.V.I.S. (GALAXY NUCLEUS - ADVANCED MEMORY)

High-performance context filtering using 26-bit Bitmap Pruning and 
Leiden-inspired Path Community Clustering.
"""

import os
import re
import logging
from typing import List, Dict, Set, Tuple

logger = logging.getLogger(__name__)

class BitmapFilter:
    """A 26-bit char-presence filter for high-speed block indexing."""
    
    def __init__(self):
        # We map a-z to bits 0-25
        self.char_map = {chr(i + 97): 1 << i for i in range(26)}

    def compute_bitmap(self, text: str) -> int:
        """Computes the 26-bit character presence bitmap for a block."""
        bitmap = 0
        text_lower = text.lower()
        for char in text_lower:
            if 'a' <= char <= 'z':
                bitmap |= self.char_map[char]
        return bitmap

    def match(self, query: str, block_bitmap: int) -> bool:
        """Returns True if the block contains all alpha chars of the query."""
        query_bitmap = self.compute_bitmap(query)
        if query_bitmap == 0: return True # Query has no alpha chars
        return (block_bitmap & query_bitmap) == query_bitmap

class CommunityClustering:
    """Groups project files into 'Communities' based on directory structural weight."""
    
    def __init__(self, project_root: str):
        self.root = project_root
        self.communities = {}

    def cluster_files(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """Groups files by their lowest common directory depth (simplified Leiden)."""
        logger.info(f"💎 [MEM] Clustering {len(file_paths)} files into communities...")
        
        community_buckets = {}
        for path in file_paths:
            # We use the parent directory as the community ID
            rel_path = os.path.relpath(path, self.root)
            parts = rel_path.split(os.sep)
            
            if len(parts) > 1:
                comm_name = "/".join(parts[:-1]) # The directory path
            else:
                comm_name = "ROOT"
                
            if comm_name not in community_buckets:
                community_buckets[comm_name] = []
            community_buckets[comm_name].append(path)
            
        self.communities = community_buckets
        return community_buckets

class AdvancedMemory:
    """The master memory engine combining Bitmaps and Communities."""
    
    def __init__(self, project_root: str):
        self.root = project_root
        self.filter = BitmapFilter()
        self.clustering = CommunityClustering(project_root)
        self.index = {} # Maps path -> bitmap
        
    def build_index(self, files: List[str]):
        """Builds the bitmap index for all provided files."""
        for path in files:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self.index[path] = self.filter.compute_bitmap(content)
            except Exception as e:
                logger.error(f"Error indexing {path}: {str(e)}")

    def search_pruned(self, query: str) -> List[str]:
        """Returns only files that satisfy the 26-bit bitmap match for the query."""
        results = []
        for path, bitmap in self.index.items():
            if self.filter.match(query, bitmap):
                results.append(path)
        return results

# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mem = AdvancedMemory(project_root=".")
    test_files = ["core/jarvis_engine.py", "core/prompts.py", "README.md"]
    # (Simplified for testing)
    mem.index = {
        "core/jarvis_engine.py": mem.filter.compute_bitmap("class JarvisEngine: ... context compactor"),
        "core/prompts.py": mem.filter.compute_bitmap("DNA GALAXY NUCLEUS PROMPT"),
    }
    
    query = "jarvis context"
    results = mem.search_pruned(query)
    print(f"🔍 Pruning Cluster Search for '{query}': {results}")
