# Zava Insurance — Hybrid AI Demo 🛡️

A demo application showcasing **hybrid AI** for insurance claims processing: AI inference runs locally on the NPU (Phi Silica), while Microsoft WorkIQ securely connects organizational data from M365. Sensitive data never leaves the device.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Windows 11 Copilot+ PC                │
│                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │  NPU         │    │  Foundry Local (CPU)         │   │
│  │  Phi Silica  │    │  qwen2.5-1.5b fallback       │   │
│  │  ~5-7s       │    │  ~10-15s                     │   │
│  └──────┬───────┘    └──────────────┬───────────────┘   │
│         │     AI Inference (local)   │                  │
│         └────────────┬───────────────┘                  │
│                      │                                  │
│  ┌───────────────────▼──────────────────────────────┐   │
│  │              Flask App (localhost:5000)           │   │
│  └───────────────────┬──────────────────────────────┘   │
└──────────────────────│──────────────────────────────────┘
                       │ (optional, secure)
              ┌────────▼─────────┐
              │  Microsoft WorkIQ │
              │  M365 / CRM Data  │
              └──────────────────┘
```

**Key principle:** Organizational knowledge flows IN → AI reasoning stays ON-DEVICE → PII never leaves the hardware.

---

## Quick Start

```powershell
# 1. Clone and install
git clone https://github.com/gusing_microsoft/zava-hybrid-ai-demo.git
cd zava-hybrid-ai-demo
pip install -r requirements.txt

# 2. Run
python app.py

# 3. Open browser
# http://localhost:5000
```

## Prerequisites

- **Windows 11 Copilot+ PC** (any chip: Qualcomm, Intel, or AMD)
- **Python 3.10+**
- **Foundry Local** installed (`winget install Microsoft.FoundryLocal`)
- **phi-npu.exe** (included with Windows AI features on Copilot+ PCs)

## Features

| Tab | Description |
|-----|-------------|
| **Home** | Overview of hybrid AI architecture and value proposition |
| **Claims AI** | Upload field photos → NPU vision analysis → instant damage assessment → submit for approval via WorkIQ |
| **Policy Assistant** | Chat with AI expert — toggle WorkIQ to enrich with customer history, CRM data, and M365 context |
| **Document Analyzer** | Paste docs for summarization/extraction — toggle WorkIQ for cross-referencing organizational data |
| **NPU Dashboard** | Real-time inference metrics, fleet-scale cost projections, system status |

## Hybrid AI: How It Works

### Without WorkIQ (offline mode)
- All AI features work completely offline
- NPU handles vision + chat inference
- Perfect for field adjusters in dead zones or secure facilities

### With WorkIQ (connected mode)
- Toggle "Connect securely to Microsoft WorkIQ" in any tab
- Customer history, prior claims, vendor networks, and M365 context enrich AI responses
- AI reasoning still happens 100% on-device — only organizational context flows in
- Approval workflows route through M365 (email/Teams)

## Sample Data

- 6 sample damage scenarios (flood, fire, hurricane, burst pipe, collapse, interior flood)
- Sample insurance policy document
- Simulated CRM data (prior claims, vendor network, communications)

## Demo Script

See `DEMO_SCRIPT.txt` for a guided walkthrough. Key moments:

1. **Claims AI** — Upload photo, get instant NPU assessment (~5-7s)
2. **WorkIQ toggle** — Show how CRM data enriches the Policy Assistant
3. **Submit for Approval** — Report routes to supervisor via M365
4. **Airplane mode** — Turn off Wi-Fi, AI keeps working (core features)
5. **NPU Dashboard** — $0.00 cloud inference cost at fleet scale

---

## Prototype & Sample Code Disclosure

This repository contains experimental prototypes and sample code for educational and demonstration purposes only.

- All code is provided "as-is," without warranties or guarantees of any kind
- AI outputs may be non-deterministic, incomplete, or incorrect
- Any names, data, or scenarios are fictitious and for illustration only
- Not a supported or production-ready Microsoft offering
- Developers are responsible for evaluating fairness, reliability, privacy, and safety before using similar approaches in real applications

By using this repository, you acknowledge that it contains illustrative prototypes and sample code only.
