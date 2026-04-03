# 📋 COMPREHENSIV JARVIS CAPABILITY MAP
## Agent Fram - Full System Audit

---

## 🎯 EXECUTIVE SUMMARY

**JARVIS (Galaxy Nucleus - AEGIS Edition)** este un sistem AI autonom, productie-grade cu ~**105+ module Python** across core, tools, si bridge.

| Categorie | Numar |
|-----------|-------|
| Core Modules | 86 |
| Tools | 18 |
| API Endpoints | 50+ |
| Memory Systems | 8 |
| Agents | 15+ |
| Cognitive Layers (Neuro) | 7 |

---

## 🧠 1. STRATUL NEURAL (LLM Brain)

### 1.1 Brain Principal (ACTUAL - FOLOSIT)
| File | Descriere | Status |
|------|-----------|---------|
| `core/brain.py` | LiteLLM gateway - apeleaza LLM-ul | ✅ FOLOSIT PESTRE TOT |
| `core/llm_gateway.py` | Abstractizare multi-provider (gemerl, OpenAI, etc) | ⚠️ INSTALAT, NU E FOLOSIT |

**Folosire curenta:**
```python
# chat_jarvis.py - foloseste brain.py
from core.brain import call_brain_with_tools, PRO_MODEL

# Toate celelalte模块 folosesc tot brain.py:
# - orchestrator.py ✅
# - autonomy_daemon.py ✅
# - cowork_mode.py ✅
# - eval_harness.py ✅
# - memory_tool.py ✅
```

### 1.2 Neuro Brain (7 Cognitive Layers)
| Layer | File | Functie |
|-------|------|---------|
| **TemporalMemory** | `neuro/temporal_memory.py` | Event sequence tracking (NuPIC) |
| **BeliefState** | `neuro/belief_state.py` | Hypothesis management cu entropy |
| **EventGate** | `neuro/event_gate.py` | Event filtering si decision gating |
| **RoutingAdapter** | `neuro/routing_adaptation.py` | Dynamic routing adaptation |
| **MetaReasoner** | `neuro/meta_reasoner.py` | Meta-cognitive rules engine |
| **AsyncTriggerGraph** | `neuro/async_trigger_graph.py` | Async event triggers |
| **SemanticBinder** | `neuro/semantic_binding.py` | Semantic memory binding |

---

## 🗂️ 2. SISTEME DE MEMORIE

| Sistem | Locatie | Functie | Status |
|--------|---------|---------|--------|
| **Short-term** | `tools/memory_tool.py` | In-memory, session_id | ✅ |
| **Long-term** | `memory/long_term_memory.json` | JSON file storage | ✅ |
| **Entity** | `tools/memory_tool.py` | Entity memory | ✅ |
| **Episodic** | `core/episodic_memory.py` | Event-based storage | ✅ |
| **Lessons** | `memory/lessons_learned.json` | Extracted learnings | ✅ |
| **Observational** | `core/observational_memory.py` | Mastra pattern | ✅ |
| **Neuro/Temporal** | `core/neuro/` | 7-layer cognitive | ✅ |
| **Mem0** | `core/mem0_memory.py` | Mem0 bridge | ⚠️ Goale (pass) |

---

## 🤖 3. AGENTI DEFINITI

### 3.1 CrewAI Agents (in orchestrator.py)
| Agent | Rol | Tools |
|-------|-----|-------|
| chronos | Memory & Context Analyst | memory_summary, search_memory, obsidian_search |
| scout | Web Researcher | duck_duck_go_search |
| architect | Strategic Planner | memory_summary |
| researcher | ML Researcher | file_read, file_write, execute_command |
| ui_designer | UI/UX Designer | duckduckgo_tool, file_write_tool |
| marketing_guru | Marketing Strategist | duckduckgo_tool, file_write_tool |
| web_developer | Full-Stack Developer | file_read, file_write, execute_command |
| critic | QA & Auto-Evaluator | save_lesson_tool, memory_summary_tool |

### 3.2 Auto Agents (in auto_agents.py)
| Rol | Descriere |
|-----|-----------|
| MANAGER | Coordinates workers |
| WORKER | Executes tasks |
| RESEARCHER | Gathers information |
| REVIEWER | Evaluates outputs |
| CREATOR | Creates content |

### 3.3 Special Agents
| Agent | Locatie | Functie |
|-------|---------|---------|
| **ResearchAgent** | `core/research_agent.py` | Deep research (GPT Researcher style) |
| **CoWorkMode** | `core/cowork_mode.py` | Always-on desktop assistant |
| **ComputerUseAgent** | `core/computer_use_agent.py` | Computer use capabilities |

---

## 🔧 4. TOOLS-URI (MCP Registry)

### 4.1 Tools Inregistrate (80+ in MCP)
| Tool | File | Functie |
|------|------|---------|
| **browser_agent.py** | `BrowserAgent` | Unified web browsing |
| **browser_navigator.py** | `BrowserNavigator` | Basic browser navigation |
| **stagehand_browser.py** | `StagehandBrowser` | Deterministic browser |
| **computer_use.py** | `ComputerTool` | Desktop control (PyAutoGUI) |
| **desktop_control.py** | `DesktopControl` | macOS native (notifications, voice, apps) |
| **search_tool.py** | `duckduckgo_search` | Web search |
| **memory_tool.py** | `StructuredMemory` | Structured long-term memory |
| **advanced_memory.py** | `AdvancedMemory` | Bitmap filtering + clustering |
| **voice_cascade.py** | `VoiceCascade` | Voice pathway system |
| **voice_input.py** | `VoiceInput` | Voice input (SpeechRecognition) |
| **realtime_voice.py** | `RealtimeVoice` | Real-time voice (Gemini Live) |
| **jarvis_live.py** | `JarvisLiveSession` | Live session management |
| **obsidian_researcher.py** | `ObsidianResearcher` | Obsidian vault search |
| **obsidian_brain.py** | `ObsidianBrain` | Obsidian integration |
| **coding_agent.py** | `CodingAgent` | Code generation |
| **file_manager.py** | `read_text_file`, `write_text_file` | File I/O |
| **audio_cloud.py** | `ElevenLabsTTS` | Text-to-speech |

### 4.2 Tools in Chat Flow (folosite)
```python
# chat_jarvis.py - doar 14 tools sunt FOLOSITE:
BASIC_TOOLS_SCHEMA = [
    web_search,
    read_file, 
    write_file,
    run_command,
    memory_summary,
    search_memory,
    obsidian_search
]
# + MCP tools (partial)
```

---

## 🌐 5. API ENDPOINTS (nucleus_bridge.py)

### WebSocket
| Endpoint | Descriere |
|----------|-----------|
| `/ws/events` | Real-time event stream to UI |

### POST Endpoints
| Endpoint | Descriere |
|----------|-----------|
| `/api/mission` | Submit mission (CrewAI workflow) |
| `/api/chat` | Primary chat with JARVIS |
| `/api/mission/cancel` | Cancel running mission |
| `/api/governance/proposal/action` | Governance action |
| `/api/governance/proposal/bulk-action` | Bulk governance |
| `/api/planning/preview` | ULTRAPLAN preview |
| `/api/planning/ultraplan` | Run ULTRAPLAN |
| `/api/live/session/start` | Start Gemini Live |
| `/api/live/session/turn` | Process live turn |
| `/api/live/session/interrupt` | Interrupt live session |
| `/api/live/session/stop` | Stop live session |

### GET Endpoints
| Endpoint | Descriere |
|----------|-----------|
| `/api/status` | System health |
| `/api/history` | Mission history |
| `/api/graph` | Memory graph |
| `/api/skills` | Available skills |
| `/api/skills/search` | Search skills |
| `/api/skills/status` | Skills engine status |
| `/api/memory/observations` | Recent observations |
| `/api/memory/stats` | Memory statistics |
| `/api/memory/context` | Dense context |
| `/api/memory/structured/summary` | 4-type summary |
| `/api/runtime/cockpit` | Aggregate runtime intel |
| `/api/autonomy/thoughts` | Proactive thoughts |
| `/api/governance/recent` | Governance decisions |
| `/api/live/session/status` | Live session status |

---

## ⚙️ 6. ENGINE & ORCHESTRATION

### JarvisEngine
- **File:** `core/jarvis_engine.py`
- **Functie:** Main unified engine, integreaza toate capabilitatile JARVIS
- **Status:** ✅ WORKING

### Orchestrator
- **File:** `core/orchestrator.py`
- **Functie:** CrewAI-based multi-agent orchestration with dynamic routing
- **Status:** ✅ WORKING

### State Machine (FSM)
- **File:** `core/state_manager.py`
- **States:** IDLE, INTAKE, PLANNING, RISK_CHECK, EXECUTING, OBSERVING, VALIDATING, VERIFYING, REPAIRING, WAITING_APPROVAL, SUCCESS, FAILURE

---

## 🛡️ 7. GOVERNANCE & SAFETY

| Modul | Functie | Status |
|------|---------|--------|
| `aegis_interlock.py` | Emergency kill switch | ✅ |
| `symbolic_check.py` | Neuro-symbolic safety | ✅ |
| `risk_engine.py` | Risk assessment | ✅ |
| `risk_tiers.py` | Risk tier classification | ✅ |
| `promotion_gate.py` | Skill promotion gate | ✅ |
| `improvement_proposals.py` | Improvement proposals | ✅ |
| `autonomy_daemon.py` | Background autonomous daemon | ✅ |

---

## 🧩 8. PLANNING & EXECUTION

| Modul | Functie |
|-------|---------|
| `ultraplan.py` | Deep implementation planner |
| `coordinator_mode.py` | Meta-agent coordinator |
| `plan_notebook.py` | Persistent plan tracking |
| `verified_executor.py` | Execution with verification |
| `task_contracts.py` | Task contract system |
| `definition_of_done.py` | DoD evaluator |

---

## 🔄 9. EXECUTION FLOWS

### 9.1 Chat Flow (MAIN)
```
User Input
    ↓
JarvisChat.chat()
    ↓
System Prompt (GALAXY exhaustive)
    ↓
Memory Injection (structured + long-term)
    ↓
call_brain_with_tools() [brain.py]
    ↓
LLM → tool_calls?
    ├── YES → Execute tools → Loop (max 10)
    └── NO → Return text
    ↓
sanitize_output() + store in memory
    ↓
Response
```

### 9.2 Mission Flow
```
User Mission
    ↓
run_mission() / orchestrator
    ↓
[5-Phase Pipeline]
    ├─ 1. CLASSIFY
    ├─ 2. MEMORY
    ├─ 3. RESEARCH
    ├─ 4. EXECUTE
    └─ 5. QA
    ↓
Result
```

---

## 📊 10. MODEL LLM FOLOSIT

### Configurare Actuala (brain.py)
```python
PRO_MODEL = "openrouter/qwen/qwen3.6-plus:free"
CHEAP_MODEL = "openrouter/qwen/qwen3.6-plus:free"
LOCAL_MODEL = "ollama/mixtral"
```

**Specificatii Qwen 3.6 Plus:**
- Context: 1,000,000 tokens (1M!)
- Price: $0 (GRATIS)
- Provider: OpenRouter

---

## 🎯 11. PROBLEME IDENTIFICATE

### Critical Issues
| Problema | Locatie | Impact |
|----------|---------|--------|
| **LLM Gateway nefolosit** | `core/llm_gateway.py` | Arhitectura buna dar nu functioneaza |
| **Tools MCP partial** | MCP are 80+, doar 14 folosite | 66 tools nefolosite |
| **Memory duplicat** | Multiple memory systems | Nu sunt unificate |
| **Code mort** | 67 locatii cu `pass` | Functionalitati neimplementate |

### Performance Issues
| Problema | Locatie | Impact |
|----------|---------|--------|
| Cockpit refresh lent | `nucleus_bridge.py` | 5s block |
| Knowledge graph rebuild | `knowledge_graph.py` | Total, nu incremental |
| 40+ subsystems la start | `jarvis_engine.py` | Slow startup |

---

## 📈 12. DEPENDENCIES

| Category | Library |
|----------|---------|
| LLM | LiteLLM |
| Agent Framework | CrewAI |
| Web | FastAPI, WebSocket, aiohttp |
| Browser | Playwright, Stagehand |
| Memory | Mem0 (optional) |
| Database | SQLite |
| OS | pyautogui, AppKit |

---

## 🏆 13. STATUS SUMAR

| Category | Working | Broken | Unused | Total |
|----------|---------|--------|--------|-------|
| Core Modules | 80 | 0 | 6 | 86 |
| Tools | 18 | 0 | 0 | 18 |
| Memory Systems | 7 | 0 | 1 | 8 |
| API Endpoints | 50+ | 0 | 0 | 50+ |
| **TOTAL** | **~155** | **0** | **~7** | **~162** |

---

## ✅ CE FUNCTIONEAZA

- Chat text (basic)
- Tool calls standard
- Memory (short → long term)
- Risk/Verify/Repair pipeline
- State machine (FSM)
- Browser navigation
- Computer use
- Voice input/output
- Web search
- Obsidian integration

---

## ❌ CE NU FUNCTIONEAZA OPTIMAL

- llm_gateway.py (are NotImplementedError)
- 80% din MCP tools (nefolosite in chat)
- Multiple memory systems (neunificate)
- Neuro layers (neconectate la main flow)
- Gemini Live API (1011 internal error)

---

## 🚀 RECOMANDARI

### Priority 1
1. Unifica memory systems
2. Conecteaza llm_gateway sau sterge
3. Adauga MCP tools in chat

### Priority 2
4. Conecteaza Neuro layers
5. Performance optimization

### Priority 3
6. Graceful shutdown
7. Health checks per subsystem

---

*Document generat din audit complet Agent Fram (JARVIS)*
*Data: 2026-04-03*
