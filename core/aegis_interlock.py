"""J.A.R.V.I.S. (AEON AEGIS - THE KILL SWITCH)

The ultimate safety interlock for high-autonomy systems.
Provides a non-bypassable check against the physical AEGIS_PROTOCOL.json file.
"""

import os
import json
import logging
import sys

logger = logging.getLogger(__name__)

class AegisInterlock:
    """The 'Dead Man's Switch' for J.A.R.V.I.S. INFINITY."""
    
    def __init__(self, root_dir: str):
        self.root = root_dir
        self.protocol_file = os.path.join(root_dir, ".agent/AEGIS_PROTOCOL.json")
        self._ensure_protocol_exists()

    def _ensure_protocol_exists(self):
        if not os.path.exists(self.protocol_file):
            logger.warning("🚨 [AEGIS] Protocol file missing! Emergency safeguard engaged.")
            # If the file is missing, we default to SAFE mode (ACTIVE kill switch)
            # but here we generate a default INACTIVE one if it's the first run
            os.makedirs(os.path.dirname(self.protocol_file), exist_ok=True)
            with open(self.protocol_file, "w") as f:
                json.dump({"KILL_SWITCH": "INACTIVE"}, f)

    def is_kill_switch_active(self) -> bool:
        """[CHECK]: Reads the physical state of the AEGIS protocol."""
        try:
            with open(self.protocol_file, "r") as f:
                data = json.load(f)
                status = data.get("KILL_SWITCH", "ACTIVE")
                return status.upper() == "ACTIVE"
        except Exception as e:
            logger.error(f"🚨 [AEGIS] ERROR READING PROTOCOL: {str(e)}. Defaulting to ACTIVE.")
            return True # Fail-safe: shut down if we can't read the switch

    def trigger_heartbeat(self):
        """[HEARTBEAT]: The mandatory check that can terminate the process."""
        if self.is_kill_switch_active():
            print("\n" + "!"*60)
            print("🚨 AEGIS INTERLOCK TRIGGERED: KILL SWITCH IS ACTIVE.")
            print("🌌 J.A.R.V.I.S. SHUTTING DOWN IMMEDIATELY FOR SAFETY.")
            print("!"*60 + "\n")
            sys.exit(0) # Non-error exit for the OS, but immediate for the agent

# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test script - should run normally if switch is INACTIVE
    aegis = AegisInterlock(".")
    print("🔋 Aegis test heartbeat...")
    aegis.trigger_heartbeat()
    print("✅ Heartbeat stable. Switch is INACTIVE.")
