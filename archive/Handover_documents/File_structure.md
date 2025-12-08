ophthalmology_mvp/
│
├── README_V2.md                          # Main project documentation (start here)
├── app.py                                 # Flask web server (production entry point)
│
├── backend/                               # Core application code
│   ├── __init__.py
│   │
│   ├── core/                              # Six main modules
│   │   ├── __init__.py
│   │   ├── state_manager_v2.py           # Tracks consultation state
│   │   ├── question_selector.py          # Deterministic question logic
│   │   ├── response_parser.py            # LLM-based data extraction
│   │   ├── json_formatter.py             # Structured output generation
│   │   ├── summary_generator.py          # Clinical narrative generation
│   │   └── dialogue_manager_v2.py        # Orchestrates everything
│   │
│   └── utils/                             # Helper utilities
│       ├── __init__.py
│       ├── episode_classifier.py
│       ├── hf_client.py                  # HuggingFace model wrapper
│       ├── field_mappings.py             # Value standardization
│       └── helpers.py                    # Validation, IDs, filenames
│
├── data/                                  # Configuration and schemas
│   ├── ruleset.json                       # Medical protocol (89 questions)
│   └── json_schema.json                   # Output structure (71 fields)
│
├── templates/                             # Web interface templates
│   └── index.html                        # Main consultation interface
│
├── outputs/                               # Generated consultation outputs
│   └── consultations/
│       ├── consultation_*.json           # Structured data files
│       └── summary_*.txt                 # Clinical summary files
│
├── tests/                                 # Test suite
│   ├── test_state_manager.py            # (Not created - merged into integration)
│   ├── test_question_selector.py        # Question logic tests
│   ├── test_response_parser.py          # LLM extraction tests
│   ├── test_json_formatter.py           # JSON output tests
│   ├── test_summary_generator.py        # Summary generation tests
│   ├── test_dialogue_manager.py         # Orchestration tests (with mocks)
│   ├── test_integration.py              # Module integration (deprecated)
│   └── test_full_system.py              # End-to-end system test
│
└── docs/                                  # Documentation
    ├── README_V2.md                      # → Moved to root
    ├── FILE_STRUCTURE.md                 # This file
    ├── MODULE_ARCHITECTURE.md            # How modules interact
    └── handover_state_and_question_modules.md  # Session 1 handover