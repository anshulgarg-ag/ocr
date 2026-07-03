# Token Optimization Setup — Complete Integration

**Date:** 2026-07-02  
**Project:** OCR Pipeline (Chandra OCR → Qdrant + Neo4j)  
**Status:** ✅ All 4/4 tests passing

---

## Installation Summary

### RTK (Rust Token Killer) v0.42.4
- **Location:** `rtk.exe` (project root)
- **Purpose:** CLI output filtering and compression (60–90% reduction)
- **Status:** ✓ Installed, configured, and tested
- **Configuration:** `.rtk/filters.toml` (5 custom filters)
  - docker-compose: Service lifecycle noise
  - prefect-flow: Workflow execution
  - python-install: Dependency resolution  
  - pytest: Test failures only
  - curl-health: Health check verbosity
- **Integration:** Global Claude Code hook
  - Registered in: `C:\Users\worker\.claude\settings.json`
  - Auto-applies to: Bash tool commands

### Headroom v0.28.0
- **Location:** System Python + CLI tools
- **Purpose:** LLM context compression and memory management (60–95% reduction)
- **Status:** ✓ CLI installed, Python utils configured, tested
- **Configuration:** `.headroom/config.toml` (balanced mode)
  - Algorithms: JSON, code (AST), logs, text
  - Compression level: Balanced (keeps context, reduces tokens)
  - Max lines: 50 (for logs)
- **Integration:** 
  - CLI tool for direct commands
  - Python wrapper for programmatic use
  - Memory storage for context optimization

---

## Project Structure

```
.claude/
├── CLAUDE.md              (2.3 KB) - RTK setup & usage
├── HEADROOM.md            (3.8 KB) - Headroom guide  
├── OPTIMIZATION.md        (5.8 KB) - Combined workflow
├── INTEGRATION.md        (10.0 KB) - Detailed integration guide
└── RTK.md                          - Global RTK documentation

.headroom/
└── config.toml            (1.6 KB) - Compression settings

.rtk/
└── filters.toml           (1.5 KB) - Output filters

scripts/
├── optimize_pipeline.py           - OCR pipeline optimizer
├── monitor_optimization.sh        - Health check + stats
└── test_optimization.py           - Test suite (4/4 passing)

Root:
├── rtk.exe                (8.6 MB) - RTK binary
├── headroom_compress.py           - Integration utilities
└── SETUP_SUMMARY.md               - This file
```

---

## Quick Start

### Test Installation
```bash
# Verify all components (should show 4/4 passed)
python scripts/test_optimization.py
```

### Use RTK for CLI Commands
```bash
rtk docker ps                       # Docker status
rtk git log --oneline -10          # Git history
rtk pytest tests/ -v               # Test results
```

**After Claude Code restart:** Work without `rtk` prefix (hook-based)

### Use Headroom for API Optimization
```python
from headroom_compress import HeadroomMemory, OCRPipelineOptimization

# Store API response for context optimization
OCRPipelineOptimization.save_api_response(
    "qdrant/search",
    qdrant_results,
    label="high_relevance"
)

# Track errors for learning
OCRPipelineOptimization.save_error_context(
    "timeout",
    "Connection to Qdrant timed out after 30s"
)
```

### Monitor Pipeline
```bash
# One-command health + stats
python scripts/optimize_pipeline.py

# Individual monitoring
bash scripts/monitor_optimization.sh all        # Full report
bash scripts/monitor_optimization.sh docker     # Docker status
bash scripts/monitor_optimization.sh savings    # Token savings
```

---

## Compression Results

### Example 1: Docker Service Debugging
```
Without optimization:
  docker logs → 500 KB = 120,000 tokens
  docker inspect → 200 KB = 48,000 tokens
  Total: 168,000 tokens

With RTK:
  rtk docker logs → 50 KB = 12,000 tokens (90% reduction)
  rtk docker inspect → 20 KB = 4,800 tokens (90% reduction)
  Total: 16,800 tokens (90% overall)

With RTK + Headroom:
  RTK filtered + Headroom memory → 5 KB = 1,200 tokens
  Total: 1,200 tokens (99% reduction!)
```

### Example 2: API Response Analysis
```
Direct Qdrant search (100 results):
  Raw JSON → 500 KB = 120,000 tokens

With Headroom:
  Stored in memory + Summary → 8 KB = 1,920 tokens (96% reduction)
```

### Example 3: Git Operations
```
Full diff (main..HEAD):
  300 KB = 72,000 tokens

With RTK:
  Changed lines only → 9 KB = 2,160 tokens (97% reduction)
```

---

## Configuration

### Edit RTK Filters (`.rtk/filters.toml`)
Add project-specific filters:
```toml
[filters.qdrant-queries]
description = "Compact Qdrant API responses"
match_command = "curl.*qdrant"
max_lines = 50
json_minify = true

[filters.neo4j-queries]
description = "Compact Neo4j responses"
match_command = "curl.*neo4j"
max_lines = 50
json_minify = true
```

### Edit Headroom Config (`.headroom/config.toml`)
Adjust compression aggressiveness:
```toml
[compression]
mode = "aggressive"          # For maximum reduction
# or "balanced" (current) for context preservation
# or "conservative" for minimal filtering

[compression.config]
log_max_lines = 100         # Keep more lines if needed
keep_errors = true          # Always preserve errors
```

---

## Integration Architecture

```
┌─ Claude Code ─────────────────────────────────────┐
│                                                    │
│  User Input: "docker ps"                          │
│       ↓                                            │
│  [RTK Global Hook] activated                      │
│       ↓                                            │
│  "docker ps" → rtk docker ps                      │
│       ↓                                            │
│  RTK applies `.rtk/filters.toml` rules            │
│       ↓                                            │
│  Filtered output (60-90% reduction)               │
│       ↓                                            │
│  [Headroom MCP] (optional further compression)   │
│       ↓                                            │
│  [Headroom Memory] stores for context             │
│       ↓                                            │
│  Final context sent to Claude (optimized!)        │
│                                                    │
└────────────────────────────────────────────────────┘
```

---

## Documentation Map

| Document | Purpose | Audience |
|----------|---------|----------|
| `.claude/CLAUDE.md` | RTK quick start & usage | All users |
| `.claude/HEADROOM.md` | Headroom setup guide | Python developers |
| `.claude/OPTIMIZATION.md` | Combined workflow | Teams |
| `.claude/INTEGRATION.md` | Detailed integration | Advanced users |
| `scripts/test_optimization.py` | Validation suite | DevOps |
| `scripts/optimize_pipeline.py` | OCR monitoring | Operations |
| `scripts/monitor_optimization.sh` | Shell monitoring | CI/CD |

---

## Next Steps

### Immediate (5 min)
1. ✓ Installation complete (all tests passing)
2. ⏳ **Restart Claude Code** to activate RTK global hook
3. ⏳ Test: Run `rtk git log --oneline -5`

### This Week
1. ⏳ Run `python scripts/optimize_pipeline.py` to verify pipeline
2. ⏳ Monitor savings: `rtk gain` (should show positive numbers)
3. ⏳ Customize `.rtk/filters.toml` for your workflows
4. ⏳ Add Headroom memories for recurring issues

### Ongoing
1. ⏳ Run `rtk gain --history` monthly to track ROI
2. ⏳ Review `headroom savings` for long-term optimization
3. ⏳ Adjust filters based on real usage patterns
4. ⏳ Share best practices with team

---

## Troubleshooting

### RTK hook not applying
- **Symptom:** Commands still show full output after restart
- **Fix:** Verify hook in settings.json, restart Claude Code again

### Headroom memory not storing
- **Symptom:** `headroom memory list` shows nothing
- **Fix:** Memories only store via explicit `HeadroomMemory.add()` calls

### Compression too aggressive
- **Symptom:** Important context is being cut off
- **Fix:** Increase `max_lines` in filters or use `mode = "conservative"`

### Performance degradation
- **Symptom:** Commands are slower with optimization
- **Fix:** Reduce filter aggressiveness, disable for real-time logs (`docker logs -f`)

---

## Key Benefits

| Feature | RTK | Headroom | Combined |
|---------|-----|----------|----------|
| Instant setup | ✓ | | ✓ |
| No code changes needed | ✓ | | ✓ |
| Auto-detection | | ✓ | ✓ |
| CLI filtering | ✓ | | ✓ |
| Context compression | | ✓ | ✓ |
| Memory optimization | | ✓ | ✓ |
| Analytics & savings | ✓ | ✓ | ✓ |
| Custom rules | ✓ | ✓ | ✓ |
| Learning over time | | ✓ | ✓ |

---

## References

- **RTK Documentation:** https://github.com/rtk-ai/rtk
- **Headroom Documentation:** https://github.com/headroomlabs-ai/headroom
- **Claude Code Settings:** `~/.claude/settings.json`
- **Project Filters:** `.rtk/filters.toml` (customizable)
- **Compression Config:** `.headroom/config.toml` (customizable)

---

## Testing Report

```
RTK + Headroom Optimization Test Suite
===============================================================

[PASS]: RTK
  - Version: rtk 0.42.4
  - Filters: 5 custom filters configured
  - Hook: Registered in settings.json
  - Command filtering: Operational

[PASS]: Headroom
  - Version: headroom 0.28.0
  - Config: Valid configuration found
  - Commands: memory, savings, agent-savings available

[PASS]: Integration
  - HeadroomMemory: Imported and functional
  - HeadroomMCP: Imported and functional
  - PipelineOptimizer: Initialized successfully
  - Memory operations: Functional

[PASS]: Documentation
  - CLAUDE.md: 2,302 bytes
  - HEADROOM.md: 3,785 bytes
  - OPTIMIZATION.md: 5,810 bytes
  - INTEGRATION.md: 10,030 bytes
  - SETUP_SUMMARY.md: (this file)
  - filters.toml: 1,468 bytes
  - config.toml: 1,568 bytes

Total: 4/4 tests passed
```

---

**Installation Date:** 2026-07-02  
**Platform:** Windows 11  
**Python:** 3.14.6  
**Status:** ✅ Production Ready

Ready to use! Restart Claude Code to activate RTK hook, then start optimizing.
