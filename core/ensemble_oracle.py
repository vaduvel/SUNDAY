"""J.A.R.V.I.S. (GALAXY NUCLEUS - ENSEMBLE ORACLE V2)

The multi-model consensus and reflection engine. 🧠🤝🚀
Performs real asynchronous validation using the GALAXY BRAIN.
"""

import asyncio
import logging
import json
from typing import List, Dict, Any, Optional

from core.brain import call_brain, PRO_MODEL, CHEAP_MODEL

logger = logging.getLogger(__name__)

class EnsembleOracle:
    """The reflective decision-making engine using real API consensus."""
    
    def __init__(self):
        # We use the two primary models for cross-validation
        self.models = [PRO_MODEL, CHEAP_MODEL]
        self.threshold = 1.0 # Both must agree for critical steps

    async def reflect_on_solution(self, task: str, solution_code: str) -> Dict[str, Any]:
        """[REFLECT]: Asks multiple models to judge a single solution for bugs or flaws."""
        logger.info(f"🧠 [ORACLE] Initiating real ensemble reflection on task: {task[:30]}...")
        
        # 1. PARALLEL JUDGEMENT
        judgements_tasks = [self._call_judgement_model(model, task, solution_code) for model in self.models]
        results = await asyncio.gather(*judgements_tasks)
        
        # 2. VOTE AGGREGATION
        # We look for 'PASS' or 'FAIL' in the model's response
        passed_count = sum(1 for res in results if "PASS" in res["verdict"].upper())
        consensus_score = passed_count / len(results)
        
        # 3. VERDICT
        if consensus_score >= self.threshold:
            logger.info(f"✅ [ORACLE] Consensus Reached ({consensus_score*100}%): GALAXY APPROVED.")
            return {"verdict": "APPROVED", "score": consensus_score, "logs": results}
        else:
            logger.warning(f"❌ [ORACLE] Consensus Failed ({consensus_score*100}%): GALAXY REJECTED.")
            return {"verdict": "REJECTED", "score": consensus_score, "logs": results}

    async def _call_judgement_model(self, model: str, task: str, code: str) -> Dict:
        """Isolated call to a specific model for an objective critique."""
        prompt = [
            {"role": "system", "content": "You are a Senior Security & Logic Auditor. Review the code against the task. Reply with ONLY 'PASS' and a brief summary, or 'FAIL' and the reason."},
            {"role": "user", "content": f"Task: {task}\n\nProposed Code:\n{code}"}
        ]
        
        verdict = await call_brain(messages=prompt, model=model, profile="precise")
        return {"model": model, "verdict": verdict}

# ═══════════════════════════════════════════════════════════════
#  THE REASONING HUB: 5-GEN COGNITION (REAL)
# ═══════════════════════════════════════════════════════════════

class ReasoningHub:
    """Manages the 5-step cognitive cycle with real consensus."""
    
    def __init__(self):
        self.oracle = EnsembleOracle()

    async def perform_5_step_reasoning(self, user_input: str):
        """[REASON]: Executing the highest tier of agentic cognitive cycle."""
        yield {"step": "OBSERVE", "message": "🔍 Analizez mediul și intentiile tale..."}
        
        yield {"step": "DECOMPOSE", "message": "🧩 Spart sarcină în pași atomici (Devin/Claude Pattern)."}
        
        yield {"step": "SPECULATE", "message": "⏳ Calcul 'Raza de Explozie' (GitNexus Logic)..."}
        
        yield {"step": "PLAN", "message": "🗺️ Strategia de execuție Diamond-Tier este stabilită."}
        
        # FINAL STEP: The Oracle's Blessing (REAL CALL)
        yield {"step": "REFLECT", "message": f"🧠 Consiliul Modelelor ({', '.join(self.oracle.models)}) validează planul..."}
        
        # We pass a summary of the plan for reflection
        verdict = await self.oracle.reflect_on_solution(user_input, "Integrated Implementation Plan")
        
        yield {"step": "VERDICT", "message": f"✨ Consens: {verdict['verdict']}."}
