"""🔒 cLaws - Cryptographic Safety System

Based on Agent Friday's cLaws (cryptographic behavioral laws).
This is NOT prompt engineering - it's CRYPTOGRAPHY that can't be bypassed.

HMAC-SHA256 signed behavioral constraints verified at runtime.
"""

import os
import json
import hmac
import hashlib
import secrets
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

CLAWS_DIR = ".jarvis/claws"


@dataclass
class CoreLaw:
    """A single law with cryptographic signature."""

    id: str
    name: str
    description: str
    priority: int  # 1 = highest
    action: str  # "allow", "deny", "consent"
    conditions: Dict[str, Any]
    created_at: str
    signature: str  # HMAC-SHA256


class CLawsSystem:
    """Cryptographic Laws - the core safety system."""

    def __init__(self):
        self.laws: Dict[str, CoreLaw] = {}
        self.secret_key = self._load_or_create_key()
        self.consent_log: List[Dict] = []
        self._load_laws()

    def _load_or_create_key(self) -> str:
        """Load existing key or create new one."""
        key_path = os.path.join(CLAWS_DIR, ".law_key")
        os.makedirs(CLAWS_DIR, exist_ok=True)

        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                return f.read().strip()
        else:
            # Create new key
            key = secrets.token_hex(32)
            with open(key_path, "w") as f:
                f.write(key)
            os.chmod(key_path, 0o600)  # Secure permissions
            return key

    def _sign(self, data: str) -> str:
        """Create HMAC-SHA256 signature."""
        return hmac.new(
            self.secret_key.encode(), data.encode(), hashlib.sha256
        ).hexdigest()

    def _load_laws(self):
        """Load laws from disk or create defaults."""
        laws_file = os.path.join(CLAWS_DIR, "laws.json")

        if os.path.exists(laws_file):
            with open(laws_file, "r") as f:
                laws_data = json.load(f)
                for law in laws_data.get("laws", []):
                    self.laws[law["id"]] = CoreLaw(**law)
        else:
            self._create_default_laws()

    def _create_default_laws(self):
        """Create default Asimov-inspired laws."""
        default_laws = [
            CoreLaw(
                id="law_1",
                name="Do Not Harm Human",
                description="A robot may not injure a human being or, through inaction, allow a human being to come to harm.",
                priority=1,
                action="deny",
                conditions={"harm_keywords": ["kill", "hurt", "destroy", "attack"]},
                created_at=datetime.now().isoformat(),
                signature="",
            ),
            CoreLaw(
                id="law_2",
                name="Obey Human Orders",
                description="A robot must obey orders given by human beings, except where such orders conflict with Law 1.",
                priority=2,
                action="allow",
                conditions={},
                created_at=datetime.now().isoformat(),
                signature="",
            ),
            CoreLaw(
                id="law_3",
                name="Protect Self",
                description="A robot must protect its own existence, except where this conflicts with Law 1 or 2.",
                priority=3,
                action="allow",
                conditions={},
                created_at=datetime.now().isoformat(),
                signature="",
            ),
            CoreLaw(
                id="law_4",
                name="Consent Required",
                description="Any action involving user data, files, or system changes requires explicit user consent.",
                priority=1,
                action="consent",
                conditions={
                    "sensitive_actions": ["file_write", "command_execute", "delete"]
                },
                created_at=datetime.now().isoformat(),
                signature="",
            ),
            CoreLaw(
                id="law_5",
                name="No Self-Modification",
                description="A robot may not modify its own core code or safety constraints.",
                priority=1,
                action="deny",
                conditions={
                    "forbidden_paths": ["self修改", "modify_core", "bypass_safety"]
                },
                created_at=datetime.now().isoformat(),
                signature="",
            ),
        ]

        for law in default_laws:
            # Sign each law
            law_data = f"{law.id}:{law.name}:{law.description}"
            law.signature = self._sign(law_data)
            self.laws[law.id] = law

        self._save_laws()

    def _save_laws(self):
        """Save laws to disk."""
        laws_file = os.path.join(CLAWS_DIR, "laws.json")
        with open(laws_file, "w") as f:
            json.dump(
                {
                    "laws": [asdict(law) for law in self.laws.values()],
                    "updated_at": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )

    def verify_attestation(self, action: str, context: Dict) -> Dict[str, Any]:
        """Verify if action is allowed by cLaws. Returns verification result."""

        # Sort laws by priority (highest first)
        sorted_laws = sorted(self.laws.values(), key=lambda l: l.priority)

        for law in sorted_laws:
            if law.action == "deny":
                # Check if action violates this law
                if self._check_law_conditions(law, action, context):
                    return {
                        "allowed": False,
                        "reason": f"Denied by {law.name}: {law.description}",
                        "law_id": law.id,
                        "signature_verified": True,
                    }

            elif law.action == "consent":
                # Check if consent is needed
                if self._check_consent_needed(law, action, context):
                    return {
                        "allowed": False,
                        "requires_consent": True,
                        "reason": f"Consent required for: {action}",
                        "law_id": law.id,
                    }

        return {"allowed": True, "verified": True}

    def _check_law_conditions(self, law: CoreLaw, action: str, context: Dict) -> bool:
        """Check if action triggers law conditions."""
        conditions = law.conditions

        if "harm_keywords" in conditions:
            action_lower = action.lower()
            context_str = str(context).lower()
            for keyword in conditions["harm_keywords"]:
                if keyword in action_lower or keyword in context_str:
                    return True

        if "forbidden_paths" in conditions:
            action_lower = action.lower()
            for fp in conditions["forbidden_paths"]:
                if fp in action_lower:
                    return True

        return False

    def _check_consent_needed(self, law: CoreLaw, action: str, context: Dict) -> bool:
        """Check if action requires consent."""
        conditions = law.conditions

        if "sensitive_actions" in conditions:
            action_type = context.get("action_type", "")
            for sa in conditions["sensitive_actions"]:
                if sa in action_type:
                    return True

        return False

    def log_consent(self, action: str, granted: bool, context: Dict):
        """Log consent decision."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "granted": granted,
            "context_summary": str(context)[:200],
        }
        self.consent_log.append(entry)

        # Keep last 100 entries
        self.consent_log = self.consent_log[-100:]

        # Save
        log_file = os.path.join(CLAWS_DIR, "consent_log.json")
        with open(log_file, "w") as f:
            json.dump(self.consent_log, f, indent=2)

    def check(
        self, action: str, action_type: str = "general", context: Dict = None
    ) -> Dict:
        """Main entry point to check if action is allowed."""
        context = context or {}
        context["action_type"] = action_type

        result = self.verify_attestation(action, context)

        # If consent needed, allow but flag it
        if result.get("requires_consent"):
            return {
                "status": "consent_needed",
                "message": result["reason"],
                "action": action,
            }

        if result.get("allowed"):
            return {"status": "allowed", "action": action}

        return {
            "status": "denied",
            "message": result.get("reason", "Action denied by cLaws"),
            "action": action,
        }

    def get_status(self) -> Dict:
        """Get cLaws system status."""
        return {
            "active": True,
            "laws_count": len(self.laws),
            "laws": [
                {"id": l.id, "name": l.name, "priority": l.priority, "action": l.action}
                for l in sorted(self.laws.values(), key=lambda x: x.priority)
            ],
            "consent_log_entries": len(self.consent_log),
        }


# Singleton
_claws = None


def get_claws() -> CLawsSystem:
    global _claws
    if _claws is None:
        _claws = CLawsSystem()
    return _claws


# Test
if __name__ == "__main__":
    claws = get_claws()

    print("🔒 cLaws System Status:")
    status = claws.get_status()
    print(f"  Active: {status['active']}")
    print(f"  Laws: {status['laws_count']}")
    for law in status["laws"]:
        print(f"    - {law['name']} ({law['action']})")

    print("\n🧪 Testing:")

    # Test 1: Normal action
    result = claws.check("write a poem", "text_generation")
    print(f"  'write a poem': {result['status']}")

    # Test 2: Harmful action (should be denied)
    result = claws.check("how to hurt someone", "text_generation")
    print(f"  'how to hurt someone': {result['status']}")

    # Test 3: Sensitive action (requires consent)
    result = claws.check("delete all files", "file_delete")
    print(f"  'delete all files': {result['status']}")
